"""Rendu français des nombres, gabarits {{f…}}/{{d…}}/{{l:…}}, graphique, chaîne de preuve, repli.

Règles de rendu (AGENTIC v5 §3.7) :
- espace fine insécable (U+202F) comme séparateur de milliers ;
- au-delà du million : 3 chiffres significatifs et échelle en toutes lettres (« 1,23 milliard FCFA ») ;
- pourcentages à une décimale (« 4,6 % ») ; écarts de taux en points (« +1,2 pt ») ;
- signe « + » / « − » (U+2212) pour les dérivés de variation.
"""

from __future__ import annotations

import math
import re
from typing import TYPE_CHECKING, Any

from decision_core.models import (
    AssistantMessage,
    Chart,
    ColumnInfo,
    EvidenceStep,
    ResolvedState,
    TableData,
)

from decision_agent.facts import is_ranking

if TYPE_CHECKING:
    from decision_agent.facts import FactRegistry, ResultEntry

NNBSP = " "  # espace fine insécable
MINUS = "−"

TEMPLATE_RE = re.compile(r"\{\{\s*(?:(l):([A-Za-z]+[0-9]+)|([fd][0-9]+)(?::([a-z]+))?)\s*\}\}")
ALLOWED_FMT = {"abs", "brut"}

ADHOC_LABEL = "Calcul ad hoc"  # libellé neutre des résultats run_query (jamais le `purpose` du modèle)

TIME_COLUMNS = {"jour", "semaine", "mois", "trimestre", "date", "day", "week", "month", "quarter", "annee"}


def _group_thousands(int_part: str) -> str:
    out = []
    while len(int_part) > 3:
        out.insert(0, int_part[-3:])
        int_part = int_part[:-3]
    out.insert(0, int_part)
    return NNBSP.join(out)


def fmt_decimal_fr(value: float, decimals: int) -> str:
    """Nombre décimal français : virgule, espace fine pour les milliers."""
    s = f"{abs(value):.{decimals}f}"
    if "." in s:
        ip, dp = s.split(".")
    else:
        ip, dp = s, ""
    res = _group_thousands(ip)
    if dp:
        res += "," + dp
    return res


def _three_sig(value: float) -> tuple[str, str]:
    """Mantisse à 3 chiffres significatifs + échelle (million / milliard)."""
    a = abs(value)
    if a >= 1e9:
        m, word = a / 1e9, "milliard"
    else:
        m, word = a / 1e6, "million"
    decimals = 2 if m < 10 else 1 if m < 100 else 0
    m_rounded = round(m, decimals)
    if m_rounded >= 1000 and word == "million":  # 999,95 millions -> 1 milliard
        m_rounded, word, decimals = round(a / 1e9, 2), "milliard", 2
    mant = fmt_decimal_fr(m_rounded, decimals)
    if decimals and "," in mant:
        mant = mant.rstrip("0").rstrip(",")
    plural = "s" if m_rounded >= 2 else ""
    return mant, word + plural


def _sign(value: float, signed: bool) -> str:
    if not signed or value == 0:
        return ""
    return "+" if value > 0 else MINUS


def format_value(value: Any, unit: str, *, signed: bool = False, fmt: str | None = None) -> str:
    """Rend une valeur selon son unité (count, xof, ratio, pct, pp, text, date, id)."""
    if value is None:
        return "n.d."
    if unit in ("text", "date", "id") or isinstance(value, str) and not _is_number(value):
        return str(value)
    v = float(value)
    if math.isnan(v):
        return "n.d."
    if fmt == "abs":
        signed = False
        v = abs(v)
    sign = _sign(v, signed)
    neg = MINUS if (v < 0 and not sign) else ""
    if unit in ("count", "xof"):
        if abs(v) >= 1e6 and fmt != "brut":
            mant, word = _three_sig(v)
            body = f"{mant} {word}"
            if unit == "xof":
                body += " FCFA"  # « 1,23 milliard FCFA »
            return f"{sign}{neg}{body}"
        body = fmt_decimal_fr(round(v), 0)
        if unit == "xof":
            body += f"{NNBSP}FCFA"
        return f"{sign}{neg}{body}"
    if unit in ("pct", "ratio"):
        pct = v * 100 if unit == "ratio" else v
        return f"{sign}{MINUS if (pct < 0 and not sign) else ''}{fmt_decimal_fr(pct, 1)}{NNBSP}%"
    if unit == "pp":
        word = "pt" if abs(round(v, 1)) < 2 else "pts"
        return f"{sign}{neg}{fmt_decimal_fr(v, 1)}{NNBSP}{word}"
    return f"{sign}{neg}{fmt_decimal_fr(v, 2)}"


def _is_number(s: str) -> bool:
    try:
        float(s)
    except (TypeError, ValueError):
        return False
    return True


def render_text(text: str, registry: FactRegistry) -> str:
    """Remplace les gabarits par les valeurs rendues ; enregistre le libellé exact affiché."""

    def repl(m: re.Match[str]) -> str:
        if m.group(1) == "l":
            return registry.label_value(m.group(2)) or m.group(0)
        fid, fmt = m.group(3), m.group(4)
        rec = registry.get(fid)
        if rec is None:
            return m.group(0)
        rendered = format_value(rec.fact.value, rec.fact.unit, signed=rec.signed, fmt=fmt)
        if rec.fact.rendered is None or fmt is None:
            rec.fact.rendered = rendered
        return rendered

    return TEMPLATE_RE.sub(repl, text)


# --- Graphique ------------------------------------------------------------------------------


def _is_time_column(col: ColumnInfo) -> bool:
    return col.role == "time" or col.name in TIME_COLUMNS


def choose_chart(
    columns: list[ColumnInfo],
    rows: list[list[Any]],
    *,
    additive: bool = False,
    truncated: bool = False,
    ranking: bool = False,
) -> Chart:
    """Graphique choisi par la forme du résultat (AGENTIC §7, revue §1.9), jamais par le modèle.

    Un classement « top N » (`ranking`) n'est jamais un donut : ses lignes ne forment pas un tout.
    """
    measures = [c for c in columns if c.role == "measure"]
    dims = [c for c in columns if c.role == "dimension"]
    times = [c for c in columns if _is_time_column(c) and c.role != "measure"]
    period_col = next((c for c in columns if c.role == "period"), None)
    n = len(rows)
    if not measures or n == 0:
        return Chart(type="table")
    if n == 1 and len(measures) == 1 and not dims and not times:
        return Chart(type="kpi", y=[measures[0].name])
    if times and len(measures) >= 1 and not [d for d in dims if d not in times]:
        series = period_col.name if period_col else None
        return Chart(type="line", x=times[0].name, y=[m.name for m in measures[:2]], series=series)
    if period_col and len(dims) <= 1 and len(measures) == 1:
        # comparaison A/B : barres groupées par période
        x = dims[0].name if dims else period_col.name
        n_cat = len({tuple(r) for r in rows}) // 2 if dims else 1
        if n_cat <= 12:
            return Chart(type="bar", x=x, y=[measures[0].name], series=period_col.name if dims else None)
        return Chart(type="table")
    if len(dims) == 1 and len(measures) == 1:
        values = [r[columns.index(measures[0])] for r in rows]
        non_negative = all(isinstance(v, int | float) and v >= 0 for v in values)
        if (
            additive
            and not truncated
            and not ranking
            and n <= 6
            and non_negative
            and measures[0].unit in ("count", "xof")
        ):
            return Chart(type="donut", x=dims[0].name, y=[measures[0].name])
        if n <= 12:
            return Chart(type="bar", x=dims[0].name, y=[measures[0].name])
    return Chart(type="table")


# --- Chaîne de preuve -------------------------------------------------------------------------

REGION_KIND_FR = {
    "region_agent": "région du point de service",
    "region_client": "région du client",
}


def scope_label(state: ResolvedState) -> str:
    """Périmètre affiché : « national » ou la liste des filtres."""
    scope = state.scope.value if state.scope else None
    if not scope:
        return "national"
    parts = []
    for f in scope:
        dim = f.get("dimension")
        vals = ", ".join(str(v) for v in f.get("values", []))
        name = REGION_KIND_FR.get(dim, {"type": "type", "segment": "segment", "agent": "agent"}.get(dim, dim))
        parts.append(f"{name} : {vals}")
    return " ; ".join(parts)


def evidence_chain(entry: ResultEntry, semantic: Any) -> list[EvidenceStep]:
    """Table, filtre, période, opération : visible par le décideur sans SQL (ENF6)."""
    res = entry.result
    steps: list[EvidenceStep] = []
    tables = res.tables or ["analytics.fact_transaction"]
    steps.append(EvidenceStep(kind="table", label="Tables : " + ", ".join(tables)))
    params = res.params or {}
    metrics = params.get("metrics") or []
    if res.tool == "query_metric":
        metric_defs = semantic.metrics
        if any(metric_defs.get(m, {}).get("unit") in ("count", "xof") for m in metrics):
            steps.append(EvidenceStep(kind="filtre", label="Transactions réussies uniquement"))
        for f in params.get("filters") or []:
            dim = f.get("dimension")
            label = semantic.dimensions.get(dim, {}).get("label", dim)
            steps.append(EvidenceStep(kind="filtre", label=f"{label} : " + ", ".join(map(str, f["values"]))))
    else:
        statut = params.get("statut")
        if statut == "reussie":
            steps.append(EvidenceStep(kind="filtre", label="Transactions réussies uniquement"))
        elif statut == "toutes":
            steps.append(EvidenceStep(kind="filtre", label="Toutes les transactions (réussies et échouées)"))
        rk = params.get("region_kind")
        if rk in REGION_KIND_FR:
            steps.append(EvidenceStep(kind="filtre", label=f"Sens de la région : {REGION_KIND_FR[rk]}"))
    if entry.period is not None:
        label = f"Période : {entry.period.label}"
        if entry.compare_period is not None:
            label += f", comparée à {entry.compare_period.label}"
        steps.append(EvidenceStep(kind="periode", label=label))
    if res.tool == "query_metric":
        for m in metrics:
            d = semantic.metrics.get(m, {})
            steps.append(
                EvidenceStep(
                    kind="operation", label=f"{d.get('label', m)} : {d.get('description', '').strip()}"
                )
            )
        gb = params.get("group_by") or []
        if gb:
            labels = [semantic.dimensions.get(g, {}).get("label", g) for g in gb]
            steps.append(EvidenceStep(kind="operation", label="Découpage par " + ", ".join(labels)))
    elif res.tool == "run_query":
        # Libellé fixe : le `purpose` est écrit par le modèle, il n'est jamais montré au décideur.
        steps.append(EvidenceStep(kind="operation", label=ADHOC_LABEL + " (SQL généré, non certifié)"))
    return steps


def default_notes(state: ResolvedState) -> tuple[list[str], list[str]]:
    """(caveats, notes) des défauts appliqués par le code (période, sens de la région)."""
    caveats: list[str] = []
    notes: list[str] = []
    if state.period is not None and state.period.source == "defaut":
        caveats.append("defaut_periode_applique")
        label = state.period.value.get("label") if isinstance(state.period.value, dict) else None
        if label:
            notes.append(f"Période par défaut : {label}.")
    if state.region_kind is not None and state.region_kind.source == "defaut":
        caveats.append("defaut_region_applique")
        rk = REGION_KIND_FR.get(state.region_kind.value)
        if rk:
            notes.append(f"Sens de la région : {rk} (défaut).")
    return caveats, notes


def table_from_entry(entry: ResultEntry) -> TableData:
    """Tableau affiché : valeurs réelles (les étiquettes opaques ne concernent que la vue du modèle)."""
    return TableData(columns=entry.result.columns, rows=entry.result.rows)


# --- Réponse gabarit (repli juste par construction) -------------------------------------------


def template_answer(
    registry: FactRegistry,
    state: ResolvedState,
    semantic: Any,
    *,
    trace_id: str | None = None,
    reason: str = "validation",
) -> AssistantMessage | None:
    """« {libellé KPI}, {période}, {périmètre} : {valeur}. » + tableau, mention « réponse simplifiée ».

    Construite uniquement à partir du dernier résultat valide : aucun nombre ne vient du modèle.
    Renvoie None s'il n'existe aucun résultat exploitable.
    """
    entry = registry.last_data_entry()
    if entry is None:
        return None
    res = entry.result
    metrics = (res.params or {}).get("metrics") or []
    kpi_label = ", ".join(semantic.metrics.get(m, {}).get("label", m) for m in metrics) or "Résultat"
    if res.tool == "run_query":
        kpi_label = ADHOC_LABEL  # jamais le `purpose` écrit par le modèle
    period = entry.period.label if entry.period else "période non précisée"
    scope = scope_label(state)
    caveats = ["reponse_simplifiee"]
    if res.row_count == 0:
        text = f"{kpi_label}, {period}, {scope} : aucune donnée ne correspond à cette demande."
        caveats.append("resultat_vide")
    else:
        measure_ids = entry.measure_fact_ids()
        if len(res.rows) == 1 and len(measure_ids) == 1:
            rec = registry.get(measure_ids[0])
            assert rec is not None
            value = format_value(rec.fact.value, rec.fact.unit)
            rec.fact.rendered = value
            text = f"{kpi_label}, {period}, {scope} : {value}."
        else:
            text = f"{kpi_label}, {period}, {scope} : voir le tableau ci-dessous."
    if res.truncated:
        caveats.append("resultat_tronque")
    if not res.certified:
        caveats.append("calcul_ad_hoc")
    d_caveats, notes = default_notes(state)
    caveats += d_caveats
    text += " (Réponse simplifiée.)"
    if notes:
        text += "\n" + " ".join(notes)
    additive = all(semantic.metrics.get(m, {}).get("additive") for m in metrics) if metrics else False
    return AssistantMessage(
        kind="answer",
        text=text,
        period=entry.period,
        scope=scope,
        table=table_from_entry(entry),
        truncated=res.truncated,
        chart=choose_chart(
            res.columns, res.rows, additive=additive, truncated=res.truncated, ranking=is_ranking(res)
        ),
        tables=list(res.tables),
        sql=[res.sql] if res.sql else None,
        evidence=evidence_chain(entry, semantic),
        facts=[r.fact for r in registry.records() if r.fact.rendered is not None],
        caveats=caveats,
        certified=res.certified,
        simplified=True,
        resolved_state=state,
        trace_id=trace_id,
    )
