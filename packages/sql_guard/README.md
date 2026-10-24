# decision-sql-guard

Garde SQL du serveur MCP (module `decision_sql_guard`) : bibliothèque pure, sans E/S.

```python
from decision_sql_guard import guard_sql, semantic_warnings

res = guard_sql(sql, semantic, row_limit=1000, declared_scope={"statut": "reussie", "region_kind": "aucune"})
res.ok, res.sql, res.tables, res.error, res.scope, res.warnings
```

- Bornes de longueur (`sql.max_sql_chars`) et de profondeur (`sql.max_ast_depth`) **avant** l'analyse ;
  refus lexical de `E'…'`, `$$…$$`, `U&…`, antislash, multi-instructions, `$1`.
- Une seule instruction `SELECT` (CTE, sous-requêtes, `UNION` admis) ; liste blanche des **types de
  nœuds** sqlglot sur tout l'AST ; fonctions d'une liste fermée (noms normalisés) ; types de `CAST`
  limités ; tables `analytics.{5 tables}` uniquement (les noms non qualifiés sont résolus et
  qualifiés) ; pas de `CROSS JOIN`, `NATURAL JOIN`, jointure sans égalité de colonnes, `WITH RECURSIVE`,
  `INTO`, `FOR UPDATE/SHARE`, `LATERAL`, `TABLESAMPLE`, date système.
- `LIMIT` imposé à `row_limit + 1` (une valeur plus petite est conservée) ; SQL réécrit depuis l'AST
  (dialecte postgres) : seule version exécutée.
- `scope` : période (date_id, txn_ts, dim_date), région jointe, prédicat `statut`, usage de `statut_agent`.
- `semantic_issues` / `semantic_warnings` : règles de cohérence (agrégat sans `statut = 'reussie'`,
  agent actif via `statut_agent`, région incohérente avec `region_kind`, dénominateur du taux d'échec
  filtré) ; les contradictions avec `declared_scope` sont marquées bloquantes.

Tests : `uv run pytest packages/sql_guard -q` (70 payloads nommés refusés, 14 requêtes légitimes).
