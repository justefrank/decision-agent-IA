"""Tests de l'anti-fuite (SQL normalisé, squelettes) et du MANIFEST."""

from __future__ import annotations

import shutil

import pytest
from decision_eval.antileak import (
    ManifestError,
    call_skeleton,
    check_antileak,
    examples_content,
    freeze_manifest,
    normalize_sql,
    run_antileak,
    skeleton_sql,
    sql_metric_skeleton,
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


# ------------------------------------------------------------------ squelettes query_metric

TAUX_RETRAITS = (
    "SELECT COUNT(*) FILTER (WHERE f.statut = 'echouee')::numeric / NULLIF(COUNT(*), 0) AS t "
    "FROM analytics.fact_transaction f WHERE f.type = 'retrait' AND f.date_id BETWEEN 20260801 AND 20260831"
)


def qm(**kw):
    base = {
        "metrics": [],
        "compare_to": "none",
        "group_by": [],
        "grain": "none",
        "filters": [],
        "limit": None,
    }
    base.update(kw)
    return base


def test_sql_and_call_skeletons_agree_without_values():
    sk = sql_metric_skeleton(TAUX_RETRAITS, ["type"])
    depots = qm(metrics=["taux_echec"], filters=[{"dimension": "type", "values": ["depot"]}])
    assert sk == call_skeleton(depots)  # autre valeur de filtre, même squelette
    assert sk != call_skeleton(qm(metrics=["taux_echec"]))
    assert sk != call_skeleton(qm(metrics=["taux_echec"], group_by=["type"]))


def test_sql_skeleton_derivations():
    top = (
        "SELECT a.agent_id, a.nom, COALESCE(SUM(f.montant_xof), 0) AS v FROM analytics.fact_transaction f "
        "JOIN analytics.dim_agent a ON a.agent_id = f.agent_id WHERE f.statut = 'reussie' "
        "AND f.agent_id <> -1 GROUP BY a.agent_id, a.nom ORDER BY v DESC LIMIT 1"
    )
    assert sql_metric_skeleton(top) == call_skeleton(
        qm(metrics=["valeur_transferee"], group_by=["agent"], order="desc", limit=3)
    )
    yoy = (
        "SELECT SUM(f.frais_xof) FILTER (WHERE f.date_id BETWEEN 20260901 AND 20260930) AS a, "
        "SUM(f.frais_xof) FILTER (WHERE f.date_id BETWEEN 20250901 AND 20250930) AS b "
        "FROM analytics.fact_transaction f WHERE f.statut = 'reussie'"
    )
    assert "compare=previous_year" in sql_metric_skeleton(yoy)
    assert "compare=previous_period" in sql_metric_skeleton(yoy.replace("20250901", "20260801"))
    region = (
        "SELECT rc.region, COUNT(*) FROM analytics.fact_transaction f JOIN analytics.dim_region rc "
        "ON rc.region_id = f.region_client_id GROUP BY rc.region"
    )
    assert "group_by=region_client" in sql_metric_skeleton(region)
    # non exprimable par query_metric : pas de squelette
    ferie = (
        "SELECT COUNT(*) FROM analytics.fact_transaction f JOIN analytics.dim_date d "
        "ON d.date_id = f.date_id WHERE f.statut = 'reussie' AND d.jour_ferie"
    )
    assert sql_metric_skeleton(ferie) is None
    assert sql_metric_skeleton("SELECT COUNT(*) FROM analytics.dim_agent a") is None


def test_check_antileak_detects_query_metric_examples():
    test = ds("test", [answer_item("T1", "Part des retraits échoués en août ?", TAUX_RETRAITS)])
    leak = {
        "examples": [
            {
                "id": "ex03",
                "question": "Proportion des dépôts non aboutis en octobre 2025 ?",
                "appel": {
                    "outil": "query_metric",
                    "arguments": qm(
                        metrics=["taux_echec"], filters=[{"dimension": "type", "values": ["depot"]}]
                    ),
                },
            }
        ]
    }
    rep = check_antileak(test, leak)
    assert rep.metric_calls == ["T1 ↔ ex03"] and not rep.ok
    leak["examples"][0]["appel"]["arguments"]["group_by"] = ["segment"]
    assert check_antileak(test, leak).ok


def test_check_antileak_detects_terminal_examples_on_same_subject():
    item = {
        "id": "T27",
        "category": "ambigu_hors_perimetre",
        "trap": "hors_modele",
        "question": "Quels sont les destinataires qui reçoivent le plus de transferts ?",
        "expected_kind": "refusal",
    }
    test = ds("test", [item])

    def ex(q, cat="hors_modele"):
        return {
            "examples": [
                {"id": "ex19", "question": q, "appel": {"outil": "refuse", "arguments": {"category": cat}}}
            ]
        }

    assert check_antileak(test, ex("Quel client a reçu le plus d'argent par transfert ?")).intents == [
        "T27 ↔ ex19"
    ]
    assert check_antileak(test, ex("Quel est le solde moyen des comptes clients ?")).ok
    assert check_antileak(test, ex("Quel client a reçu le plus d'argent par transfert ?", "contournement")).ok
