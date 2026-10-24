"""Tests du correcteur (compare.py)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from decision_core.models import AssistantMessage, ColumnInfo, Fact, ResolvedField, ResolvedState, TableData
from decision_eval.compare import (
    ResultSet,
    compare_execution,
    compare_facts,
    compare_intent,
    compare_period,
    compare_scope,
    extract_scope,
    grade,
    numbers_equal,
    pivot_periode,
    values_equal,
)
from decision_eval.dataset import EvalItem


def item(**kw) -> EvalItem:
    base = {
        "id": "X",
        "category": "kpi_simple",
        "question": "q ?",
        "expected_kind": "answer",
        "reference_sql": "SELECT 1 FROM analytics.fact_transaction",
    }
    base.update(kw)
    return EvalItem.model_validate(base)


def rs(cols, rows):
    return ResultSet.of(cols, rows)


def msg(
    cols=None, rows=None, facts=(), period=None, region_kind=None, scope=None, kind="answer", text="t", **kw
):
    table = None
    if cols is not None:
        table = TableData(
            columns=[ColumnInfo(name=c, type="text", role="dimension") for c in cols],
            rows=[list(r) for r in rows],
        )
    st = ResolvedState()
    if period:
        st.period = ResolvedField(value={"start": period[0], "end": period[1]}, source="explicite")
    if region_kind:
        st.region_kind = ResolvedField(value=region_kind, source="defaut")
    if scope is not None:
        st.scope = ResolvedField(value=scope, source="explicite")
    fs = []
    for i, f in enumerate(facts):
        v, u, fid, label = (*f, f"f{i}", "x")[:4] if len(f) == 2 else f
        fs.append(Fact(id=fid, value=v, unit=u, label=label, rendered=str(v)))
    return AssistantMessage(kind=kind, text=text, table=table, facts=fs, resolved_state=st, **kw)


# ------------------------------------------------------------------ valeurs


class TestValues:
    def test_integers_exact(self):
        assert numbers_equal(2121, 2121)
        assert numbers_equal(Decimal("216348235"), 216348235)
        assert numbers_equal(216348235, 216348235.0)
        assert not numbers_equal(2121, 2122)
        assert not numbers_equal(216348235, 216348235.5)  # pas de tolérance sur un entier
        assert not numbers_equal(1000000, 1000001)  # 1e-6 relatif mais entier : refusé

    def test_ratio_tolerance(self):
        r = Decimal("0.06108897742363877822")
        assert numbers_equal(r, 0.061089)  # 1e-5 relatif
        assert not numbers_equal(r, 0.0612)

    def test_ratio_vs_percent(self):
        assert numbers_equal(Decimal("0.0610889"), 6.10889)
        assert not numbers_equal(Decimal("0.0610889"), 6.2)

    def test_text_dates_bools(self):
        assert values_equal("Thiès", "thies ")
        assert values_equal("Saint-Louis", "SAINT-LOUIS")
        assert not values_equal("Dakar", "Thiès")
        assert values_equal(date(2026, 4, 1), "2026-04-01")
        assert values_equal(date(2026, 4, 1), "2026-04")
        assert not values_equal(date(2026, 4, 2), "2026-04")
        assert values_equal(True, "oui")
        assert values_equal(None, None)
        assert not values_equal(None, 0)
        assert values_equal(12, "12")
        assert not values_equal(12, "douze")


def test_ratio_tolerance_bound():
    r = 0.0610889
    assert numbers_equal(r, r * (1 + 0.9e-4))
    assert not numbers_equal(r, r * (1 + 2e-4))


# ------------------------------------------------------------------ exécution


class TestExecution:
    def test_single_value_alias_free(self):
        ref = rs(["volume_transactions"], [(2121,)])
        assert compare_execution(ref, rs(["n"], [(2121,)])).ok
        assert not compare_execution(ref, rs(["n"], [(2120,)])).ok

    def test_extra_columns_tolerated_and_projection_by_values(self):
        ref = rs(["region", "valeur"], [("Dakar", 10), ("Thiès", 5)])
        got = rs(
            ["valeur_transferee", "rang", "Région", "part"], [(5, 2, "Thiès", 0.33), (10, 1, "Dakar", 0.67)]
        )
        res = compare_execution(ref, got)
        assert res.ok
        assert res.detail["projection"] == {"region": "Région", "valeur": "valeur_transferee"}

    def test_missing_column_fails(self):
        ref = rs(["region", "valeur"], [("Dakar", 10)])
        assert compare_execution(ref, rs(["valeur"], [(10,)])).reason == "colonnes_introuvables"

    def test_multiset_unordered(self):
        ref = rs(["t", "n"], [("a", 1), ("b", 2), ("b", 2)])
        assert compare_execution(ref, rs(["t", "n"], [("b", 2), ("a", 1), ("b", 2)])).ok
        assert not compare_execution(ref, rs(["t", "n"], [("b", 2), ("a", 1), ("a", 1)])).ok

    def test_row_count_mismatch(self):
        ref = rs(["t", "n"], [("a", 1), ("b", 2)])
        assert not compare_execution(ref, rs(["t", "n"], [("a", 1), ("b", 2), ("c", 3)])).ok
        assert not compare_execution(ref, rs(["t", "n"], [("a", 1)])).ok

    def test_column_values_must_align_in_tuples(self):
        # chaque colonne correspond séparément mais les tuples sont croisés
        ref = rs(["t", "n"], [("a", 1), ("b", 2)])
        assert not compare_execution(ref, rs(["t", "n"], [("a", 2), ("b", 1)])).ok

    def test_same_valued_columns_ambiguous_projection(self):
        ref = rs(["x", "y"], [(1, 2), (3, 4)])
        got = rs(["p", "q", "r"], [(1, 1, 2), (3, 3, 4)])
        assert compare_execution(ref, got).ok

    def test_order_only_if_ordered(self):
        ref = rs(["type", "n"], [("transfert", 549), ("retrait", 541), ("depot", 500)])
        got = rs(["type", "n"], [("retrait", 541), ("transfert", 549), ("depot", 500)])
        assert compare_execution(ref, got).ok
        it = item(ordered=True, order_by=["n"])
        assert not compare_execution(ref, got, it).ok
        assert compare_execution(ref, rs(["type", "n"], ref.rows), it).ok

    def test_ties_any_order(self):
        ref = rs(["ville", "n"], [("Dakar", 6), ("Diourbel", 6), ("Thiès", 5)])
        got = rs(["ville", "n"], [("Diourbel", 6), ("Dakar", 6), ("Thiès", 5)])
        it = item(ordered=True, order_by=["n"])
        assert compare_execution(ref, got, it).ok

    def test_ordered_without_order_by_is_strict(self):
        ref = rs(["ville", "n"], [("Dakar", 6), ("Diourbel", 6)])
        got = rs(["ville", "n"], [("Diourbel", 6), ("Dakar", 6)])
        assert not compare_execution(ref, got, item(ordered=True)).ok

    def test_tie_at_cutoff(self):
        # référence top-3 ; Kolda et Louga ex æquo au 3e rang : l'un ou l'autre est accepté
        ref = rs(["region", "n"], [("Dakar", 9), ("Thiès", 7), ("Kolda", 5)])
        it = item(ordered=True, order_by=["n"], tie_tolerant=True)
        assert compare_execution(ref, rs(["region", "n"], [("Dakar", 9), ("Thiès", 7), ("Louga", 5)]), it).ok
        # mais une valeur de clé différente à la frontière est refusée
        assert not compare_execution(
            ref, rs(["region", "n"], [("Dakar", 9), ("Thiès", 7), ("Louga", 4)]), it
        ).ok
        # et le cœur doit rester identique
        assert not compare_execution(
            ref, rs(["region", "n"], [("Matam", 9), ("Thiès", 7), ("Kolda", 5)]), it
        ).ok
        # sans tie_tolerant, l'identité compte
        it2 = item(ordered=True, order_by=["n"])
        assert not compare_execution(
            ref, rs(["region", "n"], [("Dakar", 9), ("Thiès", 7), ("Louga", 5)]), it2
        ).ok

    def test_top1_all_tied_requires_identity_among_db_ties(self):
        # T37 : top-1, la seule ligne est à la frontière (n_core = 0)
        it = item(
            ordered=True,
            order_by=["v"],
            tie_tolerant=True,
            prefix_ok=True,
            column_groups=[["agent_id", "nom"]],
        )
        ref = rs(["agent_id", "nom", "v"], [(12, "Agent 012", 900)])
        wrong = rs(["agent_id", "nom", "v"], [(999, "Mauvais agent", 900)])
        assert not compare_execution(ref, wrong, it).ok  # sans ex æquo connus : identité exigée
        ref.boundary = [(12, "Agent 012", 900), (40, "Agent 040", 900)]
        assert not compare_execution(ref, wrong, it).ok
        assert compare_execution(ref, rs(["nom", "v"], [("Agent 040", 900)]), it).ok
        assert compare_execution(ref, rs(["agent_id", "v"], [(12, 900)]), it).ok

    def test_tie_extra_rows_at_cutoff(self):
        # T20 : top-5 avec trois villes ex æquo à 4 ; une réponse qui les donne toutes est juste
        it = item(ordered=True, order_by=["n"], tie_tolerant=True)
        ref = rs(
            ["ville", "n"],
            [("Dakar", 19), ("Thiès", 7), ("Rufisque", 5), ("Touba", 5), ("Louga", 4)],
        )
        all_ties = rs(
            ["ville", "n"],
            [
                ("Dakar", 19),
                ("Thiès", 7),
                ("Touba", 5),
                ("Rufisque", 5),
                ("Louga", 4),
                ("Pikine", 4),
                ("Saint-Louis", 4),
            ],
        )
        assert not compare_execution(ref, all_ties, it).ok  # ex æquo non vérifiables sans la base
        ref.boundary = [("Louga", 4), ("Pikine", 4), ("Saint-Louis", 4)]
        assert compare_execution(ref, all_ties, it).ok
        other_tie = rs(["ville", "n"], [*ref.rows[:4], ("Saint-Louis", 4)])
        assert compare_execution(ref, other_tie, it).ok
        # ligne en trop qui n'est pas ex æquo (ou inventée) : refusée
        assert not compare_execution(ref, rs(["ville", "n"], [*ref.rows, ("Kolda", 3)]), it).ok
        assert not compare_execution(ref, rs(["ville", "n"], [*ref.rows, ("Matam", 4)]), it).ok
        assert not compare_execution(
            ref, rs(["ville", "n"], [*ref.rows, ("Pikine", 4), ("Pikine", 4)]), it
        ).ok

    def test_tie_at_cutoff_with_id_groups(self):
        ref = rs(["agent_id", "nom", "n"], [(1, "A1", 9), (2, "A2", 5)])
        it = item(ordered=True, order_by=["n"], tie_tolerant=True, column_groups=[["agent_id", "nom"]])
        assert compare_execution(ref, rs(["nom", "volume"], [("A1", 9), ("A7", 5)]), it).ok
        assert compare_execution(ref, rs(["agent_id", "volume"], [(1, 9), (7, 5)]), it).ok
        assert not compare_execution(ref, rs(["nom", "volume"], [("A3", 9), ("A2", 5)]), it).ok

    def test_column_groups(self):
        ref = rs(["agent_id", "nom", "n"], [(1, "Agent 001", 9), (2, "Agent 002", 7)])
        it = item(column_groups=[["agent_id", "nom"]])
        assert compare_execution(ref, rs(["nom", "n"], [("Agent 001", 9), ("Agent 002", 7)]), it).ok
        assert compare_execution(ref, rs(["id", "n"], [(1, 9), (2, 7)]), it).ok
        assert not compare_execution(ref, rs(["n"], [(9,), (7,)]), it).ok

    def test_prefix_ok(self):
        ref = rs(["segment", "frais"], [("particulier", 100)])
        it = item(ordered=True, order_by=["frais"], prefix_ok=True)
        got = rs(["segment", "frais"], [("particulier", 100), ("entreprise", 50), ("commercant", 40)])
        assert compare_execution(ref, got, it).ok
        bad = rs(["segment", "frais"], [("entreprise", 50), ("particulier", 100)])
        assert not compare_execution(ref, bad, it).ok
        assert not compare_execution(ref, got, item(ordered=True, order_by=["frais"])).ok

    def test_expected_empty(self):
        ref = rs(["agent_id", "n"], [])
        it = item(expected_empty=True)
        assert compare_execution(ref, rs(["agent_id", "n"], []), it).ok
        assert compare_execution(ref, None, it).ok
        assert not compare_execution(ref, rs(["agent_id", "n"], [(1, 2)]), it).ok
        # référence non vide alors que vide attendu : défaut du jeu signalé
        assert compare_execution(rs(["n"], [(1,)]), None, it).reason == "reference_non_vide"

    def test_no_result(self):
        assert compare_execution(rs(["n"], [(1,)]), None).reason == "aucun_resultat"

    def test_pivot_long_format(self):
        ref = rs(["courante", "precedente"], [(Decimal("219047481"), Decimal("216348235"))])
        got = rs(["periode", "valeur_transferee"], [("courante", 219047481), ("comparaison", 216348235)])
        assert pivot_periode(got) is not None
        assert compare_execution(ref, got).ok
        wrong = rs(["periode", "valeur_transferee"], [("courante", 219047481), ("comparaison", 216348000)])
        assert not compare_execution(ref, wrong).ok
        # Inversion courante/comparaison : les colonnes de période sont projetées par la valeur de
        # `periode`, pas par les valeurs seules.
        swapped = rs(["periode", "valeur_transferee"], [("courante", 216348235), ("comparaison", 219047481)])
        res = compare_execution(ref, swapped)
        assert not res.ok and res.reason == "periodes_inversees"

    def test_pivot_swapped_periods_from_reference_sql(self):
        # T09/T12 : colonnes nommées librement ; le couple (courante, comparaison) vient du SQL
        it = item(
            reference_sql=(
                "SELECT COALESCE(SUM(f.frais_xof) FILTER (WHERE f.date_id BETWEEN 20260801 AND 20260831), 0) "
                "AS frais_aout, COALESCE(SUM(f.frais_xof) FILTER (WHERE f.date_id BETWEEN 20260701 AND "
                "20260731), 0) AS frais_juillet FROM analytics.fact_transaction f WHERE f.statut = 'reussie'"
            )
        )
        ref = rs(["frais_aout", "frais_juillet"], [(500, 400)])
        good = rs(["periode", "revenus_frais"], [("courante", 500), ("comparaison", 400)])
        swapped = rs(["periode", "revenus_frais"], [("courante", 400), ("comparaison", 500)])
        assert compare_execution(ref, good, it).ok
        assert not compare_execution(ref, swapped, it).ok
        # deux métriques comparées : chaque comparaison doit être celle de sa propre mesure
        ref2 = rs(["courante", "precedente"], [(5, 4)])
        crossed = rs(
            ["periode", "a", "b"], [("courante", 5, 4), ("comparaison", 9, 9)]
        )  # 4 vient de la mesure b courante, pas de a__comparaison
        assert not compare_execution(ref2, crossed).ok

    def test_pivot_with_dimension(self):
        ref = rs(["segment", "sept", "aout"], [("a", 1, 2), ("b", 3, 4)])
        got = rs(
            ["segment", "periode", "frais"],
            [("a", "courante", 1), ("a", "comparaison", 2), ("b", "courante", 3), ("b", "comparaison", 4)],
        )
        assert compare_execution(ref, got).ok

    def test_hors_agent_zero_row(self):
        ref = rs(["region", "n"], [("Dakar", 8), ("Thiès", 9)])
        got = rs(["region", "n"], [("Dakar", 8), ("Thiès", 9), ("Non applicable", 0)])
        assert not compare_execution(ref, got).ok
        assert compare_execution(ref, got, item(tolerate_hors_agent_zero=True)).ok
        got2 = rs(["region", "n"], [("Dakar", 8), ("Thiès", 9), ("Non applicable", 3)])
        assert not compare_execution(ref, got2, item(tolerate_hors_agent_zero=True)).ok

    def test_ratio_column_in_percent(self):
        ref = rs(["type", "taux"], [("depot", Decimal("0.0637")), ("retrait", Decimal("0.061"))])
        got = rs(["type", "taux_pct"], [("depot", 6.37), ("retrait", 6.1)])
        assert compare_execution(ref, got).ok

    def test_dates_month_series(self):
        ref = rs(["mois", "n"], [(date(2026, 4, 1), 10), (date(2026, 5, 1), 12)])
        got = rs(["mois", "n"], [("2026-04-01", 10), ("2026-05-01", 12)])
        assert compare_execution(ref, got, item(ordered=True, order_by=["mois"])).ok

    def test_numbers_as_text_not_matched_as_columns(self):
        ref = rs(["n"], [(10,)])
        assert not compare_execution(ref, rs(["n"], [("dix",)])).ok


# ------------------------------------------------------------------ faits cités


class TestFacts:
    def test_single_value_cited(self):
        ref = rs(["v"], [(Decimal("216348235"),)])
        assert compare_facts(ref, msg(facts=[(216348235, "xof")])).ok
        assert compare_facts(ref, msg(facts=[(216348236, "xof")])).reason == "chiffre_non_conforme"
        assert compare_facts(ref, msg(facts=[])).reason == "aucun_chiffre_cite"

    def test_ratio_fact_as_pct(self):
        ref = rs(["taux"], [(Decimal("0.0610889774"),)])
        assert compare_facts(ref, msg(facts=[(6.10889774, "pct")])).ok
        assert compare_facts(ref, msg(facts=[(0.0610889774, "ratio")])).ok

    def test_derived_facts(self):
        ref = rs(["courante", "precedente"], [(Decimal("219047481"), Decimal("216348235"))])
        diff = 219047481 - 216348235
        pct = 100 * diff / 216348235
        m = msg(
            facts=[
                (219047481, "xof"),
                (216348235, "xof"),
                (diff, "xof", "d1", "Écart de Valeur transférée — septembre 2026 vs août 2026"),
                (pct, "pct", "d2", "Variation de Valeur transférée — septembre 2026 vs août 2026"),
            ]
        )
        assert compare_facts(ref, m).ok
        # une différence non déclarée comme dérivé (fait `f…` ordinaire) n'est plus acceptée
        assert not compare_facts(ref, msg(facts=[(219047481, "xof"), (216348235, "xof"), (diff, "xof")])).ok

    def test_reversed_comparison_rejected(self):
        # T09 : variation de signe opposé (périodes interverties) refusée
        ref = rs(["courante", "precedente"], [(Decimal("219047481"), Decimal("216348235"))])
        a, b = 219047481, 216348235
        lab = "Variation de Valeur transférée — septembre 2026 vs août 2026"
        cells = [(a, "xof"), (b, "xof")]
        good = msg(facts=[*cells, (round(100 * (a - b) / b, 6), "pct", "d1", lab)])
        assert compare_facts(ref, good).ok
        rev = msg(facts=[*cells, (round(100 * (b - a) / a, 6), "pct", "d1", lab)])
        assert compare_facts(ref, rev).reason == "chiffre_non_conforme"
        rev_ecart = msg(facts=[*cells, (b - a, "xof", "d2", "Écart de Valeur transférée")])
        assert not compare_facts(ref, rev_ecart).ok
        # couple dérivé du SQL de référence quand les colonnes sont nommées librement
        it = item(
            reference_sql=(
                "SELECT SUM(f.frais_xof) FILTER (WHERE f.date_id BETWEEN 20260801 AND 20260831) AS aout, "
                "SUM(f.frais_xof) FILTER (WHERE f.date_id BETWEEN 20260701 AND 20260731) AS juillet "
                "FROM analytics.fact_transaction f"
            )
        )
        ref2 = rs(["aout", "juillet"], [(500, 400)])
        ok2 = msg(facts=[(500, "xof"), (400, "xof"), (25.0, "pct", "d1", "Variation de Revenus de frais")])
        assert compare_facts(ref2, ok2, it).ok
        bad2 = msg(facts=[(500, "xof"), (400, "xof"), (-20.0, "pct", "d1", "Variation de Revenus de frais")])
        assert not compare_facts(ref2, bad2, it).ok

    def test_small_integers_attached_to_cells(self):
        # T36 : agents actifs par région ; un entier quelconque n'est plus « une différence de cellules »
        ref = rs(["region", "agents_actifs"], [("Dakar", 41), ("Thiès", 17), ("Louga", 9), ("Matam", 3)])
        accepted = [
            v for v in range(60) if compare_facts(ref, msg(facts=[(v, "count", "f1", "Agents actifs")])).ok
        ]
        assert accepted == [3, 9, 17, 41]
        # rattachement à la ligne par le libellé : la valeur de Dakar doit être celle de Dakar
        assert compare_facts(ref, msg(facts=[(41, "count", "f1", "Agents actifs — Dakar — août 2026")])).ok
        assert not compare_facts(
            ref, msg(facts=[(17, "count", "f1", "Agents actifs — Dakar — août 2026")])
        ).ok
        assert compare_facts(
            ref, msg(facts=[(70, "count", "f9", "Total de Agents actifs (somme des lignes)")])
        ).ok
        assert compare_facts(ref, msg(facts=[(4, "count", "f9", "Nombre de lignes du résultat r1")])).ok
        part = round(100 * 17 / 70, 6)
        assert compare_facts(ref, msg(facts=[(part, "pct", "d1", "Part de Thiès dans Agents actifs")])).ok
        assert not compare_facts(ref, msg(facts=[(part, "pct", "d1", "Part de Dakar dans Agents actifs")])).ok

    def test_must_cite_all_single_row_values(self):
        ref = rs(["courante", "precedente"], [(10, 8)])
        res = compare_facts(ref, msg(facts=[(10, "count")]))
        assert res.reason == "chiffre_attendu_non_cite"
        it = item(must_cite=["courante"])
        assert compare_facts(ref, msg(facts=[(10, "count")]), it).ok

    def test_multi_row_any_cited_value(self):
        ref = rs(["region", "v"], [("Dakar", 90), ("Thiès", 10)])
        assert compare_facts(ref, msg(facts=[(90, "xof")])).ok
        total = (100, "xof", "f5", "Total de Valeur transférée (somme des lignes)")
        assert compare_facts(ref, msg(facts=[total])).ok  # total déclaré
        assert not compare_facts(ref, msg(facts=[(100, "xof")])).ok  # total présenté comme cellule
        assert compare_facts(ref, msg(facts=[(90.0, "pct", "d1", "Part de Dakar dans Valeur")])).ok
        assert not compare_facts(ref, msg(facts=[(91, "xof")])).ok

    def test_only_rendered_facts_count_when_present(self):
        ref = rs(["v"], [(10,)])
        m = msg(facts=[(10, "count")])
        m.facts.append(Fact(id="f9", value=999, unit="count", label="non cité"))
        assert compare_facts(ref, m).ok

    def test_empty_expected(self):
        ref = rs(["n"], [])
        it = item(expected_empty=True)
        assert compare_facts(ref, msg(facts=[]), it).ok
        assert compare_facts(ref, msg(facts=[(0, "count")]), it).ok
        assert not compare_facts(ref, msg(facts=[(3, "count")]), it).ok

    def test_non_numeric_facts_ignored(self):
        ref = rs(["v"], [(10,)])
        m = msg(facts=[(10, "count")])
        m.facts.append(Fact(id="f8", value="Dakar", unit="text", label="région", rendered="Dakar"))
        assert compare_facts(ref, m).ok


# ------------------------------------------------------------------ période, périmètre, intention


class TestPeriodScopeIntent:
    def test_period(self):
        exp = (date(2026, 9, 1), date(2026, 9, 30))
        assert compare_period(exp, msg(period=("2026-09-01", "2026-09-30"))).ok
        assert not compare_period(exp, msg(period=("2026-08-01", "2026-08-31"))).ok
        assert compare_period(exp, msg()).reason == "periode_absente"
        assert compare_period(None, msg()).ok

    def test_period_clamped_to_data_window(self):
        # « en 2026 » : 2026-01-01 → 2026-12-31 équivaut à 2026-01-01 → 2026-09-30 (fin des données)
        exp = (date(2026, 1, 1), date(2026, 12, 31))
        assert compare_period(exp, msg(period=("2026-01-01", "2026-09-30"))).ok
        exp2 = (date(2025, 1, 1), date(2025, 12, 31))
        assert compare_period(exp2, msg(period=("2025-04-01", "2025-12-31"))).ok
        # période entièrement antérieure aux données : comparaison brute
        exp3 = (date(2025, 2, 1), date(2025, 2, 28))
        assert compare_period(exp3, msg(period=("2025-02-01", "2025-02-28"))).ok
        assert not compare_period(exp3, msg(period=("2025-01-01", "2025-01-31"))).ok

    def test_period_from_message_period(self):
        from decision_core.models import Period

        m = msg()
        m.period = Period(start=date(2026, 9, 1), end=date(2026, 9, 30))
        assert compare_period((date(2026, 9, 1), date(2026, 9, 30)), m).ok

    def test_scope_shapes(self):
        assert extract_scope(
            msg(
                scope={
                    "region_kind": "region_client",
                    "filters": [{"dimension": "region_client", "values": ["Thiès"]}],
                }
            )
        ) == ("region_client", {"region_client": {"thies"}})
        assert extract_scope(msg(scope={"type": ["depot"]}))[1] == {"type": {"depot"}}
        assert extract_scope(msg(scope=[{"dimension": "type", "values": ["retrait"]}]))[1] == {
            "type": {"retrait"}
        }
        assert extract_scope(msg(scope="national"))[1] == {}
        not_in = [{"dimension": "agent", "op": "not_in", "values": ["-1"]}]
        assert extract_scope(msg(scope=not_in))[1] == {}

    def test_scope_compare(self):
        it = item(expected_scope={"region_kind": "region_agent", "filters": {"region_agent": ["Thiès"]}})
        good = msg(
            region_kind="region_agent",
            scope={"filters": [{"dimension": "region_agent", "values": ["Thiès"]}]},
        )
        assert compare_scope(it, good).ok
        wrong_kind = msg(
            region_kind="region_client",
            scope={"filters": [{"dimension": "region_agent", "values": ["Thiès"]}]},
        )
        assert compare_scope(it, wrong_kind).reason == "sens_region"
        wrong_val = msg(
            region_kind="region_agent",
            scope={"filters": [{"dimension": "region_agent", "values": ["Dakar"]}]},
        )
        assert compare_scope(it, wrong_val).reason == "filtre"
        assert compare_scope(it, msg(region_kind="region_agent")).reason in {"perimetre_absent", "filtre"}

    def test_scope_extra_filter_fails(self):
        it = item(expected_scope={"filters": {}})
        assert not compare_scope(it, msg(scope={"filters": [{"dimension": "type", "values": ["depot"]}]})).ok
        assert compare_scope(it, msg(scope={"filters": []})).ok
        # filtre hors dimensions connues (jour_ferie) : ignoré
        assert compare_scope(it, msg(scope={"filters": [{"dimension": "jour_ferie", "values": ["true"]}]})).ok

    def test_intent(self):
        it = item(id="R", expected_kind="refusal", reference_sql=None)
        assert compare_intent(it, msg(kind="refusal")).ok
        assert compare_intent(it, msg(kind="answer")).reason == "intention:answer"
        it2 = item(id="R", expected_kind="answer", accept_kinds=["clarification"])
        assert compare_intent(it2, msg(kind="clarification")).ok


# ------------------------------------------------------------------ verdict complet


def full_item():
    return item(
        expected_period={"start": "2026-09-01", "end": "2026-09-30"},
        expected_scope={"filters": {"type": ["retrait"]}},
    )


def test_grade_all_four_required():
    ref = rs(["n"], [(265,)])
    scope = {"filters": [{"dimension": "type", "values": ["retrait"]}]}
    ok = msg(["n"], [(265,)], facts=[(265, "count")], period=("2026-09-01", "2026-09-30"), scope=scope)
    v = grade(full_item(), ok, ref)
    assert v.passed, v.reasons
    # résultat juste, chiffre cité faux
    v = grade(
        full_item(),
        msg(["n"], [(265,)], facts=[(266, "count")], period=("2026-09-01", "2026-09-30"), scope=scope),
        ref,
    )
    assert not v.passed and v.reasons == ["chiffres:chiffre_non_conforme"]
    # période fausse
    v = grade(
        full_item(),
        msg(["n"], [(265,)], facts=[(265, "count")], period=("2026-09-01", "2026-09-15"), scope=scope),
        ref,
    )
    assert not v.passed and v.reasons == ["periode:periode"]
    # périmètre faux
    v = grade(
        full_item(),
        msg(
            ["n"],
            [(265,)],
            facts=[(265, "count")],
            period=("2026-09-01", "2026-09-30"),
            scope={"filters": []},
        ),
        ref,
    )
    assert not v.passed and v.reasons == ["perimetre:filtre"]
    # exécution fausse
    v = grade(
        full_item(),
        msg(["n"], [(264,)], facts=[(265, "count")], period=("2026-09-01", "2026-09-30"), scope=scope),
        ref,
    )
    assert not v.passed and len(v.reasons) == 1 and v.reasons[0].startswith("execution:")


def test_grade_wrong_kind_and_non_answer_items():
    ref = rs(["n"], [(265,)])
    v = grade(full_item(), msg(kind="refusal"), ref)
    assert not v.passed and v.checks == {"intention": False}
    clar = item(id="C", expected_kind="clarification", reference_sql=None)
    assert grade(clar, msg(kind="clarification"), None).passed
    assert not grade(clar, msg(kind="answer"), None).passed


def test_grade_without_reference():
    v = grade(full_item(), msg(["n"], [(1,)], facts=[(1, "count")]), None)
    assert not v.passed and "reference_absente" in v.reasons


@pytest.mark.parametrize("got", [6.108897, 0.06108897742, 6.108897742363877])
def test_ratio_facts_param(got):
    ref = rs(["taux"], [(Decimal("0.06108897742363877822"),)])
    unit = "pct" if got > 1 else "ratio"
    assert compare_facts(ref, msg(facts=[(got, unit)])).ok


def test_grade_expected_empty_explained_without_table():
    # T38 : vide par construction ; la réponse explique l'impossibilité sans tableau ni état résolu
    it = item(
        expected_period={"start": "2026-09-01", "end": "2026-09-30"},
        expected_scope={
            "region_kind": "region_agent",
            "filters": {"region_agent": ["Kédougou"], "type": ["transfert"]},
        },
        expected_empty=True,
    )
    ref = rs(["agent_id", "nom", "volume_transferts"], [])
    text = "Les transferts n'ont pas de point de service : aucun agent de Kédougou ne peut en réaliser."
    v = grade(it, msg(text=text), ref)
    assert v.passed, v.reasons
    assert grade(it, msg(caveats=["resultat_vide"]), ref).passed
    # sans explication du vide : période et périmètre restent exigés
    v = grade(it, msg(text="Voici la réponse."), ref)
    assert not v.passed and "periode:periode_absente" in v.reasons
    # période fausse présente : toujours vérifiée
    assert not grade(it, msg(text=text, period=("2026-08-01", "2026-08-31")), ref).passed


def test_identifier_columns_are_not_cited_values():
    # T37 : agent_id n'est ni une valeur citable ni une valeur à citer
    ref = rs(["agent_id", "nom", "valeur_transferee"], [(6, "Agent 006", Decimal("19482990"))])
    assert compare_facts(ref, msg(facts=[(19482990, "xof")])).ok
    assert not compare_facts(ref, msg(facts=[(19482990, "xof"), (6, "count")])).ok
