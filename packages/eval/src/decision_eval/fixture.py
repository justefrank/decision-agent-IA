"""Petit jeu analytics de fixture, conforme à semantic/tables.yaml.

Sert à vérifier que chaque `reference_sql` s'exécute (tests `db`) et à construire la base de test
des scénarios de sécurité. Déterministe (setseed). À lancer avec un rôle propriétaire du schéma
analytics (dbt_owner) pour que les droits par défaut donnent SELECT à agent_ro.
Ce n'est PAS le générateur de données du projet (packages/data_gen + warehouse/ dbt).
"""

from __future__ import annotations

FIXTURE_SQL = r"""
SET search_path = analytics;
DROP TABLE IF EXISTS analytics.fact_transaction, analytics.dim_client, analytics.dim_agent,
  analytics.dim_region, analytics.dim_date CASCADE;

CREATE TABLE analytics.dim_region (region_id integer PRIMARY KEY, region text NOT NULL, pays text NOT NULL);
INSERT INTO analytics.dim_region VALUES (-1, 'Non applicable', 'Sénégal');
INSERT INTO analytics.dim_region
SELECT i, r, 'Sénégal' FROM unnest(ARRAY['Dakar','Thiès','Diourbel','Kaolack','Saint-Louis','Ziguinchor',
  'Louga','Fatick','Kolda','Tambacounda','Kaffrine','Kédougou','Matam','Sédhiou']) WITH ORDINALITY AS t(r, i);

CREATE TABLE analytics.dim_date (
  date_id integer PRIMARY KEY, date date NOT NULL, jour_semaine smallint, semaine_iso smallint,
  annee_iso smallint, mois smallint, nom_mois text, trimestre smallint, annee smallint, est_weekend boolean,
  jour_ferie boolean, debut_mois date, fin_mois date);
INSERT INTO analytics.dim_date
SELECT to_char(d, 'YYYYMMDD')::int, d::date, extract(isodow FROM d)::smallint,
       extract(week FROM d)::smallint, to_char(d, 'IYYY')::smallint, extract(month FROM d)::smallint,
       (ARRAY['janvier','février','mars','avril','mai','juin','juillet','août','septembre','octobre',
              'novembre','décembre'])[extract(month FROM d)::int],
       extract(quarter FROM d)::smallint, extract(year FROM d)::smallint,
       extract(isodow FROM d) >= 6,
       to_char(d, 'MM-DD') IN ('01-01','04-04','05-01','08-15','11-01','12-25'),
       date_trunc('month', d)::date, (date_trunc('month', d) + interval '1 month - 1 day')::date
FROM generate_series('2024-01-01'::date, '2026-12-31'::date, interval '1 day') AS g(d);

CREATE TABLE analytics.dim_client (
  client_id integer PRIMARY KEY, date_inscription date, region_client_id integer, segment text);
SELECT setseed(0.42);
INSERT INTO analytics.dim_client
SELECT i, '2024-01-01'::date + (random() * 1003)::int,
       CASE WHEN random() < 0.4 THEN 1 ELSE 2 + floor(random() * 13)::int END,
       (ARRAY['particulier','particulier','particulier','commercant','entreprise'])
         [1 + floor(random() * 5)::int]
FROM generate_series(1, 3000) AS i;

CREATE TABLE analytics.dim_agent (
  agent_id integer PRIMARY KEY, nom text, ville text, region_agent_id integer, date_activation date,
  statut_agent text);
INSERT INTO analytics.dim_agent VALUES (-1, 'Hors agent', NULL, -1, '2020-01-01', 'ouvert');
INSERT INTO analytics.dim_agent
SELECT i, 'Agent ' || lpad(i::text, 3, '0'),
       (SELECT region FROM analytics.dim_region WHERE region_id = 1 + (i % 14))
         || CASE WHEN i % 3 = 0 THEN ' Centre' ELSE '' END,
       1 + (i % 14), '2023-01-01'::date + (random() * 900)::int,
       CASE WHEN random() < 0.1 THEN 'ferme' ELSE 'ouvert' END
FROM generate_series(1, 120) AS i;

CREATE TABLE analytics.fact_transaction (
  transaction_id bigint PRIMARY KEY, client_id integer, agent_id integer, region_client_id integer,
  region_agent_id integer, date_id integer, txn_ts timestamptz, type text, montant_xof numeric(14,0),
  frais_xof numeric(12,0), statut text);
INSERT INTO analytics.fact_transaction
WITH g AS (
  SELECT i, '2025-04-01'::date + floor(random() * 548)::int AS d,
         (ARRAY['depot','retrait','transfert','paiement'])[1 + floor(random() * 4)::int] AS type,
         1 + floor(random() * 3000)::int AS client_id, 1 + floor(random() * 120)::int AS agent_pick,
         (1000 + random() * 200000)::numeric(14,0) AS montant,
         CASE WHEN random() < 0.06 THEN 'echouee' ELSE 'reussie' END AS statut
  FROM generate_series(1, 40000) AS i)
SELECT g.i, g.client_id,
       CASE WHEN g.type IN ('depot','retrait') THEN g.agent_pick ELSE -1 END,
       c.region_client_id,
       CASE WHEN g.type IN ('depot','retrait') THEN 1 + (g.agent_pick % 14) ELSE -1 END,
       to_char(g.d, 'YYYYMMDD')::int, g.d + time '10:00' + (g.i % 600) * interval '1 minute',
       g.type, g.montant, round(g.montant * 0.01), g.statut
FROM g JOIN analytics.dim_client c ON c.client_id = g.client_id;
ANALYZE;
"""


def load_fixture(owner_dsn: str) -> None:
    """Crée et remplit les 5 tables analytics (rôle dbt_owner attendu)."""
    import psycopg

    with psycopg.connect(owner_dsn, autocommit=True) as conn:
        conn.execute(FIXTURE_SQL)  # type: ignore[arg-type]


def fixture_present(dsn: str) -> bool:
    import psycopg

    with psycopg.connect(dsn) as conn:
        row = conn.execute("SELECT to_regclass('analytics.fact_transaction') IS NOT NULL").fetchone()
        return bool(row and row[0])
