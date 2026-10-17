# Fonctionnalités et ressources

Cadrage opérationnel : chaque fonctionnalité, sa priorité, sa phase, son composant et la ressource adéquate (agent spécialisé, skill, bibliothèque). Complète [SRS.md](../SRS.md) §4 et §12.

Légende des priorités : M = Must, S = Should, C = Could. Agents au format `agent` ; skills au format `/skill`.

## 1. Fonctionnalités utilisateur

| Réf. | Fonctionnalité | Prio | Phase | Composant | Ressources |
|---|---|---|---|---|---|
| RF1 | Poser une question en français | M | P1 | agent, API | `planner`, `python-reviewer` |
| RF2 | Réponse chiffrée avec période et périmètre | M | P1 | agent, formateur | `mle-reviewer` |
| RF14 | Précision ou refus motivé | M | P1 | agent (premier tour) | `mle-reviewer` (matrice d'intention) |
| RF8 | SQL et tables visibles (analyste) | M | P1 | API (filtrage), `SqlPanel` | `security-reviewer`, `fastapi-reviewer` |
| RF3 | Graphique adapté | M | P2 | formateur, `Chart` | `react-feature-architect`, skill `dataviz` |
| RF5 | Question de suivi (état résolu) | S | P2 | agent, API | `mle-reviewer` |
| RF6 | Historique et relance | S | P2 | API, `ConversationList` | `fastapi-feature-scaffolder`, `react-reviewer` |
| RF4 | Tableau de bord KPI | S | P3 | `get_kpi`, `KpiTile` | `react-feature-architect`, skill `dataviz` |
| RF13 | Journal d'audit technique | S | P3 | API, `AuditTable` | `security-reviewer` |
| RF11 | Utilisateurs et rôles | — | P2 | Keycloak (console) | `/react-auth` |
| RF7 | Export PDF | C | P4 | API ou front | à décider |
| RF9 | KPI via `kpis.yaml` | C | P4 | couche sémantique | revue de code obligatoire |
| RF10 | Signaler une réponse | C | P4 | API, front | — |
| RF12 | Paramétrage | — | — | fichier de configuration | — |

## 2. Chantiers techniques

| Chantier | Phase | Contenu | Ressources |
|---|---|---|---|
| Fondations dépôt | P0 | Arborescence, `docker compose`, `.env.example`, pré-commit (secrets, lint), `Makefile` | `/project-init`, `secrets-auditor`, skill `docker-patterns` |
| Rôles et droits Postgres | P0 | `init.sql`, `ALTER DEFAULT PRIVILEGES`, test de droits | `database-reviewer`, `security-reviewer` |
| Générateur de données | P0 | 50 000 clients, 2 000 agents, 18 mois, saisonnalité, jours fériés, aberrations, graine fixe | `python-reviewer`, skill `python-patterns` |
| Modèle dbt | P0 | `raw` → étoile, `dim_region`, `dim_date`, agent −1, tests et tests unitaires de KPI | `database-reviewer`, skill `postgres-patterns` |
| Jeux d'évaluation | P0 | `dev.yaml`, `test.yaml` (40), comparateur, contrôle anti-fuite, hash figé | `mle-reviewer`, `tdd-guide`, skill `eval-harness` |
| Serveur MCP et garde SQL | P1 | Outils, AST sqlglot, liste blanche de fonctions, `EXPLAIN`, `truncated`, jeu de 25 payloads | `security-reviewer`, `python-reviewer`, skill `mcp-server-patterns` |
| Couche sémantique | P1 | `tables`, `kpis`, `glossary`, `examples` | `architect`, `mle-reviewer` |
| Agent | P1 | Boucle d'outils, intention, validateur de sortie, formateur, `LLMClient` | `architect`, `mle-reviewer`, skill `claude-api` |
| API FastAPI | P1-P2 | JWT, conversations, flux d'étapes, `query_log`, quotas, CORS | `fastapi-feature-scaffolder`, `fastapi-tdd-assistant`, `fastapi-reviewer`, skills `fastapi-patterns`, `api-design` |
| Authentification | P2 | Realm Keycloak versionné sans secret, client public PKCE, validation JWT | skill `react-auth`, `security-reviewer` |
| Interface | P2-P3 | Design system, écrans conversation, tableau de bord, audit | `react-feature-architect`, `react-reviewer`, `a11y-architect`, skills `frontend-design`, `dataviz` |
| Tests de bout en bout | P2-P3 | Parcours question → graphique, accessibilité, captures | `e2e-runner`, `react-tdd-assistant` |
| Évaluation et ablations | P1-P3 | Passes, intervalle de Wilson, quatre ablations, rapports | `mle-reviewer`, skill `eval-harness` |
| Documentation | continu | README par composant, ADR, rapport d'évaluation | `doc-updater` |

## 3. Ordre de réalisation

```
P0  dépôt → rôles Postgres → générateur → dbt + tests → jeux d'évaluation
P1  couche sémantique → MCP + garde SQL → agent (RF1, RF2, RF14, RF8) → première évaluation
P2  API + Keycloak → interface (RF3, RF5, RF6)
P3  RF4, RF13 → itérations d'évaluation → jeu de sécurité complet
P4  PDF, signalement, KPI via YAML, cible Snowflake
```

Chaque phase se termine par son point de contrôle (SRS §12). Je vous propose de commencer par P0 : c'est elle qui fige les 40 réponses de référence.

## 4. Points à trancher avec vous

| Sujet | Question |
|---|---|
| Fournisseur LLM | Quel modèle pour l'agent ? Je propose un modèle Claude, par `LLMClient` |
| Maquette | Voulez-vous une maquette HTML statique avant de coder `web/` ? |
| Rapport PDF (C) | Génération côté API ou côté navigateur ? À décider en P4 |
| Mémoire | Sur quelles sections du mémoire doit-on aligner le vocabulaire (étoile, couche sémantique, MCP) ? |
