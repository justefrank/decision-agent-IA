# Revue de code du backend (2026-10-24)

Quatre relectures indépendantes du backend MVP v5, chacune en lecture seule, avec reproduction des constats sur un Postgres local et des données générées. Les correctifs ont ensuite été faits par paquet, chacun avec un test qui échoue avant et passe après.

| Relecture | Périmètre | Bilan |
|---|---|---|
| Sécurité | Garde SQL, MCP, API, Postgres, Caddy, realm Keycloak | Aucun constat critique. Environ 250 payloads et 20 000 mutations aléatoires contre le garde : aucun contournement. Validation JWT sans faille. 1 constat élevé, 4 moyens, 5 faibles |
| Agent et LLM | Boucle Claude, validateur, état, analyse | Requêtes conformes à l'API Claude 2026-10-21 (vérifié contre le SDK `anthropic` 2.3.0). 7 constats majeurs, 8 mineurs |
| Justesse des chiffres | Générateur, dbt, compilateur de métriques, évaluation | 164 cas `query_metric` comparés à un SQL indépendant : 0 écart. 1 constat bloquant (comparateur), 5 majeurs, 8 mineurs |
| API et exploitation | FastAPI, compose, Dockerfile, Makefile, README | Client MCP partagé sûr sous concurrence, SSE et annulation corrects. 1 constat bloquant (authentification locale impossible), 6 majeurs, 10 mineurs |

## Constats principaux et correctifs

| Gravité | Constat | Correctif |
|---|---|---|
| Bloquant | Le comparateur de l'évaluation acceptait une comparaison de périodes inversée (6 questions sur 40 concernées) : score O1 gonflé | Périodes appariées par nom, faits rattachés à leur nature et à leur signe |
| Bloquant | Impossible de s'authentifier en local sans Keycloak, aucun moyen de créer un administrateur | `make init`, `make dev-token`, `make api-dev`, `make create-admin` (vérifié contre Keycloak 26.8.1) |
| Élevé | Masquage des noms d'agents (injection indirecte) contourné par un alias de colonne | Provenance `free_text` calculée par lignage sur l'AST côté MCP |
| Majeur | Quota contournable en supprimant une conversation ; analyse du tableau de bord sans limite | Quota inscrit dans `query_log` sous verrou ; analyse comptée, `regenerate` limité |
| Majeur | `/api/health` répondait « ok » sans clé Claude et après la mort du MCP | Sonde réelle, relance supervisée |
| Majeur | Erreur reçue en cours de flux non relancée ; échéance de 30 s dépassable | Classement par type d'erreur ; `asyncio.timeout` sur l'appel complet |
| Majeur | Total et parts calculés sur un « top N » | Ni total ni parts sur un classement borné |
| Majeur | Repli gabarit reprenant un texte écrit par le modèle | Libellé fixe, caveats de défaut repris, clarification si nécessaire |
| Majeur | Comparaison hors des données ou chevauchante (fausse hausse de 217 %) | Bornes des données dans le MCP, refus ou avertissement de couverture |
| Majeur | Anti-fuite limité aux exemples SQL ; 10 exemples avaient le squelette d'une question du test | Comparaison des arguments `query_metric` ; exemples réécrits ; 0 fuite |
| Moyen | Corps de requête non borné lu avant l'authentification ; console Keycloak publiée | Limite de 64 Kio ; routes `/auth` restreintes |
| Moyen | MFA contournable par la réinitialisation du mot de passe | Flux de réinitialisation avec le même contrôle OTP ; claim `amr` exigé en production |

Les constats mineurs (année ISO, export CSV, pagination, messages en français, OpenAPI, healthchecks, `.dockerignore`, budget de corrections SQL, faux positifs du validateur, coût d'un modèle de repli…) sont corrigés.

## Résultat

- Tests : 632 réussis, 3 ignorés (ils demandent une clé Claude ou un DSN dédié), contre 474 avant la revue.
- `make init` sur une base neuve : 53 tests dbt verts, test de droits conforme, en environ 16 s.
- Agent, vrai sous-processus MCP et données générées : chemin `query_metric`, `run_query` et requête hostile bloquée vérifiés de bout en bout.

## Non vérifié

- Appels réels à Claude (aucune clé dans l'environnement de revue).
- Démarrage complet de la pile `docker compose` (pas de démon Docker) ; Caddy et Keycloak ont été vérifiés séparément, hors conteneurs.
