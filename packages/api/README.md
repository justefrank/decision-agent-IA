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
`KEYCLOAK_*`, `LOG_PSEUDONYM_KEY`, `CORS_ORIGINS`, `ENVIRONMENT`…), plus `RIGHTS_TEST_REPORT` (rapport JSON de
`make rights-test`) et `SETTINGS_PROCEDURE_URL`. Paramètres fonctionnels (quota, longueur des questions,
historique) : `semantic/config.yaml`, modifié par PR Git.

Au démarrage, le lifespan lance **un** client MCP (`McpToolClient.start`) et l'`AnthropicClient`. Si l'un des deux
échoue, l'API démarre en mode dégradé : `/api/health` l'indique et les routes de l'agent répondent 503.

## Routes

| Route | Rôles |
|---|---|
| `GET /health` (public), `GET /me` | — / authentifié |
| `POST/GET /conversations`, `GET/DELETE /conversations/{id}` (404 si autrui) | tous |
| `POST /conversations/{id}/messages` : SSE `step`… puis `final` (ou `error`) | tous (SQL retiré pour `decideur`) |
| `GET /dashboard?period=AAAA-MM&region=`, `POST /dashboard/analysis` | tous |
| `POST /feedback` | propriétaire du message |
| `GET /admin/overview`, `/admin/audit/queries[/{trace_id}\|/export.csv]`, `/admin/eval/runs[/{id}]`, `GET/PATCH /admin/feedback`, `/admin/kpis`, `/admin/semantic/{tables\|glossary\|examples}` | analyste, admin |
| `GET /admin/security`, `POST /admin/security/rights-test`, `GET /admin/settings` | admin |

Erreurs : `{"error": {"code", "message", "request_id"}}`, sans détail Postgres ni trace.

## Choix

- **Auth** : RS256 seul (refus de `none`/HS* avant toute recherche de clé), `iss`, `aud`, `exp`, `nbf`, `sub` ;
  JWKS en cache (10 min), rechargé sur `kid` inconnu au plus une fois par 30 s ; rôles lus seulement dans
  `resource_access[KEYCLOAK_CLIENT_ID].roles`. Rôle effectif = le plus élevé (admin > analyste > decideur).
- **Journal** : `app.query_log` reçoit chaque `QueryLogRecord` (`on_log`) avec `user_ref` = HMAC-SHA256(sub) et
  `question_hash` = HMAC-SHA256(question normalisée) avec `LOG_PSEUDONYM_KEY` ; jamais le texte. `app_rw` n'a que
  SELECT/INSERT sur `query_log`, `audit_access_log`, `eval_run`, `eval_result` (droits posés par la migration 0001).
  La purge à 90 jours se fait avec `app_owner` (tâche planifiée), pas par l'API.
- **Quota** : questions du jour comptées dans Postgres (`message` de rôle `user`), plus un compteur en mémoire des
  flux simultanés par utilisateur (un worker uvicorn, décision D3).
- **Déconnexion** : la fermeture du flux annule la tâche de l'agent (qui propage l'annulation au MCP).
- **Analyse du tableau de bord** : réutilisée si période, région, `semantic_version` et `data_hash` (empreinte
  des tuiles courantes) sont identiques, sauf `regenerate=true`.
- **Test de droits** : l'API ne détient pas le DSN `agent_ro` et le contrat MCP ne comporte que trois outils ;
  `POST /admin/security/rights-test` relit donc le rapport JSON écrit par `make rights-test`
  (`{"ok": bool, "checks": [{"name", "ok", "detail"}]}`) et journalise la consultation.
- **Signalements** : états `nouveau`, `traite`, `rejete` ; rejet avec motif obligatoire ; promotion vers le jeu de
  dev seulement (jamais le test), et seulement si l'utilisateur a consenti à joindre sa question.

## Tests

```bash
uv run pytest packages/api -q      # démarre au besoin un Postgres jetable sur le port 55440 (scripts/dev_pg.sh)
```

Les tests JWT utilisent une clé RSA générée et un JWKS simulé (`httpx.MockTransport`) ; les tests de bout en bout
utilisent un vrai Postgres (migration avec `app_owner`, API avec `app_rw`) et un faux `Agent`.
`DECISION_API_TEST_KEEP_PG=1` garde le serveur démarré.
