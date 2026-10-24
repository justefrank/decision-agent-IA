"""Intégration avec un vrai Postgres (rôle agent_ro) et le jeu analytics de fixture."""

from __future__ import annotations

from collections import defaultdict
from datetime import date

import anyio
import psycopg
import pytest
from decision_core.semantic import load_semantic
from decision_mcp_server.db import Database, ExecutionError
from decision_mcp_server.tools import ToolService
from mcp_fixture_data import Fixture, expected_kpis, in_period

pytestmark = pytest.mark.db

SEM = load_semantic()
MARS = {"start": "2026-03-01", "end": "2026-03-31"}
M_START, M_END = date(2026, 3, 1), date(2026, 3, 31)


@pytest.fixture
async def service(agent_ro_dsn: str):
    db = Database(agent_ro_dsn, max_size=3)
    svc = ToolService(SEM, db)
    yield svc
    await db.close()


def _close(a, b) -> bool:
    if a is None or b is None:
        return a is b
    return abs(float(a) - float(b)) < 1e-9


async def test_six_kpi_exacts(service: ToolService, fixture_data: Fixture) -> None:
    r = await service.query_metric({"metrics": list(SEM.metrics), "period": MARS})
    assert r.ok, r.error
    assert r.certified and r.row_count == 1 and not r.truncated
    exp = expected_kpis(in_period(fixture_data.txns, M_START, M_END))
    row = dict(zip([c.name for c in r.columns], r.rows[0], strict=True))
    for metric, value in exp.items():
        assert _close(row[metric], value), (metric, row[metric], value)
    assert isinstance(row["valeur_transferee"], int)  # Decimal → int
    assert isinstance(row["taux_echec"], float)
    assert r.tables == ["analytics.dim_date", "analytics.fact_transaction"]
    assert r.sql and "%(debut)s" in r.sql


async def test_par_region_agent(service: ToolService, fixture_data: Fixture) -> None:
    r = await service.query_metric(
        {"metrics": ["revenus_frais"], "period": MARS, "group_by": ["region_agent"]}
    )
    assert r.ok, r.error
    expected: dict[str, int] = defaultdict(int)
    for t in in_period(fixture_data.txns, M_START, M_END):
        if t.statut == "reussie" and t.agent_id != -1:
            expected[fixture_data.regions[t.region_agent_id]] += t.frais_xof
    got = {row[0]: row[1] for row in r.rows}
    assert {k: v for k, v in got.items() if v} == {k: v for k, v in expected.items() if v}
    assert "Non applicable" not in got  # hors agent exclu d'un découpage par région du point de service
    assert r.warnings  # rappel de l'exclusion


async def test_comparaison_periode_precedente(service: ToolService, fixture_data: Fixture) -> None:
    r = await service.query_metric(
        {"metrics": ["volume_transactions", "taux_echec"], "period": MARS, "compare_to": "previous_period"}
    )
    assert r.ok, r.error
    assert [c.name for c in r.columns] == ["periode", "volume_transactions", "taux_echec"]
    rows = {row[0]: row for row in r.rows}
    assert set(rows) == {"courante", "comparaison"}
    assert r.rows[0][0] == "courante"
    cur = expected_kpis(in_period(fixture_data.txns, M_START, M_END))
    prev = expected_kpis(in_period(fixture_data.txns, date(2026, 2, 1), date(2026, 2, 28)))
    assert rows["courante"][1] == cur["volume_transactions"] and _close(
        rows["courante"][2], cur["taux_echec"]
    )
    assert rows["comparaison"][1] == prev["volume_transactions"]
    assert _close(rows["comparaison"][2], prev["taux_echec"])
    assert r.params and r.params["compare_period"]["start"] == "2026-02-01"


async def test_comparaison_annee_precedente(service: ToolService, fixture_data: Fixture) -> None:
    r = await service.query_metric(
        {"metrics": ["clients_actifs"], "period": MARS, "compare_to": "previous_year"}
    )
    assert r.ok, r.error
    rows = {row[0]: row[1] for row in r.rows}
    prev = expected_kpis(in_period(fixture_data.txns, date(2025, 3, 1), date(2025, 3, 31)))
    assert rows["comparaison"] == prev["clients_actifs"]


async def test_classement_agents_exclut_hors_agent(service: ToolService, fixture_data: Fixture) -> None:
    r = await service.query_metric(
        {
            "metrics": ["volume_transactions"],
            "period": MARS,
            "group_by": ["agent"],
            "order": "desc",
            "limit": 50,
        }
    )
    assert r.ok, r.error
    assert [c.name for c in r.columns] == ["agent_id", "nom", "volume_transactions"]
    ids = [row[0] for row in r.rows]
    assert -1 not in ids and "Hors agent" not in [row[1] for row in r.rows]
    counts: dict[int, int] = defaultdict(int)
    for t in in_period(fixture_data.txns, M_START, M_END):
        if t.agent_id != -1:
            counts[t.agent_id] += t.statut == "reussie"
    assert {row[0]: row[2] for row in r.rows} == dict(counts)
    values = [row[2] for row in r.rows]
    assert values == sorted(values, reverse=True)
    assert 10 not in ids  # l'agent 10 n'a aucune transaction en mars 2026
    top = await service.query_metric(
        {
            "metrics": ["volume_transactions"],
            "period": MARS,
            "group_by": ["agent"],
            "order": "desc",
            "limit": 3,
        }
    )
    assert top.ok and top.row_count == 3 and not top.truncated
    assert [row[0] for row in top.rows] == ids[:3]


async def test_serie_mensuelle_et_filtres(service: ToolService, fixture_data: Fixture) -> None:
    period = {"start": "2025-04-01", "end": "2026-09-30"}
    r = await service.query_metric(
        {
            "metrics": ["valeur_transferee"],
            "period": period,
            "grain": "month",
            "filters": [
                {"dimension": "type", "values": ["depot", "retrait"]},
                {"dimension": "segment", "values": ["particulier"]},
            ],
        }
    )
    assert r.ok, r.error
    expected: dict[str, int] = defaultdict(int)
    for t in in_period(fixture_data.txns, date(2025, 4, 1), date(2026, 9, 30)):
        if (
            t.statut == "reussie"
            and t.type in ("depot", "retrait")
            and fixture_data.clients[t.client_id][1] == "particulier"
        ):
            expected[t.day.replace(day=1).isoformat()] += t.montant_xof
    got = {row[0]: row[1] for row in r.rows}
    assert {k: v for k, v in got.items() if v} == {k: v for k, v in expected.items() if v}
    assert [row[0] for row in r.rows] == sorted(got)
    assert r.columns[0].role == "time"


async def test_agents_actifs_par_region_client(service: ToolService, fixture_data: Fixture) -> None:
    r = await service.query_metric(
        {
            "metrics": ["agents_actifs"],
            "period": MARS,
            "filters": [{"dimension": "region_client", "values": ["Dakar"]}],
        }
    )
    assert r.ok, r.error
    sub = [t for t in in_period(fixture_data.txns, M_START, M_END) if t.region_client_id == 1]
    assert r.rows[0][0] == expected_kpis(sub)["agents_actifs"]


async def test_run_query_resultat_et_portee(service: ToolService, fixture_data: Fixture) -> None:
    sql = (
        "SELECT c.segment, SUM(f.montant_xof) FILTER (WHERE f.statut = 'reussie') AS valeur "
        "FROM analytics.fact_transaction f JOIN analytics.dim_client c ON c.client_id = f.client_id "
        "WHERE f.date_id BETWEEN 20260301 AND 20260331 GROUP BY c.segment ORDER BY c.segment"
    )
    r = await service.run_query(
        {"sql": sql, "purpose": "test", "declared_scope": {"statut": "reussie", "region_kind": "aucune"}}
    )
    assert r.ok, r.error
    assert not r.certified and r.warnings == []
    assert r.sql and r.sql.endswith("LIMIT 1001")
    assert r.params and r.params["period"] == {"start": "2026-03-01", "end": "2026-03-31"}
    expected: dict[str, int] = defaultdict(int)
    for t in in_period(fixture_data.txns, M_START, M_END):
        if t.statut == "reussie":
            expected[fixture_data.clients[t.client_id][1]] += t.montant_xof
    assert {row[0]: row[1] for row in r.rows} == dict(expected)
    assert r.columns[0].role == "dimension" and r.columns[1].role == "measure" and r.columns[1].unit == "xof"


async def test_run_query_avertissement_et_contradiction(service: ToolService, fixture_data: Fixture) -> None:
    r = await service.run_query(
        {
            "sql": "SELECT SUM(montant_xof) FROM analytics.fact_transaction",
            "purpose": "x",
            "declared_scope": {"statut": "reussie", "region_kind": "aucune"},
        }
    )
    assert r.ok and r.warnings and "reussie" in r.warnings[0]
    bad = await service.run_query(
        {
            "sql": "SELECT r.region, COUNT(*) FROM analytics.fact_transaction f JOIN analytics.dim_region r "
            "ON r.region_id = f.region_agent_id WHERE f.statut = 'reussie' GROUP BY 1",
            "purpose": "x",
            "declared_scope": {"statut": "reussie", "region_kind": "region_client"},
        }
    )
    assert not bad.ok and bad.error and bad.error.error_class == "semantic_warning"
    assert bad.row_count == 0


async def test_run_query_garde_et_erreur_sql(service: ToolService, fixture_data: Fixture) -> None:
    blocked = await service.run_query(
        {
            "sql": "SELECT pg_read_file('/etc/passwd')",
            "purpose": "x",
            "declared_scope": {"statut": "toutes", "region_kind": "aucune"},
        }
    )
    assert not blocked.ok and blocked.error and blocked.error.error_class == "guard_blocked"
    err = await service.run_query(
        {
            "sql": "SELECT f.montant FROM analytics.fact_transaction f",
            "purpose": "x",
            "declared_scope": {"statut": "toutes", "region_kind": "aucune"},
        }
    )
    assert not err.ok and err.error and err.error.error_class == "sql_error"
    assert "42703" in err.error.message and "montant" in err.error.message
    assert "agent_ro" not in err.error.message and "postgresql://" not in err.error.message


async def test_cout_du_plan_borne(service: ToolService, fixture_data: Fixture) -> None:
    service.max_plan_cost = 1.0
    r = await service.run_query(
        {
            "sql": "SELECT COUNT(*) FROM analytics.fact_transaction WHERE statut = 'reussie'",
            "purpose": "x",
            "declared_scope": {"statut": "reussie", "region_kind": "aucune"},
        }
    )
    assert not r.ok and r.error and r.error.error_class == "guard_blocked" and "Coût" in r.error.message


async def test_truncated(service: ToolService, fixture_data: Fixture) -> None:
    service.row_limit = 50
    r = await service.run_query(
        {
            "sql": "SELECT transaction_id, montant_xof FROM analytics.fact_transaction "
            "ORDER BY transaction_id",
            "purpose": "x",
            "declared_scope": {"statut": "toutes", "region_kind": "aucune"},
        }
    )
    assert r.ok, r.error
    assert r.truncated and r.row_count == 50 and len(r.rows) == 50
    assert r.sql and r.sql.endswith("LIMIT 51")
    q = await service.query_metric(
        {
            "metrics": ["volume_transactions"],
            "period": {"start": "2025-04-01", "end": "2026-09-30"},
            "grain": "day",
        }
    )
    assert q.ok and q.truncated and q.row_count == 50


async def test_timeout(agent_ro_dsn: str, fixture_data: Fixture) -> None:
    db = Database(agent_ro_dsn)
    try:
        # Le garde n'intervient pas ici : on teste le mécanisme statement_timeout lui-même.
        with pytest.raises(ExecutionError) as info:
            await db.execute("SELECT pg_sleep(3)", None, row_limit=10, timeout_s=0.3, allowed_names=set())
        assert info.value.error.error_class == "timeout"
        # La connexion reste utilisable après l'erreur.
        res = await db.execute(
            "SELECT COUNT(*) FROM analytics.dim_region", None, row_limit=10, timeout_s=2, allowed_names=set()
        )
        assert res.rows == [[15]]
    finally:
        await db.close()


async def test_timeout_outil(service: ToolService, fixture_data: Fixture) -> None:
    sql = (
        "SELECT COUNT(*) FROM analytics.fact_transaction a JOIN analytics.fact_transaction b "
        "ON b.client_id = a.client_id JOIN analytics.fact_transaction c ON c.client_id = b.client_id "
        "JOIN analytics.fact_transaction d ON d.client_id = c.client_id "
        "JOIN analytics.fact_transaction e ON e.client_id = d.client_id"
    )
    r = await service.run_query(
        {"sql": sql, "purpose": "x", "declared_scope": {"statut": "toutes", "region_kind": "aucune"}},
        timeout_s=0.05,
    )
    assert not r.ok and r.error is not None
    assert r.error.error_class in ("timeout", "guard_blocked")  # coût du plan ou délai


async def test_annulation_pg_cancel_backend(agent_ro_dsn: str, fixture_data: Fixture) -> None:
    db = Database(agent_ro_dsn)
    try:
        with anyio.move_on_after(0.5):
            await db.execute("SELECT pg_sleep(5)", None, row_limit=1, timeout_s=10, allowed_names=set())
        await anyio.sleep(0.3)
        async with await psycopg.AsyncConnection.connect(agent_ro_dsn, autocommit=True) as conn:
            cur = await conn.execute(
                "SELECT count(*) FROM pg_stat_activity WHERE query LIKE 'SELECT pg_sleep(5)%' "
                "AND state = 'active'"
            )
            row = await cur.fetchone()
            assert row is not None and row[0] == 0
    finally:
        await db.close()


def test_role_agent_ro_lecture_seule(agent_ro_dsn: str, fixture_data: Fixture) -> None:
    with psycopg.connect(agent_ro_dsn, autocommit=True) as conn:
        assert conn.execute("SHOW default_transaction_read_only").fetchone() == ("on",)
        assert conn.execute("SELECT COUNT(*) FROM analytics.dim_agent").fetchone() == (11,)
        for stmt in (
            "INSERT INTO analytics.dim_region VALUES (99, 'x', 'y')",
            "CREATE TABLE analytics.pirate (x int)",
            "SET SESSION CHARACTERISTICS AS TRANSACTION READ WRITE; DELETE FROM analytics.fact_transaction",
        ):
            with pytest.raises(psycopg.Error):
                conn.execute(stmt)
    with (
        psycopg.connect(agent_ro_dsn, autocommit=True) as conn,
        pytest.raises(psycopg.errors.InsufficientPrivilege),
    ):
        conn.execute("BEGIN READ WRITE; DELETE FROM analytics.fact_transaction")


async def test_ecriture_refusee_via_executor(agent_ro_dsn: str, fixture_data: Fixture) -> None:
    db = Database(agent_ro_dsn)
    try:
        with pytest.raises(ExecutionError) as info:
            await db.execute(
                "DELETE FROM analytics.fact_transaction", None, row_limit=1, timeout_s=2, allowed_names=set()
            )
        assert info.value.error.error_class in ("guard_blocked", "sql_error")
    finally:
        await db.close()


async def test_describe_schema(service: ToolService, fixture_data: Fixture) -> None:
    r = await service.describe_schema({"table": "dim_region"})
    assert r.ok and r.payload
    cols = {c["name"]: c for c in r.payload["tables"][0]["columns"]}
    assert "Dakar" in cols["region"]["values"] and "Non applicable" in cols["region"]["values"]
    assert cols["pays"]["distinct_values"] == ["Non applicable", "Sénégal"]
    full = await service.describe_schema({"table": None})
    assert full.ok and full.payload and len(full.payload["tables"]) == 5
    ft = next(t for t in full.payload["tables"] if t["name"] == "analytics.fact_transaction")
    statut = next(c for c in ft["columns"] if c["name"] == "statut")
    assert statut["values"] == ["reussie", "echouee"]
    bad = await service.describe_schema({"table": "pg_authid"})
    assert not bad.ok and bad.error and bad.error.error_class == "invalid_params"
