"""Tests de l'anti-fuite (SQL normalisé, squelettes) et du MANIFEST."""

from __future__ import annotations

import shutil

import pytest
from decision_eval.antileak import (
    ManifestError,
    check_antileak,
    examples_content,
    freeze_manifest,
    normalize_sql,
    run_antileak,
    skeleton_sql,
    verify_manifest,
)
from decision_eval.dataset import Dataset, eval_dir

Q1 = (
    "SELECT COUNT(*) AS n FROM analytics.fact_transaction f "
    "WHERE f.statut = 'reussie' AND f.date_id BETWEEN 20260301 AND 20260331"
)


def ds(split, items):
    return Dataset.model_validate({"split": split, "items": items})


def answer_item(i, q, sql):
    return {
        "id": i,
        "category": "kpi_simple",
        "question": q,
        "expected_kind": "answer",
        "reference_sql": sql,
        "expected_period": {"start": "2026-09-01", "end": "2026-09-30"},
    }


def test_normalize_ignores_case_and_spacing():
    a = normalize_sql(Q1)
    b = normalize_sql(Q1.lower().replace(" and ", "\n   AND "))
    assert a == b


def test_skeleton_ignores_literals_and_aliases():
    other = (
        "select count(*) as volume from analytics.fact_transaction t "
        "where t.statut='echouee' and t.date_id between 20250101 and 20250131"
    )
    assert normalize_sql(Q1) != normalize_sql(other)
    assert skeleton_sql(Q1) == skeleton_sql(other)
    different = "SELECT SUM(f.montant_xof) FROM analytics.fact_transaction f WHERE f.statut = 'reussie'"
    assert skeleton_sql(Q1) != skeleton_sql(different)


def test_examples_content_any_shape():
    ex = {
        "examples": [
            {"question": "Q ?", "tool": "run_query", "args": {"sql": Q1}},
            {"user": "Autre ?", "call": {"name": "query_metric", "params": {"metrics": ["x"]}}},
        ]
    }
    sqls, qs = examples_content(ex)
    assert sqls == [Q1] and qs == ["Q ?", "Autre ?"]


def test_check_antileak_detects_exact_skeleton_and_question():
    test = ds(
        "test",
        [
            answer_item("T1", "Volume de mars ?", Q1),
            answer_item("T2", "Frais ?", "SELECT SUM(f.frais_xof) FROM analytics.fact_transaction f"),
        ],
    )
    assert check_antileak(test, {}).ok
    rep = check_antileak(test, {"examples": [{"question": "x", "sql": Q1}]})
    assert rep.exact == ["T1"] and rep.skeleton == ["T1"] and not rep.ok
    skel = Q1.replace("20260301", "20250501").replace("20260331", "20250531")
    rep = check_antileak(test, {"examples": [{"question": "x", "sql": skel}]})
    assert rep.exact == [] and rep.skeleton == ["T1"] and not rep.ok
    rep = check_antileak(test, {"examples": [{"question": "volume de MARS ?"}]})
    assert rep.questions == ["T1"] and not rep.ok


def test_check_antileak_dev_overlap():
    test = ds("test", [answer_item("T1", "Volume de mars ?", Q1)])
    dev_same_q = ds("dev", [answer_item("D1", "Volume de mars ?", "SELECT 1 FROM analytics.dim_date")])
    assert check_antileak(test, {}, dev_same_q).dev_overlap == ["T1"]
    dev_skel = ds(
        "dev", [answer_item("D1", "Volume d'avril ?", Q1.replace("0301", "0401").replace("0331", "0430"))]
    )
    rep = check_antileak(test, {}, dev_skel)
    assert rep.ok and rep.dev_skeleton_warnings == ["T1"]


def test_repository_antileak_passes():
    rep = run_antileak()
    assert rep.ok, rep.to_dict()


def test_manifest_freeze_verify(tmp_path):
    shutil.copy(eval_dir() / "test.yaml", tmp_path / "test.yaml")
    with pytest.raises(ManifestError):
        verify_manifest(tmp_path)
    h = freeze_manifest(tmp_path)
    assert verify_manifest(tmp_path) == h
    with pytest.raises(ManifestError):
        freeze_manifest(tmp_path)
    (tmp_path / "test.yaml").write_text((tmp_path / "test.yaml").read_text() + "\n# modifié\n")
    with pytest.raises(ManifestError, match="modifié"):
        verify_manifest(tmp_path)
    assert freeze_manifest(tmp_path, force=True) != h
