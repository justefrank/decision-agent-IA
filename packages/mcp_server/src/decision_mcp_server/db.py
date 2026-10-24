"""Exécution en lecture seule sur `agent_ro` : pool psycopg, EXPLAIN borné, lecture en flux,
normalisation des erreurs et des valeurs, annulation par `pg_cancel_backend`."""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from datetime import time as dtime
from decimal import Decimal
from typing import Any

import anyio
import psycopg
from decision_core.models import ColumnInfo, ToolError
from psycopg import errors as pg_errors
from psycopg_pool import AsyncConnectionPool

log = logging.getLogger("decision_mcp_server.db")

_TYPE_NAMES = {
    "int2": "integer",
    "int4": "integer",
    "int8": "integer",
    "oid": "integer",
    "numeric": "numeric",
    "float4": "numeric",
    "float8": "numeric",
    "text": "text",
    "varchar": "text",
    "bpchar": "text",
    "name": "text",
    "date": "date",
    "bool": "boolean",
    "timestamptz": "timestamptz",
    "timestamp": "timestamptz",
    "interval": "text",
}
_SECRET_PATTERNS = [
    re.compile(r"postgres(?:ql)?://\S+", re.I),
    re.compile(r"password\s*=\s*\S+", re.I),
    re.compile(r"(?:host|user|dbname)\s*=\s*\S+", re.I),
]


class ExecutionError(Exception):
    def __init__(self, error: ToolError):
        super().__init__(error.message)
        self.error = error


@dataclass
class ExecResult:
    columns: list[ColumnInfo]
    rows: list[list[Any]]
    truncated: bool
    duration_ms: int
    plan_cost: float | None = None
    warnings: list[str] = field(default_factory=list)


def json_value(value: Any) -> Any:
    """Valeur JSON sûre : Decimal → int/float, dates ISO, NaN/infini → None."""
    if value is None or isinstance(value, bool | str):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, Decimal):
        if not value.is_finite():
            return None
        if value == value.to_integral_value():
            return int(value)
        return float(value)
    if isinstance(value, float):
        return value if value == value and value not in (float("inf"), float("-inf")) else None
    if isinstance(value, datetime | date | dtime):
        return value.isoformat()
    if isinstance(value, timedelta):
        return value.total_seconds()
    return str(value)


def _sanitize(text: str | None, allowed: set[str]) -> str:
    if not text:
        return ""
    for pat in _SECRET_PATTERNS:
        text = pat.sub("«masqué»", text)

    def repl(m: re.Match[str]) -> str:
        name = m.group(1)
        parts = name.lower().split(".")
        return m.group(0) if all(p in allowed for p in parts) else '"«objet masqué»"'

    return re.sub(r'"([^"]{1,128})"', repl, text)[:500]


def normalize_pg_error(exc: BaseException, *, allowed_names: set[str], timeout_s: float) -> ToolError:
    """Erreur Postgres → ToolError sans secret (noms d'objets analytics conservés)."""
    if isinstance(exc, pg_errors.QueryCanceled):
        return ToolError(
            error_class="timeout",
            message=f"Délai d'exécution dépassé ({timeout_s:g} s) ou requête annulée.",
            hint="Restreindre la période, filtrer davantage ou agréger en SQL.",
        )
    if isinstance(exc, pg_errors.ReadOnlySqlTransaction | pg_errors.InsufficientPrivilege):
        return ToolError(
            error_class="guard_blocked",
            message="Opération refusée par la base (lecture seule, droits du rôle agent_ro).",
        )
    diag = getattr(exc, "diag", None)
    sqlstate = getattr(exc, "sqlstate", None) or ""
    if not sqlstate:
        return ToolError(error_class="internal", message="Erreur de connexion ou d'exécution inattendue.")
    primary = _sanitize(diag.message_primary if diag else str(exc), allowed_names)
    hint = _sanitize(diag.message_hint if diag else None, allowed_names) or None
    return ToolError(
        error_class="sql_error",
        message=f"Erreur SQL {sqlstate} ({type(exc).__name__}) : {primary}",
        hint=hint,
    )


def find_cartesian(plan: dict[str, Any]) -> bool:
    """Boucle imbriquée sans condition de jointure entre deux entrées de plusieurs lignes."""
    stack = [plan]
    while stack:
        node = stack.pop()
        children = node.get("Plans") or []
        if node.get("Node Type") == "Nested Loop" and len(children) == 2 and "Join Filter" not in node:
            outer, inner = children

            def has_cond(n: dict[str, Any]) -> bool:
                if any(
                    k in n
                    for k in ("Index Cond", "Recheck Cond", "Hash Cond", "Merge Cond", "Filter", "Cache Key")
                ):
                    return True
                return any(has_cond(c) for c in n.get("Plans") or [])

            if outer.get("Plan Rows", 0) > 1 and inner.get("Plan Rows", 0) > 1 and not has_cond(inner):
                return True
        stack.extend(children)
    return False


class Database:
    """Pool de 1 à 3 connexions `agent_ro` en autocommit ; chaque requête dans BEGIN READ ONLY."""

    def __init__(self, dsn: str, *, min_size: int = 1, max_size: int = 3):
        self._dsn = dsn
        self._pool = AsyncConnectionPool(
            dsn,
            min_size=min_size,
            max_size=max_size,
            open=False,
            kwargs={"autocommit": True, "application_name": "decision_mcp_server"},
        )
        self._opened = False
        self._lock = anyio.Lock()

    async def open(self) -> None:
        async with self._lock:
            if not self._opened:
                await self._pool.open(wait=True, timeout=10)
                self._opened = True

    async def close(self) -> None:
        if self._opened:
            await self._pool.close()
            self._opened = False

    async def _cancel_backend(self, pid: int) -> None:
        """Annulation côté serveur de la requête en cours (connexion dédiée, hors pool)."""
        try:
            with anyio.fail_after(3):
                conn = await psycopg.AsyncConnection.connect(self._dsn, autocommit=True)
                async with conn:
                    await conn.execute("SELECT pg_cancel_backend(%s)", (pid,))
            log.info(json.dumps({"event": "pg_cancel_backend", "pid": pid}))
        except Exception as exc:  # l'annulation reste au mieux
            log.warning(
                json.dumps({"event": "pg_cancel_backend_failed", "pid": pid, "error": type(exc).__name__})
            )

    async def execute(
        self,
        sql: str,
        bind: dict[str, Any] | None,
        *,
        row_limit: int,
        timeout_s: float,
        allowed_names: set[str],
        max_plan_cost: float | None = None,
    ) -> ExecResult:
        await self.open()
        timeout_ms = max(100, int(timeout_s * 1000))
        started = time.monotonic()
        async with self._pool.connection() as conn:
            pid = conn.info.backend_pid
            try:
                await conn.execute("BEGIN READ ONLY")
                await conn.execute(f"SET LOCAL statement_timeout = {timeout_ms}")
                plan_cost = None
                if max_plan_cost is not None:
                    cur = await conn.execute("EXPLAIN (FORMAT JSON) " + sql, bind or None)
                    row = await cur.fetchone()
                    plan_doc = row[0] if row else []
                    if isinstance(plan_doc, str):
                        plan_doc = json.loads(plan_doc)
                    plan = plan_doc[0]["Plan"]
                    plan_cost = float(plan.get("Total Cost", 0))
                    if plan_cost > max_plan_cost:
                        raise ExecutionError(
                            ToolError(
                                error_class="guard_blocked",
                                message=f"Coût estimé trop élevé ({plan_cost:,.0f} > {max_plan_cost:,.0f}).",
                                hint="Filtrer la période sur f.date_id, réduire les jointures, "
                                "agréger avant de joindre.",
                            )
                        )
                    if find_cartesian(plan):
                        raise ExecutionError(
                            ToolError(
                                error_class="guard_blocked",
                                message="Produit cartésien détecté dans le plan d'exécution.",
                                hint="Chaque jointure doit relier des clés (ON x.cle = f.cle).",
                            )
                        )
                async with conn.cursor(name=f"q_{uuid.uuid4().hex[:12]}") as cur:
                    await cur.execute(sql, bind or None)
                    fetched = await cur.fetchmany(row_limit + 1)
                    description = cur.description or []
                await conn.execute("COMMIT")
            except ExecutionError:
                await _rollback(conn)
                raise
            except anyio.get_cancelled_exc_class():
                with anyio.CancelScope(shield=True):
                    await self._cancel_backend(pid)
                    await _rollback(conn)
                raise
            except psycopg.Error as exc:
                await _rollback(conn)
                raise ExecutionError(
                    normalize_pg_error(exc, allowed_names=allowed_names, timeout_s=timeout_s)
                ) from exc
        columns = []
        for col in description:
            info = conn.adapters.types.get(col.type_code)
            pg_type = info.name if info else "text"
            columns.append(ColumnInfo(name=col.name, type=_TYPE_NAMES.get(pg_type, "text"), role="measure"))
        truncated = len(fetched) > row_limit
        rows = [[json_value(v) for v in r] for r in fetched[:row_limit]]
        return ExecResult(
            columns=columns,
            rows=rows,
            truncated=truncated,
            duration_ms=int((time.monotonic() - started) * 1000),
            plan_cost=plan_cost,
        )


async def _rollback(conn: psycopg.AsyncConnection[Any]) -> None:
    try:
        status = conn.info.transaction_status
        if status in (psycopg.pq.TransactionStatus.INTRANS, psycopg.pq.TransactionStatus.INERROR):
            await conn.execute("ROLLBACK")
    except Exception:  # connexion cassée ou occupée (annulation) : le pool la jettera
        log.debug("rollback impossible")
