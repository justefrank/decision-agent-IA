# Fonctionnalités, écrans et ressources

Version 3 (MVP). Cadrage opérationnel : chaque exigence du MVP, ses écrans, sa phase et le paquet du dépôt qui la porte. Complète [SRS.md](../SRS.md) §4 et §12, [SYSTEM_DESIGN.md](SYSTEM_DESIGN.md) §9 et [DESIGN_SYSTEM.md](DESIGN_SYSTEM.md) §5. Origine : [EVALUATION_V5.md](EVALUATION_V5.md) §6 et §7.

Priorités : M = Must, S = Should, C = Could. Écrans : A = authentification, U = application, B = back-office. Les identifiants de la maquette v4 sont conservés.

## 1. Exigences MVP → écrans → phases → paquets

| Réf. | Fonctionnalité | Prio | Phase | Écrans | Paquets et dossiers | Ressources |
|---|---|---|---|---|---|---|
| RF1 | Poser une question en français | M | P1 (moteur), P2 (écran) | U01, U02 | `agent`, `api`, `frontend/` | `planner`, `python-reviewer` |
| RF2 | Réponse chiffrée avec période et périmètre | M | P1 | U03, U05, U06 | `agent` (faits, formateur), `core` | `mle-reviewer` |
| RF14 | Précision, refus motivé | M | P1 | U04, U09 | `agent` (outils terminaux, clarification) | `mle-reviewer` |
| RF8 | SQL visible pour l'analyste | M | P1 (contrat), P2 (écran) | U17 | `core` (`for_role`), `api` | `security-reviewer`, `fastapi-reviewer` |
| RF3 | Graphique adapté | M | P2 | U03, U05, U06, U07 | `agent` (choix du graphique), `frontend/` | `react-feature-architect`, skill `dataviz` |
| RF15 | Connexion, OTP, session expirée, déconnexion | M | P2 | A01, A05, A08, A09 | `infra/keycloak/`, `frontend/`, `api` (JWT) | skill `react-auth`, `security-reviewer`, `a11y-architect` |
| RF5 | Question de suivi | S | P1 (état), P2 | U03, U04 | `agent` (état résolu) | `mle-reviewer` |
| RF6 | Historique et relance | S | P2 | U03 (panneau d'historique) | `api`, `frontend/` | `fastapi-feature-scaffolder`, `react-reviewer` |
| RF4 | Tableau de bord KPI | S | P3 | U12 | `agent.dashboard`, `api`, `frontend/` | `react-feature-architect`, skill `dataviz` |
| RF17 | Analyse du tableau de bord (workflow) | S | P3 | U12 | `agent.dashboard`, `eval` | `mle-reviewer`, `security-reviewer` |
| RF16 | Récupérer son accès (pages Keycloak de base) | S | P2 | — (thème de base Keycloak) | `infra/keycloak/`, Mailpit | `security-reviewer` |
| RF10 | Signaler, lister, rejeter, promouvoir | S | P3 | U03 (action), B12 | `api`, `frontend/` | `mle-reviewer` |
| RF13 | Journal d'audit et détail | S | P3 | B08 (détail en tiroir) | `api` (`audit_access_log`) | `security-reviewer`, `database-reviewer` |
| RF11 | Utilisateurs et rôles | S | P2 | — (console Keycloak) | `infra/keycloak/` (realm, procédure) | `security-reviewer` |
| RF9 | Catalogue de KPI (lecture + PR) | S | P3 | B05 | `semantic/kpis.yaml`, `api`, CI | `database-reviewer` |
| RF18 | Couche sémantique (lecture + PR) | S | P3 | B05 | `semantic/`, `api`, CI anti-fuite | `mle-reviewer` |
| RF12 | Paramètres (lecture + PR) | S | P3 | B05 | `semantic/config.yaml`, `api` | `architect` |
| RF19 | Évaluation (lecture ; lancement CLI) | S | P1 (CLI), P3 (écran) | B11 | `eval`, `api` | `mle-reviewer`, skill `eval-harness` |
| RF20 | Exploitation et sécurité | S | P3 | B01 | `api`, `mcp_server` (test de droits) | `security-reviewer`, `performance-optimizer` |
| RF7 | Export PDF | C | P5 | — | à décider | — |

Transverses : garde SQL et MCP (`sql_guard`, `mcp_server`, P1, ENF3) ; générateur et dbt (`data_gen`, `warehouse/`, P0, ENF8) ; Postgres (`infra/postgres/init/`, P0) ; proxy (`infra/Caddyfile`, P0) ; accessibilité (ENF7, toutes phases, audit en P4).

## 2. Écrans MVP (22)

Tous responsive de 320 à 1440 px (les écrans mobiles M1-M3 sont remplacés par le responsive).

| Groupe | Écrans | Nature |
|---|---|---|
| Authentification (4) | A01 Connexion · A05 Vérification en deux étapes | Thème Keycloakify |
| | A08 Session expirée (inclut l'avertissement de fin de session SSO, ex-U16) · A09 Déconnecté | SPA |
| Application (13) | U01 Accueil · U02 Calcul en cours · U03 Réponse avec courbe (et panneau d'historique) · U04 Précision · U05 Classement · U06 Répartition · U07 Tableau tronqué · U08 Résultat vide · U09 Refus (hors périmètre ou modification, ex-U09 et U10) · U11 Panne du modèle · U12 Indicateurs et analyse · U15 Accès refusé · U17 Réponse avec SQL (analyste) | SPA |
| Back-office (5) | B01 Exploitation et sécurité (fusion B01 + B10) · B05 Configuration en lecture (onglets KPI, couche sémantique, paramètres ; fusion B05 + B07 + B13) · B08 Journal d'audit (détail d'un appel en tiroir, ex-B09) · B11 Évaluation · B12 Signalements | SPA, routes `/admin` |

Accès au back-office : analyste = B05 (KPI et sémantique), B08, B11, B12 ; admin = les 5 vues (B05 avec l'onglet paramètres).

### Reporté ou supprimé

| Écrans v4 | Sort |
|---|---|
| A02, A03, A04, A07 (récupération, première connexion) | Pages Keycloak en thème de base aux jetons (RF16), pas d'écran conçu |
| A06 Compte verrouillé | **Supprimé** : contredit les messages neutres de la détection de force brute |
| A10 Connexion réussie | Supprimé : retour direct sur U01 |
| U13, U18 (thème sombre) | Option : jetons sombres prévus, écrans non exigés |
| U14 Audit analyste | Couvert par B08 |
| U16 Session expirée dans l'application | Fusionné dans A08 |
| M1-M3 | Remplacés par le responsive |
| B02, B03, B04 (utilisateurs) | Console Keycloak (RF11) |
| B06 Éditeur de KPI, éditeurs de B07 et B13 | Remplacés par la PR Git ; P5 si le temps le permet |
| B09 Détail d'un appel | Tiroir de B08 |
| B10 Sécurité | Fusionné dans B01 |

## 3. Phases et paquets

| Phase | Contenu | Paquets et dossiers | Point de contrôle | Estimation |
|---|---|---|---|---|
| **P0 Fondations** | Retrait des squelettes ; espace de travail uv ; compose (Postgres 17, Keycloak, Caddy, Mailpit) ; init des rôles ; générateur ; dbt et tests ; couche sémantique ; jeux `test`, `dev`, `intent` ; `compare.py` | `core`, `data_gen`, `warehouse/`, `semantic/`, `infra/`, `eval/`, `eval` (comparateur), `scripts/` | `make seed` vert, références recalculées, hash du test figé | 12-15 j |
| **P1 Tranche verticale** | Garde SQL et payloads ; `MCPServer` ; `LLMClient` ; boucle et outils terminaux ; faits, validateur, formateur ; `make eval` ; banc de latence ; comparatif de modèles | `sql_guard`, `mcp_server`, `agent`, `eval` | Première évaluation (pass^3 + Wilson, ablations, latence, coût) ; **bloquant avant toute interface** | 18-22 j |
| **P2 Produit** | API (JWT, conversations, SSE, quota, `query_log`) ; realm, Audience mapper, thème de connexion ; SPA (migration Vite, conversation, graphiques, chaîne de preuve, SQL, historique, responsive) | `api`, `infra/keycloak/`, `frontend/` | e2e connexion → question → graphique, axe-core vert | 15-18 j |
| **P3 Pilotage** | Tableau de bord et analyse ; back-office en lecture (5 vues) ; signalements | `agent.dashboard`, `api`, `frontend/`, `eval` (jeu `analysis`) | O1 à O3 mesurés et visibles | 10-12 j |
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
| Dossier de la SPA | Migrer `frontend/` vers Vite sous `web/` ou garder `frontend/` (SRS Q-g) |
| Modèle final | Sonnet 5.5 par défaut, à confirmer par la mesure en P1 (SRS Q-a) |
| Vue B05 en onglets | Valider sur la maquette la fusion KPI + sémantique + paramètres |
| Rapport PDF (C) | Génération côté API ou côté navigateur ? À décider en P5 |
| Mémoire | Vocabulaire commun (étoile, couche métrique, MCP, chaîne de preuve, citation par référence) |
