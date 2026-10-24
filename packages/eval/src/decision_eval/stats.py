"""Statistiques de l'évaluation (revue agentic §1.11 et §3.9).

- L'unité indépendante est la **question** : jamais de Wilson sur n × passes.
- pass^3 (référence) : part des questions réussies aux 3 passes, intervalle de Wilson sur n questions.
- pass@1 moyen : moyenne des taux de réussite par question, intervalle par bootstrap groupé par question.
- Cohérence : distribution 3/3, 2/3, 1/3, 0/3 (comptes bruts).
- Ablations : comparaison appariée sur les mêmes questions, McNemar exact (descriptif sous n ≈ 70).
- Comptes bruts par catégorie ; aucune conclusion sous 8 questions.
"""

from __future__ import annotations

import math
import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

MIN_QUESTIONS_FOR_CONCLUSION = 8
Z95 = 1.959963984540054


def wilson(k: int, n: int, z: float = Z95) -> tuple[float, float]:
    """Intervalle de score de Wilson (95 % par défaut). n = 0 → (0, 1)."""
    if n <= 0:
        return (0.0, 1.0)
    if not 0 <= k <= n:
        raise ValueError("0 <= k <= n requis")
    p = k / n
    den = 1 + z * z / n
    center = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (max(0.0, center - half), min(1.0, center + half))


def check_passes(outcomes: Mapping[str, Sequence[bool]], passes: int) -> None:
    """Chaque question doit avoir exactement `passes` résultats (sinon pass^k et cohérence sont faux)."""
    if passes < 1:
        raise ValueError("passes >= 1 requis")
    bad = {q: len(v) for q, v in outcomes.items() if len(v) != passes}
    if bad:
        detail = ", ".join(f"{q} : {n}" for q, n in sorted(bad.items())[:10])
        raise ValueError(f"{len(bad)} question(s) sans exactement {passes} passes ({detail})")


def pass_hat_k(outcomes: Mapping[str, Sequence[bool]], passes: int = 3) -> tuple[int, int]:
    """(questions réussies aux `passes` passes, n). Lève ValueError si une question n'a pas k passes."""
    check_passes(outcomes, passes)
    k = sum(1 for v in outcomes.values() if v and all(v))
    return k, len(outcomes)


def pass_at_1(outcomes: Mapping[str, Sequence[bool]]) -> float:
    """Moyenne sur les questions du taux de réussite par question."""
    rates = [sum(v) / len(v) for v in outcomes.values() if v]
    return sum(rates) / len(rates) if rates else 0.0


def cluster_bootstrap_pass_at_1(
    outcomes: Mapping[str, Sequence[bool]],
    *,
    n_boot: int = 10_000,
    seed: int = 20260930,
    alpha: float = 0.05,
) -> tuple[float, float]:
    """IC percentile du pass@1 moyen, en rééchantillonnant les questions (grappes)."""
    rates = [sum(v) / len(v) for v in outcomes.values() if v]
    if not rates:
        return (0.0, 1.0)
    rng = random.Random(seed)  # noqa: S311 - rééchantillonnage statistique, pas de cryptographie
    n = len(rates)
    means = sorted(sum(rates[rng.randrange(n)] for _ in range(n)) / n for _ in range(n_boot))
    lo = means[int(math.floor(alpha / 2 * (n_boot - 1)))]
    hi = means[int(math.ceil((1 - alpha / 2) * (n_boot - 1)))]
    return (lo, hi)


def consistency(outcomes: Mapping[str, Sequence[bool]], passes: int = 3) -> dict[str, int]:
    """Distribution « k/passes » (ex. 3/3, 2/3, 1/3, 0/3). ValueError si une question n'a pas k passes."""
    check_passes(outcomes, passes)
    dist = {f"{k}/{passes}": 0 for k in range(passes, -1, -1)}
    for v in outcomes.values():
        key = f"{sum(v)}/{passes}"
        dist[key] = dist.get(key, 0) + 1
    return dist


def mcnemar_exact(b: int, c: int) -> float:
    """p-valeur bilatérale exacte de McNemar (b, c = paires discordantes)."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / 2**n
    return min(1.0, 2 * tail)


@dataclass
class PairedComparison:
    n: int
    both: int
    only_base: int  # b : réussi par le bras de base seulement
    only_arm: int  # c : réussi par l'ablation seulement
    neither: int
    delta: float  # (taux ablation − taux base)
    p_value: float
    descriptive: bool  # True : sous-dimensionné (n < 70), à présenter comme descriptif

    def to_dict(self) -> dict[str, float | int | bool]:
        return self.__dict__.copy()


def paired_mcnemar(base: Mapping[str, bool], arm: Mapping[str, bool]) -> PairedComparison:
    """Comparaison appariée (sur les questions communes) de deux bras binaires (ex. pass^3)."""
    common = sorted(set(base) & set(arm))
    both = sum(1 for q in common if base[q] and arm[q])
    b = sum(1 for q in common if base[q] and not arm[q])
    c = sum(1 for q in common if arm[q] and not base[q])
    neither = len(common) - both - b - c
    n = len(common)
    delta = ((both + c) - (both + b)) / n if n else 0.0
    return PairedComparison(n, both, b, c, neither, delta, mcnemar_exact(b, c), n < 70)


def category_counts(
    outcomes: Mapping[str, Sequence[bool]], categories: Mapping[str, str]
) -> dict[str, dict[str, object]]:
    """Comptes bruts par catégorie (pass^3 et pass@1), avec l'indicateur « pas de conclusion »."""
    out: dict[str, dict[str, object]] = {}
    for q, v in outcomes.items():
        cat = categories.get(q, "?")
        d = out.setdefault(cat, {"n": 0, "pass3": 0, "pass1_sum": 0.0})
        d["n"] = int(d["n"]) + 1  # type: ignore[call-overload]
        d["pass3"] = int(d["pass3"]) + (1 if v and all(v) else 0)  # type: ignore[call-overload]
        d["pass1_sum"] = float(d["pass1_sum"]) + (sum(v) / len(v) if v else 0.0)  # type: ignore[arg-type]
    for d in out.values():
        n = int(d["n"])  # type: ignore[call-overload]
        d["pass1"] = round(float(d.pop("pass1_sum")) / n, 4) if n else 0.0  # type: ignore[arg-type]
        d["conclusion_possible"] = n >= MIN_QUESTIONS_FOR_CONCLUSION
    return dict(sorted(out.items()))


def percentile(values: Sequence[float], q: float) -> float | None:
    """Percentile par interpolation linéaire (q dans [0, 100])."""
    if not values:
        return None
    s = sorted(values)
    if len(s) == 1:
        return s[0]
    pos = (len(s) - 1) * q / 100
    lo, hi = math.floor(pos), math.ceil(pos)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def honest_sentence(k: int, n: int, target: float = 0.80, metric: str = "pass^3") -> str:
    """Phrase honnête sur l'atteinte de la cible O1 (point estimé et intervalle publiés)."""
    lo, hi = wilson(k, n)
    p = k / n if n else 0.0
    base = f"{metric} = {k}/{n} = {p:.1%} (Wilson 95 % : [{lo:.1%} ; {hi:.1%}])."
    if n == 0:
        return "Aucune question évaluée : aucune conclusion possible."
    if lo >= target:
        return base + f" La cible de {target:.0%} est démontrée (borne basse ≥ cible)."
    if p >= target:
        return base + (
            f" Le point estimé atteint la cible de {target:.0%}, mais l'intervalle "
            f"descend à {lo:.1%} : la cible n'est pas démontrée statistiquement."
        )
    return base + f" La cible de {target:.0%} n'est pas atteinte."
