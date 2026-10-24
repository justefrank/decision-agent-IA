"""Provenance `free_text` des projections (sécurité E1) : lignage sur l'AST validé par le garde."""

from __future__ import annotations

import pytest
from decision_core.semantic import load_semantic
from decision_sql_guard import free_text_columns, free_text_projections, guard_sql

SEM = load_semantic()
JOIN_R = "JOIN analytics.dim_region r ON r.region_id = a.region_agent_id"


def _flags(sql: str) -> list[bool] | None:
    g = guard_sql(sql, SEM, row_limit=10)
    assert g.ok and g.ast is not None, g.error
    return free_text_projections(g.ast, SEM)


def test_colonnes_free_text_de_tables_yaml() -> None:
    assert free_text_columns(SEM) == {("dim_agent", "nom"), ("dim_agent", "ville")}


@pytest.mark.parametrize(
    ("sql", "expected"),
    [
        # Repro du constat : alias et fonction masquaient la provenance.
        ("SELECT nom AS libelle, upper(ville) AS l2 FROM analytics.dim_agent", [True, True]),
        (
            "SELECT a.agent_id, lower(a.nom) AS x, a.statut_agent FROM analytics.dim_agent a",
            [False, True, False],
        ),
        (
            "SELECT CASE WHEN agent_id > 1 THEN coalesce(nom, '') ELSE 'x' END AS k, "
            "CAST(ville AS text) AS t FROM analytics.dim_agent",
            [True, True],
        ),
        ("SELECT * FROM analytics.dim_agent", [False, True, True, False, False, False]),
        (
            f"SELECT r.region, a.nom AS region_bis FROM analytics.dim_agent a {JOIN_R}",
            [False, True],
        ),
        (
            "WITH x AS (SELECT nom AS l FROM analytics.dim_agent) SELECT y.z FROM (SELECT l AS z FROM x) y",
            [True],
        ),
        (
            "SELECT region FROM analytics.dim_region UNION ALL SELECT ville FROM analytics.dim_agent",
            [True],
        ),
        (
            "SELECT (SELECT max(a.nom) FROM analytics.dim_agent a) AS m, region FROM analytics.dim_region",
            [True, False],
        ),
        # Même nom de sortie que la colonne libre sans en dériver : non marqué.
        (
            f"SELECT r.region AS nom, count(*) AS ville FROM analytics.dim_agent a {JOIN_R} "
            "WHERE a.nom = 'x' GROUP BY 1",
            [False, False],
        ),
    ],
)
def test_provenance(sql: str, expected: list[bool]) -> None:
    assert _flags(sql) == expected
