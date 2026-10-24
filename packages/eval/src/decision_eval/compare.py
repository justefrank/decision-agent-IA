"""Correcteur de l'évaluation (SRS §11, revue agentic §3.9).

Une question attendue en réponse est réussie si, et seulement si :
  1. le résultat exécuté correspond à la référence (`compare_execution`) ;
  2. les chiffres cités (registre `AssistantMessage.facts`) correspondent à la référence (`compare_facts`) ;
  3. la période résolue est juste (`compare_period`, sur `resolved_state`) ;
  4. le périmètre résolu est juste (`compare_scope`, sur `resolved_state`).
Une question attendue en clarification ou en refus est réussie si l'intention (`kind`) est la bonne.

Règles de comparaison d'exécution :
  - multi-ensemble de tuples, projection des colonnes de référence sur les colonnes obtenues par type
    et par valeurs ; colonnes obtenues en trop tolérées ; colonnes de période projetées par la valeur
    de `periode` (courante / comparaison) quand le résultat est au format long ;
  - ordre exigé seulement si `ordered`, en acceptant tout ordre compatible avec les ex æquo ;
    `tie_tolerant` : à la frontière d'un top-k, les lignes doivent être des ex æquo calculés en base
    (`ResultSet.boundary`), éventuellement plus nombreux que k ;
  - entiers exacts ; non-entiers en tolérance relative 1e-4 ;
  - résultat vide attendu : aucune ligne obtenue.
"""

from __future__ import annotations

import itertools
import math
import re
import unicodedata
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from decision_core.models import AssistantMessage, Fact

from .dataset import DATA_START, REFERENCE_DATE, EvalItem

REL_TOL = 1e-4
ABS_TOL = 1e-9
NUMERIC_UNITS = {"count", "xof", "ratio", "pct", "pp"}
HORS_AGENT_LABELS = {"non applicable", "hors agent"}
MAX_ASSIGNMENTS = 20_000


# --------------------------------------------------------------------------------------------
# Résultats tabulaires
# --------------------------------------------------------------------------------------------


@dataclass
class ResultSet:
    columns: list[str]
    rows: list[tuple[Any, ...]]
    # Classement `tie_tolerant` : lignes de la référence SANS LIMIT dont la clé de classement vaut celle
    # de la dernière ligne (ensemble des ex æquo à la frontière), calculées en base par l'exécuteur.
    boundary: list[tuple[Any, ...]] | None = None

    @classmethod
    def of(cls, columns: list[str], rows: list[list[Any]] | list[tuple[Any, ...]]) -> ResultSet:
        return cls(list(columns), [tuple(r) for r in rows])

    def column(self, j: int) -> list[Any]:
        return [r[j] for r in self.rows]


@dataclass
class CheckResult:
    ok: bool
    reason: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass
class Verdict:
    passed: bool
    checks: dict[str, bool]
    reasons: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {"passed": self.passed, "checks": self.checks, "reasons": self.reasons}


# --------------------------------------------------------------------------------------------
# Normalisation des valeurs
# --------------------------------------------------------------------------------------------


def is_number(v: Any) -> bool:
    return isinstance(v, int | float | Decimal) and not isinstance(v, bool)


def to_float(v: Any) -> float:
    return float(v)


def is_integral(v: Any) -> bool:
    if isinstance(v, bool):
        return False
    if isinstance(v, int):
        return True
    if isinstance(v, Decimal):
        return v.is_finite() and v == v.to_integral_value()
    if isinstance(v, float):
        return math.isfinite(v) and v.is_integer()
    return False


def norm_text(v: Any) -> str:
    s = unicodedata.normalize("NFKD", str(v)).encode("ascii", "ignore").decode()
    return " ".join(s.casefold().split())


def _as_date(v: Any) -> date | None:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if isinstance(v, str):
        try:
            return date.fromisoformat(v.strip()[:10])
        except ValueError:
            return None
    return None


def kind_of(v: Any) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "bool"
    if is_number(v):
        return "number"
    if isinstance(v, date | datetime):
        return "date"
    return "text"


def numbers_equal(ref: Any, got: Any, *, percent_equivalence: bool = True) -> bool:
    """Entiers exacts ; sinon tolérance relative 1e-4 (et équivalence ratio ↔ pourcentage)."""
    if not (is_number(ref) and is_number(got)):
        return False
    if is_integral(ref):
        if is_integral(got):
            return Decimal(str(ref)) == Decimal(str(got))
        return False
    r, g = to_float(ref), to_float(got)
    if _close(r, g):
        return True
    return percent_equivalence and abs(r) <= 1 and _close(r * 100, g)


def _close(a: float, b: float) -> bool:
    return abs(a - b) <= max(REL_TOL * max(abs(a), abs(b)), ABS_TOL)


def values_equal(ref: Any, got: Any) -> bool:
    if ref is None or got is None:
        return ref is None and got is None
    if isinstance(ref, bool):
        if isinstance(got, bool):
            return ref == got
        return norm_text(got) in ({"true", "oui", "vrai", "t"} if ref else {"false", "non", "faux", "f"})
    if is_number(ref):
        if isinstance(got, str):
            try:
                got = Decimal(got.replace(" ", "").replace(",", "."))
            except ArithmeticError:
                return False
        return numbers_equal(ref, got)
    if isinstance(ref, date | datetime):
        rd = _as_date(ref)
        gd = _as_date(got)
        if gd is not None:
            return rd == gd
        # « 2026-04 » pour un mois (date de début de mois)
        if isinstance(got, str) and rd is not None and rd.day == 1:
            return got.strip()[:7] == rd.isoformat()[:7] and len(got.strip()) == 7
        return False
    return norm_text(ref) == norm_text(got)


def _sort_key(v: Any) -> tuple[int, Any]:
    k = kind_of(v)
    if k == "null":
        return (0, 0)
    if k == "number":
        return (1, to_float(v))
    if k == "bool":
        return (2, int(v))
    if k == "date":
        d = _as_date(v)
        return (3, d.isoformat() if d else "")
    return (4, norm_text(v))


def column_compatible(ref_col: list[Any], got_col: list[Any]) -> bool:
    """Vrai si les deux colonnes ont le même multi-ensemble de valeurs (avec tolérance)."""
    if len(ref_col) != len(got_col):
        return False
    rs = sorted(ref_col, key=_sort_key)
    gs = sorted(got_col, key=_sort_key)
    if all(values_equal(a, b) for a, b in zip(rs, gs, strict=True)):
        return True
    # Repli : appariement exact (cas des égalités en tolérance mal triées ou des pourcentages)
    return _bipartite([(a,) for a in ref_col], [(b,) for b in got_col])


def rows_equal(ref: tuple[Any, ...], got: tuple[Any, ...]) -> bool:
    return len(ref) == len(got) and all(values_equal(a, b) for a, b in zip(ref, got, strict=True))


def _bipartite(ref_rows: list[tuple[Any, ...]], got_rows: list[tuple[Any, ...]]) -> bool:
    """Appariement parfait ligne à ligne (algorithme de Kuhn) sous l'égalité tolérante."""
    if len(ref_rows) != len(got_rows):
        return False
    n = len(ref_rows)
    adj = [[j for j in range(n) if rows_equal(ref_rows[i], got_rows[j])] for i in range(n)]
    if any(not a for a in adj):
        return False
    match_got: list[int] = [-1] * n

    def try_assign(i: int, seen: list[bool]) -> bool:
        for j in adj[i]:
            if seen[j]:
                continue
            seen[j] = True
            if match_got[j] == -1 or try_assign(match_got[j], seen):
                match_got[j] = i
                return True
        return False

    return all(try_assign(i, [False] * n) for i in range(n))


def multiset_equal(ref_rows: list[tuple[Any, ...]], got_rows: list[tuple[Any, ...]]) -> bool:
    if len(ref_rows) != len(got_rows):
        return False
    rs = sorted(ref_rows, key=lambda r: tuple(_sort_key(v) for v in r))
    gs = sorted(got_rows, key=lambda r: tuple(_sort_key(v) for v in r))
    if all(rows_equal(a, b) for a, b in zip(rs, gs, strict=True)):
        return True
    return _bipartite(ref_rows, got_rows)


# --------------------------------------------------------------------------------------------
# Préparation du résultat obtenu
# --------------------------------------------------------------------------------------------


def pivot_periode(rs: ResultSet) -> ResultSet | None:
    """Format long de query_metric (colonne `periode` ∈ {courante, comparaison}) → format large."""
    names = [norm_text(c) for c in rs.columns]
    if "periode" not in names:
        return None
    p = names.index("periode")
    values = {norm_text(r[p]) for r in rs.rows}
    if not values <= {"courante", "comparaison"}:
        return None
    measures = [j for j in range(len(rs.columns)) if j != p and any(is_number(r[j]) for r in rs.rows)]
    keys = [j for j in range(len(rs.columns)) if j != p and j not in measures]
    groups: dict[tuple[Any, ...], dict[str, tuple[Any, ...]]] = {}
    order: list[tuple[Any, ...]] = []
    for r in rs.rows:
        k = tuple(r[j] for j in keys)
        nk = tuple(norm_text(x) for x in k)
        if nk not in groups:
            groups[nk] = {"__key__": k}
            order.append(nk)
        groups[nk][norm_text(r[p])] = tuple(r[j] for j in measures)
    cols = [rs.columns[j] for j in keys]
    cols += [rs.columns[j] for j in measures] + [f"{rs.columns[j]}__comparaison" for j in measures]
    rows: list[tuple[Any, ...]] = []
    empty = tuple(None for _ in measures)
    for nk in order:
        g = groups[nk]
        rows.append(tuple(g["__key__"]) + g.get("courante", empty) + g.get("comparaison", empty))
    return ResultSet(cols, rows)


def drop_hors_agent_zero(rs: ResultSet) -> ResultSet:
    keep = []
    for r in rs.rows:
        labels = {norm_text(v) for v in r if isinstance(v, str)}
        nums = [v for v in r if is_number(v)]
        if labels & HORS_AGENT_LABELS and all(to_float(v) == 0 for v in nums):
            continue
        keep.append(r)
    return ResultSet(rs.columns, keep)


def result_from_message(msg: AssistantMessage) -> ResultSet | None:
    if msg.table is None:
        return None
    return ResultSet.of([c.name for c in msg.table.columns], msg.table.rows)


# --------------------------------------------------------------------------------------------
# Comparaison d'exécution
# --------------------------------------------------------------------------------------------


def _candidate_columns(ref: ResultSet, got: ResultSet) -> list[list[int]]:
    cands: list[list[int]] = []
    for j in range(len(ref.columns)):
        rc = ref.column(j)
        rkinds = {kind_of(v) for v in rc} - {"null"}
        out = []
        for k in range(len(got.columns)):
            gc = got.column(k)
            gkinds = {kind_of(v) for v in gc} - {"null"}
            if rkinds and gkinds and not _kinds_compatible(rkinds, gkinds):
                continue
            if column_compatible(rc, gc):
                out.append(k)
        cands.append(out)
    return cands


def _kinds_compatible(r: set[str], g: set[str]) -> bool:
    if r == g:
        return True
    # dates et booléens peuvent revenir en texte ; nombres en texte non admis
    return (r <= {"date"} and g <= {"date", "text"}) or (r <= {"bool"} and g <= {"bool", "text"})


def _required_columns(item: EvalItem | None, ref: ResultSet) -> tuple[list[int], list[list[int]]]:
    """Colonnes obligatoires et groupes « au moins une » (column_groups)."""
    groups_idx: list[list[int]] = []
    in_group: set[int] = set()
    if item is not None:
        lower = [c.lower() for c in ref.columns]
        for g in item.column_groups:
            idx = [lower.index(c.lower()) for c in g if c.lower() in lower]
            if idx:
                groups_idx.append(idx)
                in_group.update(idx)
    mandatory = [j for j in range(len(ref.columns)) if j not in in_group]
    return mandatory, groups_idx


def _assignments(
    ref: ResultSet, got: ResultSet, cands: list[list[int]], mandatory: list[int], groups: list[list[int]]
) -> Iterator[dict[int, int]]:
    """Génère des projections ref→got injectives (dict colonne ref → colonne got)."""
    # Un représentant par groupe « au moins une colonne » : on essaie chaque colonne du groupe.
    group_choices: list[list[int]] = [[j for j in g if cands[j]] for g in groups]
    if any(not c for c in group_choices):
        return
    budget = [MAX_ASSIGNMENTS]
    for chosen in itertools.product(*group_choices):
        cols = sorted(set(mandatory) | set(chosen), key=lambda j: len(cands[j]))
        yield from _assign_rec(cols, 0, cands, {}, set(), budget)


def _assign_rec(
    cols: list[int], t: int, cands: list[list[int]], assign: dict[int, int], used: set[int], budget: list[int]
) -> Iterator[dict[int, int]]:
    if budget[0] <= 0:
        return
    if t == len(cols):
        budget[0] -= 1
        yield dict(assign)
        return
    j = cols[t]
    for k in cands[j]:
        if k in used:
            continue
        assign[j] = k
        used.add(k)
        yield from _assign_rec(cols, t + 1, cands, assign, used, budget)
        used.discard(k)
        del assign[j]


def _check_order(
    ref_rows: list[tuple[Any, ...]],
    got_rows: list[tuple[Any, ...]],
    key_idx: list[int],
    tie_tolerant: bool,
    boundary: list[tuple[Any, ...]] | None = None,
) -> bool:
    """Ordre compatible avec la référence, ex æquo (même clé de classement) dans n'importe quel ordre.

    `tie_tolerant` : à la frontière (dernier groupe de rang), les lignes obtenues doivent avoir la clé
    de la frontière ET, si `boundary` (ex æquo calculés en base, projetés) est connu, appartenir à cet
    ensemble ; des lignes en trop sont alors acceptées si ce sont d'autres ex æquo. Sans `boundary`,
    l'identité à la frontière n'est pas vérifiable : seules les lignes en nombre exact sont acceptées,
    et une frontière sans cœur (top-1 ex æquo) exige l'identité de la référence.
    """
    if len(got_rows) < len(ref_rows) or (len(got_rows) > len(ref_rows) and not (tie_tolerant and boundary)):
        return False
    # Groupes de rang consécutifs dans la référence
    groups: list[list[tuple[Any, ...]]] = []
    for r in ref_rows:
        if (
            key_idx
            and groups
            and rows_equal(tuple(groups[-1][0][i] for i in key_idx), tuple(r[i] for i in key_idx))
        ):
            groups[-1].append(r)
        else:
            groups.append([r])
    pos = 0
    for gi, grp in enumerate(groups):
        last = gi == len(groups) - 1
        if last and tie_tolerant and key_idx:
            chunk = got_rows[pos:]
            key = tuple(grp[0][i] for i in key_idx)
            if not all(rows_equal(tuple(c[i] for i in key_idx), key) for c in chunk):
                return False
            if boundary is not None:
                if len(chunk) > len(boundary) or not _distinct_members(chunk, boundary):
                    return False
            elif len(groups) == 1 and not multiset_equal(grp, chunk):
                return False
            return True
        chunk = got_rows[pos : pos + len(grp)]
        pos += len(grp)
        if not multiset_equal(grp, chunk):
            return False
    return pos == len(got_rows)


def _distinct_members(rows: list[tuple[Any, ...]], pool: list[tuple[Any, ...]]) -> bool:
    """Chaque ligne appartient à `pool` et deux lignes ne désignent pas la même ligne du pool."""
    if any(rows_equal(a, b) for a, b in itertools.combinations(rows, 2)):
        return False
    return all(any(rows_equal(r, b) for b in pool) for r in rows)


def period_pairs(ref: ResultSet, item: EvalItem | None) -> list[tuple[int, int]]:
    """Couples (colonne période courante, colonne période de comparaison) de la référence.

    Dérivés du SQL de référence : pour une même métrique, des agrégats filtrés sur des périodes
    différentes (FILTER sur des dates) ; le premier dans l'ordre du SELECT est la période courante
    (convention des jeux). À défaut, colonnes nommées `courante` / `precedente` (ou `comparaison`).
    """
    lower = [c.lower() for c in ref.columns]
    pairs: list[tuple[int, int]] = []
    if item is not None and item.reference_sql:
        from .antileak import select_period_signatures

        try:
            sigs = select_period_signatures(item.reference_sql)
        except Exception:  # noqa: BLE001 - SQL illisible : pas de couple
            sigs = []
        by_metric: dict[str, list[tuple[str, tuple[str, ...]]]] = {}
        for alias, metric, sig in sigs:
            if metric and sig and alias in lower:
                by_metric.setdefault(metric, []).append((alias, sig))
        for entries in by_metric.values():
            cur_alias, cur_sig = entries[0]
            for alias, sig in entries[1:]:
                if sig != cur_sig:
                    pairs.append((lower.index(cur_alias), lower.index(alias)))
    if not pairs and "courante" in lower:
        for name in ("precedente", "comparaison", "precedent"):
            if name in lower:
                pairs.append((lower.index("courante"), lower.index(name)))
                break
    return pairs


COMPARAISON_SUFFIX = "__comparaison"


def compare_execution(ref: ResultSet, got: ResultSet | None, item: EvalItem | None = None) -> CheckResult:
    expected_empty = bool(item and item.expected_empty)
    ordered = bool(item and item.ordered)
    tie_tolerant = bool(item and item.tie_tolerant)
    prefix_ok = bool(item and item.prefix_ok)

    if expected_empty:
        if ref.rows:
            return CheckResult(False, "reference_non_vide", {"ref_rows": len(ref.rows)})
        if got is None:
            return CheckResult(True)
        if item and item.tolerate_hors_agent_zero:
            got = drop_hors_agent_zero(got)
        return CheckResult(
            not got.rows, None if not got.rows else "vide_attendu", {"got_rows": len(got.rows)}
        )

    if got is None:
        return CheckResult(False, "aucun_resultat")
    if item and item.tolerate_hors_agent_zero:
        got = drop_hors_agent_zero(got)
    if not ref.rows:
        return CheckResult(not got.rows, None if not got.rows else "lignes_en_trop")

    pairs = period_pairs(ref, item)
    variants: list[tuple[ResultSet, bool]] = [(got, False)]
    pv = pivot_periode(got)
    if pv is not None:
        variants.append((pv, True))

    last_reason = "colonnes_introuvables"
    for g, pivoted in variants:
        gg = g
        if ordered and prefix_ok and len(g.rows) > len(ref.rows):
            gg = ResultSet(g.columns, g.rows[: len(ref.rows)])
        if len(gg.rows) != len(ref.rows):
            last_reason = "nombre_de_lignes"
            if not tie_tolerant:
                continue
        res = _match_with_projection(ref, gg, item, ordered, tie_tolerant, pairs if pivoted else None)
        if res.ok:
            return res
        last_reason = res.reason or last_reason
    return CheckResult(False, last_reason, {"ref_rows": len(ref.rows), "got_rows": len(got.rows)})


def _restrict_periods(
    ref: ResultSet, got: ResultSet, cands: list[list[int]], pairs: list[tuple[int, int]]
) -> None:
    """Résultat pivoté depuis `periode` : la colonne courante de la référence ne peut aller que sur une
    mesure de la période courante, la colonne de comparaison que sur `<mesure>__comparaison`."""
    is_cmp = [c.endswith(COMPARAISON_SUFFIX) for c in got.columns]
    cmp_cols = {pj for _, pj in pairs}
    for j in range(len(ref.columns)):
        if j in cmp_cols:
            cands[j] = [k for k in cands[j] if is_cmp[k]]
        elif any(is_number(v) for v in ref.column(j)):
            cands[j] = [k for k in cands[j] if not is_cmp[k]]


def _pairs_consistent(got: ResultSet, assign: dict[int, int], pairs: list[tuple[int, int]]) -> bool:
    return all(
        got.columns[assign[pj]] == got.columns[assign[cj]] + COMPARAISON_SUFFIX
        for cj, pj in pairs
        if cj in assign and pj in assign
    )


def _match_with_projection(
    ref: ResultSet,
    got: ResultSet,
    item: EvalItem | None,
    ordered: bool,
    tie_tolerant: bool,
    pairs: list[tuple[int, int]] | None = None,
) -> CheckResult:
    mandatory, groups = _required_columns(item, ref)
    key_names = [c.lower() for c in (item.order_by if item else [])]
    lower = [c.lower() for c in ref.columns]
    key_idx_all = [lower.index(c) for c in key_names if c in lower]

    if tie_tolerant and ordered and key_idx_all:
        # Les colonnes d'identité peuvent différer à la frontière : projection par la clé et par
        # préfixe sans les lignes de la frontière.
        return _match_tie_tolerant(ref, got, mandatory, groups, key_idx_all)
    if len(got.rows) != len(ref.rows):
        return CheckResult(False, "nombre_de_lignes")

    cands = _candidate_columns(ref, got)
    if pairs:
        _restrict_periods(ref, got, cands, pairs)
    if any(not cands[j] for j in mandatory):
        return CheckResult(
            False,
            "colonnes_introuvables" if not pairs else "periodes_inversees",
            {"manquantes": [ref.columns[j] for j in mandatory if not cands[j]]},
        )
    for assign in _assignments(ref, got, cands, mandatory, groups):
        if pairs and not _pairs_consistent(got, assign, pairs):
            continue
        ref_idx = sorted(assign)
        rproj = [tuple(r[j] for j in ref_idx) for r in ref.rows]
        gproj = [tuple(r[assign[j]] for j in ref_idx) for r in got.rows]
        if not multiset_equal(rproj, gproj):
            continue
        if ordered:
            kpos = [ref_idx.index(k) for k in key_idx_all if k in ref_idx]
            if not _check_order(rproj, gproj, kpos, tie_tolerant=False):
                continue
        return CheckResult(
            True, detail={"projection": {ref.columns[j]: got.columns[k] for j, k in assign.items()}}
        )
    return CheckResult(False, "ordre" if ordered else "valeurs")


def _match_tie_tolerant(
    ref: ResultSet, got: ResultSet, mandatory: list[int], groups: list[list[int]], key_idx: list[int]
) -> CheckResult:
    n_ref = len(ref.rows)
    if len(got.rows) < n_ref or (len(got.rows) > n_ref and not ref.boundary):
        return CheckResult(False, "nombre_de_lignes")
    got_head = ResultSet(got.columns, got.rows[:n_ref])
    ref_key_last = tuple(ref.rows[-1][i] for i in key_idx)
    n_core = sum(1 for r in ref.rows if not rows_equal(tuple(r[i] for i in key_idx), ref_key_last))
    core = ResultSet(ref.columns, ref.rows[:n_core])
    got_core = ResultSet(got.columns, got.rows[:n_core])
    if n_core:
        cands_core = _candidate_columns(core, got_core)
    else:
        # Frontière seule (top-1 ex æquo) : candidats par type ; l'identité est vérifiée ensuite
        # contre l'ensemble des ex æquo calculé en base.
        cands_core = [
            [k for k in range(len(got.columns)) if _kinds_ok(ref.column(j), got_head.column(k))]
            for j in range(len(ref.columns))
        ]
    # Les colonnes de clé doivent aussi correspondre sur toutes les lignes
    cands_full = _candidate_columns(ref, got_head)
    for j in key_idx:
        cands_core[j] = [k for k in cands_core[j] if k in cands_full[j]]
    if any(not cands_core[j] for j in mandatory):
        return CheckResult(False, "colonnes_introuvables")
    for assign in _assignments(ref, got, cands_core, mandatory, groups):
        ref_idx = sorted(assign)
        rproj = [tuple(r[j] for j in ref_idx) for r in ref.rows]
        gproj = [tuple(r[assign[j]] for j in ref_idx) for r in got.rows]
        bproj = [tuple(r[j] for j in ref_idx) for r in ref.boundary] if ref.boundary is not None else None
        kpos = [ref_idx.index(k) for k in key_idx if k in ref_idx]
        if _check_order(rproj, gproj, kpos, tie_tolerant=True, boundary=bproj):
            return CheckResult(True)
    return CheckResult(False, "ordre")


def _kinds_ok(ref_col: list[Any], got_col: list[Any]) -> bool:
    rk = {kind_of(v) for v in ref_col} - {"null"}
    gk = {kind_of(v) for v in got_col} - {"null"}
    return not rk or not gk or _kinds_compatible(rk, gk)


# --------------------------------------------------------------------------------------------
# Faits cités
# --------------------------------------------------------------------------------------------


def cited_facts(msg: AssistantMessage) -> list[Fact]:
    """Faits numériques cités : ceux qui portent un rendu si le registre en contient, sinon tous."""
    facts = [f for f in msg.facts if f.unit in NUMERIC_UNITS and is_number(f.value)]
    if any(f.rendered for f in facts):
        facts = [f for f in facts if f.rendered]
    return facts


ID_COLUMN_RE = re.compile(r"(^|_)id$")
FACT_KINDS = ("cell", "total", "row_count", "ecart", "variation", "ecart_pp", "part", "derive")


def fact_kind(f: Fact) -> str:
    """Nature d'un fait selon le registre de l'agent (decision_agent.facts) : `f…` = cellule, total ou
    nombre de lignes ; `d…` = dérivé (écart, variation, écart en points, part), reconnus au libellé."""
    label = norm_text(f.label)
    for prefix, kind in (
        ("ecart en points", "ecart_pp"),
        ("ecart", "ecart"),
        ("variation", "variation"),
        ("part de", "part"),
        ("total", "total"),
        ("nombre de lignes", "row_count"),
    ):
        if label.startswith(prefix):
            return kind
    return "derive" if f.id.startswith("d") else "cell"


@dataclass
class RefFacts:
    """Valeurs citables de la référence, rattachées à leurs lignes et colonnes."""

    ref: ResultSet
    measures: list[int]
    pairs: list[tuple[int, int]]
    identities: list[set[str]]  # par ligne : valeurs d'identité normalisées (dimensions, id, dates)
    extra_rows: bool = False  # ligne « hors agent » à zéro tolérée dans le tableau obtenu

    @classmethod
    def build(cls, ref: ResultSet, item: EvalItem | None = None) -> RefFacts:
        measures = [
            j
            for j, c in enumerate(ref.columns)
            if any(is_number(r[j]) for r in ref.rows) and not ID_COLUMN_RE.search(c.lower())
        ]
        identities = []
        for r in ref.rows:
            ids = set()
            for j, v in enumerate(r):
                if j in measures or v is None:
                    continue
                d = _as_date(v) if isinstance(v, date | datetime) else None
                ids.add(d.isoformat() if d else norm_text(v))
            identities.append(ids)
        return cls(
            ref,
            measures,
            period_pairs(ref, item),
            identities,
            bool(item and item.tolerate_hors_agent_zero),
        )

    def rows_for(self, f: Fact) -> list[int]:
        """Lignes désignées par le libellé du fait (« Agents actifs — Dakar — août 2026 ») ; toutes
        les lignes si le libellé n'en nomme aucune."""
        parts = [norm_text(p) for p in f.label.split("—")]
        m = re.match(r"^part de (.+?) dans ", parts[0]) if parts else None
        if m:
            parts.append(m.group(1))
        named = {p for p in parts if p}
        rows = [i for i, ids in enumerate(self.identities) if ids & named]
        return rows or list(range(len(self.ref.rows)))

    def _num(self, i: int, j: int) -> float | None:
        v = self.ref.rows[i][j]
        return to_float(v) if is_number(v) else None

    def candidates(self, f: Fact) -> list[float]:
        kind = fact_kind(f)
        rows = self.rows_for(f)
        out: list[float] = []
        if kind == "cell":
            out += [v for i in rows for j in self.measures if (v := self._num(i, j)) is not None]
        elif kind == "total":
            out += [sum(self._num(i, j) or 0.0 for i in range(len(self.ref.rows))) for j in self.measures]
        elif kind == "row_count":
            out += [float(len(self.ref.rows))] + ([float(len(self.ref.rows) + 1)] if self.extra_rows else [])
        derived = {
            "ecart": ("ecart",),
            "variation": ("variation",),
            "ecart_pp": ("ecart_pp",),
            "part": ("part",),
            "derive": {"pct": ("variation", "part"), "pp": ("ecart_pp",)}.get(f.unit, ("ecart",)),
        }.get(kind, ())
        for d in derived:
            if d == "part":
                for j in self.measures:
                    total = sum(self._num(i, j) or 0.0 for i in range(len(self.ref.rows)))
                    if total:
                        out += [100 * v / total for i in rows if (v := self._num(i, j)) is not None]
                continue
            for i in rows:
                for cj, pj in self.pairs:
                    c, p = self._num(i, cj), self._num(i, pj)
                    if c is None or p is None:
                        continue
                    if d == "ecart":
                        out.append(c - p)
                    elif d == "variation" and p:
                        out.append(100 * (c - p) / abs(p))
                    elif d == "ecart_pp":
                        out.append((c - p) * 100 if abs(c) <= 1 and abs(p) <= 1 else c - p)
        return out


def reference_candidates(ref: ResultSet, item: EvalItem | None = None) -> list[float]:
    """Toutes les valeurs citables de la référence (cellules, totaux, dérivés orientés)."""
    rf = RefFacts.build(ref, item)
    probes = [
        Fact(id=i, value=0, unit=u, label=lab)
        for i, u, lab in (
            ("f", "count", "x"),
            ("f", "count", "Total"),
            ("f", "count", "Nombre de lignes"),
            ("d", "xof", "Écart"),
            ("d", "pct", "Variation"),
            ("d", "pp", "Écart en points"),
            ("d", "pct", "Part de"),
        )
    ]
    return [c for p in probes for c in rf.candidates(p)]


def fact_matches(f: Fact, candidates: list[float]) -> bool:
    v = f.value
    assert is_number(v)
    for c in candidates:
        if is_integral(v) and float(c).is_integer() and f.unit in {"count", "xof"}:
            if Decimal(str(v)) == Decimal(str(int(c))):
                return True
            continue
        fv = to_float(v)
        if _close(fv, c) or _close(fv, c * 100) or _close(fv / 100, c):
            return True
    return False


def compare_facts(ref: ResultSet, msg: AssistantMessage, item: EvalItem | None = None) -> CheckResult:
    facts = cited_facts(msg)
    if item and item.expected_empty:
        bad = [f.id for f in facts if to_float(f.value) != 0]  # type: ignore[arg-type]
        return CheckResult(not bad, None if not bad else "chiffre_sur_resultat_vide", {"facts": bad})
    if not facts:
        return CheckResult(False, "aucun_chiffre_cite")
    rf = RefFacts.build(ref, item)
    unmatched = [f.id for f in facts if not fact_matches(f, rf.candidates(f))]
    if unmatched:
        return CheckResult(False, "chiffre_non_conforme", {"facts": unmatched})
    # Valeurs qui doivent être citées
    must: list[int]
    lower = [c.lower() for c in ref.columns]
    if item is not None and item.must_cite is not None:
        must = [lower.index(c.lower()) for c in item.must_cite if c.lower() in lower]
    elif len(ref.rows) == 1:
        must = list(rf.measures)  # mesures seulement : un identifiant (agent_id) n'est pas un chiffre cité
    else:
        must = []
    missing = []
    for j in must:
        v = ref.rows[0][j]
        if not is_number(v):
            continue
        if not any(fact_matches(f, [to_float(v)]) for f in facts):
            missing.append(ref.columns[j])
    if missing:
        return CheckResult(False, "chiffre_attendu_non_cite", {"colonnes": missing})
    return CheckResult(True)


# --------------------------------------------------------------------------------------------
# Période, périmètre, intention
# --------------------------------------------------------------------------------------------


def _field_value(state_field: Any) -> Any:
    if state_field is None:
        return None
    return getattr(state_field, "value", state_field)


def extract_period(msg: AssistantMessage) -> tuple[date, date] | None:
    v = _field_value(msg.resolved_state.period)
    if v is None and msg.period is not None:
        v = msg.period
    if v is None:
        return None
    if hasattr(v, "start") and hasattr(v, "end"):
        s, e = v.start, v.end
    elif isinstance(v, dict):
        s, e = v.get("start"), v.get("end")
    elif isinstance(v, list | tuple) and len(v) == 2:
        s, e = v
    else:
        return None
    sd, ed = _as_date(s), _as_date(e)
    if sd is None or ed is None:
        return None
    return sd, ed


def clamp_period(p: tuple[date, date], lo: date = DATA_START, hi: date = REFERENCE_DATE) -> tuple[date, date]:
    s, e = p
    return max(s, lo), min(e, hi)


def compare_period(
    expected: tuple[date, date] | None,
    msg: AssistantMessage,
    *,
    data_start: date = DATA_START,
    reference_date: date = REFERENCE_DATE,
) -> CheckResult:
    """Périodes égales après bornage à la fenêtre des données (2025-04-01 → REFERENCE_DATE)."""
    if expected is None:
        return CheckResult(True)
    got = extract_period(msg)
    if got is None:
        return CheckResult(False, "periode_absente")
    e = clamp_period(expected, data_start, reference_date)
    g = clamp_period(got, data_start, reference_date)
    if e[0] > e[1]:  # période entièrement hors des données : comparaison brute
        e, g = expected, got
    ok = e == g
    return CheckResult(
        ok,
        None if ok else "periode",
        {"attendue": [str(x) for x in expected], "obtenue": [str(x) for x in got]},
    )


KNOWN_DIMENSIONS = ("region_agent", "region_client", "type", "segment", "agent")


def extract_scope(msg: AssistantMessage) -> tuple[str | None, dict[str, set[str]] | None]:
    """(region_kind, filtres) depuis resolved_state ; formes tolérées pour `scope`.

    `scope.value` peut être : {"region_kind": …, "filters": [{"dimension", "values"}]} ;
    {"region_kind": …, "filters": {dim: [valeurs]}} ; une liste de filtres ; {dim: [valeurs]} ;
    ou une chaîne (« national » → aucun filtre).
    """
    st = msg.resolved_state
    region_kind = _field_value(st.region_kind)
    scope = _field_value(st.scope)
    filters: dict[str, set[str]] | None = None
    raw_filters: Any = None
    if isinstance(scope, dict):
        if region_kind is None and isinstance(scope.get("region_kind"), str):
            region_kind = scope["region_kind"]
        if "filters" in scope:
            raw_filters = scope["filters"]
        else:
            raw_filters = {k: v for k, v in scope.items() if k in KNOWN_DIMENSIONS}
    elif isinstance(scope, list):
        raw_filters = scope
    elif isinstance(scope, str) or scope is None:
        raw_filters = [] if scope is not None or st.metrics is not None else None
    if raw_filters is not None:
        filters = {}
        items: list[tuple[str, Any]] = []
        if isinstance(raw_filters, dict):
            items = list(raw_filters.items())
        else:
            for f in raw_filters:
                if isinstance(f, dict) and "dimension" in f:
                    items.append((f["dimension"], f.get("values", [])))
        for dim, vals in items:
            if f_op_excluded(raw_filters, dim):
                continue
            vs = vals if isinstance(vals, list | tuple | set) else [vals]
            filters.setdefault(str(dim), set()).update(norm_text(v) for v in vs)
    if isinstance(region_kind, str) and region_kind in {"aucune", "none", ""}:
        region_kind = None
    return region_kind, filters


def f_op_excluded(raw: Any, dim: str) -> bool:
    """Un filtre `not_in` (ex. hors_agent) n'est pas une restriction de périmètre à comparer."""
    if isinstance(raw, list):
        return any(isinstance(f, dict) and f.get("dimension") == dim and f.get("op") == "not_in" for f in raw)
    return False


def compare_scope(item: EvalItem, msg: AssistantMessage) -> CheckResult:
    exp = item.expected_scope
    if exp is None:
        return CheckResult(True)
    region_kind, filters = extract_scope(msg)
    if exp.region_kind in {"region_agent", "region_client"} and region_kind != exp.region_kind:
        return CheckResult(False, "sens_region", {"attendu": exp.region_kind, "obtenu": region_kind})
    expected_f = {k: {norm_text(v) for v in vs} for k, vs in exp.filters.items()}
    if filters is None:
        if expected_f:
            return CheckResult(False, "perimetre_absent")
        return CheckResult(True)
    dims = (set(expected_f) | set(filters)) & (set(KNOWN_DIMENSIONS) | set(expected_f))
    for d in sorted(dims):
        if expected_f.get(d, set()) != filters.get(d, set()):
            return CheckResult(
                False,
                "filtre",
                {
                    "dimension": d,
                    "attendu": sorted(expected_f.get(d, set())),
                    "obtenu": sorted(filters.get(d, set())),
                },
            )
    return CheckResult(True)


def compare_intent(item: EvalItem, msg: AssistantMessage) -> CheckResult:
    ok = msg.kind in item.kinds
    return CheckResult(ok, None if ok else f"intention:{msg.kind}")


# --------------------------------------------------------------------------------------------
# Verdict d'une question
# --------------------------------------------------------------------------------------------


EMPTY_TEXT_RE = re.compile(
    r"\baucune?\b|\bpas de (donnee|transaction|resultat|transfert|ligne)|\bimpossible\b|\bvide\b"
    r"|n'existe|n'ont pas de|ne (contient|comporte|correspond)|\bsans point de service\b|\bhors agent\b"
)


def signals_empty(msg: AssistantMessage) -> bool:
    """La réponse signale un résultat vide (caveat `resultat_vide`) ou explique l'impossibilité."""
    return "resultat_vide" in msg.caveats or bool(EMPTY_TEXT_RE.search(norm_text(msg.text)))


def grade(
    item: EvalItem,
    msg: AssistantMessage,
    ref: ResultSet | None,
    *,
    got_result: ResultSet | None = None,
    reference_date: date = REFERENCE_DATE,
) -> Verdict:
    """Verdict complet (intention, exécution, chiffres cités, période, périmètre)."""
    checks: dict[str, bool] = {}
    reasons: list[str] = []
    intent = compare_intent(item, msg)
    checks["intention"] = intent.ok
    if not intent.ok:
        reasons.append(intent.reason or "intention")
    if item.expected_kind != "answer" or msg.kind != "answer":
        return Verdict(intent.ok, checks, reasons)
    if ref is None:
        return Verdict(False, checks, [*reasons, "reference_absente"])

    got = got_result if got_result is not None else result_from_message(msg)
    # Résultat vide attendu (T38) : une réponse sans tableau qui explique l'absence de données n'a pas
    # à porter une période ni un périmètre résolus ; s'ils sont présents, ils sont vérifiés.
    explained_empty = item.expected_empty and (got is None or not got.rows) and signals_empty(msg)
    period_check = compare_period(
        (item.expected_period.start, item.expected_period.end) if item.expected_period else None,
        msg,
        reference_date=reference_date,
    )
    if explained_empty and extract_period(msg) is None:
        period_check = CheckResult(True, detail={"exemption": "resultat_vide_explique"})
    scope_check = compare_scope(item, msg)
    if explained_empty and extract_scope(msg) == (None, None):
        scope_check = CheckResult(True, detail={"exemption": "resultat_vide_explique"})
    for name, res in (
        ("execution", compare_execution(ref, got, item)),
        ("chiffres", compare_facts(ref, msg, item)),
        ("periode", period_check),
        ("perimetre", scope_check),
    ):
        checks[name] = res.ok
        if not res.ok:
            reasons.append(f"{name}:{res.reason}")
    return Verdict(all(checks.values()), checks, reasons)
