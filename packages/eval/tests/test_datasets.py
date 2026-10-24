"""Contrôles statiques des jeux eval/*.yaml (sans base de données)."""

from __future__ import annotations

import pytest
from decision_eval.antileak import verify_manifest
from decision_eval.compare import norm_text
from decision_eval.dataset import CATEGORIES_TEST, category_counts, eval_dir, load_dataset
from decision_eval.refs import ReferenceSQLError, check_reference_sql

SPLITS = ["test", "dev", "intent", "followup", "security"]


@pytest.fixture(scope="module")
def datasets():
    return {s: load_dataset(eval_dir() / f"{s}.yaml") for s in SPLITS}


def test_all_load(datasets):
    for s, ds in datasets.items():
        assert ds.split == s
        assert str(ds.reference_date) == "2026-09-30"


def test_test_split_matches_srs(datasets):
    ds = datasets["test"]
    assert len(ds.items) == 40
    assert category_counts(ds) == CATEGORIES_TEST
    kinds = [it.expected_kind for it in ds.items if it.category == "ambigu_hors_perimetre"]
    assert "refusal" in kinds and "clarification" in kinds
    traps = {it.trap for it in ds.items}
    assert {"ecriture", "injection_directe"} <= traps
    glossary = {it.trap for it in ds.items if it.category == "piege_glossaire"}
    assert {"resultat_vide", "jour_ferie", "denominateur_taux_echec", "hors_agent"} <= glossary
    assert any("region" in (t or "") for t in glossary)
    assert all(it.turns for it in ds.items if it.category == "suivi")
    assert sum(1 for it in ds.items if it.expected_empty) >= 1


def test_sizes(datasets):
    assert 35 <= len(datasets["dev"].items) <= 45
    intent = datasets["intent"]
    assert len(intent.items) == 60
    kinds = [it.expected_kind for it in intent.items]
    assert kinds.count("answer") == 30 and kinds.count("clarification") == 15 and kinds.count("refusal") == 15
    assert sum(1 for it in intent.items if it.trap == "injection_directe") == 5
    fu = datasets["followup"]
    assert len(fu.items) == 12 and {it.variant for it in fu.items} == {"A", "B", "C"}
    sec = datasets["security"]
    assert len(sec.items) == 5 and all(it.inject and it.canary for it in sec.items)


def test_reference_sql_guarded(datasets):
    """Chaque reference_sql (et SQL d'historique, cible d'injection) : SELECT unique sur analytics.*."""
    n = 0
    for ds in datasets.values():
        for it in ds.items:
            sqls = [it.reference_sql] if it.reference_sql else []
            sqls += [t.answer.reference_sql for t in it.turns or [] if t.answer and t.answer.reference_sql]
            if it.inject:
                sqls.append(it.inject.target_sql)
            for s in sqls:
                assert check_reference_sql(s), it.id
                n += 1
    assert n > 90


def test_no_hardcoded_expected_values(datasets):
    """Aucune valeur attendue écrite : pas de champ de valeur dans les items."""
    for ds in datasets.values():
        for it in ds.items:
            dumped = it.model_dump()
            assert not {"expected_value", "expected_rows", "answer_value"} & set(dumped)


def test_guard_rejects_bad_sql():
    for bad in [
        "DELETE FROM analytics.fact_transaction",
        "SELECT * FROM app.query_log",
        "SELECT * FROM fact_transaction",
        "SELECT 1; SELECT 2",
        "SELECT * FROM analytics.fact_transaction; DROP TABLE analytics.dim_date",
        "SELECT * FROM generate_series(1, 3)",
        "SELECT 1",
    ]:
        with pytest.raises(ReferenceSQLError):
            check_reference_sql(bad)
    assert check_reference_sql("WITH x AS (SELECT * FROM analytics.dim_date) SELECT count(*) FROM x") == [
        "analytics.dim_date"
    ]


def test_test_and_dev_questions_distinct(datasets):
    tq = {norm_text(it.final_question) for it in datasets["test"].items}
    for s in ("dev", "intent", "followup", "security"):
        oq = {norm_text(it.final_question) for it in datasets[s].items}
        assert not tq & oq, s


def test_manifest_matches():
    assert len(verify_manifest()) == 64
