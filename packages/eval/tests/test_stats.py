"""Tests des statistiques (Wilson, pass^k, bootstrap groupé, McNemar exact)."""

from __future__ import annotations

import pytest
from decision_eval import stats


def test_wilson_reference_values():
    # Repères de la revue agentic §3.9 : 32/40 → [65 %, 90 %] ; 37/40 → [80 %, 97 %]
    lo, hi = stats.wilson(32, 40)
    assert lo == pytest.approx(0.652, abs=1e-3) and hi == pytest.approx(0.895, abs=1e-3)
    lo, hi = stats.wilson(37, 40)
    assert lo == pytest.approx(0.801, abs=2e-3) and hi == pytest.approx(0.974, abs=2e-3)
    lo, hi = stats.wilson(64, 80)
    assert lo == pytest.approx(0.70, abs=5e-3) and hi == pytest.approx(0.87, abs=5e-3)


def test_wilson_edges():
    assert stats.wilson(0, 0) == (0.0, 1.0)
    lo, hi = stats.wilson(0, 30)
    assert lo == 0.0 and hi >= 0.11  # « borne haute ≥ 11 % même à 0 erreur »
    lo, hi = stats.wilson(10, 10)
    assert hi == pytest.approx(1.0) and lo < 1
    with pytest.raises(ValueError):
        stats.wilson(5, 3)


OUT = {
    "q1": [True, True, True],
    "q2": [True, False, True],
    "q3": [False, False, False],
    "q4": [True, True, True],
}


def test_pass_hat_and_pass1():
    assert stats.pass_hat_k(OUT) == (2, 4)
    assert stats.pass_at_1(OUT) == pytest.approx((1 + 2 / 3 + 0 + 1) / 4)


def test_consistency():
    assert stats.consistency(OUT) == {"3/3": 2, "2/3": 1, "1/3": 0, "0/3": 1}


def test_cluster_bootstrap():
    lo, hi = stats.cluster_bootstrap_pass_at_1(OUT, n_boot=2000)
    p1 = stats.pass_at_1(OUT)
    assert 0 <= lo <= p1 <= hi <= 1
    # déterministe (graine figée)
    assert stats.cluster_bootstrap_pass_at_1(OUT, n_boot=2000) == (lo, hi)
    same = {f"q{i}": [True, True, True] for i in range(10)}
    assert stats.cluster_bootstrap_pass_at_1(same, n_boot=500) == (1.0, 1.0)


def test_mcnemar_exact():
    assert stats.mcnemar_exact(0, 0) == 1.0
    # b=0, c=6 : p = 2 × 0,5^6 = 0,03125
    assert stats.mcnemar_exact(0, 6) == pytest.approx(0.03125)
    assert stats.mcnemar_exact(6, 0) == pytest.approx(0.03125)
    # b=2, c=8 : p = 2 × P(X ≤ 2 | n=10) = 2 × 56/1024
    assert stats.mcnemar_exact(2, 8) == pytest.approx(2 * 56 / 1024)
    assert stats.mcnemar_exact(5, 5) == 1.0


def test_paired_mcnemar():
    base = {"a": True, "b": True, "c": False, "d": True, "e": False}
    arm = {"a": True, "b": False, "c": False, "d": False, "e": True, "z": True}
    cmp = stats.paired_mcnemar(base, arm)
    assert cmp.n == 5 and cmp.both == 1 and cmp.only_base == 2 and cmp.only_arm == 1 and cmp.neither == 1
    assert cmp.delta == pytest.approx((2 - 3) / 5)
    assert cmp.descriptive is True
    assert cmp.p_value == pytest.approx(1.0)


def test_category_counts():
    cats = {"q1": "kpi", "q2": "kpi", "q3": "classement", "q4": "classement"}
    out = stats.category_counts(OUT, cats)
    assert out["kpi"]["n"] == 2 and out["kpi"]["pass3"] == 1
    assert out["classement"]["pass1"] == pytest.approx(0.5)
    assert out["kpi"]["conclusion_possible"] is False
    big = {f"q{i}": [True] for i in range(8)}
    assert stats.category_counts(big, dict.fromkeys(big, "x"))["x"]["conclusion_possible"] is True


def test_percentile():
    assert stats.percentile([], 50) is None
    assert stats.percentile([5], 90) == 5
    assert stats.percentile([1, 2, 3, 4], 50) == pytest.approx(2.5)
    assert stats.percentile(list(range(1, 11)), 90) == pytest.approx(9.1)


def test_honest_sentence():
    assert "n'est pas démontrée" in stats.honest_sentence(32, 40)
    assert "est démontrée" in stats.honest_sentence(38, 40)
    assert "n'est pas atteinte" in stats.honest_sentence(20, 40)
    assert "Aucune" in stats.honest_sentence(0, 0)
