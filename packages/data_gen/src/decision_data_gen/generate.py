"""Génération vectorisée (numpy) des tables brutes.

Tout le tirage passe par un unique `numpy.random.Generator(PCG64(seed))`, dans un ordre fixe :
même graine, même échelle et même version de numpy ⇒ données identiques (voir `data_hash`).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np

from . import reference as ref

VOLUME_ECHELLE_1 = 2_200_000  # transactions à l'échelle 1.0 (cible SRS : 1,5 à 3 M)
CLIENTS_ECHELLE_1 = 50_000
AGENTS_ECHELLE_1 = 2_000
EPOCH = date(1970, 1, 1)


@dataclass
class Dataset:
    """Colonnes des tables brutes (tableaux numpy alignés, dates en jours depuis 1970-01-01)."""

    scale: float
    seed: int
    days: np.ndarray  # jours calendaires de la période (int, jours depuis 1970)
    day_weight: np.ndarray  # poids journalier (saisonnalité) utilisé pour le tirage
    # clients
    client_id: np.ndarray
    client_inscription: np.ndarray
    client_region: np.ndarray
    client_segment: np.ndarray  # index dans ref.SEGMENTS
    # agents
    agent_id: np.ndarray
    agent_nom: list[str]
    agent_ville: list[str]
    agent_region: np.ndarray
    agent_activation: np.ndarray
    agent_fermeture: np.ndarray  # -1 si ouvert
    # transactions (triées par horodatage)
    txn_id: np.ndarray
    txn_client: np.ndarray
    txn_agent: np.ndarray  # -1 = hors agent (NULL dans raw)
    txn_seconds: np.ndarray  # secondes depuis 1970 (UTC = heure de Dakar)
    txn_type: np.ndarray  # index dans ref.TYPES
    txn_montant: np.ndarray
    txn_frais: np.ndarray
    txn_echec: np.ndarray  # booléen


def _d(x: date) -> int:
    return (x - EPOCH).days


def daily_weights(days: np.ndarray) -> np.ndarray:
    """Saisonnalité : tendance, jour de semaine, fin de mois, fêtes, jours fériés."""
    n = len(days)
    dates = [EPOCH + timedelta(days=int(x)) for x in days]
    w = 1.0 + 0.10 * np.arange(n) / max(n - 1, 1)  # croissance de la base d'utilisateurs
    semaine = np.array([1.00, 0.97, 0.98, 1.00, 1.08, 0.93, 0.72])
    w *= semaine[[d.weekday() for d in dates]]
    for i, d in enumerate(dates):
        fin = (d.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
        if d.day >= fin.day - 4 or d.day <= 3:  # salaires : fin et début de mois
            w[i] *= 1.30 if d.day == fin.day else 1.22
        if d.month == 10 and d.day <= 10:  # rentrée scolaire
            w[i] *= 1.08
    index = {x: i for i, x in enumerate(days.tolist())}
    for jour, nom, _cat in ref.JOURS_FERIES:
        i = index.get(_d(jour))
        if i is None:
            continue
        pic = next((p for p in ref.FETES_PIC if p[0] in nom), None)
        if pic is not None:
            _, avant, mult = pic
            for k in range(1, avant + 1):  # montée progressive jusqu'à la veille
                j = i - k
                if 0 <= j < n:
                    w[j] *= 1 + (mult - 1) * (avant - k + 1) / avant
        w[i] *= 0.65 if pic is not None else 0.78  # le jour férié lui-même est calme
    return w


def generate(scale: float = 1.0, seed: int = 42) -> Dataset:
    if not 0 < scale <= 2:
        raise ValueError("scale doit être dans ]0, 2]")
    rng = np.random.Generator(np.random.PCG64(seed))
    start, end = _d(ref.START_DATE), _d(ref.REFERENCE_DATE)
    days = np.arange(start, end + 1)
    n_days = len(days)
    day_w = daily_weights(days)

    n_regions = len(ref.REGIONS)
    region_w = np.array([r.poids for r in ref.REGIONS])
    region_w = region_w / region_w.sum()
    region_ids = np.array([r.region_id for r in ref.REGIONS])

    # ---------------------------------------------------------------- agents
    n_agents = max(2 * n_regions, round(AGENTS_ECHELLE_1 * scale))
    # Un agent « historique » par région (toujours ouvert), puis tirage pondéré.
    a_region_idx = np.concatenate(
        [np.arange(n_regions), rng.choice(n_regions, size=n_agents - n_regions, p=region_w)]
    )
    a_region_idx.sort(kind="stable")  # agents regroupés par région
    historique = np.zeros(n_agents, dtype=bool)
    first_of_region = np.searchsorted(a_region_idx, np.arange(n_regions))
    historique[first_of_region] = True

    activation = np.where(
        rng.random(n_agents) < 0.78,
        rng.integers(_d(date(2018, 1, 1)), start, size=n_agents),
        rng.integers(start, _d(date(2026, 6, 30)), size=n_agents),
    )
    activation[historique] = rng.integers(_d(date(2018, 1, 1)), _d(date(2020, 1, 1)), size=n_regions)
    ferme = (rng.random(n_agents) < 0.05) & ~historique
    debut_fermeture = np.maximum(activation, start) + 60
    fermeture = np.where(
        ferme & (debut_fermeture < end - 30),
        debut_fermeture + (rng.random(n_agents) * np.maximum(end - 30 - debut_fermeture, 1)).astype(int),
        -1,
    )
    popularite = rng.lognormal(0.0, 0.8, size=n_agents)

    noms: list[str] = []
    villes: list[str] = []
    prenom_i = rng.integers(0, len(ref.PRENOMS), size=n_agents)
    nom_i = rng.integers(0, len(ref.NOMS), size=n_agents)
    ens_i = rng.integers(0, len(ref.ENSEIGNES), size=n_agents)
    ville_u = rng.random(n_agents)
    atypique = rng.choice(n_agents, size=min(len(ref.NOMS_ATYPIQUES), n_agents), replace=False)
    atypique_map = {int(a): ref.NOMS_ATYPIQUES[k] for k, a in enumerate(atypique)}
    for i in range(n_agents):
        region = ref.REGIONS[int(a_region_idx[i])]
        # La ville principale de la région concentre la moitié des points de service.
        u = float(ville_u[i])
        v = 0 if u < 0.5 else 1 + int((u - 0.5) * 2 * (len(region.villes) - 1))
        villes.append(region.villes[min(v, len(region.villes) - 1)])
        if i in atypique_map:
            noms.append(atypique_map[i])
        else:
            noms.append(f"{ref.ENSEIGNES[ens_i[i]]} {ref.PRENOMS[prenom_i[i]]} {ref.NOMS[nom_i[i]]}")

    # ---------------------------------------------------------------- clients
    n_clients = max(200, round(CLIENTS_ECHELLE_1 * scale))
    c_region_idx = rng.choice(n_regions, size=n_clients, p=region_w)
    c_segment = rng.choice(len(ref.SEGMENTS), size=n_clients, p=np.array(ref.SEGMENT_PROBA))
    inscription = np.where(
        rng.random(n_clients) < 0.68,
        rng.integers(_d(date(2021, 1, 1)), start, size=n_clients),
        rng.integers(start, end - 14, size=n_clients),
    )
    activite = rng.lognormal(0.0, 0.9, size=n_clients) * np.array(ref.SEGMENT_ACTIVITE)[c_segment]
    activite[rng.random(n_clients) < 0.03] = 0.0  # comptes ouverts mais jamais utilisés

    # ------------------------------------------------------------ transactions
    n_txn = round(VOLUME_ECHELLE_1 * scale)
    cdf = np.cumsum(day_w) / day_w.sum()
    insc_idx = np.clip(inscription - start, 0, n_days - 1)
    cdf_lo = np.where(insc_idx > 0, cdf[np.maximum(insc_idx - 1, 0)], 0.0)
    p_client = activite * (1.0 - cdf_lo)  # un client inscrit tard a moins de jours actifs
    p_client = p_client / p_client.sum()
    t_client = rng.choice(n_clients, size=n_txn, p=p_client)
    u = cdf_lo[t_client] + rng.random(n_txn) * (1.0 - cdf_lo[t_client])
    t_day = np.minimum(np.searchsorted(cdf, u, side="left"), n_days - 1)
    t_day = np.maximum(t_day, insc_idx[t_client])  # garde-fou : jamais avant l'inscription

    heures_w = np.array(
        [0.2, 0.1, 0.05, 0.05, 0.1, 0.3, 1.0, 2.5, 4.5, 6.0, 6.5, 6.5,
         6.0, 5.5, 5.5, 6.0, 6.5, 7.0, 7.0, 6.0, 4.5, 3.0, 1.5, 0.6]
    )
    t_sec = rng.choice(24, size=n_txn, p=heures_w / heures_w.sum()) * 3600 + rng.integers(
        0, 3600, size=n_txn
    )

    seg = c_segment[t_client]
    type_p = np.array(ref.TYPE_PROBA)
    t_type = (rng.random(n_txn)[:, None] > np.cumsum(type_p, axis=1)[seg]).sum(axis=1)
    t_type = np.minimum(t_type, len(ref.TYPES) - 1)
    avec_agent = t_type <= 1  # dépôt et retrait uniquement

    # Agent : 82 % dans la région du client, sinon région tirée selon les poids ; agent tiré
    # selon sa popularité parmi ceux de la région, ouvert à la date de la transaction.
    t_agent = np.full(n_txn, -1, dtype=np.int64)
    idx_ag = np.flatnonzero(avec_agent)
    cible = np.where(
        rng.random(len(idx_ag)) < 0.82,
        c_region_idx[t_client[idx_ag]],
        rng.choice(n_regions, size=len(idx_ag), p=region_w),
    )
    jour_abs = days[t_day]
    for r in range(n_regions):
        sel = idx_ag[cible == r]
        if len(sel) == 0:
            continue
        lo = first_of_region[r]
        hi = first_of_region[r + 1] if r + 1 < n_regions else n_agents
        pop = popularite[lo:hi]
        pcdf = np.cumsum(pop) / pop.sum()
        choix = lo + np.minimum(np.searchsorted(pcdf, rng.random(len(sel))), hi - lo - 1)
        for _ in range(8):  # re-tirage des agents pas encore activés ou déjà fermés
            j = jour_abs[sel]
            ko = (activation[choix] > j) | ((fermeture[choix] >= 0) & (fermeture[choix] <= j))
            if not ko.any():
                break
            choix[ko] = lo + np.minimum(np.searchsorted(pcdf, rng.random(int(ko.sum()))), hi - lo - 1)
        j = jour_abs[sel]
        ko = (activation[choix] > j) | ((fermeture[choix] >= 0) & (fermeture[choix] <= j))
        choix[ko] = lo  # repli : agent historique de la région, toujours ouvert
        t_agent[sel] = choix

    # Montants log-normaux, arrondis à 5 XOF, avec quelques valeurs aberrantes.
    med = np.array(ref.MONTANT_MEDIAN)[t_type] * np.array(ref.SEGMENT_MONTANT)[seg]
    sig = np.array(ref.MONTANT_SIGMA)[t_type]
    montant = np.exp(np.log(med) + sig * rng.standard_normal(n_txn))
    montant = np.clip(montant, 100, 5_000_000)
    aberrant = rng.random(n_txn) < 0.0004
    montant[aberrant] *= rng.uniform(20, 80, size=int(aberrant.sum()))
    montant = np.maximum(np.round(montant / 5) * 5, 100).astype(np.int64)

    # Échecs : base 5,5 %, plus fréquents pour les paiements, les jours de pointe,
    # les régions à réseau fragile et les gros montants.
    pic = (day_w / np.median(day_w))[t_day] > 1.3
    fragile = np.array([r.reseau_fragile for r in ref.REGIONS])[c_region_idx[t_client]]
    p_echec = (
        0.055
        + 0.03 * (t_type == 3)
        + 0.01 * (t_type == 2)
        + 0.02 * pic
        + 0.025 * fragile
        + 0.04 * (montant > 1_000_000)
    )
    echec = rng.random(n_txn) < p_echec

    taux = np.array(ref.FRAIS_TAUX)[t_type]
    frais = (np.round(montant * taux / 5) * 5).astype(np.int64)
    frais = np.where((taux > 0) & (frais == 0), 5, frais)
    frais = np.minimum(frais, montant)
    frais[echec] = 0  # une transaction échouée n'est pas facturée

    seconds = jour_abs.astype(np.int64) * 86_400 + t_sec
    order = np.lexsort((t_client, seconds))  # tri chronologique, stable et déterministe

    return Dataset(
        scale=scale,
        seed=seed,
        days=days,
        day_weight=day_w,
        client_id=np.arange(1, n_clients + 1),
        client_inscription=inscription,
        client_region=region_ids[c_region_idx],
        client_segment=c_segment,
        agent_id=np.arange(1, n_agents + 1),
        agent_nom=noms,
        agent_ville=villes,
        agent_region=region_ids[a_region_idx],
        agent_activation=activation,
        agent_fermeture=fermeture,
        txn_id=np.arange(1, n_txn + 1, dtype=np.int64),
        txn_client=(t_client + 1)[order],
        txn_agent=np.where(t_agent >= 0, t_agent + 1, -1)[order],
        txn_seconds=seconds[order],
        txn_type=t_type[order],
        txn_montant=montant[order],
        txn_frais=frais[order],
        txn_echec=echec[order],
    )
