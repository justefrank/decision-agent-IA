"""Ablations de l'évaluation : prompt, outils et validation varient selon le bras (a à e)."""

from __future__ import annotations

import pytest
from decision_agent import Agent, FakeToolClient, ScriptedClient
from decision_agent.llm import tool_step
from decision_agent.testing import kpi_result, qm_input, submit


def _agent(semantic, settings, ablation, steps, tools=None):
    return Agent(ScriptedClient(steps), tools or FakeToolClient(), semantic, settings, ablation=ablation)


def _tools():
    return FakeToolClient({"query_metric": kpi_result({"valeur_transferee": 564_000_000})})


async def _ask(agent):
    return await agent.answer("Valeur transférée ?", history=[], state=None, role="analyste", trace_id="t")


def test_unknown_ablation_rejected(semantic, settings):
    with pytest.raises(ValueError):
        _agent(semantic, settings, "z", [])


@pytest.mark.parametrize("ablation", ["a", "c"])
def test_without_query_metric(semantic, settings, ablation):
    a = _agent(semantic, settings, ablation, [])
    assert "query_metric" not in {t["name"] for t in a.claude_tools}
    assert "query_metric n'est pas disponible" in a.system[0]["text"]


def test_schema_only_and_without_examples(semantic, settings):
    raw = _agent(semantic, settings, "a", []).system[1]["text"]
    assert "<schema" in raw and "valeur_transferee" not in raw
    full = _agent(semantic, settings, "none", []).system[1]["text"]
    no_ex = _agent(semantic, settings, "b", []).system[1]["text"]
    assert "examples:" in full and "examples:" not in no_ex


def test_prompt_version_differs_per_arm(semantic, settings):
    versions = {_agent(semantic, settings, x, []).prompt_version for x in ("none", "a", "b", "c", "d", "e")}
    assert len(versions) == 6


async def test_literal_numbers_accepted_and_converted_in_e(semantic, settings):
    steps = [
        tool_step(("query_metric", qm_input(["valeur_transferee"]))),
        tool_step(submit("La valeur transférée atteint 564 millions FCFA.", ["r1"])),
    ]
    msg = await _ask(_agent(semantic, settings, "e", steps, _tools()))
    assert msg.kind == "answer" and not msg.simplified, msg.text
    assert "564 millions FCFA" in msg.text
    assert msg.facts, "le nombre apparié doit devenir un fait cité"


async def test_literal_numbers_rejected_without_ablation(semantic, settings):
    literal = submit("La valeur transférée atteint 564 millions FCFA.", ["r1"])
    steps = [
        tool_step(("query_metric", qm_input(["valeur_transferee"]))),
        tool_step(literal),
        tool_step(literal),
    ]
    msg = await _ask(_agent(semantic, settings, "none", steps, _tools()))
    assert msg.simplified  # repli gabarit après le nouvel essai


async def test_unsourced_number_passes_without_validator(semantic, settings):
    steps = [
        tool_step(("query_metric", qm_input(["valeur_transferee"]))),
        tool_step(submit("La valeur transférée atteint 999 millions FCFA.", ["r1"])),
    ]
    msg = await _ask(_agent(semantic, settings, "d", steps, _tools()))
    assert "999 millions" in msg.text and not msg.simplified
