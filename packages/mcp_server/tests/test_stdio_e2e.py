"""Bout en bout par le protocole MCP stdio : client `stdio_client` du SDK, sous-processus réel."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import anyio
import psycopg
import pytest
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp_fixture_data import Fixture, expected_kpis, in_period

pytestmark = pytest.mark.db

ROOT = Path(__file__).resolve().parents[3]
SLOW_SQL = (
    "SELECT COUNT(*) FROM analytics.fact_transaction a JOIN analytics.fact_transaction b "
    "ON b.client_id = a.client_id JOIN analytics.fact_transaction c ON c.client_id = b.client_id "
    "JOIN analytics.fact_transaction d ON d.client_id = c.client_id "
    "JOIN analytics.fact_transaction e ON e.client_id = d.client_id"
)


def _params(dsn: str) -> StdioServerParameters:
    # Environnement minimal, comme McpToolClient : DSN, dossier sémantique, date de référence, PATH.
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "decision_mcp_server"],
        env={
            "AGENT_RO_DSN": dsn,
            "SEMANTIC_DIR": str(ROOT / "semantic"),
            "REFERENCE_DATE": "2026-09-30",
            "PATH": os.environ.get("PATH", ""),
        },
    )


async def test_trois_outils_par_stdio(agent_ro_dsn: str, fixture_data: Fixture, tmp_path: Path) -> None:
    errlog = (tmp_path / "stderr.log").open("w+")
    async with (
        stdio_client(_params(agent_ro_dsn), errlog=errlog) as (read, write),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        tools = {t.name: t for t in (await session.list_tools()).tools}
        assert set(tools) == {"query_metric", "run_query", "describe_schema"}
        assert tools["query_metric"].output_schema is not None
        assert "_timeout_s" in tools["run_query"].input_schema["properties"]

        res = await session.call_tool(
            "query_metric",
            {
                "metrics": ["volume_transactions", "taux_echec"],
                "period": {"start": "2026-03-01", "end": "2026-03-31"},
                "compare_to": "previous_period",
                "_timeout_s": 5,
            },
        )
        assert not res.is_error
        data = res.structured_content
        assert data and data["ok"] and data["tool"] == "query_metric" and data["certified"]
        assert json.loads(res.content[0].text) == data  # copie texte JSON pour compatibilité
        rows = {r[0]: r for r in data["rows"]}
        from datetime import date

        exp = expected_kpis(in_period(fixture_data.txns, date(2026, 3, 1), date(2026, 3, 31)))
        assert rows["courante"][1] == exp["volume_transactions"]

        res = await session.call_tool(
            "run_query",
            {
                "sql": "SELECT COUNT(*) AS n FROM analytics.fact_transaction WHERE statut = 'reussie'",
                "purpose": "compter",
                "declared_scope": {"statut": "reussie", "region_kind": "aucune"},
            },
        )
        data = res.structured_content
        assert data and data["ok"], data
        assert data["rows"][0][0] == sum(1 for t in fixture_data.txns if t.statut == "reussie")

        res = await session.call_tool(
            "run_query",
            {
                "sql": "SELECT * FROM pg_catalog.pg_authid",
                "purpose": "x",
                "declared_scope": {"statut": "toutes", "region_kind": "aucune"},
            },
        )
        assert res.is_error and res.structured_content
        assert res.structured_content["error"]["error_class"] == "guard_blocked"

        res = await session.call_tool("describe_schema", {"table": "dim_agent"})
        data = res.structured_content
        assert data and data["ok"] and data["payload"]["tables"][0]["name"] == "analytics.dim_agent"

        res = await session.call_tool(
            "query_metric", {"metrics": ["inconnu"], "period": {"start": "2026-03-01", "end": "2026-03-31"}}
        )
        assert res.is_error and res.structured_content["error"]["error_class"] == "invalid_params"
    errlog.seek(0)
    lines = [json.loads(line) for line in errlog.read().splitlines() if line.startswith("{")]
    assert any(line.get("event") == "tool_call" for line in lines)  # journaux JSON sur stderr


async def test_annulation_par_protocole(agent_ro_dsn: str, fixture_data: Fixture, tmp_path: Path) -> None:
    errlog = (tmp_path / "stderr.log").open("w+")
    async with (
        stdio_client(_params(agent_ro_dsn), errlog=errlog) as (read, write),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        with anyio.move_on_after(1.0) as scope:
            await session.call_tool(
                "run_query",
                {
                    "sql": SLOW_SQL,
                    "purpose": "lent",
                    "declared_scope": {"statut": "toutes", "region_kind": "aucune"},
                    "_timeout_s": 10,
                },
            )
        assert scope.cancelled_caught  # l'appel a bien été abandonné → notifications/cancelled
        await anyio.sleep(1.0)
        async with await psycopg.AsyncConnection.connect(agent_ro_dsn, autocommit=True) as conn:
            cur = await conn.execute(
                "SELECT count(*) FROM pg_stat_activity WHERE state = 'active' AND query LIKE "
                "'%fact_transaction AS e%'"
                " AND pid <> pg_backend_pid()"
            )
            row = await cur.fetchone()
            assert row is not None and row[0] == 0
    errlog.seek(0)
    assert '"pg_cancel_backend"' in errlog.read()
