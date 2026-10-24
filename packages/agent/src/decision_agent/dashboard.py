"""Tableau de bord (RF4) et analyse en workflow (RF17, AGENTIC v5 §3.8).

1. Le code appelle `query_metric` (2 à 3 requêtes) : les 6 KPI sur la période et la précédente, puis le
   découpage régional.
2. Le code calcule les constats candidats et leur confiance selon des règles versionnées
   (`analysis_rules.yaml`), avec un ordre de saillance déterministe.
3. Un seul appel LLM, sans outil, en sortie structurée : sélection de ≤ 3 candidats et rédaction.
4. Le code valide (traçabilité, littéraux, causalité) ; analyse indisponible si rien ne passe.
   Les tuiles sont toujours renvoyées.
"""

from __future__ import annotations

import json
import statistics
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from decision_core.models import AnalysisFinding, DashboardAnalysis, Period, QueryLogRecord, QueryMetricParams

from decision_agent import periods
from decision_agent.facts import FactRegistry, ResultEntry
from decision_agent.formatting import format_value, render_text
from decision_agent.llm import LLMClient, LLMError, LLMRequest, cost_usd_prudent
from decision_agent.prompts import ANALYSIS_SCHEMA, ANALYSIS_SYSTEM, analysis_prompt_version
from decision_agent.state import normalize
from decision_agent.tools import METRICS, ToolClient
from decision_agent.validator import NUMBER_KINDS, extract_numeric_literals_fr, validate_text

LogCb = Callable[[QueryLogRecord], Awaitable[None]] | None
TOOL_TIMEOUT_S = 10.0
ANALYSIS_DEADLINE_S = 30.0


@lru_cache(maxsize=1)
def analysis_rules() -> dict[str, Any]:
    return yaml.safe_load((Path(__file__).parent / "analysis_rules.yaml").read_text(encoding="utf-8"))


def _region_kind_for(metric: str, semantic: Any) -> str:
    """Filtre régional du tableau de bord : défaut du KPI, sinon région du client."""
    return semantic.metrics.get(metric, {}).get("default_region_kind") or "region_client"


@dataclass
class _Collected:
    period: Period
    compare_period: Period
    region: str | None
    registry: FactRegistry
    national: list[ResultEntry] = field(default_factory=list)
    regional: dict[str, ResultEntry] = field(default_factory=dict)  # region_kind -> entrée
    errors: list[str] = field(default_factory=list)


async def _call_metric(
    tools: ToolClient,
    params: QueryMetricParams,
    registry: FactRegistry,
    *,
    trace_id: str,
    step: int,
    on_log: LogCb,
    semantic_version: str,
) -> ResultEntry:
    t = time.monotonic()
    res = await tools.call("query_metric", params.model_dump(mode="json"), timeout_s=TOOL_TIMEOUT_S)
    if on_log is not None:
        await on_log(
            QueryLogRecord(
                trace_id=trace_id,
                step=step,
                tool="query_metric",
                status="ok" if res.ok else "error",
                error_class=res.error.error_class if res.error else None,
                sql=res.sql,
                row_count=res.row_count if res.ok else None,
                truncated=res.truncated if res.ok else None,
                duration_ms=res.duration_ms or int((time.monotonic() - t) * 1000),
                semantic_version=semantic_version,
            )
        )
    cmp = periods.compare_period(params.period, params.compare_to)
    return registry.register(res, period=params.period, compare_period=cmp)


async def _collect(
    tools: ToolClient,
    semantic: Any,
    *,
    period: Period,
    region: str | None,
    trace_id: str,
    on_log: LogCb,
    with_regions: bool,
) -> _Collected:
    period = periods.ensure_label(period)
    registry = FactRegistry(rows_to_llm=50, metric_defs=semantic.metrics)
    col = _Collected(
        period=period, compare_period=periods.previous_period(period), region=region, registry=registry
    )
    step = 0
    groups: dict[str, list[str]] = {}
    if region:
        for m in METRICS:
            groups.setdefault(_region_kind_for(m, semantic), []).append(m)
    else:
        groups["national"] = list(METRICS)
    for kind, metrics in groups.items():
        filters = [] if kind == "national" else [{"dimension": kind, "values": [region]}]
        params = QueryMetricParams(
            metrics=metrics, period=period, compare_to="previous_period", filters=filters
        )
        step += 1
        entry = await _call_metric(
            tools,
            params,
            registry,
            trace_id=trace_id,
            step=step,
            on_log=on_log,
            semantic_version=semantic.version,
        )
        if not entry.result.ok:
            col.errors.append(entry.result.error.message if entry.result.error else "erreur")
        col.national.append(entry)
    if with_regions and not region:
        by_kind: dict[str, list[str]] = {}
        for m in analysis_rules()["regional_deviation"]["metrics"]:
            by_kind.setdefault(_region_kind_for(m, semantic), []).append(m)
        for kind, metrics in by_kind.items():
            # comparaison par région : la variation régionale se compare à la variation nationale
            params = QueryMetricParams(
                metrics=metrics, period=period, group_by=[kind], compare_to="previous_period"
            )
            step += 1
            entry = await _call_metric(
                tools,
                params,
                registry,
                trace_id=trace_id,
                step=step,
                on_log=on_log,
                semantic_version=semantic.version,
            )
            if entry.result.ok:
                col.regional[kind] = entry
    return col


def _metric_cells(entry: ResultEntry, metric: str) -> dict[str, str]:
    """{'current': f…, 'compare': f…} pour un KPI d'un résultat comparatif sans dimension."""
    res = entry.result
    out: dict[str, str] = {}
    if not res.ok:
        return out
    j = next((i for i, c in enumerate(res.columns) if c.name == metric), None)
    pj = next((i for i, c in enumerate(res.columns) if c.role == "period" or c.name == "periode"), None)
    if j is None:
        return out
    for row, ids in zip(res.rows, entry.cell_ids, strict=False):
        which = str(row[pj]) if pj is not None else "courante"
        key = {"courante": "current", "comparaison": "compare"}.get(which)
        if key and ids[j]:
            out[key] = ids[j]
    return out


def _derived_for(registry: FactRegistry, entry: ResultEntry, metric: str) -> dict[str, str]:
    out = {}
    for did in entry.derived_ids:
        rec = registry.get(did)
        if rec is None or rec.column != metric:
            continue
        out[rec.kind] = did
    return out


def _tiles(col: _Collected, semantic: Any) -> list[dict[str, Any]]:
    reg = col.registry
    tiles = []
    for m in METRICS:
        d = semantic.metrics[m]
        entry = next(
            (e for e in col.national if e.result.ok and any(c.name == m for c in e.result.columns)), None
        )
        tile: dict[str, Any] = {
            "metric": m,
            "label": d["label"],
            "unit": d["unit"],
            "available": entry is not None,
            "region_kind": _region_kind_for(m, semantic) if col.region else None,
        }
        if entry is not None:
            cells = _metric_cells(entry, m)
            der = _derived_for(reg, entry, m)
            cur = reg.get(cells["current"]) if "current" in cells else None
            prev = reg.get(cells["compare"]) if "compare" in cells else None
            tile.update(
                {
                    "value": cur.fact.value if cur else None,
                    "previous": prev.fact.value if prev else None,
                    "rendered": format_value(cur.fact.value, d["unit"]) if cur else "n.d.",
                    "rendered_previous": format_value(prev.fact.value, d["unit"]) if prev else "n.d.",
                    "fact_ids": {**cells, **der},
                }
            )
            for kind in ("ecart", "variation", "ecart_pp"):
                rec = reg.get(der[kind]) if kind in der else None
                tile[{"ecart": "delta_abs", "variation": "delta_pct", "ecart_pp": "delta_pp"}[kind]] = (
                    rec.fact.value if rec else None
                )
                if rec:
                    tile[
                        "rendered_"
                        + {"ecart": "delta_abs", "variation": "delta_pct", "ecart_pp": "delta_pp"}[kind]
                    ] = format_value(rec.fact.value, rec.fact.unit, signed=True)
        tiles.append(tile)
    return tiles


async def fetch_dashboard(
    tools: ToolClient,
    semantic: Any,
    *,
    period: Period,
    region: str | None,
    on_log: LogCb = None,
    trace_id: str | None = None,
) -> dict[str, Any]:
    """Les 6 KPI sur la période et la précédente, avec dérivés (sans LLM)."""
    col = await _collect(
        tools,
        semantic,
        period=period,
        region=region,
        trace_id=trace_id or _trace(),
        on_log=on_log,
        with_regions=False,
    )
    return _dashboard_dict(col, semantic)


def _dashboard_dict(col: _Collected, semantic: Any) -> dict[str, Any]:
    return {
        "period": col.period.model_dump(mode="json"),
        "compare_period": col.compare_period.model_dump(mode="json"),
        "region": col.region,
        "tiles": _tiles(col, semantic),
        "facts": [f.model_dump(mode="json") for f in col.registry.public_facts(only_rendered=False)],
        "errors": col.errors,
        "semantic_version": semantic.version,
    }


# --- Constats candidats -------------------------------------------------------------------------


@dataclass
class Candidate:
    id: str
    tag: str
    metric: str
    confidence: str  # elevee | moyenne
    facts: list[str]
    salience: float
    rule: str


def build_candidates(col: _Collected, semantic: Any, rules: dict[str, Any] | None = None) -> list[Candidate]:
    """Règles versionnées → candidats triés par saillance décroissante (ordre déterministe)."""
    rules = rules or analysis_rules()
    worse = set(rules.get("higher_is_worse") or [])
    raw: list[tuple[float, str, str, str, list[str], str]] = []
    nv = rules["national_variation"]
    for tile in _tiles(col, semantic):
        if not tile.get("available"):
            continue
        m, ids = tile["metric"], tile.get("fact_ids", {})
        base = [ids[k] for k in ("current", "compare") if k in ids]
        if tile.get("delta_pp") is not None and abs(tile["delta_pp"]) >= nv["pp_min"]:
            up = tile["delta_pp"] > 0
            tag = (
                ("À surveiller" if up else "Écart favorable")
                if m in worse
                else ("Hausse" if up else "Baisse")
            )
            raw.append(
                (
                    abs(tile["delta_pp"]) / nv["pp_min"],
                    tag,
                    m,
                    "elevee",
                    [*base, ids["ecart_pp"]],
                    "national_variation",
                )
            )
        elif tile.get("delta_pct") is not None and abs(tile["delta_pct"]) >= nv["pct_min"]:
            up = tile["delta_pct"] > 0
            tag = (
                ("À surveiller" if up else "Écart favorable")
                if m in worse
                else ("Hausse" if up else "Baisse")
            )
            raw.append(
                (
                    abs(tile["delta_pct"]) / nv["pct_min"],
                    tag,
                    m,
                    "elevee",
                    [*base, ids["variation"]],
                    "national_variation",
                )
            )
        alert = rules.get("failure_rate_alert", {}).get("ratio_min")
        if (
            m == "taux_echec"
            and alert is not None
            and isinstance(tile.get("value"), int | float)
            and tile["value"] >= alert
        ):
            raw.append((tile["value"] / alert, "À surveiller", m, "elevee", base[:1], "failure_rate_alert"))
    national_variation = {
        t["metric"]: t["fact_ids"].get("variation")
        for t in _tiles(col, semantic)
        if t.get("available") and t.get("fact_ids", {}).get("variation")
    }
    regional = _regional_candidates(col, semantic, rules, worse, national_variation)
    # Priorité : constats nationaux (variation significative, alerte) avant les écarts régionaux, pour
    # qu'ils restent dans les candidats envoyés au modèle ; puis saillance décroissante.
    national = [(0, *r) for r in raw]
    ranked = sorted(
        national + [(1, *r) for r in regional],
        key=lambda r: (r[0], -round(r[1], 9), r[3], r[5][0] if r[5] else ""),
    )
    return [
        Candidate(id=f"c{i}", tag=t, metric=m, confidence=c, facts=f, salience=round(sal, 4), rule=rule)
        for i, (_, sal, t, m, c, f, rule) in enumerate(ranked, 1)
    ]


_EXCLUDED_REGIONS = ("Non applicable", "-1", "None")


def _regional_candidates(
    col: _Collected,
    semantic: Any,
    rules: dict[str, Any],
    worse: set[str],
    national_variation: dict[str, str],
) -> list[tuple[float, str, str, str, list[str], str]]:
    """Écarts régionaux normalisés : jamais sur des totaux bruts (la taille de Dakar n'est pas un écart).

    - taux (unité ratio / pct) : écart à la moyenne inter-régions, en écarts-types, sur la période courante ;
    - volumes et montants : variation de la région comparée à la variation nationale (en points de %).
    Au plus un constat par région (le plus saillant).
    """
    rd = rules["regional_deviation"]
    reg = col.registry
    gap_min = float(rd.get("variation_gap_pct", 10.0))
    best: dict[str, tuple[float, str, str, str, list[str], str]] = {}

    def keep(region: str, cand: tuple[float, str, str, str, list[str], str]) -> None:
        cur = best.get(region)
        if cur is None or (-cand[0], cand[2]) < (-cur[0], cur[2]):
            best[region] = cand

    def tag_for(m: str, high: bool) -> str:
        if m in worse:
            return "À surveiller" if high else "Écart favorable"
        return "Écart favorable" if high else "Écart"

    for kind, entry in sorted(col.regional.items()):
        res = entry.result
        dim_j = next((i for i, c in enumerate(res.columns) if c.name == kind or c.role == "dimension"), None)
        if dim_j is None:
            continue
        pj = next((i for i, c in enumerate(res.columns) if c.role == "period" or c.name == "periode"), None)
        for m in rd["metrics"]:
            j = next((i for i, c in enumerate(res.columns) if c.name == m), None)
            if j is None:
                continue
            unit = semantic.metrics.get(m, {}).get("unit") or res.columns[j].unit
            if unit in ("ratio", "pct"):
                pts = [
                    (str(row[dim_j]), row[j], ids[j])
                    for row, ids in zip(res.rows, entry.cell_ids, strict=False)
                    if isinstance(row[j], int | float)
                    and ids[j]
                    and str(row[dim_j]) not in _EXCLUDED_REGIONS
                    and (pj is None or str(row[pj]) == "courante")
                ]
                if len(pts) < rd["min_regions"]:
                    continue
                vals = [v for _, v, _ in pts]
                mean, sd = statistics.fmean(vals), statistics.pstdev(vals)
                if sd == 0:
                    continue
                for region, v, fid in pts:
                    z = (v - mean) / sd
                    if abs(z) >= rd["z_min"]:
                        keep(
                            region,
                            (
                                abs(z) / rd["z_min"],
                                tag_for(m, z > 0),
                                m,
                                "moyenne",
                                [fid],
                                "regional_deviation",
                            ),
                        )
                continue
            nat_id = national_variation.get(m)
            nat = reg.get(nat_id) if nat_id else None
            if nat is None or not isinstance(nat.fact.value, int | float):
                continue
            region_vars = [
                (str(rec.dims[0]), rec)
                for did in entry.derived_ids
                if (rec := reg.get(did)) is not None
                and rec.kind == "variation"
                and rec.column == m
                and rec.dims
                and str(rec.dims[0]) not in _EXCLUDED_REGIONS
                and isinstance(rec.fact.value, int | float)
            ]
            if len(region_vars) < rd["min_regions"]:
                continue
            for region, rec in region_vars:
                gap = float(rec.fact.value) - float(nat.fact.value)
                if abs(gap) >= gap_min:
                    keep(
                        region,
                        (
                            abs(gap) / gap_min,
                            tag_for(m, gap > 0),
                            m,
                            "moyenne",
                            [rec.fact.id, nat.fact.id],
                            "regional_deviation",
                        ),
                    )
    return [best[r] for r in sorted(best)]


def _candidate_view(c: Candidate, reg: FactRegistry, semantic: Any) -> dict[str, Any]:
    facts = []
    for fid in c.facts:
        rec = reg.get(fid)
        if rec:
            facts.append(
                {
                    "id": fid,
                    "label": rec.fact.label,
                    "v": rec.fact.value,
                    "unit": rec.fact.unit,
                    "rendu": format_value(rec.fact.value, rec.fact.unit, signed=rec.signed),
                }
            )
    return {
        "id": c.id,
        "tag": c.tag,
        "kpi": semantic.metrics[c.metric]["label"],
        "regle": c.rule,
        "faits": facts,
    }


def _catalog_words(semantic: Any) -> list[str]:
    words = set()
    for key, d in semantic.metrics.items():
        words.add(normalize(key.replace("_", " ")))
        words.add(normalize(d.get("label", "")))
    for d in semantic.dimensions.values():
        words.add(normalize(d.get("label", "")))
    words |= {
        "frais",
        "volume",
        "taux d echec",
        "clients actifs",
        "agents actifs",
        "valeur",
        "region",
        "segment",
        "type",
        "agent",
        "transactions",
        "montant",
    }
    return sorted(w for w in words if w)


def _trace() -> str:
    return f"dash-{uuid.uuid4().hex[:12]}"


async def run_dashboard_analysis(
    llm: LLMClient,
    tools: ToolClient,
    semantic: Any,
    settings: Any,
    *,
    period: Period,
    region: str | None,
    on_log: LogCb = None,
    trace_id: str | None = None,
) -> DashboardAnalysis:
    trace_id = trace_id or _trace()
    rules = analysis_rules()
    col = await _collect(
        tools, semantic, period=period, region=region, trace_id=trace_id, on_log=on_log, with_regions=True
    )
    reg = col.registry
    base = {"period": col.period, "region": region, "semantic_version": semantic.version}
    if not any(e.result.ok for e in col.national):
        return DashboardAnalysis(
            **base,
            lead="Analyse indisponible : les indicateurs n'ont pas pu être calculés.",
            findings=[],
            available=False,
        )
    candidates = build_candidates(col, semantic, rules)
    top = candidates[: rules.get("max_candidates_to_llm", 6)]
    if not top:
        return DashboardAnalysis(
            **base,
            lead=f"Aucun écart notable sur {col.period.label} selon les règles "
            f"d'analyse (version {rules['version']}).",
            findings=[],
            facts=reg.public_facts(only_rendered=False),
        )
    payload = {
        "periode": col.period.label,
        "periode_precedente": col.compare_period.label,
        "perimetre": region or "national",
        "regles": rules["version"],
        "candidats": [_candidate_view(c, reg, semantic) for c in top],
    }
    req = LLMRequest(
        model=settings.llm_model,
        system=[
            {"type": "text", "text": ANALYSIS_SYSTEM, "cache_control": {"type": "ephemeral", "ttl": "1h"}}
        ],
        tools=[],
        messages=[{"role": "user", "content": json.dumps(payload, ensure_ascii=False, default=str)}],
        effort=settings.llm_effort,
        max_tokens=4000,
        deadline_s=ANALYSIS_DEADLINE_S,
        output_format={"type": "json_schema", "schema": ANALYSIS_SCHEMA},
    )
    t = time.monotonic()
    model_id = None
    try:
        step = await llm.step(req)
    except LLMError as e:
        if on_log is not None:
            await on_log(
                QueryLogRecord(
                    trace_id=trace_id,
                    step=len(col.national) + len(col.regional) + 1,
                    tool="llm",
                    status="error",
                    error_class=f"llm_{e.kind}",
                    duration_ms=int((time.monotonic() - t) * 1000),
                    model_requested=settings.llm_model,
                    effort=settings.llm_effort,
                    prompt_version=analysis_prompt_version(),
                    semantic_version=semantic.version,
                )
            )
        return DashboardAnalysis(
            **base,
            lead="Analyse indisponible.",
            findings=[],
            available=False,
            facts=reg.public_facts(only_rendered=False),
        )
    model_id = step.model_served or settings.llm_model
    cost, estimated = cost_usd_prudent(step.usage, model_id)
    if on_log is not None:
        await on_log(
            QueryLogRecord(
                trace_id=trace_id,
                step=len(col.national) + len(col.regional) + 1,
                tool="llm",
                status="ok",
                error_class="cout_estime_tarif_max" if estimated else None,
                duration_ms=step.latency_ms,
                model_requested=settings.llm_model,
                model_served=step.model_served or None,
                effort=settings.llm_effort,
                stop_reason=step.stop_reason,
                request_id=step.request_id,
                ttft_ms=step.ttft_ms,
                tokens_in=step.usage.input_tokens,
                tokens_out=step.usage.output_tokens,
                tokens_cache_read=step.usage.cache_read_tokens,
                tokens_cache_write=step.usage.cache_write_tokens,
                cost_usd=cost,
                prompt_version=analysis_prompt_version(),
                semantic_version=semantic.version,
            )
        )
    try:
        if step.stop_reason in ("refusal", "max_tokens"):
            raise ValueError(step.stop_reason)
        out = json.loads(step.text)
    except ValueError:
        return DashboardAnalysis(
            **base,
            lead="Analyse indisponible.",
            findings=[],
            available=False,
            model_id=model_id,
            facts=reg.public_facts(only_rendered=False),
        )
    findings, follow, lead = validate_analysis(out, top, reg, semantic, col, rules)
    if not findings:
        return DashboardAnalysis(
            **base,
            lead="Analyse indisponible : aucun constat n'a passé la vérification.",
            findings=[],
            available=False,
            model_id=model_id,
            facts=reg.public_facts(only_rendered=False),
        )
    return DashboardAnalysis(
        **base, lead=lead, findings=findings, follow_up=follow, model_id=model_id, facts=reg.public_facts()
    )


def validate_analysis(
    out: dict[str, Any],
    top: list[Candidate],
    reg: FactRegistry,
    semantic: Any,
    col: _Collected,
    rules: dict[str, Any],
) -> tuple[list[AnalysisFinding], list[str], str]:
    """Traçabilité, littéraux et causalité ; un constat invalide est supprimé."""
    by_id = {c.id: c for c in top}
    years = {col.period.start.year, col.period.end.year, col.compare_period.start.year}
    findings: list[AnalysisFinding] = []
    seen: set[str] = set()
    for f in out.get("findings") or []:
        cid = str(f.get("candidate_id"))
        cand = by_id.get(cid)
        if cand is None or cid in seen or len(findings) >= rules.get("max_findings", 3):
            continue
        text = str(f.get("text") or "").strip()
        cited = {m for m in cand.facts if "{{" + m in text}
        errs = validate_text(
            text, reg, allowed_years=years, allow_hypothesis=False, restrict_to=set(cand.facts)
        )
        if not cited:
            errs.append("constat sans source")
        hyp = f.get("hypothesis")
        hyp = str(hyp).strip() if hyp else None
        if hyp and any(lit.kind in NUMBER_KINDS for lit in extract_numeric_literals_fr(hyp)):
            hyp = None  # une hypothèse ne porte pas de chiffre : on la retire
        if hyp and "{{" in hyp:
            hyp = None
        if errs:
            continue
        seen.add(cid)
        findings.append(
            AnalysisFinding(
                tag=cand.tag,
                text=render_text(reg.deopaque(text), reg),  # type: ignore[arg-type]
                confidence=cand.confidence,
                sources=cand.facts,
                hypothesis=hyp,
            )
        )  # type: ignore[arg-type]
    lead = str(out.get("lead") or "").strip()
    if not lead or validate_text(lead, reg, allowed_years=years, allow_hypothesis=False):
        lead = _template_lead(col, semantic)
    else:
        lead = render_text(reg.deopaque(lead), reg)
    words = _catalog_words(semantic)
    follow = []
    for q in out.get("follow") or []:
        q = str(q).strip()
        nq = normalize(q)
        if (
            q
            and len(q) <= 150
            and any(w in nq for w in words)
            and not any(lit.kind in NUMBER_KINDS for lit in extract_numeric_literals_fr(q))
        ):
            follow.append(q)
    return findings, follow[:3], lead


def _template_lead(col: _Collected, semantic: Any) -> str:
    scope = col.region or "national"
    return f"Indicateurs de {col.period.label} ({scope}), comparés à {col.compare_period.label}."
