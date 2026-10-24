"""Tableau de bord et analyse en workflow (un appel LLM sans outil, validateur de traçabilité)."""

from __future__ import annotations

import json
from datetime import date

from decision_agent import FakeToolClient, ScriptedClient
from decision_agent.dashboard import analysis_rules, fetch_dashboard, run_dashboard_analysis
from decision_agent.llm import LLMError, LLMStep, LLMUsage
from decision_agent.periods import make_period
from decision_agent.testing import UNITS
from decision_core.models import ColumnInfo, ToolResult

PERIOD = make_period(date(2026, 9, 1), date(2026, 9, 30))
CUR = {
    "volume_transactions": 110_000,
    "valeur_transferee": 5_000_000_000,
    "revenus_frais": 200_000_000,
    "clients_actifs": 50_000,
    "agents_actifs": 1_200,
    "taux_echec": 0.09,
}
PREV = {
    "volume_transactions": 100_000,
    "valeur_transferee": 4_900_000_000,
    "revenus_frais": 200_000_000,
    "clients_actifs": 49_000,
    "agents_actifs": 1_180,
    "taux_echec": 0.07,
}
REGIONS = [
    "Dakar",
    "Thiès",
    "Diourbel",
    "Kaolack",
    "Saint-Louis",
    "Ziguinchor",
    "Louga",
    "Fatick",
    "Kolda",
    "Tambacounda",
    "Kaffrine",
    "Kédougou",
    "Matam",
    "Sédhiou",
]


def fake_query_metric(args):
    metrics = args["metrics"]
    cols = [ColumnInfo(name=m, type="numeric", role="measure", unit=UNITS[m]) for m in metrics]
    if args["group_by"]:
        dim = args["group_by"][0]
        rows = []
        for r in REGIONS:
            row = [r]
            for m in metrics:
                row.append(
                    0.25 if (m == "taux_echec" and r == "Kédougou") else 0.07 if m == "taux_echec" else 1000
                )
            rows.append(row)
        return ToolResult(
            tool="query_metric",
            ok=True,
            sql="SELECT region",
            certified=True,
            columns=[ColumnInfo(name=dim, type="text", role="dimension"), *cols],
            rows=rows,
            row_count=len(rows),
            params=args,
            tables=["analytics.fact_transaction"],
        )
    rows = [["courante", *[CUR[m] for m in metrics]], ["comparaison", *[PREV[m] for m in metrics]]]
    return ToolResult(
        tool="query_metric",
        ok=True,
        sql="SELECT national",
        certified=True,
        columns=[ColumnInfo(name="periode", type="text", role="period"), *cols],
        rows=rows,
        row_count=2,
        params=args,
        tables=["analytics.fact_transaction"],
    )


def llm_output(build):
    def step(req):
        payload = json.loads(req.messages[0]["content"])
        out = build(payload["candidats"])
        return LLMStep(
            content=[{"type": "text", "text": json.dumps(out, ensure_ascii=False)}],
            stop_reason="end_turn",
            usage=LLMUsage(input_tokens=3000, output_tokens=400),
            model_served="claude-sonnet-5-5",
        )

    return step


def by_rule(cands, kpi, rule):
    return next(c for c in cands if c["kpi"] == kpi and c["regle"] == rule)


async def test_fetch_dashboard_tiles(semantic):
    tools = FakeToolClient({"query_metric": fake_query_metric})
    d = await fetch_dashboard(tools, semantic, period=PERIOD, region=None)
    assert len(tools.calls) == 1
    tiles = {t["metric"]: t for t in d["tiles"]}
    assert tiles["volume_transactions"]["delta_pct"] == 10.0
    assert tiles["volume_transactions"]["rendered_delta_pct"] == "+10,0 %"
    assert tiles["taux_echec"]["delta_pp"] == 2.0
    assert tiles["valeur_transferee"]["rendered"] == "5 milliards FCFA"
    assert d["compare_period"]["label"] == "août 2026"


async def test_fetch_dashboard_region_filter_splits_by_region_kind(semantic):
    tools = FakeToolClient({"query_metric": fake_query_metric})
    await fetch_dashboard(tools, semantic, period=PERIOD, region="Dakar")
    dims = sorted(c[1]["filters"][0]["dimension"] for c in tools.calls)
    assert dims == ["region_agent", "region_client"]


async def test_analysis_workflow(semantic, settings):
    def build(cands):
        taux = by_rule(cands, "Taux d'échec", "national_variation")
        vol = by_rule(cands, "Volume de transactions", "national_variation")
        reg = by_rule(cands, "Taux d'échec", "regional_deviation")
        d_id = taux["faits"][-1]["id"]
        return {
            "lead": "Le taux d'échec est le principal point d'attention de septembre 2026.",
            "findings": [
                {
                    "candidate_id": taux["id"],
                    "text": f"Le taux d'échec progresse de {{{{{d_id}}}}}.",
                    "hypothesis": "Un incident technique pourrait être en cause.",
                },
                {"candidate_id": vol["id"], "text": "Le volume augmente nettement.", "hypothesis": None},
                {
                    "candidate_id": reg["id"],
                    "text": f"Une région se distingue avec {{{{{reg['faits'][0]['id']}}}}}, "
                    "à cause des pannes réseau.",
                    "hypothesis": None,
                },
            ],
            "follow": ["Quel est le taux d'échec par région ?", "Montre les 42 agents"],
        }

    llm = ScriptedClient([llm_output(build)])
    tools = FakeToolClient({"query_metric": fake_query_metric})
    logs = []

    async def on_log(r):
        logs.append(r)

    a = await run_dashboard_analysis(
        llm, tools, semantic, settings, period=PERIOD, region=None, on_log=on_log
    )
    assert a.available
    assert len(a.findings) == 1  # constat sans source et cause non étiquetée rejetés
    f = a.findings[0]
    assert f.tag == "À surveiller" and f.confidence == "elevee"
    assert "+2,0 pts" in f.text
    assert f.hypothesis == "Un incident technique pourrait être en cause."
    assert a.follow_up == ["Quel est le taux d'échec par région ?"]
    assert a.lead.startswith("Le taux d'échec")
    # un seul appel LLM, sans outil, en sortie structurée
    req = llm.requests[0]
    assert req.tools == [] and req.output_format["type"] == "json_schema"
    assert len(tools.calls) == 3  # national + 2 découpages régionaux
    assert [r.tool for r in logs].count("llm") == 1


async def test_candidates_are_deterministic_and_ranked(semantic, settings):
    seen = []

    def build(cands):
        seen.append([(c["id"], c["kpi"], c["regle"], c["tag"]) for c in cands])
        return {"lead": "x", "findings": [], "follow": []}

    for _ in range(2):
        await run_dashboard_analysis(
            ScriptedClient([llm_output(build)]),
            FakeToolClient({"query_metric": fake_query_metric}),
            semantic,
            settings,
            period=PERIOD,
            region=None,
        )
    assert seen[0] == seen[1]
    assert seen[0][0][1] == "Taux d'échec"  # saillance la plus forte : +2 pts pour un seuil de 0,5 pt
    assert len(seen[0]) <= analysis_rules()["max_candidates_to_llm"]
    assert any(r == "regional_deviation" and t == "À surveiller" for _, _, r, t in seen[0])


async def test_analysis_unavailable_when_nothing_validates(semantic, settings):
    def build(cands):
        return {
            "lead": "Hausse de 12 %.",
            "findings": [
                {
                    "candidate_id": cands[0]["id"],
                    "text": "Hausse de 12 % grâce à la campagne.",
                    "hypothesis": None,
                }
            ],
            "follow": [],
        }

    a = await run_dashboard_analysis(
        ScriptedClient([llm_output(build)]),
        FakeToolClient({"query_metric": fake_query_metric}),
        semantic,
        settings,
        period=PERIOD,
        region=None,
    )
    assert not a.available and a.findings == []


async def test_lead_with_cause_replaced_by_template(semantic, settings):
    def build(cands):
        c = cands[0]
        return {
            "lead": "Tout s'explique par la Tabaski.",
            "findings": [
                {
                    "candidate_id": c["id"],
                    "text": f"Valeur : {{{{{c['faits'][0]['id']}}}}}.",
                    "hypothesis": None,
                }
            ],
            "follow": [],
        }

    a = await run_dashboard_analysis(
        ScriptedClient([llm_output(build)]),
        FakeToolClient({"query_metric": fake_query_metric}),
        semantic,
        settings,
        period=PERIOD,
        region=None,
    )
    assert a.available and a.lead.startswith("Indicateurs de septembre 2026")


async def test_analysis_llm_error_keeps_tiles_path(semantic, settings):
    a = await run_dashboard_analysis(
        ScriptedClient([LLMError("overloaded", "x")]),
        FakeToolClient({"query_metric": fake_query_metric}),
        semantic,
        settings,
        period=PERIOD,
        region=None,
    )
    assert not a.available and a.facts  # les faits (tuiles) restent disponibles
