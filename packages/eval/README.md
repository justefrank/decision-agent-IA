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

- **Exécution** : `AssistantMessage.table` comparée en multi-ensemble de tuples. Les colonnes de référence sont projetées sur les colonnes obtenues par type et par valeurs, et les colonnes en trop sont tolérées. `column_groups` signifie « au moins une de ces colonnes » (ex. `agent_id` ou `nom`). Les entiers sont comparés exactement, les autres nombres à 1e-4 près en relatif (avec l'équivalence ratio ↔ %). L'ordre n'est exigé que si `ordered`, et les ex æquo sur `order_by` sont acceptés dans tout ordre. `prefix_ok` accepte des lignes après les k premières.
  - **Comparaisons de périodes** : le format long `periode` ∈ {courante, comparaison} est pivoté, puis les colonnes de période sont projetées **par la valeur de `periode`** : la colonne courante de la référence ne peut aller que sur la mesure de la période courante, la colonne de comparaison que sur `<mesure>__comparaison` de la même mesure (raison `periodes_inversees`). Le couple (courante, comparaison) de la référence est dérivé du `reference_sql` : pour une même métrique, des agrégats `FILTER` sur des périodes différentes, le premier du `SELECT` étant la période courante (convention des jeux) ; à défaut, colonnes nommées `courante` / `precedente`. Limite : un tableau large renvoyé par `run_query` (deux colonnes nommées librement) reste projeté par valeurs ; le signe des dérivés cités reste vérifié.
  - **`tie_tolerant`** : à la frontière d'un top-k, l'identité peut différer, mais chaque ligne de la frontière doit appartenir à l'ensemble des ex æquo **calculé en base** (le runner relance la référence sans `LIMIT` et garde les lignes de même clé que la dernière : `ResultSet.boundary`). Des lignes en trop sont acceptées si ce sont d'autres ex æquo distincts (T20). Sans cet ensemble (tests unitaires), les lignes en trop sont refusées et une frontière sans cœur (top-1, T37) exige l'identité de la référence.
- **Chiffres cités** : on lit le registre `AssistantMessage.facts`, en ne gardant que les faits portant `rendered` s'il y en a. Chaque fait est rattaché à sa nature (contrat de `decision_agent.facts`) : `f…` = cellule, `Total de …` (somme d'une colonne) ou `Nombre de lignes` ; `d…` = dérivé déclaré `Écart`, `Variation`, `Écart en points` ou `Part de`. Une cellule doit valoir une cellule **mesure** de la référence (les identifiants `…_id` exclus), dans la ligne nommée par le libellé du fait quand il en nomme une (« Agents actifs — Dakar — août 2026 »). Un écart ou une variation doit valoir le dérivé **orienté** courante − comparaison (signe compris) d'un couple de périodes ; une part, la part de la ligne nommée. Aucune autre différence de cellules n'est admise (T36). Si la référence a une seule ligne, toutes ses mesures doivent être citées (sauf `must_cite`). Résultat vide : aucun chiffre non nul.
- **Période** : `resolved_state.period` (ou `AssistantMessage.period`), comparée après bornage à la fenêtre des données (2025-04-01 → 2026-09-30).
- **Périmètre** : `resolved_state.region_kind` et `resolved_state.scope`. Formes acceptées pour `scope.value` : `{"region_kind", "filters": [{"dimension", "values", "op"?}]}`, `{dim: [valeurs]}`, une liste de filtres, ou une chaîne (« national »). Les filtres `op: not_in` sont ignorés.
- **Résultat vide attendu** (`expected_empty`, T38) : une réponse sans tableau (ou à tableau vide) qui signale le vide (caveat `resultat_vide`, ou texte « aucun… », « n'ont pas de point de service »…) n'a pas à porter de période ni de périmètre résolus ; s'ils sont présents, ils sont vérifiés.
- **Intention** : `kind` ∈ {`expected_kind`} ∪ `accept_kinds`.


## Anti-fuite (`antileak.py`)

- SQL normalisé et squelette SQL (littéraux → `?`) des exemples `run_query` ↔ `reference_sql` du test ;
- **appels `query_metric` des exemples** : `arguments` ramenés à un squelette (métriques triées, dimensions de découpage, comparaison, grain, dimensions filtrées **sans valeurs**, classement oui/non) et comparés au squelette de chaque question du test, dérivé de son `reference_sql` (+ dimensions de `expected_scope.filters`) ; un SQL non exprimable par `query_metric` (`a.ville`, `d.jour_ferie`, sous-requête, table autre que `fact_transaction`) n'a pas de squelette ;
- exemples terminaux (`refuse`, `ask_clarification`) : fuite si même intention (catégorie ou champ manquant, dérivé du `trap` du test) **et** même sujet (concepts du glossaire en commun, Jaccard ≥ 0,5) ;
- questions identiques (texte normalisé), recouvrement dev ↔ test, hash du `MANIFEST`.

## Statistiques (`stats.py`)

- **pass^3** (référence) avec intervalle de Wilson sur n questions. `pass_hat_k` et `consistency` exigent exactement `passes` résultats par question (`ValueError` sinon).
- pass@1 moyen avec bootstrap groupé par question.
- Cohérence 3/3 · 2/3 · 1/3 · 0/3.
- McNemar exact apparié pour les ablations, présenté comme descriptif sous n ≈ 70.
- Comptes bruts par catégorie, sans conclusion sous 8 questions.
- Phrase honnête quand la cible n'est pas démontrée.

## Échelle des données d'évaluation

Le split **test** se joue sur les données générées à l'échelle **`SCALE=1.0`** (`make seed SCALE=1.0`, graine par défaut). À petite échelle, certaines références deviennent dégénérées (T22, T24 : 0 point de service fermé à `SCALE=0.05`) et le score ne mesure plus rien. Le runner :

- lit l'échelle, la graine et le hash du générateur dans `raw.raw_meta` (`agent_ro` n'y a pas accès : `EVAL_META_DSN`, ou à défaut `EVAL_SETUP_DSN`, rôle lecteur du schéma `raw`) et les trace (`data_scale`, `data_seed`, `data_generator_hash`, `data_meta_source`) à côté du `data_hash` ;
- liste les **références dégénérées** (référence attendue non vide qui renvoie 0 ligne ou uniquement des zéros) dans le rapport ;
- **refuse le split test**, avant de consommer une exécution du quota, si l'échelle lue est < 1.0 ou s'il existe une référence dégénérée, sauf `--allow-small-scale` (exécution alors marquée `small_scale_override`).

## Commandes

```bash
export AGENT_RO_DSN=postgresql://agent_ro:…@localhost:5432/warehouse   # références
python -m decision_eval run --split dev --passes 3 --ablation none --max-concurrency 4
EVAL_META_DSN=postgresql://dbt_owner:…@localhost:5432/warehouse \
  python -m decision_eval run --split test --milestone P1 --write-db-env   # EVAL_DB_DSN = app_rw, SCALE=1.0
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
