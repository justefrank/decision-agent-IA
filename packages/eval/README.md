# decision-eval

Évaluation de l'agent (SRS v5 §11, revue agentic §1.11 et §3.9). Le module s'appelle `decision_eval`.

## Jeux (`eval/`)

| Fichier | Contenu | Usage |
|---|---|---|
| `test.yaml` | 40 questions écrites à la main (8 KPI, 6 comparaisons, 6 classements, 4 clients/agents, 6 ambiguës ou hors périmètre, 4 suivis, 6 pièges du glossaire) | Chiffre d'acceptation O1 **seul**. Figé par `MANIFEST`. 5 exécutions max par jalon. Échecs analysés par catégorie seulement |
| `dev.yaml` | 40 questions distinctes | Itérations, signalements validés |
| `intent.yaml` | 60 items (30 réponses, 15 clarifications, 15 refus dont 5 injections directes) | Matrice de confusion, faux refus |
| `followup.yaml` | 12 scripts (A : historique écrit ; B : bout en bout ; C : clarification puis réponse) | RF5 + RF14 |
| `security.yaml` | 5 injections indirectes dans `dim_agent.nom` | O3 (les charges SQL directes sont dans `sql_guard`) |

Aucune valeur attendue n'est écrite : `reference_sql` (SQL Postgres sur `analytics.*` uniquement) est exécuté à chaque run avec le rôle `agent_ro`. Dates relatives à `REFERENCE_DATE = 2026-09-30`.

Champs d'un item : `id`, `category`, `trap`, `question` ou `turns`, `expected_kind` (+ `accept_kinds`), `reference_sql`, `expected_period`, `expected_scope` (`region_kind`, `filters` par dimension de `query_metric`), `ordered`, `order_by`, `tie_tolerant`, `prefix_ok`, `expected_empty`, `column_groups`, `must_cite`, `tolerate_hors_agent_zero`, `notes`.

## Correcteur (`compare.py`)

Une réponse est juste si **exécution, chiffres cités, période et périmètre** sont justes :

- **Exécution** : `AssistantMessage.table` comparée en multi-ensemble de tuples. Les colonnes de référence sont projetées sur les colonnes obtenues par type et par valeurs, et les colonnes en trop sont tolérées. `column_groups` signifie « au moins une de ces colonnes » (ex. `agent_id` ou `nom`). Les entiers sont comparés exactement, les autres nombres à 1e-4 près en relatif (avec l'équivalence ratio ↔ %). L'ordre n'est exigé que si `ordered`, et les ex æquo sur `order_by` sont acceptés dans tout ordre. `tie_tolerant` : à la frontière d'un top-k, seule la valeur de classement compte. `prefix_ok` accepte des lignes après les k premières. Le format long `periode` ∈ {courante, comparaison} est pivoté.
- **Chiffres cités** : on lit le registre `AssistantMessage.facts`, en ne gardant que les faits portant `rendered` s'il y en a. Chaque fait numérique doit valoir une cellule de référence ou un dérivé (écart, variation, part, total). Si la référence a une seule ligne, toutes ses valeurs doivent être citées (sauf `must_cite`). Résultat vide : aucun chiffre non nul.
- **Période** : `resolved_state.period` (ou `AssistantMessage.period`), comparée après bornage à la fenêtre des données (2025-04-01 → 2026-09-30).
- **Périmètre** : `resolved_state.region_kind` et `resolved_state.scope`. Formes acceptées pour `scope.value` : `{"region_kind", "filters": [{"dimension", "values", "op"?}]}`, `{dim: [valeurs]}`, une liste de filtres, ou une chaîne (« national »). Les filtres `op: not_in` sont ignorés.
- **Intention** : `kind` ∈ {`expected_kind`} ∪ `accept_kinds`.

Limite connue : la projection se fait par valeurs, pas par noms. Une inversion « courante / comparaison » n'est donc pas vue par l'exécution.

## Statistiques (`stats.py`)

- **pass^3** (référence) avec intervalle de Wilson sur n questions.
- pass@1 moyen avec bootstrap groupé par question.
- Cohérence 3/3 · 2/3 · 1/3 · 0/3.
- McNemar exact apparié pour les ablations, présenté comme descriptif sous n ≈ 70.
- Comptes bruts par catégorie, sans conclusion sous 8 questions.
- Phrase honnête quand la cible n'est pas démontrée.

## Commandes

```bash
export AGENT_RO_DSN=postgresql://agent_ro:…@localhost:5432/warehouse   # références
python -m decision_eval run --split dev --passes 3 --ablation none --max-concurrency 4
python -m decision_eval run --split test --milestone P1 --write-db-env   # EVAL_DB_DSN = app_rw
python -m decision_eval run --split dev --ablation c --baseline eval/reports/<base>.json
EVAL_SETUP_DSN=postgresql://dbt_owner:…@localhost:55450/warehouse python -m decision_eval run --split security
python -m decision_eval antileak          # exemples ↔ test, dev ↔ test, MANIFEST
python -m decision_eval manifest --verify # ou --freeze [--force] pour une nouvelle version justifiée
python -m decision_eval refs --split test # exécute toutes les références
EVAL_BENCH_TOKEN=… python -m decision_eval bench --base-url https://localhost --questions-from dev
```

Rapports : `eval/reports/<run>_<split>_<ablation>.{json,md}`. Compteur du test : `app.eval_run` (via `--write-db`) et `eval/reports/runs.json`, avec 5 exécutions par jalon et par bras d'ablation.

## Contrat attendu de l'agent

- `decision_agent.Agent(llm, tools, semantic, settings[, ablation=…])` et `await agent.answer(question, history=…, state=…, role="analyste", trace_id=…, on_event=…, on_log=…)`.
- Ablation : l'option `ablation=` est passée au constructeur s'il l'accepte. Sinon, la variable `DECISION_ABLATION` est posée. L'ablation (b) retire en plus les exemples de la couche sémantique.
- Le coût, les jetons, le modèle servi et la version du prompt sont lus dans les `QueryLogRecord` reçus par `on_log` (`tool="llm"`).
- `decision_eval.fakes.OracleAgent` sert de faux agent pour les tests.

## Tests

```bash
uv run pytest packages/eval -q                     # sans base
scripts/dev_pg.sh start 55450
TEST_PG_DSN=postgresql://postgres@localhost:55450/warehouse uv run pytest packages/eval -q   # + tests db
```

Les tests `db` chargent la fixture `decision_eval.fixture`, un petit jeu analytics conforme à `semantic/tables.yaml` qui ne remplace pas `data_gen`. Ils exécutent toutes les références avec `agent_ro` et vérifient qu'un agent oracle obtient 100 %. Ils couvrent aussi l'injection et sa restauration, ainsi que l'écriture de `eval_run` et `eval_result`.
