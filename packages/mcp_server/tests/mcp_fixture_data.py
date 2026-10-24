"""Petit jeu analytics de fixture, déterministe, conforme à semantic/tables.yaml.

Chargé en tant que dbt_owner (les droits par défaut donnent SELECT à agent_ro_base).
Les valeurs attendues des KPI sont recalculées en Python à partir des mêmes lignes.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

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
SEGMENTS = ["particulier", "commercant", "entreprise"]
MOIS_FR = [
    "janvier",
    "février",
    "mars",
    "avril",
    "mai",
    "juin",
    "juillet",
    "août",
    "septembre",
    "octobre",
    "novembre",
    "décembre",
]

DDL = """
DROP TABLE IF EXISTS analytics.fact_transaction, analytics.dim_client, analytics.dim_agent,
  analytics.dim_region, analytics.dim_date;
CREATE TABLE analytics.dim_region (region_id integer PRIMARY KEY, region text NOT NULL, pays text NOT NULL);
CREATE TABLE analytics.dim_date (
  date_id integer PRIMARY KEY, date date NOT NULL UNIQUE, jour_semaine smallint, semaine_iso smallint,
  mois smallint, nom_mois text, trimestre smallint, annee smallint, est_weekend boolean, jour_ferie boolean,
  debut_mois date, fin_mois date);
CREATE TABLE analytics.dim_client (
  client_id integer PRIMARY KEY, date_inscription date,
  region_client_id integer REFERENCES analytics.dim_region, segment text);
CREATE TABLE analytics.dim_agent (
  agent_id integer PRIMARY KEY, nom text, ville text, region_agent_id integer REFERENCES analytics.dim_region,
  date_activation date, statut_agent text);
CREATE TABLE analytics.fact_transaction (
  transaction_id bigint PRIMARY KEY, client_id integer REFERENCES analytics.dim_client,
  agent_id integer REFERENCES analytics.dim_agent, region_client_id integer REFERENCES analytics.dim_region,
  region_agent_id integer REFERENCES analytics.dim_region, date_id integer REFERENCES analytics.dim_date,
  txn_ts timestamptz, type text, montant_xof numeric(14,0), frais_xof numeric(12,0), statut text);
CREATE INDEX ON analytics.fact_transaction (date_id);
"""


@dataclass(frozen=True)
class Txn:
    transaction_id: int
    client_id: int
    agent_id: int
    region_client_id: int
    region_agent_id: int
    date_id: int
    txn_ts: datetime
    type: str
    montant_xof: int
    frais_xof: int
    statut: str

    @property
    def day(self) -> date:
        return date(self.date_id // 10000, (self.date_id // 100) % 100, self.date_id % 100)


@dataclass
class Fixture:
    regions: dict[int, str]
    clients: dict[int, tuple[int, str]]  # client_id → (region_client_id, segment)
    agents: dict[int, tuple[str, int, str]]  # agent_id → (nom, region_agent_id, statut_agent)
    txns: list[Txn]


def build_fixture(seed: int = 42) -> Fixture:
    rng = random.Random(seed)  # noqa: S311 - données de test déterministes
    regions = {-1: "Non applicable", **{i + 1: r for i, r in enumerate(REGIONS)}}
    clients = {c: ((c % 14) + 1, SEGMENTS[c % 3]) for c in range(1, 41)}
    agents: dict[int, tuple[str, int, str]] = {-1: ("Hors agent", -1, "ouvert")}
    for a in range(1, 11):
        agents[a] = (f"Agent {a:02d}", ((a - 1) % 5) + 1, "ouvert" if a % 4 else "ferme")
    txns: list[Txn] = []
    # Jours tirés surtout en février-mars 2026 et mars 2025 (comparaisons), le reste sur 18 mois.
    hot = (
        [date(2026, 3, 1) + timedelta(days=i) for i in range(31)]
        + [date(2026, 2, 1) + timedelta(days=i) for i in range(28)]
        + [date(2025, 3, 1) + timedelta(days=i) for i in range(31)]
    )
    start = date(2025, 4, 1)
    for tid in range(1, 701):
        day = rng.choice(hot) if rng.random() < 0.7 else start + timedelta(days=rng.randrange(548))
        client = rng.randrange(1, 41)
        ttype = rng.choice(["depot", "retrait", "transfert", "paiement"])
        if ttype in ("depot", "retrait"):
            # L'agent 10 ne travaille jamais en mars 2026 (classement, agents actifs).
            agent = rng.randrange(1, 10) if day.strftime("%Y%m") == "202603" else rng.randrange(1, 11)
            region_agent = agents[agent][1]
        else:
            agent, region_agent = -1, -1
        montant = rng.randrange(1_000, 500_000)
        frais = (montant * rng.choice([0, 1, 2])) // 100
        statut = "echouee" if rng.random() < 0.15 else "reussie"
        ts = datetime(day.year, day.month, day.day, rng.randrange(24), rng.randrange(60), tzinfo=UTC)
        txns.append(
            Txn(
                tid,
                client,
                agent,
                clients[client][0],
                region_agent,
                day.year * 10000 + day.month * 100 + day.day,
                ts,
                ttype,
                montant,
                frais,
                statut,
            )
        )
    return Fixture(regions, clients, agents, txns)


def load_fixture(conn, fx: Fixture) -> None:  # conn : psycopg.Connection (dbt_owner)
    with conn.cursor() as cur:
        cur.execute(DDL)
        cur.executemany(
            "INSERT INTO analytics.dim_region VALUES (%s, %s, %s)",
            [(k, v, "Sénégal" if k > 0 else "Non applicable") for k, v in fx.regions.items()],
        )
        d = date(2025, 1, 1)
        rows = []
        while d <= date(2026, 12, 31):
            month_end = (d.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
            rows.append(
                (
                    d.year * 10000 + d.month * 100 + d.day,
                    d,
                    d.isoweekday(),
                    d.isocalendar()[1],
                    d.month,
                    MOIS_FR[d.month - 1],
                    (d.month - 1) // 3 + 1,
                    d.year,
                    d.isoweekday() >= 6,
                    False,
                    d.replace(day=1),
                    month_end,
                )
            )
            d += timedelta(days=1)
        cur.executemany("INSERT INTO analytics.dim_date VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", rows)
        cur.executemany(
            "INSERT INTO analytics.dim_client VALUES (%s, %s, %s, %s)",
            [(c, date(2024, 1, 1), r, s) for c, (r, s) in fx.clients.items()],
        )
        cur.executemany(
            "INSERT INTO analytics.dim_agent VALUES (%s, %s, %s, %s, %s, %s)",
            [(a, n, "Ville", r, date(2024, 1, 1), s) for a, (n, r, s) in fx.agents.items()],
        )
        cur.executemany(
            "INSERT INTO analytics.fact_transaction VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            [
                (
                    t.transaction_id,
                    t.client_id,
                    t.agent_id,
                    t.region_client_id,
                    t.region_agent_id,
                    t.date_id,
                    t.txn_ts,
                    t.type,
                    t.montant_xof,
                    t.frais_xof,
                    t.statut,
                )
                for t in fx.txns
            ],
        )
        cur.execute("ANALYZE analytics.fact_transaction")
    conn.commit()


# --- Valeurs attendues ---------------------------------------------------------------------------


def expected_kpis(txns: list[Txn]) -> dict[str, float | int | None]:
    ok = [t for t in txns if t.statut == "reussie"]
    total = len(txns)
    return {
        "volume_transactions": len(ok),
        "valeur_transferee": sum(t.montant_xof for t in ok),
        "revenus_frais": sum(t.frais_xof for t in ok),
        "clients_actifs": len({t.client_id for t in ok}),
        "agents_actifs": len({t.agent_id for t in ok if t.agent_id != -1}),
        "taux_echec": (sum(1 for t in txns if t.statut == "echouee") / total) if total else None,
    }


def in_period(txns: list[Txn], start: date, end: date) -> list[Txn]:
    return [t for t in txns if start <= t.day <= end]
