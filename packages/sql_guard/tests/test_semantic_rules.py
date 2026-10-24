"""Extraction de portée et règles de cohérence sémantique."""

from __future__ import annotations

from decision_core.semantic import load_semantic
from decision_sql_guard import guard_sql, semantic_issues, semantic_warnings

SEM = load_semantic()


def _guard(sql: str, statut: str = "reussie", region_kind: str = "aucune"):
    return guard_sql(sql, SEM, row_limit=1000, declared_scope={"statut": statut, "region_kind": region_kind})


def _codes(sql: str, statut: str = "reussie", region_kind: str = "aucune") -> dict[str, bool]:
    r = guard_sql(sql, SEM, row_limit=1000)
    assert r.ok, r.error
    assert r.ast is not None
    return {
        i.code: i.blocking
        for i in semantic_issues(r.ast, {"statut": statut, "region_kind": region_kind}, SEM)
    }


def test_scope_periode_date_id() -> None:
    r = _guard(
        "SELECT COUNT(*) FROM analytics.fact_transaction f WHERE f.statut = 'reussie' "
        "AND f.date_id BETWEEN 20260301 AND 20260331"
    )
    assert r.scope["period"] == {"start": "2026-03-01", "end": "2026-03-31"}
    assert r.scope["statut"] == "reussie"
    assert r.scope["region_kind"] == "aucune"


def test_scope_periode_dim_date_bornes_exclusives() -> None:
    r = _guard(
        "SELECT COUNT(*) FILTER (WHERE f.statut = 'reussie') FROM analytics.fact_transaction f "
        "JOIN analytics.dim_date d ON d.date_id = f.date_id "
        "WHERE d.date >= '2026-02-01' AND d.date < '2026-03-01'"
    )
    assert r.scope["period"] == {"start": "2026-02-01", "end": "2026-02-28"}
    assert r.scope["statut"] == "reussie"
    assert r.scope["statut_filters"] == ["reussie"]


def test_scope_annee_mois() -> None:
    r = _guard(
        "SELECT COUNT(*) FROM analytics.fact_transaction f JOIN analytics.dim_date d "
        "ON d.date_id = f.date_id WHERE d.annee = 2026 AND d.mois = 2 AND f.statut = 'reussie'"
    )
    assert r.scope["period"] == {"start": "2026-02-01", "end": "2026-02-28"}


def test_scope_region_client() -> None:
    r = _guard(
        "SELECT r.region, COUNT(*) FROM analytics.fact_transaction f JOIN analytics.dim_region r "
        "ON r.region_id = f.region_client_id WHERE f.statut = 'reussie' GROUP BY 1",
        region_kind="region_client",
    )
    assert r.scope["region_kind"] == "region_client"
    assert r.warnings == []


def test_agregat_sans_statut_signale() -> None:
    codes = _codes("SELECT SUM(f.montant_xof) FROM analytics.fact_transaction f")
    assert codes == {"statut_manquant": False}


def test_agregat_sans_statut_admis_si_toutes() -> None:
    assert _codes("SELECT SUM(f.montant_xof) FROM analytics.fact_transaction f", statut="toutes") == {}


def test_agregat_avec_filter_ok() -> None:
    sql = (
        "SELECT COUNT(*) FILTER (WHERE f.statut = 'reussie'), "
        "SUM(f.frais_xof) FILTER (WHERE f.statut = 'reussie') FROM analytics.fact_transaction f"
    )
    assert _codes(sql) == {}


def test_agent_actif_via_statut_agent() -> None:
    sql = "SELECT COUNT(*) FROM analytics.dim_agent a WHERE a.statut_agent = 'ouvert'"
    assert "agent_actif_statut_agent" in _codes(sql)


def test_region_incoherente_bloquante() -> None:
    sql = (
        "SELECT r.region, COUNT(*) FROM analytics.fact_transaction f JOIN analytics.dim_region r "
        "ON r.region_id = f.region_agent_id WHERE f.statut = 'reussie' GROUP BY 1"
    )
    assert _codes(sql, region_kind="region_client") == {"region_incoherente": True}
    assert _codes(sql, region_kind="aucune") == {"region_non_declaree": True}
    assert _codes(sql, region_kind="region_agent") == {}


def test_taux_echec_denominateur_reussie() -> None:
    sql = (
        "SELECT COUNT(*) FILTER (WHERE f.statut = 'echouee')::numeric / "
        "NULLIF(COUNT(*) FILTER (WHERE f.statut = 'reussie'), 0) FROM analytics.fact_transaction f"
    )
    assert "taux_echec_denominateur" in _codes(sql, statut="toutes")


def test_taux_echec_correct() -> None:
    sql = (
        "SELECT COUNT(*) FILTER (WHERE f.statut = 'echouee')::numeric / NULLIF(COUNT(*), 0) "
        "FROM analytics.fact_transaction f"
    )
    assert _codes(sql, statut="toutes") == {}


def test_statut_contradictoire() -> None:
    sql = "SELECT COUNT(*) FROM analytics.fact_transaction f WHERE f.statut = 'reussie'"
    assert _codes(sql, statut="toutes") == {"statut_contradictoire": True}
    sql2 = "SELECT COUNT(*) FROM analytics.fact_transaction f WHERE f.statut = 'echouee'"
    assert _codes(sql2, statut="reussie").get("statut_contradictoire") is True


def test_semantic_warnings_contrat_texte() -> None:
    msgs = semantic_warnings(
        "SELECT SUM(montant_xof) FROM analytics.fact_transaction",
        {"statut": "reussie", "region_kind": "aucune"},
    )
    assert len(msgs) == 1 and "reussie" in msgs[0]
