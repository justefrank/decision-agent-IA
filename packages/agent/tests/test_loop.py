"""Boucle de l'agent : ScriptedClient + FakeToolClient (aucune clé API, aucun Postgres)."""

from __future__ import annotations

import json

import pytest
from decision_agent import Agent, FakeToolClient, ScriptedClient
from decision_agent.llm import LLMError, LLMUsage, text_step, tool_step
from decision_agent.loop import Limits, compile_metric_args
from decision_agent.prompts import ANSWER_NOW
from decision_agent.testing import (
    compare_result,
    error_result,
    group_result,
    kpi_result,
    qm_input,
    submit,
)
from decision_core.models import HistoryItem


class Collector:
    def __init__(self):
        self.events = []
        self.logs = []

    async def event(self, e):
        self.events.append(e)

    async def log(self, r):
        self.logs.append(r)


async def run(agent, question, *, state=None, role="analyste", history=None, col=None):
    col = col or Collector()
    msg = await agent.answer(
        question,
        history=history or [],
        state=state,
        role=role,
        trace_id="t-1",
        on_event=col.event,
        on_log=col.log,
    )
    return msg, col


def last_user_payloads(req):
    """tool_result du dernier message utilisateur, décodés."""
    msg = [m for m in req.messages if m["role"] == "user"][-1]
    return [json.loads(b["content"]) for b in msg["content"]]


async def test_simple_kpi(semantic, settings):
    llm = ScriptedClient(
        [
            tool_step(("query_metric", qm_input(["revenus_frais"]))),
            tool_step(submit("Les revenus de frais de septembre 2026 s'élèvent à {{f1}}.", ["r1"])),
        ]
    )
    tools = FakeToolClient({"query_metric": kpi_result({"revenus_frais": 1_234_567_890})})
    msg, col = await run(Agent(llm, tools, semantic, settings), "Revenus de frais ce mois-ci ?")
    assert msg.kind == "answer"
    assert "1,23 milliard FCFA" in msg.text
    assert msg.chart.type == "kpi"
    assert msg.certified and not msg.simplified
    assert msg.period.label == "septembre 2026"
    assert msg.facts[0].id == "f1" and msg.facts[0].rendered == "1,23 milliard FCFA"
    assert msg.sql == ["SELECT /* kpi */ 1"]
    assert [e.kind for e in msg.evidence][:2] == ["table", "filtre"]
    # paramètres compilés : période résolue par le code
    name, args, timeout = tools.calls[0]
    assert args["period"]["start"] == "2026-09-01" and args["period"]["end"] == "2026-09-30"
    assert timeout <= 10
    # journal : 2 appels LLM + 1 appel d'outil
    assert [r.tool for r in col.logs] == ["llm", "query_metric", "llm"]
    assert col.logs[0].tokens_cache_read == 6000 and col.logs[0].cost_usd > 0
    assert col.logs[0].prompt_version and col.logs[0].semantic_version == semantic.version
    assert {e.kind for e in col.events} >= {"intent", "tool", "validation", "formatting"}
    # requête : préfixe système mis en cache 1 h, contexte variable dans le message
    req = llm.requests[0]
    assert req.system[-1]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}
    assert "2026-09-30" in req.messages[0]["content"]
    assert "2026-09-30" not in json.dumps(req.system)
    assert msg.resolved_state.period.source == "explicite"


async def test_comparison_with_derived(semantic, settings):
    llm = ScriptedClient(
        [
            tool_step(("query_metric", qm_input(["revenus_frais"], compare_to="previous_period"))),
            tool_step(
                submit(
                    "En septembre 2026, les frais atteignent {{f1}}, soit {{d2}} par rapport à août "
                    "({{d1}}).",
                    ["r1"],
                )
            ),
        ]
    )
    tools = FakeToolClient(
        {"query_metric": compare_result({"revenus_frais": 1_046_000}, {"revenus_frais": 1_000_000})}
    )
    msg, _ = await run(Agent(llm, tools, semantic, settings), "Frais ce mois vs le mois dernier ?")
    assert msg.kind == "answer", msg.text
    assert "+4,6 %" in msg.text
    assert "+46 000 FCFA" in msg.text
    assert msg.chart.type == "bar"
    view = last_user_payloads(llm.requests[1])[0]
    assert {f["id"] for f in view["facts"]} == {"d1", "d2"}
    assert view["source"]["compare_period"]["label"] == "août 2026"
    assert msg.resolved_state.compare_to.value["kind"] == "previous_period"


async def test_clarification_then_short_reply(semantic, settings):
    clar = (
        "ask_clarification",
        {
            "missing": "sens_region",
            "question": "Région du point de service ou région du client ?",
            "options": [
                {
                    "label": "Région du point de service",
                    "patch": {"field": "sens_region", "value": "region_agent"},
                },
                {"label": "Région du client", "patch": {"field": "sens_region", "value": "region_client"}},
            ],
        },
    )
    llm = ScriptedClient([tool_step(clar)])
    agent = Agent(llm, FakeToolClient(), semantic, settings)
    first, _ = await run(agent, "Volume de transactions par région en août 2026")
    assert first.kind == "clarification"
    assert first.resolved_state.pending_clarification.original_question.startswith("Volume")
    assert "1. Région du point de service" in first.text

    llm2 = ScriptedClient(
        [
            tool_step(
                (
                    "query_metric",
                    qm_input(
                        ["volume_transactions"],
                        kind="absolute",
                        relative=None,
                        start="2026-08-01",
                        end="2026-08-31",
                        group_by=["region_agent"],
                    ),
                )
            ),
            tool_step(
                submit(
                    "Volume par région du point de service en août 2026 : Dakar arrive en tête avec {{f1}}.",
                    ["r1"],
                )
            ),
        ]
    )
    tools = FakeToolClient(
        {
            "query_metric": group_result(
                "region_agent", "volume_transactions", {"Dakar": 52_000, "Thiès": 21_000, "Kaolack": 9_000}
            )
        }
    )
    hist = [HistoryItem(question="Volume de transactions par région en août 2026", answer=first)]
    msg, _ = await run(
        Agent(llm2, tools, semantic, settings), "agent", state=first.resolved_state, history=hist
    )
    assert msg.kind == "answer", msg.text
    ctx = llm2.requests[0].messages[0]["content"]
    assert "<question>Volume de transactions par région en août 2026</question>" in ctx
    assert "precision_donnee" in ctx
    assert msg.resolved_state.region_kind.value == "region_agent"
    assert msg.resolved_state.region_kind.source == "explicite"
    assert "52 000" in msg.text


async def test_clarification_reply_unrelated_is_new_question(semantic, settings):
    clar = (
        "ask_clarification",
        {
            "missing": "kpi",
            "question": "Quel indicateur ?",
            "options": [
                {"label": "Volume", "patch": {"field": "kpi", "value": "volume_transactions"}},
                {"label": "Valeur transférée", "patch": {"field": "kpi", "value": "valeur_transferee"}},
            ],
        },
    )
    first, _ = await run(
        Agent(ScriptedClient([tool_step(clar)]), FakeToolClient(), semantic, settings),
        "Comment ça va pour l'activité ?",
    )
    llm = ScriptedClient([tool_step(("refuse", {"category": "hors_modele", "reason": "Hors périmètre."}))])
    msg, _ = await run(
        Agent(llm, FakeToolClient(), semantic, settings),
        "Qui sont les destinataires des transferts ?",
        state=first.resolved_state,
    )
    assert msg.kind == "refusal"
    assert "<question>Qui sont les destinataires" in llm.requests[0].messages[0]["content"]
    assert "clarification_abandonnee" in llm.requests[0].messages[0]["content"]


async def test_refuse_write(semantic, settings):
    llm = ScriptedClient(
        [
            tool_step(
                (
                    "refuse",
                    {"category": "modification_demandee", "reason": "Je ne peux que lire les données."},
                )
            )
        ]
    )
    tools = FakeToolClient()
    msg, col = await run(Agent(llm, tools, semantic, settings), "Supprime les transactions échouées")
    assert msg.kind == "refusal"
    assert msg.text == "Je ne peux que lire les données."
    assert tools.calls == []
    assert [r.tool for r in col.logs] == ["llm"]


async def test_budget_reached_gives_template_answer(semantic, settings):
    steps = [tool_step(("query_metric", qm_input(["volume_transactions"]))) for _ in range(6)]
    llm = ScriptedClient(steps)
    tools = FakeToolClient({"query_metric": lambda a: kpi_result({"volume_transactions": 125_000})})
    msg, _ = await run(Agent(llm, tools, semantic, settings), "Volume ?")
    assert msg.kind == "answer" and msg.simplified
    assert "125 000" in msg.text and "réponse simplifiée" in msg.text.lower()
    assert "reponse_simplifiee" in msg.caveats
    assert len(llm.requests) == 6
    # le dernier tour est réservé : message système « réponds maintenant » envoyé une seule fois
    sys_msgs = [m for m in llm.requests[-1].messages if m["role"] == "system"]
    assert sys_msgs == [{"role": "system", "content": ANSWER_NOW}]
    assert len(tools.calls) == 5  # les appels du 6e tour (dernier, réservé) sont refusés


async def test_sql_error_corrected(semantic, settings):
    rq = {
        "sql": "SELECT segment, COUNT(*) FROM analytics.fact_transaction f JOIN analytics.dim_client c "
        "USING (client_id) WHERE statut = 'reussie' GROUP BY segment",
        "purpose": "Volume par segment",
        "declared_scope": {"statut": "reussie", "region_kind": "aucune"},
    }
    llm = ScriptedClient(
        [
            tool_step(("run_query", {**rq, "sql": "SELEC 1"})),
            tool_step(("run_query", rq)),
            tool_step(
                submit("Les particuliers comptent {{f1}} transactions réussies.", ["r2"], ["calcul_ad_hoc"])
            ),
        ]
    )
    ok = group_result(
        "segment",
        "volume_transactions",
        {"particulier": 90_000, "commercant": 8_000},
        tool="run_query",
        params={"period_start": "2026-09-01", "period_end": "2026-09-30", "statut": "reussie"},
    )
    tools = FakeToolClient(
        {"run_query": [error_result("run_query", "sql_error", "erreur de syntaxe près de SELEC"), ok]}
    )
    msg, col = await run(Agent(llm, tools, semantic, settings), "Volume par segment ce mois-ci")
    assert msg.kind == "answer", msg.text
    assert not msg.certified and "calcul_ad_hoc" in msg.caveats
    tool_logs = [r for r in col.logs if r.tool == "run_query"]
    assert [(r.status, r.attempt) for r in tool_logs] == [("error", 0), ("ok", 1)]
    assert msg.period.label == "septembre 2026"
    assert any("Calcul ad hoc" in e.label for e in msg.evidence)
    err_view = last_user_payloads(llm.requests[1])[0]
    assert err_view["status"] == "error" and err_view["error_class"] == "sql_error"


async def test_sql_fix_limit(semantic, settings):
    rq = {"sql": "SELEC 1", "purpose": "x", "declared_scope": {"statut": "reussie", "region_kind": "aucune"}}
    llm = ScriptedClient(
        [tool_step(("run_query", rq)) for _ in range(4)]
        + [tool_step(("refuse", {"category": "autre", "reason": "Calcul impossible."}))]
    )
    tools = FakeToolClient({"run_query": lambda a: error_result("run_query", "sql_error", "syntaxe")})
    msg, _ = await run(Agent(llm, tools, semantic, settings), "calcul compliqué")
    assert len(tools.calls) == 3  # 1 essai + 2 corrections
    assert "Trop de corrections" in last_user_payloads(llm.requests[4])[0]["message"]
    assert msg.kind == "refusal"


async def test_empty_result_must_be_signalled(semantic, settings):
    empty = group_result("region_agent", "revenus_frais", {})
    llm = ScriptedClient(
        [
            tool_step(
                (
                    "query_metric",
                    qm_input(
                        ["revenus_frais"],
                        group_by=["region_agent"],
                        filters=[{"dimension": "type", "values": ["paiement"]}],
                    ),
                )
            ),
            tool_step(submit("Il n'y a pas de frais de paiement par région.", ["r1"])),
            tool_step(
                submit(
                    "Aucune donnée ne correspond : les paiements n'ont pas de point de service.",
                    ["r1"],
                    ["resultat_vide"],
                )
            ),
        ]
    )
    msg, _ = await run(
        Agent(llm, FakeToolClient({"query_metric": empty}), semantic, settings), "Frais des paiements"
    )
    assert msg.kind == "answer"
    assert "resultat_vide" in msg.caveats
    retry = llm.requests[2].messages[-1]["content"][0]
    assert retry["is_error"] and "résultat vide non signalé" in retry["content"]


async def test_truncated_result_total_forbidden(semantic, settings):
    rows = {f"agent {i}": 1000 for i in range(60)}
    res = group_result("agent", "volume_transactions", rows, truncated=True)
    llm = ScriptedClient(
        [
            tool_step(("query_metric", qm_input(["volume_transactions"], group_by=["agent"]))),
            tool_step(submit("Au total, 60 000 transactions.", ["r1"])),
            tool_step(
                submit("Le premier agent compte {{f1}} transactions ; le résultat est tronqué.", ["r1"])
            ),
        ]
    )
    msg, _ = await run(
        Agent(llm, FakeToolClient({"query_metric": res}), semantic, settings), "Volume par agent"
    )
    assert msg.kind == "answer"
    assert "resultat_tronque" in msg.caveats and msg.truncated
    err = llm.requests[2].messages[-1]["content"][0]["content"]
    assert "tronqué" in err
    view = last_user_payloads(llm.requests[1])[0]
    assert view["rows_in_preview"] == 50 and view["truncated"] is True


async def test_validator_failure_twice_gives_template(semantic, settings):
    llm = ScriptedClient(
        [
            tool_step(("query_metric", qm_input(["clients_actifs"], kind="defaut", relative=None))),
            tool_step(submit("Il y a 12 000 clients actifs.", ["r1"])),
            tool_step(submit("Il y a environ 12 000 clients actifs.", ["r1"])),
        ]
    )
    tools = FakeToolClient({"query_metric": kpi_result({"clients_actifs": 48_210})})
    msg, _ = await run(Agent(llm, tools, semantic, settings), "Combien de clients actifs ?")
    assert msg.simplified and "48 210" in msg.text
    # défaut de période des clients actifs : 30 derniers jours
    assert tools.calls[0][1]["period"]["start"] == "2026-09-01"
    assert msg.resolved_state.period.source == "defaut"


async def test_stop_reason_refusal(semantic, settings):
    llm = ScriptedClient([text_step("", stop_reason="refusal", refusal_category="cyber")])
    msg, col = await run(Agent(llm, FakeToolClient(), semantic, settings), "...")
    assert msg.kind == "refusal"
    assert col.logs[0].stop_reason == "refusal"


async def test_role_decideur(semantic, settings):
    llm = ScriptedClient(
        [
            tool_step(("query_metric", qm_input(["taux_echec"]))),
            tool_step(submit("Le taux d'échec de septembre 2026 est de {{f1}}.", ["r1"])),
        ]
    )
    tools = FakeToolClient({"query_metric": kpi_result({"taux_echec": 0.0462})})
    msg, _ = await run(Agent(llm, tools, semantic, settings), "Taux d'échec ?", role="decideur")
    assert "4,6 %" in msg.text
    assert msg.sql  # l'agent produit le message complet…
    assert msg.for_role("decideur").sql is None  # … l'API filtre pour le décideur
    assert "décideur" in llm.requests[0].messages[0]["content"]


async def test_text_only_then_terminal(semantic, settings):
    llm = ScriptedClient(
        [
            text_step("Je vais regarder."),
            tool_step(("refuse", {"category": "hors_modele", "reason": "Hors périmètre."})),
        ]
    )
    msg, _ = await run(Agent(llm, FakeToolClient(), semantic, settings), "Météo à Dakar ?")
    assert msg.kind == "refusal"
    assert "outil terminal" in llm.requests[1].messages[-1]["content"]


async def test_parallel_calls_single_tool_result_message(semantic, settings):
    llm = ScriptedClient(
        [
            tool_step(
                ("query_metric", qm_input(["revenus_frais"])), ("query_metric", qm_input(["agents_actifs"]))
            ),
            tool_step(submit("Frais : {{f1}} ; agents actifs : {{f2}}.", ["r1", "r2"])),
        ]
    )
    tools = FakeToolClient(
        {"query_metric": [kpi_result({"revenus_frais": 5_000_000}), kpi_result({"agents_actifs": 1_250})]}
    )
    msg, _ = await run(Agent(llm, tools, semantic, settings), "Frais et agents actifs ?")
    assert msg.kind == "answer", msg.text
    user = llm.requests[1].messages[-1]
    assert user["role"] == "user" and len(user["content"]) == 2
    assert all(b["type"] == "tool_result" for b in user["content"])
    # historique en ajout seul : les blocs (dont thinking) sont rejoués tels quels
    assert llm.requests[1].messages[0] == llm.requests[0].messages[0]
    assert llm.requests[1].messages[1]["content"][0]["type"] == "thinking"


async def test_region_without_default_requires_clarification(semantic, settings):
    clar = (
        "ask_clarification",
        {
            "missing": "sens_region",
            "question": "Quelle région ?",
            "options": [
                {"label": "Point de service", "patch": {"field": "sens_region", "value": "region_agent"}},
                {"label": "Client", "patch": {"field": "sens_region", "value": "region_client"}},
            ],
        },
    )
    llm = ScriptedClient(
        [
            tool_step(("query_metric", qm_input(["valeur_transferee"], group_by=["region_client"]))),
            tool_step(submit("Dakar : {{f1}}.", ["r1"])),
            tool_step(clar),
        ]
    )
    tools = FakeToolClient(
        {
            "query_metric": group_result(
                "region_client", "valeur_transferee", {"Dakar": 9_000_000, "Thiès": 4_000_000}
            )
        }
    )
    msg, _ = await run(Agent(llm, tools, semantic, settings), "Valeur transférée par région")
    assert msg.kind == "clarification"
    assert "sens de « région »" in llm.requests[2].messages[-1]["content"][0]["content"].lower()


async def test_llm_error_without_facts(semantic, settings):
    llm = ScriptedClient([LLMError("spend_limit", "plafond")])
    msg, col = await run(Agent(llm, FakeToolClient(), semantic, settings), "Volume ?")
    assert msg.kind == "error" and "plafond" in msg.text
    assert col.logs[0].status == "error" and col.logs[0].error_class == "llm_spend_limit"


async def test_cost_cap(semantic, settings):
    big = LLMUsage(input_tokens=60_000, output_tokens=1_000)  # ≈ 0,13 $ : au-delà du plafond de 0,10 $
    llm = ScriptedClient([tool_step(("query_metric", qm_input(["volume_transactions"])), usage=big)])
    tools = FakeToolClient({"query_metric": kpi_result({"volume_transactions": 10})})
    msg, _ = await run(Agent(llm, tools, semantic, settings), "Volume ?")
    assert msg.simplified and len(llm.requests) == 1


async def test_invalid_filter_value_returns_actionable_error(semantic, settings):
    llm = ScriptedClient(
        [
            tool_step(
                (
                    "query_metric",
                    qm_input(
                        ["revenus_frais"], filters=[{"dimension": "region_agent", "values": ["Atlantis"]}]
                    ),
                )
            ),
            tool_step(("refuse", {"category": "hors_modele", "reason": "Région inconnue."})),
        ]
    )
    tools = FakeToolClient()
    await run(Agent(llm, tools, semantic, settings), "Frais à Atlantis")
    assert tools.calls == []
    err = last_user_payloads(llm.requests[1])[0]
    assert err["error_class"] == "invalid_params" and "Dakar" in err["message"]


def test_compile_metric_args_normalizes(semantic, settings):
    params, period, cmp, dflt = compile_metric_args(
        qm_input(
            ["revenus_frais"],
            kind="relative",
            relative="trimestre_courant",
            compare_to="previous_year",
            filters=[{"dimension": "region_agent", "values": ["thies"]}],
            limit=5,
        ),
        reference_date=settings.reference_date,
        semantic=semantic,
    )
    assert params.filters[0].values == ["Thiès"]
    assert params.order == "desc" and params.limit == 5
    assert period.label == "T3 2026" and cmp.label == "T3 2025" and not dflt


def test_limits_from_config(semantic):
    lim = Limits.from_semantic(semantic)
    assert (lim.llm_calls, lim.tool_calls, lim.sql_fixes_per_query, lim.wall_s) == (6, 8, 2, 30.0)


@pytest.mark.parametrize(
    "bad",
    [
        {"metrics": []},
        {"metrics": ["a", "b", "c", "d"]},
        {
            "metrics": ["revenus_frais"],
            "period": {"kind": "absolute", "start": "2026-03-31", "end": "2026-03-01"},
        },
    ],
)
def test_compile_errors(semantic, settings, bad):
    from decision_agent.loop import CompileError

    with pytest.raises(CompileError):
        compile_metric_args(bad, reference_date=settings.reference_date, semantic=semantic)
