# decision-api

API FastAPI minimale du MVP v5 (module `decision_api`) : JWT Keycloak, conversations avec réponses en flux SSE,
tableau de bord et analyse, signalements, back-office en lecture. Préfixe `/api`.

## Lancer

```bash
uv sync --all-packages
# Migrations du schéma app avec le rôle propriétaire (app_owner) :
cd packages/api && OWNER_DATABASE_URL=postgresql://app_owner:...@hote:5432/warehouse uv run alembic upgrade head
# API avec le rôle app_rw (le DSN agent_ro n'est transmis qu'au sous-processus MCP) :
APP_DATABASE_URL=postgresql://app_rw:...@hote:5432/warehouse AGENT_RO_DSN=... ANTHROPIC_API_KEY=... \
KEYCLOAK_ISSUER=https://hote/auth/realms/decision uv run uvicorn decision_api.main:app
```

Variables : celles de `decision_core.settings` (`APP_DATABASE_URL`, `OWNER_DATABASE_URL`, `AGENT_RO_DSN`,
`KEYCLOAK_*`, `LOG_PSEUDONYM_KEY`, `CORS_ORIGINS`, `ENVIRONMENT`…), plus (`decision_api.config.ApiSettings`) :
`RIGHTS_TEST_REPORT` (rapport JSON de `make rights-test`, défaut `var/reports/rights-test.json`),
`SETTINGS_PROCEDURE_URL`, `REQUIRE_MFA_CLAIM` / `MFA_MIN_ACR`, `AGENT_RO_PASSWORD_FILE` + `PG_HOST` / `PG_PORT` /
`PG_DATABASE` (compose : DSN agent_ro construit depuis le secret), `MCP_PROBE_TIMEOUT_S`, `MCP_PROBE_INTERVAL_S`,
`MCP_MAX_RESTARTS`, `MCP_BACKOFF_INITIAL_S` / `_MAX_S`, `DASHBOARD_CACHE_TTL_S` (300),
`ANALYSIS_REGENERATE_MIN_INTERVAL_S` (60), `MAX_BODY_BYTES` (65 536). Paramètres fonctionnels (quota, longueur
des questions, historique) : `semantic/config.yaml`, modifié par PR Git.

Au démarrage, le lifespan lance **un** client MCP supervisé (`McpSupervisor` autour de `McpToolClient.start`) et
l'`AnthropicClient` (seulement si `ANTHROPIC_API_KEY` est renseignée). Le superviseur sonde le sous-processus
(`list_tools`, délai court) toutes les 15 s, à chaque `/api/health` (résultat gardé 5 s) et après une erreur
d'outil `internal` ; il le relance s'il meurt (backoff exponentiel 1 → 30 s, 5 relances consécutives au plus,
puis `down`). Sans MCP ou sans clé, l'API reste en mode dégradé : les routes de l'agent répondent 503.
En production, le démarrage est refusé si `LOG_PSEUDONYM_KEY` vaut la valeur par défaut (ou fait moins de
16 caractères) ; Swagger (`/api/docs`) n'est servi qu'hors production. `AGENT_RO_DSN` est retiré de
`os.environ` une fois les réglages lus (il ne reste que dans `settings`, transmis au seul sous-processus MCP).

## Routes

| Route | Rôles |
|---|---|
| `GET /health` (public : `status` ok \| degraded \| down, `db`, `mcp`, `agent`), `GET /me` | — / authentifié |
| `POST/GET /conversations`, `GET/DELETE /conversations/{id}` (404 si autrui) | tous |
| `POST /conversations/{id}/messages` : SSE `step`… puis `final` (ou `error`) | tous (SQL retiré pour `decideur`) |
| `GET /dashboard?period=AAAA-MM&region=`, `POST /dashboard/analysis` | tous (`regenerate=true` : analyste, admin) |
| `POST /feedback` | propriétaire du message |
| `GET /admin/overview`, `/admin/audit/queries[/{trace_id}\|/export.csv]`, `/admin/eval/runs[/{id}]`, `GET/PATCH /admin/feedback`, `/admin/kpis`, `/admin/semantic/{tables\|glossary\|examples}` | analyste, admin |
| `GET /admin/security`, `POST /admin/security/rights-test`, `GET /admin/settings` | admin |

Erreurs : `{"error": {"code", "message", "request_id"}}`, sans détail Postgres ni trace, messages en français
(404 et 405 compris). Corps de requête `/api/*` limité à 64 Kio par un middleware ASGI (`Content-Length` vérifié
sans rien lire, sinon lecture bornée) : 413 `payload_too_large` avant toute lecture complète et avant
l'authentification (Caddy applique aussi `request_body max_size 64KB`). OpenAPI déclare le schéma `bearerAuth`.

## Choix

- **Auth** : RS256 seul (refus de `none`/HS* avant toute recherche de clé), `iss`, `aud`, `exp`, `nbf`, `sub` ;
  JWKS en cache (10 min), rechargé (expiration ou `kid` inconnu) au plus une fois par 30 s, y compris après un
  échec : les clés connues restent alors servies ; rôles lus seulement dans
  `resource_access[KEYCLOAK_CLIENT_ID].roles`. Rôle effectif = le plus élevé (admin > analyste > decideur).
- **MFA** : si `REQUIRE_MFA_CLAIM` (défaut : vrai en production, faux sinon), un jeton portant `analyste` ou
  `admin` doit prouver l'OTP (`amr` contient `otp`, posé par le mapper AMR du realm, ou `acr` numérique
  ≥ `MFA_MIN_ACR`, 2) ; sinon 403 `mfa_required`. Les jetons de `dev-token` portent `amr: ["pwd", "otp"]`.
- **Journal** : `app.query_log` reçoit chaque `QueryLogRecord` (`on_log`) avec `user_ref` = HMAC-SHA256(sub) et
  `question_hash` = HMAC-SHA256(question normalisée) avec `LOG_PSEUDONYM_KEY` ; jamais le texte. `app_rw` n'a que
  SELECT/INSERT sur `query_log`, `audit_access_log`, `eval_run`, `eval_result` (droits posés par la migration 0001).
  La purge à 90 jours se fait avec `app_owner` : `make purge-logs` (`python -m decision_api.cli purge-logs`),
  à planifier ; `app_rw` n'a pas DELETE.
- **Quota** : chaque question acceptée et chaque analyse générée inscrivent une ligne `step = 0` dans
  `query_log` (`tool` = `question` | `analysis`, `user_ref`, même `trace_id` que la réponse) ; le quota du jour
  compte ces lignes. Le journal étant en ajout seul, supprimer une conversation ne rend pas de quota. Comptage et
  inscription se font sous `pg_advisory_xact_lock` par utilisateur (pas de course entre requêtes simultanées).
  Le créneau de flux (compteur mémoire des flux simultanés par utilisateur, un worker uvicorn, D3) est acquis
  AVANT le quota : un refus 429 n'enregistre jamais de message `user` sans réponse.
- **Déconnexion** : la fermeture du flux annule la tâche de l'agent (qui propage l'annulation au MCP).
- **Tableau de bord** : tuiles en cache mémoire (clé période, région, `semantic_version` ; 5 min ; calculs
  partiels exclus) — agrégats déterministes, pas des réponses de l'agent.
- **Analyse du tableau de bord** : réutilisée si période, région, `semantic_version` et `data_hash` (empreinte
  des tuiles) sont identiques. Une génération est imputée au quota et occupe un créneau de flux. Elle se fait sous
  `pg_advisory_xact_lock` par (période, région, version, `data_hash`) : des demandes simultanées ne produisent
  qu'une analyse. `regenerate=true` est réservé à l'analyste et à l'admin et sans effet (analyse existante
  renvoyée) moins de 60 s après la précédente génération pour la même clé.
- **Test de droits** : l'API ne transmet le DSN `agent_ro` qu'au sous-processus MCP, dont le contrat ne comporte
  que trois outils ; `POST /admin/security/rights-test` relit donc le rapport JSON écrit par `make rights-test`
  (`{"ok": bool, "checks": [{"name", "ok", "detail"}]}`) et journalise la consultation.
- **Audit** : pagination triée par (`ts`, `trace_id`) décroissants (départage stable) ; l'export CSV neutralise
  les formules (`=`, `+`, `-`, `@`, `|` en tête après espaces, ou tabulation / CR / LF initiaux).
- **Signalements** : états `nouveau`, `traite`, `rejete` ; rejet avec motif obligatoire ; promotion vers le jeu de
  dev seulement (jamais le test), et seulement si l'utilisateur a consenti à joindre sa question.

## Tests

```bash
uv run pytest packages/api -q      # démarre au besoin un Postgres jetable sur le port 55440 (scripts/dev_pg.sh)
```

Les tests JWT utilisent une clé RSA générée et un JWKS simulé (`httpx.MockTransport`) ; les tests de bout en bout
utilisent un vrai Postgres (migration avec `app_owner`, API avec `app_rw`) et un faux `Agent`. `test_hardening.py`
(supervision MCP, limite de corps, MFA, JWKS, CSV…) et `test_infra.py` (compose, realm, Caddyfile, `.env.example`)
n'ont pas besoin de Postgres.
`DECISION_API_TEST_KEEP_PG=1` garde le serveur démarré.
