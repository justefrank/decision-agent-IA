# decision-mcp-server

Serveur MCP stdio (SDK `mcp` 2.x, `MCPServer`) exposant trois outils en lecture seule sur `analytics` :

| Outil | Rôle |
|---|---|
| `query_metric` | KPI certifiés compilés de façon déterministe depuis `semantic/kpis.yaml` (paramètres liés `%(nom)s`), puis repassés par le garde |
| `run_query` | SQL libre : garde → règles sémantiques (`declared_scope`) → `EXPLAIN (FORMAT JSON)` borné (`sql.max_plan_cost`, produit cartésien) → exécution |
| `describe_schema` | Métadonnées normalisées de `semantic/tables.yaml` (+ valeurs distinctes courtes) |

Chaque outil renvoie un `ToolResult` (decision_core) en `structuredContent` et en texte JSON ;
`isError` vaut `not ok`. Argument facultatif `_timeout_s` : `statement_timeout` = min(délai, config).

Lancement : `AGENT_RO_DSN=postgresql://agent_ro:…@hôte:5432/warehouse python -m decision_mcp_server`
(`SEMANTIC_DIR` facultatif). Journaux JSON sur stderr uniquement.

Exécution : pool psycopg (1 à 3 connexions, autocommit), `BEGIN READ ONLY`, `SET LOCAL statement_timeout`,
curseur serveur et lecture de `row_limit + 1` lignes (`truncated`), Decimal → int/float, dates ISO,
erreurs Postgres normalisées (classe SQLSTATE, noms `analytics` conservés, le reste masqué).
Annulation (`notifications/cancelled`) : `pg_cancel_backend` de la requête en cours.

Comparaison : colonne `periode` ∈ {courante, comparaison}. `previous_period` = même durée juste avant,
en mois calendaires si la période couvre des mois entiers (mars → février) ; `previous_year` = un an avant.
Classements : `limit` ≤ 50, tri sur la première métrique, une ligne lue en plus pour signaler les ex æquo.

Tests : `uv run pytest packages/mcp_server -q`. Les tests marqués `db` utilisent le Postgres du port
55420 (`MCP_TEST_PG_PORT`) ; s'il est absent, ils le démarrent avec `scripts/dev_pg.sh` et l'arrêtent
à la fin (`MCP_TEST_PG_KEEP=1` pour le garder). Le jeu de fixture est créé en tant que `dbt_owner`.
