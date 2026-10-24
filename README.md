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
│   ├── Caddyfile              même origine : / SPA (ou page d'attente), /api → API, /auth/realms/decision → Keycloak
│   ├── api.Dockerfile         image de l'API (uv, multi-étapes, non root)
│   ├── postgres/init/         rôles, bases warehouse et keycloak, schémas raw/analytics/app
│   ├── keycloak/realm/        realm « decision » versionné, sans secret ni utilisateur
│   └── secrets/               secrets Docker (non versionnés, `make secrets`)
├── scripts/dev_pg.sh          Postgres local jetable (sans Docker)
├── web/                       SPA Vite + React + TypeScript (conversation, indicateurs, back-office en lecture)
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
cp .env.example .env               # facultatif ; ANTHROPIC_API_KEY à exporter ou décommenter
make api                           # http://127.0.0.1:8000/api/health
make test lint                     # tests et ruff
make db-down PG_PORT=55432
```

Raccourci : `make init` (Postgres, données factices, dbt, droits, migrations) puis `make api-dev` et
`make dev-token ROLE=admin`. `.env.example` ne contient que des composants commentés (hôte, port,
mots de passe de développement) : les DSN sont calculés par le Makefile, donc `make init PG_PORT=55410`
ou `make seed PG_PORT=55410` s'appliquent partout, même avec un `.env` copié de l'exemple.

### Administrateur et utilisateurs

| Contexte | Commande | Effet |
|---|---|---|
| Local, sans Keycloak | `make dev-token ROLE=admin` (ou `analyste`, `decideur`) | Jeton JWT signé par une clé locale (`var/dev-auth/`), accepté par `make api-dev` ; refusé en production |
| Avec Keycloak | `make create-admin EMAIL=prenom.nom@exemple.sn` | Crée l'administrateur dans le realm `decision` : mot de passe temporaire affiché une fois, changement et enrôlement OTP à la première connexion ; relançable sans doublon |
| Avec Keycloak | `make create-user EMAIL=... ROLE=decideur` | Idem pour un décideur ou un analyste |

`create-admin` lit `KEYCLOAK_URL` (URL interne, ex. `http://localhost:8081`) et les identifiants
d'administration `KEYCLOAK_ADMIN_USER` / `KEYCLOAK_ADMIN_PASSWORD` (ou un compte de service
`KEYCLOAK_ADMIN_CLIENT_ID` / `KEYCLOAK_ADMIN_CLIENT_SECRET`). La console Keycloak n'est pas publiée
par le proxy : passer par le tunnel décrit plus bas.

### Tester l'agent avec Claude

```bash
export ANTHROPIC_API_KEY=...                                  # jamais dans un fichier versionné
uv run python -m decision_eval run --split dev --passes 1     # essai rapide sur le jeu de dev
make seed SCALE=1.0 && make eval                              # jeu de test : échelle 1.0 exigée
```

`SCALE=1.0` (valeur par défaut) produit 50 000 clients, 2 000 agents et 2,2 M de transactions
en ≈ 35 s (génération + COPY ≈ 11 s, dbt build ≈ 20 s). Une même graine donne les mêmes données ;
le `data_hash` imprimé est enregistré dans `raw.raw_meta` et dans les campagnes d'évaluation.

## Interface web (`web/`)

SPA Vite + React 19 + TypeScript, servie en production par Caddy (même origine que l'API et Keycloak).
Elle ne garde que le logo et les jetons de design de la maquette ; la présentation est celle d'un
relevé : chaque réponse est un reçu avec son chiffre clé et sa chaîne de preuve (table, filtre, période).

| Mode | Commandes | Connexion |
|---|---|---|
| Développement local | `make init`, `make api-dev`, puis dans un second terminal `make web-dev` → http://localhost:5173 | Trois boutons (décideur, analyste, administrateur) : jetons signés localement par la CLI de l'API, sans Keycloak |
| Développement en conteneurs | `make dev-up`, puis `make web-dev-dc` → http://localhost:5173 | Idem, jetons signés dans le conteneur outils |
| Pile complète (Keycloak) | `make dc-web-build` (ou `make web-build` avec Node 22), puis `make up` → https://localhost | Keycloak : Authorization Code + PKCE, jeton en mémoire, renouvellement silencieux, OTP pour analyste et admin |

Avant un commit : `make web-check` (types, lint, tests). Les types de l'API sont générés depuis son
OpenAPI et les contrats Python : `cd web && npm run api-types`. Les polices sont installées en local
(CSP stricte, aucun appel à un CDN).

## Démarrage en conteneurs (Docker sur votre machine)

Mêmes commandes que le mode local, préfixées `dc-` : elles s'exécutent dans le conteneur « outils »
(`infra/tools.Dockerfile` : Python, uv, dbt, make, psql), sur le réseau Docker, avec les mots de passe
des secrets. Le dépôt est monté dans ce conteneur : vos modifications de code sont prises en compte
sans reconstruire. Seul Docker (avec Compose v2) est nécessaire sur la machine.

```bash
make dc-init                         # secrets + pile + données factices (0,05) + test de droits
make dc-admin EMAIL=prenom.nom@exemple.sn   # administrateur Keycloak (mot de passe temporaire affiché)
make ps                              # état des services ; make logs S=api pour les journaux
```

| Besoin | Commande |
|---|---|
| Lancer / arrêter la pile | `make up` / `make down` (les données restent dans le volume `pgdata`) |
| API de développement sans interface | `make dev-up` puis `make dc-token ROLE=admin` : API sur `http://127.0.0.1:8000/api/docs`, jetons locaux acceptés, MFA non exigée |
| Données à l'échelle de l'évaluation | `make dc-seed SCALE=1.0` |
| Évaluer avec Claude | clé dans `infra/secrets/anthropic_api_key.txt`, `make restart S=api` (l'API lit ses secrets au démarrage), puis `make dc-eval SPLIT=dev PASSES=1` ; jeu de test : `make dc-eval` (échelle 1.0 exigée) |
| Utilisateur Keycloak | `make dc-user EMAIL=... ROLE=decideur` |
| Shell outils | `make dc-shell` (make, uv, dbt, psql déjà configurés) |
| Repartir de zéro | `make dc-reset` (**supprime les volumes**, donc toutes les données) |
| Après un changement de dépendances (`uv.lock`) | `make dc-build` |

- **Secrets** : `make secrets` (appelé par `make up`) crée `infra/secrets/*.txt`. Le dossier est en
  700 ; les fichiers sont en 644, car Compose (hors Swarm) les monte tels quels et Postgres, Keycloak
  et l'API les lisent sous des UID différents du vôtre.
- **Production locale** (`make up`) : l'API exige des jetons Keycloak avec OTP ; la SPA n'existant pas
  encore, utilisez `make dev-up` pour appeler l'API directement.
- **Fichiers créés par les outils** (`var/`, `warehouse/target/`) : ils appartiennent à votre
  utilisateur (le conteneur outils tourne avec votre UID).

- **Migrations** : le service `migrate` (Alembic, rôle `app_owner`) s'exécute à chaque démarrage ;
  l'API attend sa fin (`service_completed_successfully`).
- **Interface** : Caddy sert `web/dist` (`WEB_DIST`). Tant qu'il ne contient pas d'`index.html`
  (interface non construite : `make dc-web-build`), il sert une page d'attente statique
  (`infra/web-fallback/`, statut 503) ; l'API et Keycloak restent servis.
- **Proxy** : `/api/*` (corps limité à 64 Kio, sans compression pour ne pas tamponner le flux SSE) ;
  de Keycloak, seuls `/auth/realms/decision/*`, `/auth/resources/*` et `/auth/js/*` sont publiés.
  `/auth/admin*`, `/auth/realms/master*` et le reste de `/auth` répondent 404.
- **Administration Keycloak par tunnel** : la console n'est joignable que sur la boucle locale de
  l'hôte (`127.0.0.1:${KC_ADMIN_PORT:-8081}`, `KC_HOSTNAME_ADMIN`) :
  `ssh -L 8081:127.0.0.1:8081 hote` puis `http://localhost:8081/auth/admin/` depuis le poste.
  `make create-user` passe par la même adresse (`KEYCLOAK_URL=http://localhost:8081/auth`).
- **Keycloak** tourne en mode production (`start`) derrière le proxy (`/auth`, en-têtes X-Forwarded).
  Le realm importé ne contient ni secret ni utilisateur ; ses URL (`redirectUris`, `webOrigins`,
  déconnexion) sont dérivées de `PUBLIC_HOST` (substitution `${PUBLIC_HOST}` à l'import). Créer les
  comptes (`make create-user EMAIL=… ROLE=…`) avec un rôle du client `decision-web` (`decideur`,
  `analyste`, `admin`). L'OTP est imposé aux analystes et administrateurs (rôle composite
  `mfa-requise`), à la connexion **et** après « mot de passe oublié » (flux `decision-reset-credentials` :
  enrôlement forcé si l'OTP manque, jamais de session sans OTP). Le compte `admin-temporaire` du realm
  master sert seulement à créer un administrateur nominatif.
- **Preuve d'OTP côté API** : le mapper AMR du realm ajoute `amr` au jeton (`["pwd"]`, ou
  `["pwd","otp"]` après saisie d'un code). En production (`REQUIRE_MFA_CLAIM`, vrai par défaut hors
  dev), l'API refuse (403 `mfa_required`) un jeton analyste/admin sans `otp` dans `amr` (ou `acr`
  ≥ `MFA_MIN_ACR`). La session ouverte juste après l'**enrôlement** ne porte que `pwd` : l'interface
  doit alors relancer la connexion avec `prompt=login` (saisie du code).
- **Santé** : `GET /api/health` sonde réellement la base, le sous-processus MCP (`list_tools`, 2 s)
  et la configuration de l'agent (clé API) ; `status` vaut `ok`, `degraded` (MCP ou agent
  indisponible) ou `down` (base injoignable, HTTP 503). Le MCP est relancé automatiquement (backoff
  exponentiel, 5 relances consécutives au plus). Le healthcheck compose de l'API exige `status=ok`.
  Celui de Keycloak lit le code HTTP de `/auth/health/ready` sur le port de gestion 9000 :
  `KC_HTTP_MANAGEMENT_RELATIVE_PATH=/auth` est fixé explicitement (sans lui, le chemin hérite de
  `KC_HTTP_RELATIVE_PATH`) ; la sous-chaîne `"UP"` ne suffit pas (présente dans la réponse 503 de
  l'amorçage). Postgres : `pg_isready -h 127.0.0.1` (sain seulement après les scripts d'init).
- **Rétention** : `make purge-logs` (rôle `app_owner`, seul à avoir DELETE sur `app.query_log`)
  supprime les lignes de plus de 90 jours ; à planifier, par exemple chaque nuit :
  `15 3 * * * cd /srv/decision && make purge-logs OWNER_DATABASE_URL=postgresql://app_owner:…@127.0.0.1:5432/warehouse`.
- **Variables compose** : `PUBLIC_HOST`, `PG_PUBLISH_PORT` (Postgres publié sur 127.0.0.1, distinct
  de `PG_PORT` du Makefile), `KC_ADMIN_PORT`, `API_ENVIRONMENT` (défaut `production` : Swagger
  désactivé, démarrage refusé si `LOG_PSEUDONYM_KEY` vaut la valeur par défaut), `WEB_DIST`.
  Le DSN `agent_ro` n'est jamais exporté dans l'environnement de l'API : elle le construit depuis
  le secret (`AGENT_RO_PASSWORD_FILE`) et ne le transmet qu'au sous-processus MCP.
- `--import-realm` n'écrase jamais un realm existant. Pour réappliquer
  `infra/keycloak/realm/decision-realm.json` : supprimer le realm `decision` dans la console (ou
  le volume `pgdata` en développement), puis redémarrer Keycloak.
- Les mots de passe des rôles Postgres ne sont lus qu'à la création du volume `pgdata`.

Vérifié hors Docker : Caddyfile (Caddy 2.10.2 local : routes, 404, 413, page d'attente, SSE non
compressé) ; realm (Keycloak 26.8.1 local : import, substitution de `PUBLIC_HOST`, `amr`, flux de
réinitialisation, healthcheck `/auth/health/ready` sur 9000). Non vérifié sans démon Docker :
démarrage complet de la pile compose, console d'administration par tunnel (`KC_HOSTNAME_ADMIN`).

## Données

Schéma `analytics` (SRS §7) : `fact_transaction` (une transaction ; `agent_id` −1 = hors agent pour
les transferts et paiements), `dim_client`, `dim_agent`, `dim_region` (14 régions + −1), `dim_date`
(AAAAMMJJ, jours fériés du Sénégal). REFERENCE_DATE = 2026-09-30 tient lieu d'« aujourd'hui ».
