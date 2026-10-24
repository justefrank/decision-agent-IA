# warehouse (dbt)

Projet dbt (dbt-core 1.11 + dbt-postgres 1.11, isolé de l'espace de travail uv et lancé par
`uvx`, versions dans `requirements.txt`) : `raw` → `analytics.{fact_transaction, dim_client,
dim_agent, dim_region, dim_date}` selon SRS §7 et `semantic/tables.yaml`.

```bash
make seed SCALE=0.02 PG_PORT=55432   # générateur + dbt build
make dbt-build                         # dbt build seul
make rights-test                       # droits de agent_ro avant/après un second dbt run
```

- Profil `profiles.yml` : variables `DBT_PG_HOST/PORT/USER/PASSWORD/DBNAME`, rôle `dbt_owner`.
- Contrats dbt appliqués : types exacts (`montant_xof numeric(14,0)`, `date_id` int AAAAMMJJ…),
  NOT NULL, CHECK (montant > 0, frais bornés, type ↔ agent -1), clés primaires.
- Lignes -1 : `dim_region` « Non applicable », `dim_agent` « Hors agent » (ville, date d'activation
  et statut NULL : jamais compté parmi les agents ouverts/fermés).
- Index en post-hook (`date_id`, `client_id`, `agent_id`, partiel `WHERE statut = 'reussie'`),
  `ANALYZE` en on-run-end, `GRANT SELECT` à `agent_ro_base` (en plus des droits par défaut).
- Tests : unique/not_null, relationships (y compris -1), accepted_values, tests singuliers dans
  `tests/` (frais, type ↔ agent, inscription ≤ première transaction, date_id ↔ txn_ts,
  réconciliation raw ↔ fact, max(date) ≤ `reference_date`, référentiel des régions, profil en
  avertissement) et **tests unitaires des 6 KPI** (`models/qa/kpi_reference.yml`). La vue
  `raw.kpi_reference` reprend mot pour mot les fragments de `semantic/kpis.yaml` (vérifié par
  `packages/data_gen/tests/test_kpi_sync.py`).
- `scripts/check_agent_ro_rights.py` : test de droits de `agent_ro` (rapport JSON lu par le
  back-office).
