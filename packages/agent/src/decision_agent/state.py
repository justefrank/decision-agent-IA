"""État résolu (produit par le code, jamais par le LLM) et clarification en attente.

- L'état vient des paramètres compilés de `query_metric` ou de la portée extraite de l'AST (`scope`)
  pour `run_query`.
- Chaque champ est étiqueté `explicite`, `herite` ou `defaut` en comparant avec l'état précédent.
- `resolve_clarification_reply` est déterministe : numéro d'option, correspondance floue normalisée
  (distance ≤ 2), puis synonymes.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date
from typing import Any

from decision_core.models import (
    ClarificationOption,
    PendingClarification,
    Period,
    ResolvedField,
    ResolvedState,
)

from decision_agent.periods import make_period

ORDINALS = {
    "premier": 1,
    "premiere": 1,
    "un": 1,
    "une": 1,
    "1er": 1,
    "1re": 1,
    "1ere": 1,
    "deuxieme": 2,
    "second": 2,
    "seconde": 2,
    "deux": 2,
    "2e": 2,
    "2eme": 2,
    "troisieme": 3,
    "trois": 3,
    "3e": 3,
    "3eme": 3,
    "dernier": -1,
    "derniere": -1,
}

# Synonymes des réponses courtes (glossaire : « région » = point de service ou client).
SYNONYMS: dict[str, str] = {
    "agent": "region_agent",
    "agents": "region_agent",
    "point de service": "region_agent",
    "points de service": "region_agent",
    "guichet": "region_agent",
    "region agent": "region_agent",
    "region de l agent": "region_agent",
    "region du point de service": "region_agent",
    "client": "region_client",
    "clients": "region_client",
    "region client": "region_client",
    "region du client": "region_client",
    "region des clients": "region_client",
    "volume": "volume_transactions",
    "nombre de transactions": "volume_transactions",
    "valeur": "valeur_transferee",
    "montant": "valeur_transferee",
    "montants": "valeur_transferee",
    "frais": "revenus_frais",
    "revenus": "revenus_frais",
    "commissions": "revenus_frais",
    "taux d echec": "taux_echec",
    "echecs": "taux_echec",
    "echec": "taux_echec",
    "clients actifs": "clients_actifs",
    "agents actifs": "agents_actifs",
    "national": "national",
    "tout le pays": "national",
    "senegal": "national",
}

REGION_WORDS_AGENT = re.compile(r"\b(agents?|points? de service|guichets?)\b")
REGION_WORDS_CLIENT = re.compile(r"\bclients?\b")


def normalize(s: str) -> str:
    s = unicodedata.normalize("NFD", s.lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return " ".join(s.split())


def levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


_OPTION_NUM_RE = re.compile(
    r"^\s*(?:(?:option|choix|n°|no|numero|numéro)\s*|(?:le|la|l')\s*)?(\d{1,2})\s*[.)]?\s*$", re.IGNORECASE
)
_ORDINAL_WORDS = {k: v for k, v in ORDINALS.items() if k not in ("un", "une", "deux", "trois")}
_OPTION_ORD_RE = re.compile(
    r"^(?:la |le |l )?(" + "|".join(sorted(_ORDINAL_WORDS, key=len, reverse=True)) + r")(?: option| choix)?$"
)


def _option_number(reply: str, normalized: str) -> int | None:
    m = _OPTION_NUM_RE.match(reply)
    if m:
        return int(m.group(1))
    m = _OPTION_ORD_RE.match(normalized)
    if m:
        return _ORDINAL_WORDS[m.group(1)]
    return None


def resolve_clarification_reply(
    reply: str, pending: PendingClarification, *, synonyms: dict[str, str] | None = None
) -> dict[str, Any] | None:
    """Patch de l'option choisie, ou None si la réponse est une nouvelle question."""
    opts = pending.options
    text = normalize(reply)
    if not text:
        return None
    words = text.split()
    # 1. numéro d'option : seulement « 2 », « 2. », « option 2 », « le 2 », « la deuxième (option) ».
    #    « Top 2 régions », « une semaine » ou « frais du 1er » ne sont pas des choix d'option.
    n = _option_number(reply, text)
    if n is not None:
        if n == -1:
            return dict(opts[-1].patch)
        if 1 <= n <= len(opts):
            return dict(opts[n - 1].patch)
    # 2. correspondance floue normalisée avec un libellé
    stripped = re.sub(r"^(la |le |les |l |par |pour |de |du |des |en )+", "", text)
    best: tuple[int, ClarificationOption] | None = None
    for opt in opts:
        lab = normalize(opt.label)
        if stripped == lab or (len(stripped) >= 4 and (stripped in lab.split() or lab.startswith(stripped))):
            return dict(opt.patch)
        d = levenshtein(stripped, lab)
        if d <= 2 and (best is None or d < best[0]):
            best = (d, opt)
    if best is not None:
        return dict(best[1].patch)
    # 3. synonymes du glossaire
    syn = {**SYNONYMS, **(synonyms or {})}
    target = syn.get(stripped) or syn.get(text)
    if target is None and len(words) <= 4:
        for key, val in syn.items():
            if re.search(rf"\b{re.escape(key)}\b", text):
                target = val
                break
    if target is not None:
        for opt in opts:
            if any(str(v) == target for v in opt.patch.values()):
                return dict(opt.patch)
    return None


def apply_patch(state: ResolvedState | None, patch: dict[str, Any]) -> ResolvedState:
    """Fixe les champs choisis par l'utilisateur (étiquetés explicites)."""
    st = (state or ResolvedState()).model_copy(deep=True)
    for field, value in patch.items():
        key = {"periode": "period", "kpi": "metrics", "perimetre": "scope", "sens_region": "region_kind"}.get(
            field, field
        )
        if key == "metrics" and isinstance(value, str):
            value = [value]
        if key == "scope" and value == "national":
            value = []
        if key in ResolvedState.model_fields and key not in ("certified", "pending_clarification"):
            setattr(st, key, ResolvedField(value=value, source="explicite"))
    st.pending_clarification = None
    return st


def _val(field: ResolvedField | None) -> Any:
    return field.value if field else None


def _source(value: Any, prev: ResolvedField | None, *, default: bool = False) -> str:
    if default:
        return "defaut"
    if prev is not None and prev.value == value:
        return "herite"
    return "explicite"


def _period_dict(p: Period | None) -> dict[str, Any] | None:
    if p is None:
        return None
    return {"start": p.start.isoformat(), "end": p.end.isoformat(), "label": p.label}


def region_kind_of(params: dict[str, Any]) -> str | None:
    dims = list(params.get("group_by") or []) + [f.get("dimension") for f in params.get("filters") or []]
    for d in dims:
        if d in ("region_agent", "region_client"):
            return d
    return None


def state_from_query_metric(
    params: dict[str, Any],
    *,
    period: Period,
    compare_period: Period | None,
    period_is_default: bool,
    prev: ResolvedState | None,
    question: str,
    metric_defs: dict[str, Any],
    clarified_fields: set[str] | None = None,
    clarified_values: dict[str, Any] | None = None,
) -> ResolvedState:
    prev = prev or ResolvedState()
    clarified = clarified_fields or set()
    chosen = clarified_values or {}
    metrics = list(params.get("metrics") or [])
    pdict = _period_dict(period)
    st = ResolvedState(certified=True)
    st.metrics = ResolvedField(
        value=metrics, source="explicite" if "metrics" in clarified else _source(metrics, prev.metrics)
    )  # type: ignore[arg-type]
    st.period = ResolvedField(
        value=pdict,
        source="explicite"
        if "period" in clarified
        else _source(pdict, prev.period, default=period_is_default),  # type: ignore[arg-type]
    )
    compare = params.get("compare_to", "none")
    st.compare_to = ResolvedField(
        value={"kind": compare, "period": _period_dict(compare_period)},
        source=_source({"kind": compare, "period": _period_dict(compare_period)}, prev.compare_to),  # type: ignore[arg-type]
    )
    rk = region_kind_of(params)
    if rk is not None:
        q = normalize(question)
        mentioned = bool(
            REGION_WORDS_AGENT.search(q) if rk == "region_agent" else REGION_WORDS_CLIENT.search(q)
        )
        defaults = {metric_defs.get(m, {}).get("default_region_kind") for m in metrics}
        chosen_rk = chosen.get("region_kind")
        if chosen_rk is not None and chosen_rk != rk:
            # jamais « explicite » pour une valeur qui contredit le choix de l'utilisateur
            src = "defaut"
        elif "region_kind" in clarified or mentioned:
            src = "explicite"
        elif prev.region_kind is not None and prev.region_kind.value == rk:
            src = "herite"
        elif defaults == {rk} or None in defaults:
            # défaut du KPI, ou choix sans fondement pour un KPI sans défaut (→ clarification exigée)
            src = "defaut"
        else:
            src = "explicite"
        st.region_kind = ResolvedField(value=rk, source=src)  # type: ignore[arg-type]
    filters = [dict(f) for f in params.get("filters") or []]
    st.scope = ResolvedField(value=filters, source=_source(filters, prev.scope))  # type: ignore[arg-type]
    gb = list(params.get("group_by") or [])
    st.group_by = ResolvedField(value=gb, source=_source(gb, prev.group_by))  # type: ignore[arg-type]
    return st


def _scope_dates(scope: dict[str, Any]) -> tuple[date | None, date | None]:
    nested = scope.get("period")
    if isinstance(nested, dict):  # forme du garde SQL : {"period": {"start", "end"}}
        scope = {**scope, "start": nested.get("start"), "end": nested.get("end")}
    pairs = (
        ("period_start", "period_end"),
        ("date_from", "date_to"),
        ("start", "end"),
        ("date_min", "date_max"),
    )
    for a, b in pairs:
        if scope.get(a) and scope.get(b):
            try:
                return date.fromisoformat(str(scope[a])[:10]), date.fromisoformat(str(scope[b])[:10])
            except ValueError:
                continue
    return None, None


def period_from_scope(scope: dict[str, Any] | None) -> Period | None:
    if not scope:
        return None
    start, end = _scope_dates(scope)
    if start and end and start <= end:
        return make_period(start, end)
    return None


def state_from_run_query(
    scope: dict[str, Any] | None,
    declared_scope: dict[str, Any] | None,
    *,
    prev: ResolvedState | None,
) -> ResolvedState:
    """État d'un calcul ad hoc : portée extraite de l'AST par le garde SQL (jamais déclarée par le modèle)."""
    prev = prev or ResolvedState()
    scope = scope or {}
    st = ResolvedState(certified=False)
    p = period_from_scope(scope)
    if p is not None:
        pdict = _period_dict(p)
        st.period = ResolvedField(value=pdict, source=_source(pdict, prev.period))  # type: ignore[arg-type]
    rk = scope.get("region_kind")
    col = str(scope.get("region_column") or "")
    if rk is None and col:
        rk = "region_agent" if "agent" in col else "region_client" if "client" in col else None
    if rk is None and declared_scope:
        rk = declared_scope.get("region_kind")
    if rk in ("region_agent", "region_client"):
        st.region_kind = ResolvedField(value=rk, source=_source(rk, prev.region_kind))  # type: ignore[arg-type]
    filters = scope.get("filters")
    if isinstance(filters, list):
        st.scope = ResolvedField(value=filters, source=_source(filters, prev.scope))  # type: ignore[arg-type]
    return st


def field_policy(glossary: dict[str, Any]) -> dict[str, Any]:
    """Politique par champ de glossary.yaml (`field_policy`), avec les défauts du rapport v5."""
    default = {
        "kpi": {"missing": "clarify", "ambiguous": "clarify"},
        "period": {"missing": "default_announced", "default": "month_of_reference_date"},
        "region_kind": {"missing": "default_from_metric_or_clarify"},
        "geographic_scope": {"missing": "default_announced", "default": "national"},
    }
    return {**default, **(glossary.get("field_policy") or {})}


def region_kind_needs_clarification(
    metrics: list[str], metric_defs: dict[str, Any], region_source: str | None
) -> bool:
    """Le sens de « région » n'a pas été donné et aucun KPI n'a de défaut : il faut demander."""
    if region_source != "defaut" and region_source is not None:
        return False
    return any(metric_defs.get(m, {}).get("default_region_kind") is None for m in metrics)


def make_pending(
    original_question: str, missing: str, question: str, options: list[dict[str, Any]]
) -> PendingClarification:
    opts = [
        ClarificationOption(label=o["label"], patch={o["patch"]["field"]: o["patch"]["value"]})
        for o in options
    ]
    return PendingClarification(
        original_question=original_question, missing=[missing], question=question, options=opts
    )
