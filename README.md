# Agent d'aide à la décision (Wave, données synthétiques)

Agent conversationnel qui répond en français à des questions de pilotage sur des transactions
mobile money (dépôts, retraits, transferts, paiements) au Sénégal. Les chiffres viennent d'un
entrepôt Postgres en étoile, interrogé par Claude via un serveur MCP qui ne détient qu'un rôle en
lecture seule ; chaque nombre cité est tracé jusqu'au résultat d'outil qui le produit.

Documents : [`SRS.md`](SRS.md) (exigences), [`docs/EVALUATION_V5.md`](docs/EVALUATION_V5.md)
(décisions v5, prioritaires en cas de conflit), [`docs/SYSTEM_DESIGN.md`](docs/SYSTEM_DESIGN.md),
[`docs/AGENTIC_DESIGN.md`](docs/AGENTIC_DESIGN.md), revues détaillées dans `docs/reviews/`.

## Arborescence

```
.
├── SRS.md, docs/              exigences, conception, revues, diagrammes
├── semantic/                  source unique : tables, KPI, glossaire, exemples, paramètres (YAML, modifiés par PR)
├── packages/                  espace de travail uv (Python 3.12+)
│   ├── core/                  contrats partagés (decision_core), chargement de la couche sémantique, Settings
│   ├── sql_guard/             garde SQL (AST sqlglot, liste blanche, réécriture)
│   ├── mcp_server/            serveur MCP stdio : query_metric, run_query, describe_schema (rôle agent_ro)
│   ├── agent/                 boucle agentique Claude, formateur, validateur, analyse du tableau de bord
│   ├── api/                   FastAPI (SSE), JWT Keycloak, migrations Alembic du schéma app
│   ├── data_gen/              générateur de données synthétiques → schéma raw
│   └── eval/                  évaluation (pass@1, pass^3, intervalle de Wilson)
├── warehouse/                 projet dbt : raw → analytics (étoile), tests, test de droits agent_ro
├── eval/                      jeux de questions (dev, test figé, sécurité) et rapports
├── infra/
│   ├── compose.yaml           postgres 17, keycloak 26.8.1, api, proxy Caddy, mailpit (dev)
│   ├── Caddyfile              même origine : / SPA, /api → API, /auth → Keycloak, TLS interne
│   ├── api.Dockerfile         image de l'API (uv, multi-étapes, non root)
│   ├── postgres/init/         rôles, bases warehouse et keycloak, schémas raw/analytics/app
│   ├── keycloak/realm/        realm « decision » versionné, sans secret ni utilisateur
│   └── secrets/               secrets Docker (non versionnés, `make secrets`)
├── scripts/dev_pg.sh          Postgres local jetable (sans Docker)
├── frontend/                  ancien squelette Next.js (remplacé par la SPA Vite web/, D1)
└── Makefile                   tâches courantes (`make help`)
```

## Démarrage en développement (sans Docker)

Prérequis : [uv](https://docs.astral.sh/uv/), binaires Postgres 16+ (`/usr/lib/postgresql/*/bin`).

```bash
make sync                          # dépendances Python (uv sync --all-packages)
make db-up PG_PORT=55432           # Postgres local : rôles et schémas de infra/postgres/init
make seed SCALE=0.02 PG_PORT=55432 # données (44 000 transactions) puis dbt build (tests compris)
make rights-test PG_PORT=55432     # droits de agent_ro, avant et après un second dbt run
make migrate                       # tables app (Alembic, rôle app_owner)
cp .env.example .env               # puis renseigner ANTHROPIC_API_KEY
make api                           # http://127.0.0.1:8000/api/health
make test lint                     # tests et ruff
make db-down PG_PORT=55432
```

`SCALE=1.0` (valeur par défaut) produit 50 000 clients, 2 000 agents et 2,2 M de transactions
en ≈ 35 s (génération + COPY ≈ 11 s, dbt build ≈ 20 s). Une même graine donne les mêmes données ;
le `data_hash` imprimé est enregistré dans `raw.raw_meta` et dans les campagnes d'évaluation.

## Déploiement (compose)

```bash
make secrets                       # infra/secrets/*.txt aléatoires ; remplir anthropic_api_key.txt
# compiler la SPA dans web/dist (ou WEB_DIST=…)
make compose-up                    # https://localhost (certificat de l'autorité interne Caddy)
make seed PG_PORT=5432 DBT_PG_PASSWORD="$(cat infra/secrets/dbt_owner_password.txt)"
docker compose -f infra/compose.yaml run --rm migrate
```

- Keycloak tourne en mode production (`start`) derrière le proxy (`/auth`, en-têtes X-Forwarded).
  Le realm importé ne contient ni secret ni utilisateur : créer les comptes dans la console et leur
  attribuer un rôle du client `decision-web` (`decideur`, `analyste`, `admin`). L'OTP est imposé
  aux analystes et administrateurs (enrôlement à la première connexion). Le compte
  `admin-temporaire` du realm master sert seulement à créer un administrateur nominatif.
- `--import-realm` n'écrase jamais un realm existant. Pour réappliquer
  `infra/keycloak/realm/decision-realm.json` : supprimer le realm `decision` dans la console (ou
  le volume `pgdata` en développement), puis redémarrer Keycloak.
- Les mots de passe des rôles Postgres ne sont lus qu'à la création du volume `pgdata`.

## Données

Schéma `analytics` (SRS §7) : `fact_transaction` (une transaction ; `agent_id` −1 = hors agent pour
les transferts et paiements), `dim_client`, `dim_agent`, `dim_region` (14 régions + −1), `dim_date`
(AAAAMMJJ, jours fériés du Sénégal). REFERENCE_DATE = 2026-09-30 tient lieu d'« aujourd'hui ».
