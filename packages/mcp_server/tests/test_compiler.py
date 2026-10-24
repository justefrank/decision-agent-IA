"""Tests unitaires du compilateur query_metric (sans base)."""

from __future__ import annotations

from datetime import date

import pytest
from decision_core.models import Period, QueryMetricParams
from decision_core.semantic import load_semantic
from decision_mcp_server.compiler import CompileError, comparison_period, compile_query_metric, parse_params
from decision_sql_guard import guard_sql

SEM = load_semantic()
MARS = {"start": "2026-03-01", "end": "2026-03-31"}


def _compile(**kw):
    args = {"metrics": ["volume_transactions"], "period": MARS, **kw}
    return compile_query_metric(parse_params(args), SEM)


@pytest.mark.parametrize("metric", list(SEM.metrics))
def test_chaque_metrique(metric: str) -> None:
    c = _compile(metrics=[metric])
    assert SEM.metrics[metric]["sql"].split("(")[0] in c.sql
    assert f"AS {metric}" in c.sql
    assert c.bind == {"debut": 20260301, "fin": 20260331}
    assert "%(debut)s" in c.sql and "2026" not in c.sql  # jamais interpolé
    assert [col.name for col in c.columns] == [metric]
    col = c.columns[0]
    assert col.role == "measure" and col.unit == SEM.metrics[metric]["unit"]
    assert col.label == SEM.metrics[metric]["label"]
    g = guard_sql(c.sql, SEM, row_limit=1000, allow_placeholders=True)
    assert g.ok, g.error
    assert g.tables == ["analytics.dim_date", "analytics.fact_transaction"]


def test_group_by_region_et_type() -> None:
    c = _compile(group_by=["region_client", "type"])
    assert "JOIN analytics.dim_region rc ON rc.region_id = f.region_client_id" in c.sql
    assert "GROUP BY 1, 2" in c.sql
    assert [x.name for x in c.columns] == ["region_client", "type", "volume_transactions"]
    assert [x.role for x in c.columns] == ["dimension", "dimension", "measure"]
    assert c.params["region_kind"] == "region_client"


def test_dimension_agent_exclut_hors_agent() -> None:
    c = _compile(metrics=["revenus_frais"], group_by=["agent"], order="desc", limit=5)
    assert "f.agent_id <> -1" in c.sql
    assert [x.name for x in c.columns] == ["agent_id", "nom", "revenus_frais"]
    assert c.columns[0].unit == "id" and c.columns[1].unit == "text"
    assert "ORDER BY 3 DESC NULLS LAST, 1, 2" in c.sql
    assert c.sql.endswith("LIMIT 6")  # une ligne de plus pour les ex æquo
    assert guard_sql(c.sql, SEM, row_limit=1000, allow_placeholders=True).ok


@pytest.mark.parametrize(
    ("grain", "name", "expr"),
    [
        ("day", "jour", "d.date"),
        ("week", "semaine", "date_trunc('week', d.date)::date"),
        ("month", "mois", "d.debut_mois"),
        ("quarter", "trimestre", "date_trunc('quarter', d.date)::date"),
    ],
)
def test_grains(grain: str, name: str, expr: str) -> None:
    c = _compile(grain=grain)
    assert f"{expr} AS {name}" in c.sql
    assert c.columns[0].name == name and c.columns[0].role == "time" and c.columns[0].unit == "date"
    assert "GROUP BY 1" in c.sql and "ORDER BY 1" in c.sql
    assert guard_sql(c.sql, SEM, row_limit=1000, allow_placeholders=True).ok


def test_comparaison_periode_precedente_mois_calendaire() -> None:
    c = _compile(compare_to="previous_period")
    assert c.bind["debut_comparaison"] == 20260201 and c.bind["fin_comparaison"] == 20260228
    assert "THEN 'courante' ELSE 'comparaison' END AS periode" in c.sql
    assert c.columns[0].name == "periode" and c.columns[0].role == "period"
    assert "ORDER BY 1 DESC" in c.sql
    assert c.params["compare_period"] == {"start": "2026-02-01", "end": "2026-02-28", "label": None}


def test_comparaison_annee_precedente() -> None:
    c = _compile(compare_to="previous_year")
    assert c.bind["debut_comparaison"] == 20250301 and c.bind["fin_comparaison"] == 20250331


def test_comparaison_duree_quelconque() -> None:
    p = comparison_period(Period(start=date(2026, 3, 10), end=date(2026, 3, 16)), "previous_period")
    assert p is not None and (p.start, p.end) == (date(2026, 3, 3), date(2026, 3, 9))
    q = comparison_period(Period(start=date(2026, 1, 1), end=date(2026, 3, 31)), "previous_period")
    assert q is not None and (q.start, q.end) == (date(2025, 10, 1), date(2025, 12, 31))
    r = comparison_period(Period(start=date(2024, 2, 29), end=date(2024, 2, 29)), "previous_year")
    assert r is not None and r.start == date(2023, 2, 28)


def test_filtres_lies() -> None:
    c = _compile(
        filters=[
            {"dimension": "region_agent", "values": ["Dakar", "Thiès"]},
            {"dimension": "type", "values": ["depot"]},
        ]
    )
    assert "ra.region IN (%(f0_0)s, %(f0_1)s)" in c.sql
    assert "f.type IN (%(f1_0)s)" in c.sql
    assert c.bind["f0_0"] == "Dakar" and c.bind["f0_1"] == "Thiès" and c.bind["f1_0"] == "depot"
    assert "Dakar" not in c.sql


def test_filtre_agent_entier() -> None:
    c = _compile(filters=[{"dimension": "agent", "values": ["3", "7"]}])
    assert c.bind["f0_0"] == 3 and c.bind["f0_1"] == 7
    assert "f.agent_id <> -1" in c.sql


@pytest.mark.parametrize(
    ("kwargs", "fragment"),
    [
        ({"metrics": ["chiffre_affaires"]}, "Métrique(s) inconnue(s)"),
        ({"filters": [{"dimension": "region_agent", "values": ["Paris"]}]}, "Valeur(s) inconnue(s)"),
        ({"filters": [{"dimension": "segment", "values": ["vip"]}]}, "Valeur(s) inconnue(s)"),
        ({"filters": [{"dimension": "agent", "values": ["abc"]}]}, "identifiant invalide"),
        ({"filters": [{"dimension": "agent", "values": ["-1"]}]}, "Hors agent"),
        ({"group_by": ["ville_agent"]}, "Paramètres query_metric invalides"),
        ({"group_by": ["agent"], "limit": 51}, "Paramètres query_metric invalides"),
        ({"group_by": ["agent"], "limit": 5, "compare_to": "previous_period"}, "Combinaison non supportée"),
        ({"limit": 5}, "group_by"),
        ({"period": {"start": "2026-03-31", "end": "2026-03-01"}}, "Période invalide"),
        ({"group_by": ["type", "type"]}, "group_by"),
    ],
)
def test_erreurs_actionnables(kwargs: dict, fragment: str) -> None:
    with pytest.raises(CompileError) as info:
        _compile(**kwargs)
    err = info.value.error
    assert err.error_class == "invalid_params"
    assert fragment in err.message
    assert err.hint


def test_dimension_non_supportee_donne_definition_canonique() -> None:
    import copy
    from dataclasses import replace

    kpis = copy.deepcopy(SEM.kpis)
    kpis["metrics"]["taux_echec"]["dimensions"] = ["region_agent", "region_client", "type"]
    sem = replace(SEM, kpis=kpis)
    params = QueryMetricParams.model_validate(
        {"metrics": ["taux_echec"], "period": MARS, "group_by": ["segment"]}
    )
    with pytest.raises(CompileError) as info:
        compile_query_metric(params, sem)
    err = info.value.error
    assert "non supportée" in err.message
    assert err.hint and "Définition canonique de taux_echec" in err.hint
    assert "COUNT(*) FILTER (WHERE f.statut = 'echouee')" in err.hint and "run_query" in err.hint


# --- Constats de revue : texte libre (E1), chevauchement (D4), fin février (D14), couverture (D3) ---

BOUNDS = (date(2025, 4, 1), date(2026, 10, 15))


def test_nom_agent_marque_free_text() -> None:
    c = _compile(metrics=["revenus_frais"], group_by=["agent"], order="desc", limit=5)
    flags = {col.name: col.free_text for col in c.columns}
    assert flags == {"agent_id": False, "nom": True, "revenus_frais": False}


@pytest.mark.parametrize(
    "period",
    [
        {"start": "2025-01-01", "end": "2026-03-31"},  # 15 mois : recouvrement janv.-mars 2025
        {"start": "2025-03-01", "end": "2026-03-01"},  # un an et un jour
    ],
)
def test_comparaison_chevauchante_refusee(period: dict) -> None:
    with pytest.raises(CompileError) as info:
        _compile(period=period, compare_to="previous_year")
    assert info.value.error.error_class == "invalid_params"
    assert "chevauchant" in info.value.error.message


def test_annee_exacte_sans_chevauchement() -> None:
    c = _compile(period={"start": "2025-03-01", "end": "2026-02-28"}, compare_to="previous_year")
    assert c.bind["fin_comparaison"] == 20250228 and c.bind["debut_comparaison"] == 20240301


@pytest.mark.parametrize(
    ("start", "end", "cmp_start", "cmp_end"),
    [
        (date(2025, 2, 1), date(2025, 2, 28), date(2024, 2, 1), date(2024, 2, 29)),
        (date(2025, 1, 1), date(2025, 2, 28), date(2024, 1, 1), date(2024, 2, 29)),
        (date(2024, 2, 1), date(2024, 2, 29), date(2023, 2, 1), date(2023, 2, 28)),
        (date(2026, 2, 10), date(2026, 2, 20), date(2025, 2, 10), date(2025, 2, 20)),
    ],
)
def test_previous_year_fin_fevrier(start: date, end: date, cmp_start: date, cmp_end: date) -> None:
    p = comparison_period(Period(start=start, end=end), "previous_year")
    assert p is not None and (p.start, p.end) == (cmp_start, cmp_end)


def _compile_bounds(**kw):
    args = {"metrics": ["valeur_transferee"], "period": MARS, **kw}
    return compile_query_metric(parse_params(args), SEM, BOUNDS)


def test_comparaison_hors_donnees_refusee() -> None:
    with pytest.raises(CompileError) as info:
        _compile_bounds(period={"start": "2026-02-01", "end": "2026-02-28"}, compare_to="previous_year")
    err = info.value.error
    assert err.error_class == "invalid_params"
    assert "Période de comparaison hors des données (données du 2025-04-01 au 2026-10-15)" in err.message


def test_comparaison_partielle_signalee() -> None:
    c = _compile_bounds(period={"start": "2026-03-15", "end": "2026-04-14"}, compare_to="previous_year")
    assert any("comparaison partielle : 14 jours sur 31 couverts" in w for w in c.warnings)
    cov = c.params["coverage"]
    assert cov["data_start"] == "2025-04-01" and cov["data_end"] == "2026-10-15"
    assert cov["current"] == {"days": 31, "covered_days": 31, "complete": True}
    assert cov["comparison"] == {"days": 31, "covered_days": 14, "complete": False}


def test_periode_courante_hors_donnees() -> None:
    c = _compile_bounds(period={"start": "2027-01-01", "end": "2027-01-31"})
    assert any(w.startswith("période hors des données (données du 2025-04-01") for w in c.warnings)
    assert c.params["coverage"]["current"]["covered_days"] == 0
    with pytest.raises(CompileError) as info:
        _compile_bounds(period={"start": "2027-01-01", "end": "2027-01-31"}, compare_to="previous_period")
    assert "Période courante hors des données" in info.value.error.message


def test_periode_courante_partielle() -> None:
    c = _compile_bounds(period={"start": "2026-10-01", "end": "2026-10-31"})
    assert any("période partielle : 15 jours sur 31 couverts" in w for w in c.warnings)


def test_couverture_complete_sans_avertissement() -> None:
    c = _compile_bounds(compare_to="previous_period")
    assert not c.warnings and c.params["coverage"]["comparison"]["complete"]


def test_annee_iso_colonne_identifiant() -> None:
    from decision_core.models import ColumnInfo
    from decision_mcp_server.tools import ToolService

    svc = ToolService(SEM, None)
    col = svc._describe_column(ColumnInfo(name="annee_iso", type="integer", role="measure"))
    assert col.role == "dimension" and col.unit == "id"
