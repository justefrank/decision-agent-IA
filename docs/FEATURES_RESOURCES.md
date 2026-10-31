# Fonctionnalités, écrans et ressources

Version 3 (MVP). Cadrage opérationnel : chaque exigence du MVP, ses écrans, sa phase et le paquet du dépôt qui la porte. Complète [SRS.md](../SRS.md) §4 et §12, [SYSTEM_DESIGN.md](SYSTEM_DESIGN.md) §9 et [DESIGN_SYSTEM.md](DESIGN_SYSTEM.md) §5. Origine : [EVALUATION_V5.md](EVALUATION_V5.md) §6 et §7.

Priorités : M = Must, S = Should, C = Could. Écrans : A = authentification, U = application, B = back-office. Les identifiants de la maquette v4 sont conservés.

## 1. Exigences MVP → écrans → phases → paquets

| Réf. | Fonctionnalité | Prio | Phase | Écrans | Paquets et dossiers | Ressources |
|---|---|---|---|---|---|---|
| RF1 | Poser une question en français | M | P1 (moteur), P2 (écran) | Questions | `agent`, `api`, `web/` | `planner`, `python-reviewer` |
| RF2 | Réponse chiffrée avec période et périmètre | M | P1 | Questions (reçu) | `agent` (faits, formateur), `core` | `mle-reviewer` |
| RF14 | Précision, refus motivé | M | P1 | Questions (précision, refus) | `agent` (outils terminaux, clarification) | `mle-reviewer` |
| RF8 | SQL visible pour l'analyste | M | P1 (contrat), P2 (écran) | Questions (« Voir le calcul ») | `core` (`for_role`), `api` | `security-reviewer`, `fastapi-reviewer` |
| RF3 | Graphique adapté | M | P2 | Questions (graphiques) | `agent` (choix du graphique), `web/` | `react-feature-architect`, skill `dataviz` |
| RF15 | Connexion, OTP, session expirée, déconnexion | M | P2 | Connexion, session expirée, déconnecté | `infra/keycloak/`, `web/`, `api` (JWT) | skill `react-auth`, `security-reviewer`, `a11y-architect` |
| RF5 | Question de suivi | S | P1 (état), P2 | Questions (suivi) | `agent` (état résolu) | `mle-reviewer` |
| RF6 | Historique et relance | S | P2 | Questions (historique) | `api`, `web/` | `fastapi-feature-scaffolder`, `react-reviewer` |
| RF4 | Tableau de bord KPI | S | P3 | Indicateurs | `agent.dashboard`, `api`, `web/` | `react-feature-architect`, skill `dataviz` |
| RF17 | Analyse du tableau de bord (workflow) | S | P3 | Indicateurs (analyse) | `agent.dashboard`, `eval` | `mle-reviewer`, `security-reviewer` |
| RF16 | Récupérer son accès (pages Keycloak de base) | S | P2 | — (thème de base Keycloak) | `infra/keycloak/`, Mailpit | `security-reviewer` |
| RF10 | Signaler, lister, rejeter, promouvoir | S | P3 | Questions (signaler), Signalements | `api`, `web/` | `mle-reviewer` |
| RF13 | Journal d'audit et détail | S | P3 | Journal d'audit (détail en tiroir) | `api` (`audit_access_log`) | `security-reviewer`, `database-reviewer` |
| RF11 | Utilisateurs et rôles | S | P2 | — (console Keycloak) | `infra/keycloak/` (realm, procédure) | `security-reviewer` |
| RF9 | Catalogue de KPI (lecture + PR) | S | P3 | Catalogue de KPI | `semantic/kpis.yaml`, `api`, CI | `database-reviewer` |
| RF18 | Couche sémantique (lecture + PR) | S | P3 | Couche sémantique | `semantic/`, `api`, CI anti-fuite | `mle-reviewer` |
| RF12 | Paramètres (lecture + PR) | S | P3 | Paramètres | `semantic/config.yaml`, `api` | `architect` |
| RF19 | Évaluation (lecture ; lancement CLI) | S | P1 (CLI), P3 (écran) | Évaluation | `eval`, `api` | `mle-reviewer`, skill `eval-harness` |
| RF20 | Exploitation et sécurité | S | P3 | Exploitation, Sécurité | `api`, `mcp_server` (test de droits) | `security-reviewer`, `performance-optimizer` |
| RF7 | Export PDF | C | P5 | — | à décider | — |

Transverses : garde SQL et MCP (`sql_guard`, `mcp_server`, P1, ENF3) ; générateur et dbt (`data_gen`, `warehouse/`, P0, ENF8) ; Postgres (`infra/postgres/init/`, P0) ; proxy (`infra/Caddyfile`, P0) ; accessibilité (ENF7, toutes phases, audit en P4).

## 2. Écrans de l'interface réelle

La maquette de 45 écrans n'est **plus la référence** (l'auteur l'a jugée trop éloignée de l'usage) : l'interface `web/` en garde le logo et les jetons de design, et propose sa propre présentation (« le relevé », [DESIGN_SYSTEM §1](DESIGN_SYSTEM.md)). Une seule interface responsive de 320 à 1440 px, thèmes clair et sombre. Liste des écrans et des routes : [DESIGN_SYSTEM §5](DESIGN_SYSTEM.md#5-écrans-routes).

| Zone | Pages | Nature |
|---|---|---|
| Hors session | Connexion, déconnecté, session expirée (avec l'avertissement avant la fin de session), vérification en deux étapes à refaire | SPA ; saisie du mot de passe et du code sur les pages Keycloak |
| Application | Questions (accueil, fil, historique, signalement), Indicateurs (relevé et analyse), Accès réservé | SPA |
| Back-office | Exploitation, journal d'audit, évaluation, signalements, KPI, couche sémantique, sécurité, paramètres | SPA, routes `/admin` |

Accès au back-office : analyste = exploitation, audit, évaluation, signalements, KPI, couche sémantique ; admin = en plus sécurité et paramètres.

## 3. Phases et paquets

| Phase | Contenu | Paquets et dossiers | Point de contrôle | Estimation |
|---|---|---|---|---|
| **P0 Fondations** | Retrait des squelettes ; espace de travail uv ; compose (Postgres 17, Keycloak, Caddy, Mailpit) ; init des rôles ; générateur ; dbt et tests ; couche sémantique ; jeux `test`, `dev`, `intent` ; `compare.py` | `core`, `data_gen`, `warehouse/`, `semantic/`, `infra/`, `eval/`, `eval` (comparateur), `scripts/` | `make seed` vert, références recalculées, hash du test figé | 12-15 j |
| **P1 Tranche verticale** | Garde SQL et payloads ; `MCPServer` ; `LLMClient` ; boucle et outils terminaux ; faits, validateur, formateur ; `make eval` ; banc de latence ; comparatif de modèles | `sql_guard`, `mcp_server`, `agent`, `eval` | Première évaluation (pass^3 + Wilson, ablations, latence, coût) ; **bloquant avant toute interface** | 18-22 j |
| **P2 Produit** | API (JWT, conversations, SSE, quota, `query_log`) ; realm, Audience mapper, thème de connexion ; SPA (migration Vite, conversation, graphiques, chaîne de preuve, SQL, historique, responsive) | `api`, `infra/keycloak/`, `web/` | e2e connexion → question → graphique, axe-core vert | 15-18 j |
| **P3 Pilotage** | Tableau de bord et analyse ; back-office en lecture (5 vues) ; signalements | `agent.dashboard`, `api`, `web/`, `eval` (jeu `analysis`) | O1 à O3 mesurés et visibles | 10-12 j |
| **P4 Finition** | Audit WCAG 2.2 AA, campagne finale, documents et ADR | tous | Acceptation | 5-8 j |
| P5 (Could) | PDF, Snowflake, éditeurs du back-office | — | Selon le temps | — |

```
P0  uv + compose + rôles → générateur → dbt + tests → sémantique → jeux d'évaluation + compare.py
P1  sql_guard → mcp_server → agent (boucle, faits, validateur) → make eval → comparatif de modèles   [jalon bloquant]
P2  api + Keycloak (connexion, OTP) → SPA Vite (conversation, graphiques, historique, responsive)
P3  tableau de bord + analyse → back-office en lecture (5 vues) → signalements
P4  accessibilité → campagne finale → documents
```

## 4. Chantiers techniques

| Chantier | Phase | Contenu | Ressources |
|---|---|---|---|
| Fondations dépôt | P0 | Espace de travail uv, compose, Caddyfile, `.env.example`, pré-commit (secrets, lint), `Makefile` | skill `docker-patterns`, `secrets-auditor` |
| Rôles et droits Postgres | P0 | `infra/postgres/init/`, migration initiale des droits `app_rw`, test de droits | `database-reviewer`, `security-reviewer` |
| Générateur et dbt | P0 | 50 000 clients, 2 000 agents, 18 mois, valeurs ASCII, membres −1, tests et tests unitaires de KPI | `database-reviewer` |
| Jeux d'évaluation | P0 | `test` (40, hash figé), `dev`, `intent`, `followup`, `security`, comparateur, anti-fuite | `mle-reviewer`, `tdd-guide` |
| Garde SQL et MCP | P1 | Types de nœuds, noms normalisés, bornes, `BEGIN READ ONLY`, `query_metric`, payloads de différentiel | `security-reviewer`, `python-reviewer` |
| Agent | P1 | Boucle, outils terminaux, faits, validateur, formateur, état résolu, intégration Claude | `architect`, `mle-reviewer`, skill `claude-api` |
| API | P2, P3 | JWT, conversations, SSE, quota, `query_log`, routes `/api/admin/*` en lecture | `fastapi-feature-scaffolder`, `fastapi-tdd-assistant`, `fastapi-reviewer` |
| Keycloak | P2 | Realm sans secret, Audience mapper, MFA, force brute, événements, thème connexion + OTP | `security-reviewer`, skill `react-auth` |
| SPA | P2, P3 | Migration Vite ; features `conversation`, `dashboard`, `auth`, `admin` | `react-feature-architect`, `react-reviewer`, `a11y-architect` |
| Tests de bout en bout | P2-P4 | Connexion → question → graphique ; back-office ; accessibilité | `e2e-runner`, `react-tdd-assistant` |
| Documentation | continu | README par paquet, ADR, rapports d'évaluation | `doc-updater` |

## 5. Comment les sous-agents ont été utilisés pour la maquette

`gan-generator` (×4) : pages d'authentification, coque du back-office et ses vues. `a11y-architect` : deux audits WCAG 2.2 AA puis deux séries de corrections. Un contrôleur statique (`check2.js`) vérifiait chaque composant dans tous ses états avant publication. Aucun rendu navigateur n'a encore eu lieu. La maquette garde ses 45 écrans ; le MVP en retient 22 (§2).

## 6. Points à trancher

| Sujet | Question |
|---|---|
| Modèle final | Sonnet 5.5 par défaut, à confirmer par la mesure en P1 (SRS Q-a) |
| Rapport PDF (C) | Génération côté API ou côté navigateur ? À décider en P5 |
| Mémoire | Vocabulaire commun (étoile, couche métrique, MCP, chaîne de preuve, citation par référence) |
