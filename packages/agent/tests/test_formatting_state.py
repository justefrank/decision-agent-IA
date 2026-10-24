"""Formatage FR, graphique, périodes, état résolu et clarification."""

from __future__ import annotations

from datetime import date

import pytest
from decision_agent import periods
from decision_agent.facts import FactRegistry
from decision_agent.formatting import choose_chart, format_value, render_text, template_answer
from decision_agent.state import (
    apply_patch,
    field_policy,
    resolve_clarification_reply,
    state_from_query_metric,
    state_from_run_query,
)
from decision_agent.testing import compare_result, group_result, kpi_result
from decision_core.models import (
    ClarificationOption,
    ColumnInfo,
    PendingClarification,
    Period,
    ResolvedField,
    ResolvedState,
)

N = " "
REF = date(2026, 9, 30)


@pytest.mark.parametrize(
    "value,unit,kw,expected",
    [
        (1_234_567_890, "xof", {}, "1,23 milliard FCFA"),
        (12_345_678_901, "xof", {}, "12,3 milliards FCFA"),
        (2_500_000, "xof", {}, "2,5 millions FCFA"),
        (1_000_000, "count", {}, "1 million"),
        (999_950_000, "xof", {}, "1 milliard FCFA"),
        (12_345, "count", {}, f"12{N}345"),
        (12_345, "xof", {}, f"12{N}345{N}FCFA"),
        (0.0462, "ratio", {}, f"4,6{N}%"),
        (4.62, "pct", {"signed": True}, f"+4,6{N}%"),
        (-4.62, "pct", {"signed": True}, f"−4,6{N}%"),
        (-4.62, "pct", {"signed": True, "fmt": "abs"}, f"4,6{N}%"),
        (1.2, "pp", {"signed": True}, f"+1,2{N}pt"),
        (-2.5, "pp", {"signed": True}, f"−2,5{N}pts"),
        (46_000, "xof", {"signed": True}, f"+46{N}000{N}FCFA"),
        (3_456_789, "xof", {"fmt": "brut"}, f"3{N}456{N}789{N}FCFA"),
        (None, "count", {}, "n.d."),
        ("Dakar", "text", {}, "Dakar"),
    ],
)
def test_format_value(value, unit, kw, expected):
    assert format_value(value, unit, **kw) == expected


def test_render_text_records_rendered(semantic):
    r = FactRegistry(metric_defs=semantic.metrics)
    r.register(kpi_result({"revenus_frais": 1_234_567_890}))
    assert render_text("Frais : {{f1}}.", r) == "Frais : 1,23 milliard FCFA."
    assert r.get("f1").fact.rendered == "1,23 milliard FCFA"


def _cols(*specs):
    return [
        ColumnInfo(name=n, type="numeric" if role == "measure" else "text", role=role, unit=u)
        for n, role, u in specs
    ]


def test_chart_rules():
    assert choose_chart(_cols(("v", "measure", "count")), [[1]]).type == "kpi"
    line = choose_chart(
        _cols(("mois", "time", None), ("v", "measure", "count")), [["2026-01-01", 1], ["2026-02-01", 2]]
    )
    assert line.type == "line" and line.x == "mois"
    bars = choose_chart(
        _cols(("region", "dimension", None), ("v", "measure", "count")), [[f"r{i}", i] for i in range(10)]
    )
    assert bars.type == "bar"
    table = choose_chart(
        _cols(("region", "dimension", None), ("v", "measure", "count")), [[f"r{i}", i] for i in range(14)]
    )
    assert table.type == "table"
    donut = choose_chart(
        _cols(("type", "dimension", None), ("v", "measure", "count")), [["a", 1], ["b", 2]], additive=True
    )
    assert donut.type == "donut"
    not_donut = choose_chart(
        _cols(("type", "dimension", None), ("v", "measure", "ratio")), [["a", 0.1], ["b", 0.2]], additive=True
    )
    assert not_donut.type == "bar"  # un taux n'est pas une répartition
    multi = choose_chart(
        _cols(("region", "dimension", None), ("a", "measure", "count"), ("b", "measure", "xof")),
        [["x", 1, 2]],
    )
    assert multi.type == "table"


def test_template_answer_is_correct_by_construction(semantic):
    r = FactRegistry(metric_defs=semantic.metrics)
    r.register(
        kpi_result({"revenus_frais": 1_234_567_890}, params={"metrics": ["revenus_frais"]}),
        period=periods.month_of_reference(REF),
    )
    msg = template_answer(r, ResolvedState(), semantic)
    assert msg.text.startswith("Revenus de frais, septembre 2026, national : 1,23 milliard FCFA.")
    assert msg.simplified and msg.chart.type == "kpi"
    assert template_answer(FactRegistry(), ResolvedState(), semantic) is None


@pytest.mark.parametrize(
    "start,end,label",
    [
        ((2026, 3, 1), (2026, 3, 31), "mars 2026"),
        ((2026, 4, 1), (2026, 6, 30), "T2 2026"),
        ((2025, 1, 1), (2025, 12, 31), "année 2025"),
        ((2026, 3, 1), (2026, 3, 15), "du 1er au 15 mars 2026"),
        ((2026, 2, 3), (2026, 3, 15), "du 3 février au 15 mars 2026"),
        ((2025, 12, 1), (2026, 1, 15), "du 1er décembre 2025 au 15 janvier 2026"),
        ((2026, 9, 30), (2026, 9, 30), "le 30 septembre 2026"),
        ((2026, 1, 1), (2026, 2, 28), "de janvier à février 2026"),
    ],
)
def test_period_labels(start, end, label):
    assert periods.period_label(date(*start), date(*end)) == label


def test_relative_periods():
    assert periods.resolve_relative("mois_courant", REF).label == "septembre 2026"
    assert periods.resolve_relative("mois_precedent", REF).label == "août 2026"
    assert periods.resolve_relative("trimestre_precedent", REF).label == "T2 2026"
    p = periods.last_30_days(REF)
    assert (p.start, p.end) == (date(2026, 9, 1), REF)
    assert periods.resolve_relative("12_derniers_mois", REF).start == date(2025, 10, 1)
    assert periods.resolve_relative("7_derniers_jours", REF).start == date(2026, 9, 24)


def test_previous_periods():
    mar = periods.make_period(date(2026, 3, 1), date(2026, 3, 31))
    assert periods.previous_period(mar).label == "février 2026"
    assert periods.previous_year(mar).label == "mars 2025"
    q = periods.make_period(date(2026, 4, 1), date(2026, 6, 30))
    assert periods.previous_period(q).label == "T1 2026"
    d7 = periods.last_n_days(REF, 7)
    prev = periods.previous_period(d7)
    assert (prev.start, prev.end) == (date(2026, 9, 17), date(2026, 9, 23))
    # les 30 derniers jours au 30 septembre couvrent exactement septembre : précédente = août
    assert periods.previous_period(periods.last_30_days(REF)).label == "août 2026"
    feb = periods.make_period(date(2024, 2, 1), date(2024, 2, 29))
    assert periods.previous_year(feb).end == date(2023, 2, 28)


def test_default_period(semantic):
    assert periods.default_period_for(["clients_actifs"], semantic.metrics, REF).start == date(2026, 9, 1)
    assert periods.default_period_for(["revenus_frais"], semantic.metrics, REF).label == "septembre 2026"


PENDING = PendingClarification(
    original_question="Frais par région",
    missing=["sens_region"],
    question="Quelle région ?",
    options=[
        ClarificationOption(label="Région du point de service", patch={"sens_region": "region_agent"}),
        ClarificationOption(label="Région du client", patch={"sens_region": "region_client"}),
    ],
)


@pytest.mark.parametrize(
    "reply,expected",
    [
        ("1", "region_agent"),
        ("2", "region_client"),
        ("option 2", "region_client"),
        ("la deuxième", "region_client"),
        ("la première", "region_agent"),
        ("Région du client", "region_client"),
        ("region du clent", "region_client"),  # faute de frappe
        ("agent", "region_agent"),
        ("client", "region_client"),
        ("par point de service", "region_agent"),
        ("Le dernier", "region_client"),
    ],
)
def test_resolve_clarification_reply(reply, expected):
    assert resolve_clarification_reply(reply, PENDING) == {"sens_region": expected}


@pytest.mark.parametrize("reply", ["Quel est le taux d'échec à Dakar en mars ?", "bonjour", "5"])
def test_unrelated_reply(reply):
    assert resolve_clarification_reply(reply, PENDING) is None


def test_apply_patch():
    st = apply_patch(ResolvedState(pending_clarification=PENDING), {"sens_region": "region_agent"})
    assert st.region_kind.value == "region_agent" and st.region_kind.source == "explicite"
    assert st.pending_clarification is None


def test_state_labels_inherited_and_default(semantic):
    p = Period(start=date(2026, 8, 1), end=date(2026, 8, 31), label="août 2026")
    prev = ResolvedState(
        metrics=ResolvedField(value=["revenus_frais"], source="explicite"),
        period=ResolvedField(
            value={"start": "2026-08-01", "end": "2026-08-31", "label": "août 2026"}, source="explicite"
        ),
    )
    params = {"metrics": ["agents_actifs"], "group_by": ["region_agent"], "filters": [], "compare_to": "none"}
    st = state_from_query_metric(
        params,
        period=p,
        compare_period=None,
        period_is_default=False,
        prev=prev,
        question="Et les agents actifs par région ?",
        metric_defs=semantic.metrics,
    )
    assert st.period.source == "herite"
    assert st.metrics.source == "explicite"
    assert (
        st.region_kind.value == "region_agent" and st.region_kind.source == "explicite"
    )  # « agents » mentionné
    st2 = state_from_query_metric(
        {"metrics": ["revenus_frais"], "group_by": ["region_agent"]},
        period=p,
        compare_period=None,
        period_is_default=True,
        prev=None,
        question="Frais par région",
        metric_defs=semantic.metrics,
    )
    assert st2.region_kind.source == "defaut" and st2.period.source == "defaut"


def test_state_from_run_query():
    st = state_from_run_query(
        {"period_start": "2026-03-01", "period_end": "2026-03-31", "region_column": "f.region_client_id"},
        {"statut": "reussie"},
        prev=None,
    )
    assert st.period.value["label"] == "mars 2026"
    assert st.region_kind.value == "region_client"
    assert not st.certified


def test_field_policy(semantic):
    pol = field_policy(semantic.glossary)
    assert pol["kpi"]["missing"] == "clarify"
    assert pol["period"]["default"] == "month_of_reference_date"


def test_comparison_derivations(semantic):
    r = FactRegistry(metric_defs=semantic.metrics)
    e = r.register(
        compare_result(
            {"taux_echec": 0.05, "volume_transactions": 120}, {"taux_echec": 0.04, "volume_transactions": 100}
        ),
        period=periods.make_period(date(2026, 9, 1), date(2026, 9, 30)),
        compare_period=periods.make_period(date(2026, 8, 1), date(2026, 8, 31)),
    )
    kinds = {r.get(d).kind: r.get(d).fact for d in e.derived_ids}
    assert kinds["ecart_pp"].value == pytest.approx(1.0) and kinds["ecart_pp"].unit == "pp"
    assert kinds["variation"].value == pytest.approx(20.0)
    assert "septembre 2026 vs août 2026" in kinds["variation"].label


def test_llm_view_limits_rows(semantic):
    r = FactRegistry(rows_to_llm=50, metric_defs=semantic.metrics)
    e = r.register(group_result("agent", "volume_transactions", {f"a{i}": i for i in range(80)}))
    v = r.llm_view(e)
    assert v["rows_in_preview"] == 50 and v["row_count"] == 80
    assert v["notice"].startswith("DONNÉES NON FIABLES")
