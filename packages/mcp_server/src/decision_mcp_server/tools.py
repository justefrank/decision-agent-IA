"""Implémentation des trois outils, indépendante du transport MCP (testable directement)."""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from decision_core.models import ColumnInfo, ToolError, ToolResult
from decision_core.semantic import SemanticLayer
from decision_sql_guard import guard_sql, semantic_issues

from decision_mcp_server.compiler import CompileError, compile_query_metric, parse_params
from decision_mcp_server.db import Database, ExecutionError

log = logging.getLogger("decision_mcp_server.tools")

DECLARED_STATUT = ("reussie", "echouee", "toutes")
DECLARED_REGION = ("region_agent", "region_client", "aucune")
DISTINCT_VALUES_MAX = 30


class ToolService:
    def __init__(self, semantic: SemanticLayer, db: Database | None):
        self.semantic = semantic
        self.db = db
        sql_cfg = semantic.config.get("sql") or {}
        self.row_limit = int(sql_cfg.get("row_limit", 1000))
        self.timeout_s = float(sql_cfg.get("statement_timeout_s", 10))
        self.max_plan_cost = float(sql_cfg.get("max_plan_cost", 5_000_000))
        names = {semantic.tables["schema"]}
        for tname, spec in semantic.tables["tables"].items():
            names.add(tname)
            names.update((spec.get("columns") or {}).keys())
        self.allowed_names = names

    # --- utilitaires -------------------------------------------------------------------------

    def _timeout(self, requested: float | None) -> float:
        if requested is None or requested <= 0:
            return self.timeout_s
        return max(0.1, min(float(requested), self.timeout_s))

    def _log(self, result: ToolResult) -> None:
        log.info(
            json.dumps(
                {
                    "event": "tool_call",
                    "tool": result.tool,
                    "ok": result.ok,
                    "error_class": result.error.error_class if result.error else None,
                    "row_count": result.row_count,
                    "truncated": result.truncated,
                    "duration_ms": result.duration_ms,
                },
                ensure_ascii=False,
            )
        )

    def _error(self, tool: str, error: ToolError, started: float, **extra: Any) -> ToolResult:
        result = ToolResult(
            tool=tool, ok=False, error=error, duration_ms=int((time.monotonic() - started) * 1000), **extra
        )
        self._log(result)
        return result

    def _no_db(self, tool: str, started: float, **extra: Any) -> ToolResult:
        return self._error(
            tool, ToolError(error_class="internal", message="AGENT_RO_DSN non configuré."), started, **extra
        )

    # --- query_metric ------------------------------------------------------------------------

    async def query_metric(self, args: dict[str, Any], *, timeout_s: float | None = None) -> ToolResult:
        started = time.monotonic()
        try:
            params = parse_params(args)
            compiled = compile_query_metric(params, self.semantic)
        except CompileError as exc:
            return self._error("query_metric", exc.error, started, certified=True)
        guard = guard_sql(compiled.sql, self.semantic, row_limit=self.row_limit, allow_placeholders=True)
        if not guard.ok or guard.sql is None:
            # Ne devrait jamais arriver : le compilateur ne produit que du SQL de la liste blanche.
            err = guard.error or ToolError(error_class="internal", message="Garde : refus inattendu.")
            return self._error(
                "query_metric",
                ToolError(error_class="internal", message=f"SQL compilé refusé par le garde : {err.message}"),
                started,
                certified=True,
                params=compiled.params,
            )
        if self.db is None:
            return self._no_db("query_metric", started, sql=guard.sql, params=compiled.params, certified=True)
        try:
            res = await self.db.execute(
                guard.sql,
                compiled.bind,
                row_limit=self.row_limit,
                timeout_s=self._timeout(timeout_s),
                allowed_names=self.allowed_names,
            )
        except ExecutionError as exc:
            return self._error(
                "query_metric",
                exc.error,
                started,
                sql=guard.sql,
                params=compiled.params,
                certified=True,
                tables=guard.tables,
            )
        rows = res.rows
        warnings = list(compiled.warnings)
        truncated = res.truncated
        if compiled.rank_limit is not None:
            extra = rows[compiled.rank_limit :]
            rows = rows[: compiled.rank_limit]
            truncated = False
            if extra and rows and compiled.order_column:
                idx = [c.name for c in compiled.columns].index(compiled.order_column)
                if extra[0][idx] == rows[-1][idx]:
                    warnings.append(
                        "ex_aequo : la ligne suivant la limite a la même valeur que la dernière ligne."
                    )
        result = ToolResult(
            tool="query_metric",
            ok=True,
            sql=guard.sql,
            columns=compiled.columns,
            rows=rows,
            row_count=len(rows),
            truncated=truncated,
            duration_ms=int((time.monotonic() - started) * 1000),
            certified=True,
            params=compiled.params,
            tables=guard.tables,
            warnings=warnings,
        )
        self._log(result)
        return result

    # --- run_query ---------------------------------------------------------------------------

    async def run_query(self, args: dict[str, Any], *, timeout_s: float | None = None) -> ToolResult:
        started = time.monotonic()
        sql = args.get("sql")
        declared = args.get("declared_scope") or {}
        if not isinstance(sql, str) or not sql.strip():
            return self._error(
                "run_query", ToolError(error_class="invalid_params", message="`sql` est requis."), started
            )
        if (
            not isinstance(declared, dict)
            or declared.get("statut") not in DECLARED_STATUT
            or declared.get("region_kind") not in DECLARED_REGION
        ):
            return self._error(
                "run_query",
                ToolError(
                    error_class="invalid_params",
                    message="declared_scope invalide.",
                    hint="declared_scope = "
                    "{statut: reussie|toutes, region_kind: region_agent|region_client|aucune}.",
                ),
                started,
            )
        guard = guard_sql(sql, self.semantic, row_limit=self.row_limit)
        if not guard.ok or guard.sql is None or guard.ast is None:
            assert guard.error is not None
            return self._error("run_query", guard.error, started)
        issues = semantic_issues(guard.ast, declared, self.semantic)
        warnings = [i.message for i in issues if not i.blocking]
        blocking = [i for i in issues if i.blocking]
        scope = {**guard.scope, "declared_scope": declared, "purpose": args.get("purpose")}
        if blocking:
            return self._error(
                "run_query",
                ToolError(
                    error_class="semantic_warning",
                    message=" ".join(i.message for i in blocking),
                    hint="Corriger la requête ou declared_scope pour qu'ils soient cohérents.",
                ),
                started,
                sql=guard.sql,
                params=scope,
                tables=guard.tables,
                warnings=warnings,
            )
        if self.db is None:
            return self._no_db("run_query", started, sql=guard.sql, params=scope, tables=guard.tables)
        try:
            res = await self.db.execute(
                guard.sql,
                None,
                row_limit=self.row_limit,
                timeout_s=self._timeout(timeout_s),
                allowed_names=self.allowed_names,
                max_plan_cost=self.max_plan_cost,
            )
        except ExecutionError as exc:
            return self._error(
                "run_query",
                exc.error,
                started,
                sql=guard.sql,
                params=scope,
                tables=guard.tables,
                warnings=warnings,
            )
        columns = [self._describe_column(c) for c in res.columns]
        result = ToolResult(
            tool="run_query",
            ok=True,
            sql=guard.sql,
            columns=columns,
            rows=res.rows,
            row_count=len(res.rows),
            truncated=res.truncated,
            duration_ms=int((time.monotonic() - started) * 1000),
            certified=False,
            params=scope,
            tables=guard.tables,
            warnings=warnings,
        )
        self._log(result)
        return result

    def _describe_column(self, col: ColumnInfo) -> ColumnInfo:
        """Rôle et unité déduits du nom et du type (calcul ad hoc : heuristique documentée)."""
        name = col.name.lower()
        units = {"montant": "xof", "frais": "xof", "valeur": "xof", "revenu": "xof", "taux": "ratio"}
        if col.type in ("date", "timestamptz"):
            return col.model_copy(update={"role": "time", "unit": "date"})
        if name == "periode":
            return col.model_copy(update={"role": "period", "unit": "text"})
        if col.type == "text" or col.type == "boolean":
            return col.model_copy(update={"role": "dimension", "unit": "text"})
        if name.endswith("_id") or name in ("annee", "mois", "trimestre", "semaine_iso", "jour_semaine"):
            return col.model_copy(update={"role": "dimension", "unit": "id"})
        unit = next((u for k, u in units.items() if k in name), "count" if col.type == "integer" else None)
        return col.model_copy(update={"role": "measure", "unit": unit})

    # --- describe_schema ---------------------------------------------------------------------

    async def describe_schema(self, args: dict[str, Any], *, timeout_s: float | None = None) -> ToolResult:
        started = time.monotonic()
        schema = self.semantic.tables["schema"]
        tables = self.semantic.tables["tables"]
        requested = args.get("table")
        if requested:
            name = str(requested).strip().lower().removeprefix(f"{schema}.")
            if name not in tables:
                return self._error(
                    "describe_schema",
                    ToolError(
                        error_class="invalid_params",
                        message=f"Table inconnue : {requested}.",
                        hint="Tables : " + ", ".join(f"{schema}.{t}" for t in tables) + ".",
                    ),
                    started,
                )
            selected = [name]
        else:
            selected = list(tables)
        payload: dict[str, Any] = {"schema": schema, "semantic_version": self.semantic.version, "tables": []}
        warnings: list[str] = []
        regions = list(self.semantic.kpis.get("regions") or [])
        for tname in selected:
            spec = tables[tname]
            cols = []
            for cname, cspec in (spec.get("columns") or {}).items():
                entry = {"name": cname, "type": cspec.get("type")}
                for key in ("description", "values", "unit", "references", "key", "free_text"):
                    if cspec.get(key) is not None:
                        entry[key] = cspec[key]
                if tname == "dim_region" and cname == "region":
                    entry["values"] = regions + ["Non applicable"]
                cols.append(entry)
            payload["tables"].append(
                {
                    "name": f"{schema}.{tname}",
                    "grain": spec.get("grain"),
                    "description": spec.get("description"),
                    "columns": cols,
                }
            )
        if requested and self.db is not None:
            try:
                await self._add_distinct_values(payload["tables"][0], selected[0], timeout_s)
            except ExecutionError as exc:
                warnings.append(f"Valeurs distinctes indisponibles : {exc.error.message}")
        result = ToolResult(
            tool="describe_schema",
            ok=True,
            payload=payload,
            tables=[f"{schema}.{t}" for t in selected],
            warnings=warnings,
            duration_ms=int((time.monotonic() - started) * 1000),
        )
        self._log(result)
        return result

    async def _add_distinct_values(
        self, table_doc: dict[str, Any], tname: str, timeout_s: float | None
    ) -> None:
        """Valeurs distinctes courtes des colonnes texte catégorielles sans énumération déclarée."""
        assert self.db is not None
        schema = self.semantic.tables["schema"]
        for col in table_doc["columns"]:
            if col.get("type") != "text" or col.get("values") or col.get("free_text"):
                continue
            # Noms issus de tables.yaml uniquement (jamais de l'entrée) : pas d'interpolation d'entrée.
            sql = (
                f"SELECT DISTINCT {col['name']} FROM {schema}.{tname} ORDER BY 1 "
                f"LIMIT {DISTINCT_VALUES_MAX + 1}"
            )
            guard = guard_sql(sql, self.semantic, row_limit=DISTINCT_VALUES_MAX)
            if not guard.ok or guard.sql is None:
                continue
            res = await self.db.execute(
                guard.sql,
                None,
                row_limit=DISTINCT_VALUES_MAX,
                timeout_s=self._timeout(timeout_s),
                allowed_names=self.allowed_names,
            )
            if not res.truncated:
                col["distinct_values"] = [r[0] for r in res.rows]
