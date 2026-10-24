"""Déterminisme et contraintes métier du générateur (sans base de données)."""

from __future__ import annotations

from datetime import date

import numpy as np
import pytest
from decision_data_gen import data_hash, generate
from decision_data_gen import reference as ref
from decision_data_gen.generate import EPOCH

SCALE = 0.01


@pytest.fixture(scope="module")
def ds():
    return generate(SCALE, 42)


def _d(x: date) -> int:
    return (x - EPOCH).days


def test_deterministe(ds):
    autre = generate(SCALE, 42)
    assert data_hash(ds) == data_hash(autre)
    assert np.array_equal(ds.txn_montant, autre.txn_montant)


def test_graine_differente_donne_autres_donnees(ds):
    assert data_hash(ds) != data_hash(generate(SCALE, 43))


def test_volumes_proportionnels(ds):
    assert len(ds.client_id) == 500
    assert len(ds.agent_id) == 28  # minimum : deux agents par région
    assert len(ds.txn_id) == 22_000
    assert np.array_equal(ds.txn_id, np.arange(1, len(ds.txn_id) + 1))


def test_periode_et_reference_date(ds):
    jours = ds.txn_seconds // 86_400
    assert jours.min() >= _d(ref.START_DATE)
    assert jours.max() <= _d(ref.REFERENCE_DATE)
    assert np.all(np.diff(ds.txn_seconds) >= 0)  # tri chronologique


def test_type_et_agent_coherents(ds):
    hors_agent = ds.txn_agent < 0
    assert np.array_equal(hors_agent, ds.txn_type >= 2)  # transfert, paiement ⇔ hors agent
    part = hors_agent.mean()
    assert 0.10 <= part <= 0.15


def test_taux_echec(ds):
    assert 0.05 <= ds.txn_echec.mean() <= 0.10


def test_montants_et_frais(ds):
    assert ds.txn_montant.min() > 0
    assert np.all(ds.txn_frais >= 0)
    assert np.all(ds.txn_frais <= ds.txn_montant)
    assert np.all(ds.txn_frais[ds.txn_type == 0] == 0)  # dépôts gratuits
    assert np.all(ds.txn_frais[ds.txn_echec] == 0)  # échecs non facturés
    retraits = (ds.txn_type == 1) & ~ds.txn_echec
    taux = ds.txn_frais[retraits].sum() / ds.txn_montant[retraits].sum()
    assert 0.009 <= taux <= 0.011
    assert ds.txn_montant.max() > 20 * np.median(ds.txn_montant)  # valeurs aberrantes présentes


def test_inscription_avant_premiere_transaction(ds):
    premiere = np.full(len(ds.client_id) + 1, np.iinfo(np.int64).max)
    np.minimum.at(premiere, ds.txn_client, ds.txn_seconds // 86_400)
    actifs = premiere[1:] < np.iinfo(np.int64).max
    assert np.all(ds.client_inscription[actifs] <= premiere[1:][actifs])


def test_agents_ouverts_a_la_date(ds):
    avec = ds.txn_agent > 0
    a = ds.txn_agent[avec] - 1
    jour = ds.txn_seconds[avec] // 86_400
    assert np.all(ds.agent_activation[a] <= jour)
    ferm = ds.agent_fermeture[a]
    assert np.all((ferm < 0) | (jour < ferm))


def test_dakar_majoritaire():
    big = generate(0.05, 42)
    region_client = big.client_region[big.txn_client - 1]
    assert 0.35 <= (region_client == 1).mean() <= 0.42
    avec = big.txn_agent > 0
    region_agent = big.agent_region[big.txn_agent[avec] - 1]
    assert 0.35 <= (region_agent == 1).mean() <= 0.42


def test_saisonnalite_fin_de_mois_et_tabaski():
    big = generate(0.05, 42)
    jours = big.txn_seconds // 86_400
    compte = np.bincount(jours - big.days[0], minlength=len(big.days))

    def n(x: date) -> int:
        return int(compte[_d(x) - big.days[0]])

    milieu = np.mean([n(date(2026, 5, d)) for d in (12, 13, 19, 20)])  # mardis/mercredis
    assert n(date(2026, 5, 26)) > 1.4 * milieu  # veille de Tabaski 2026
    assert n(date(2026, 4, 30)) > 1.15 * milieu  # fin de mois


def test_tables_de_reference(ds):
    assert [r.nom for r in ref.REGIONS][0] == "Dakar"
    assert len(ref.REGIONS) == 14
    assert set(np.unique(ds.agent_region)) == set(range(1, 15))  # au moins un agent par région
    assert any(nom in ds.agent_nom for nom in ref.NOMS_ATYPIQUES)
    assert sum(1 for f in ds.agent_fermeture if f >= 0) >= 0
