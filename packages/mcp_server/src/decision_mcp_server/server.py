"""Serveur MCP (SDK `mcp` 2.x, classe `MCPServer`, transport stdio)."""

from __future__ import annotations

import functools
import inspect
import json
import logging
import os
import sys
import time
from collections.abc import Awaitable, Callable
from typing import Annotated, Any

import anyio
from decision_core.models import ToolResult
from decision_core.semantic import load_semantic
from mcp.server import MCPServer
from mcp_types import CallToolResult, TextContent, ToolAnnotations
from pydantic import Field

from decision_mcp_server.db import Database
from decision_mcp_server.tools import ToolService

TimeoutArg = Annotated[
    float | None,
    Field(alias="_timeout_s", description="Délai maximal en secondes (statement_timeout ≤ ce délai)."),
]
_READ_ONLY = ToolAnnotations(
    read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False
)


class JsonFormatter(logging.Formatter):
    """Une ligne JSON par événement, sur stderr (stdout est réservé au canal JSON-RPC)."""

    def format(self, record: logging.LogRecord) -> str:
        doc: dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)),
            "level": record.levelname.lower(),
            "logger": record.name,
        }
        msg = record.getMessage()
        try:
            parsed = json.loads(msg)
            doc.update(parsed if isinstance(parsed, dict) else {"message": msg})
        except ValueError:
            doc["message"] = msg
        if record.exc_info:
            doc["exception"] = record.exc_info[0].__name__ if record.exc_info[0] else None
        return json.dumps(doc, ensure_ascii=False)


def setup_logging(level: str | None = None) -> None:
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level or os.environ.get("LOG_LEVEL", "INFO"))
    for noisy in ("sqlglot", "psycopg", "psycopg.pool", "mcp", "httpx"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def to_call_result(result: ToolResult) -> CallToolResult:
    data = result.model_dump(mode="json")
    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps(data, ensure_ascii=False))],
        structured_content=data,
        is_error=not result.ok,
    )


def _private_timeout(
    fn: Callable[..., Awaitable[CallToolResult]],
) -> Callable[..., Awaitable[CallToolResult]]:
    """Le SDK refuse les paramètres commençant par « _ » : on publie `_timeout_s` en alias."""
    sig = inspect.signature(fn, eval_str=True)

    @functools.wraps(fn)
    async def wrapper(**kwargs: Any) -> CallToolResult:
        if "_timeout_s" in kwargs:
            kwargs["timeout_s"] = kwargs.pop("_timeout_s")
        return await fn(**kwargs)

    wrapper.__signature__ = sig  # type: ignore[attr-defined]
    return wrapper


def build_server(service: ToolService) -> MCPServer:
    server: MCPServer = MCPServer(
        name="decision-mcp-server",
        version="0.5.0",
        instructions="Outils de données en lecture seule sur le schéma analytics (Wave, données "
        "synthétiques).",
    )

    async def query_metric(
        metrics: Annotated[list[str], Field(description="KPI certifiés de kpis.yaml (1 à 6).")],
        period: Annotated[dict[str, Any], Field(description="{start: AAAA-MM-JJ, end: AAAA-MM-JJ, label?}")],
        compare_to: Annotated[str, Field(description="none | previous_period | previous_year")] = "none",
        group_by: Annotated[
            list[str], Field(description="⊂ {region_agent, region_client, type, segment, agent}")
        ]
        | None = None,
        grain: Annotated[str, Field(description="none | day | week | month | quarter")] = "none",
        filters: Annotated[list[dict[str, Any]], Field(description="[{dimension, values}]")] | None = None,
        order: Annotated[str, Field(description="none | desc | asc")] = "none",
        limit: Annotated[int | None, Field(description="1 à 50, avec group_by")] = None,
        timeout_s: TimeoutArg = None,
    ) -> Annotated[CallToolResult, ToolResult]:
        args = {
            "metrics": metrics,
            "period": period,
            "compare_to": compare_to,
            "group_by": group_by or [],
            "grain": grain,
            "filters": filters or [],
            "order": order,
            "limit": limit,
        }
        return to_call_result(await service.query_metric(args, timeout_s=timeout_s))

    async def run_query(
        sql: Annotated[str, Field(description="Un seul SELECT PostgreSQL sur analytics.*")],
        purpose: Annotated[str, Field(description="But du calcul, en une phrase")] = "",
        declared_scope: Annotated[
            dict[str, Any] | None,
            Field(description="{statut: reussie|toutes, region_kind: region_agent|region_client|aucune}"),
        ] = None,
        timeout_s: TimeoutArg = None,
    ) -> Annotated[CallToolResult, ToolResult]:
        args = {"sql": sql, "purpose": purpose, "declared_scope": declared_scope}
        return to_call_result(await service.run_query(args, timeout_s=timeout_s))

    async def describe_schema(
        table: Annotated[str | None, Field(description="Nom de table analytics, ou null pour toutes")] = None,
        timeout_s: TimeoutArg = None,
    ) -> Annotated[CallToolResult, ToolResult]:
        return to_call_result(await service.describe_schema({"table": table}, timeout_s=timeout_s))

    server.add_tool(
        _private_timeout(query_metric),
        name="query_metric",
        annotations=_READ_ONLY,
        description=(
            "Calcule des KPI certifiés (définitions de semantic/kpis.yaml) : volume_transactions, "
            "valeur_transferee, revenus_frais, clients_actifs, agents_actifs, taux_echec ; par dimension, "
            "classement, série temporelle (grain) ou comparaison (colonne periode ∈ "
            "{courante, comparaison}). "
            "En cas de dimension non supportée, l'erreur donne la définition canonique à reprendre "
            "dans run_query."
        ),
    )
    server.add_tool(
        _private_timeout(run_query),
        name="run_query",
        annotations=_READ_ONLY,
        description=(
            "SELECT PostgreSQL gardé sur analytics.* quand query_metric ne couvre pas la question "
            "(calcul ad hoc, non certifié). declared_scope est vérifié contre la requête."
        ),
    )
    server.add_tool(
        _private_timeout(describe_schema),
        name="describe_schema",
        annotations=_READ_ONLY,
        description="Métadonnées normalisées des tables analytics (colonnes, types, valeurs possibles).",
    )
    return server


def main() -> None:
    setup_logging()
    semantic = load_semantic()
    dsn = os.environ.get("AGENT_RO_DSN")
    db = Database(dsn) if dsn else None
    service = ToolService(semantic, db)
    server = build_server(service)
    logging.getLogger("decision_mcp_server").info(
        json.dumps(
            {
                "event": "start",
                "semantic_version": semantic.version,
                "db_configured": db is not None,
            }
        )
    )

    async def run() -> None:
        try:
            async with anyio.create_task_group() as tg:
                tg.start_soon(service.data_bounds)  # bornes des données en cache dès le démarrage
                await server.run_stdio_async()
        finally:
            if db is not None:
                with anyio.CancelScope(shield=True):
                    await db.close()

    anyio.run(run)
