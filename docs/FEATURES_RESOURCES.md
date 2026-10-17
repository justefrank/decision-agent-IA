# Fonctionnalités, écrans et ressources

Version 2. Cadrage opérationnel : chaque exigence, ses écrans de la maquette, sa phase, son composant et la ressource adéquate. Complète [SRS.md](../SRS.md) §4 et §12 et [DESIGN_SYSTEM.md](DESIGN_SYSTEM.md) §5.

Priorités : M = Must, S = Should, C = Could. Écrans : A = authentification, U = application, M = mobile, B = back-office.

## 1. Exigences, écrans, phases

| Réf. | Fonctionnalité | Prio | Phase | Écrans | Ressources |
|---|---|---|---|---|---|
| RF1 | Poser une question en français | M | P1 | U01, U02, U03 | `planner`, `python-reviewer` |
| RF2 | Réponse chiffrée avec période et périmètre | M | P1 | U03, U05, U06 | `mle-reviewer` |
| RF14 | Précision, refus motivé | M | P1 | U04, U09, U10, U08 | `mle-reviewer` |
| RF8 | SQL visible pour l'analyste | M | P1 | U17 | `security-reviewer`, `fastapi-reviewer` |
| RF3 | Graphique adapté | M | P2 | U03, U05, U06, U07 | `react-feature-architect`, skill `dataviz` |
| RF15 | Se connecter, MFA, session expirée, déconnexion | M | P2 | A01, A05, A08, A09, A10, U16 | skill `react-auth`, `security-reviewer`, `a11y-architect` |
| RF5 | Question de suivi | S | P2 | U03 (suite), U04 | `mle-reviewer` |
| RF6 | Historique et relance | S | P2 | U03 à U07 (panneau d'historique), M2 | `fastapi-feature-scaffolder`, `react-reviewer` |
| RF4 | Tableau de bord KPI | S | P3 | U12, U13, M3 | `react-feature-architect`, skill `dataviz` |
| RF17 | Analyse du tableau de bord par l'agent | S | P3 | U12, U13 | `mle-reviewer`, `security-reviewer` |
| RF13 | Journal d'audit | S | P3 | U14, B08, B09 | `security-reviewer`, `database-reviewer` |
| RF19 | Piloter l'évaluation | S | P3 | B11 | `mle-reviewer`, skill `eval-harness` |
| RF20 | Exploitation et sécurité | S | P3 | B01, B10 | `security-reviewer`, `performance-optimizer` |
| RF11 | Utilisateurs et rôles | S | P4 | B02, B03, B04, U15 | `security-reviewer`, skill `react-auth` |
| RF9 | Catalogue de KPI et revue | S | P4 | B05, B06 | `database-reviewer`, `architect` |
| RF18 | Couche sémantique | S | P4 | B07 | `mle-reviewer` |
| RF12 | Paramètres avec diff et revue | S | P4 | B13 | `architect`, `security-reviewer` |
| RF10 | Signaler une réponse | S | P4 | B12 (côté traitement) | `mle-reviewer` |
| RF16 | Récupérer son accès | S | P4 | A02, A03, A04, A06, A07 | `security-reviewer` |
| RF7 | Export PDF | C | P5 | — | à décider |

## 2. Inventaire des 45 écrans

| Groupe | Identifiants et titres |
|---|---|
| Prototype | App : parcours complet relié, panneau « Démo : états » |
| Authentification | A01 Connexion · A02 Mot de passe oublié · A03 Message envoyé · A04 Nouveau mot de passe · A05 Vérification en deux étapes · A06 Compte verrouillé · A07 Première connexion · A08 Session expirée · A09 Déconnecté · A10 Connexion réussie |
| Application | U01 Accueil · U02 Calcul en cours · U03 Réponse avec courbe · U04 Précision · U05 Classement · U06 Répartition · U07 Tableau tronqué · U08 Résultat vide · U09 Refus hors périmètre · U10 Refus de modification · U11 Panne du modèle · U12 Indicateurs et analyse · U13 Indicateurs sombre · U14 Audit analyste · U15 Accès refusé · U16 Session expirée dans l'application · U17 Réponse avec SQL · U18 Réponse sombre |
| Mobile | M1 Accueil · M2 Conversation · M3 Indicateurs |
| Back-office | B01 Vue d'ensemble · B02 Utilisateurs · B03 Invitation · B04 Détail utilisateur · B05 Catalogue de KPI · B06 Éditeur de KPI · B07 Couche sémantique · B08 Journal d'audit · B09 Détail d'un appel · B10 Sécurité · B11 Évaluation · B12 Signalements · B13 Paramètres |

Écrans à dessiner plus tard : navigation restreinte du back-office pour l'analyste ; export PDF (Could) ; version mobile du back-office (aujourd'hui repliable mais non conçue).

## 3. Chantiers techniques

| Chantier | Phase | Contenu | Ressources |
|---|---|---|---|
| Fondations dépôt | P0 | Arborescence, compose, `.env.example`, pré-commit (secrets, lint), `Makefile` | skill `docker-patterns`, `secrets-auditor` |
| Rôles et droits Postgres | P0 | `init.sql`, droits par défaut, test de droits | `database-reviewer`, `security-reviewer` |
| Générateur de données | P0 | 50 000 clients, 2 000 agents, 18 mois, saisonnalité, jours fériés, graine fixe | `python-reviewer` |
| Modèle dbt | P0 | `raw` → étoile, `dim_region`, `dim_date`, agent −1, tests et tests unitaires de KPI | `database-reviewer` |
| Jeux d'évaluation | P0 | `dev.yaml`, `test.yaml` (40), comparateur, anti-fuite, hash figé | `mle-reviewer`, `tdd-guide` |
| Serveur MCP et garde SQL | P1 | Outils, AST sqlglot, liste blanche, `EXPLAIN`, `truncated`, 25 payloads | `security-reviewer`, `python-reviewer` |
| Couche sémantique et agent | P1 | `tables`, `kpis`, `glossary`, `examples`, boucle d'outils, validateur | `architect`, `mle-reviewer`, skill `claude-api` |
| API FastAPI | P1 à P4 | JWT, conversations, flux d'étapes, `query_log`, routes `/admin/*`, demandes de changement | `fastapi-feature-scaffolder`, `fastapi-tdd-assistant`, `fastapi-reviewer` |
| Keycloak | P2, P4 | Realm sans secret, thème des pages d'authentification, compte de service limité | `security-reviewer`, skill `react-auth` |
| Application React | P2, P3 | Features `conversation`, `dashboard`, `auth` | `react-feature-architect`, `react-reviewer`, `a11y-architect` |
| Back-office React | P3, P4 | Feature `admin` : lecture d'abord, écriture ensuite | `react-feature-architect`, `a11y-architect` |
| Tests de bout en bout | P2 à P4 | Connexion → question → graphique ; changement de KPI relu ; accessibilité | `e2e-runner`, `react-tdd-assistant` |
| Documentation | continu | README par composant, ADR, rapports d'évaluation | `doc-updater` |

## 4. Ordre de réalisation

```
P0  dépôt → rôles Postgres → générateur → dbt + tests → jeux d'évaluation
P1  couche sémantique → MCP + garde SQL → agent → première évaluation
P2  API + Keycloak (connexion, MFA) → application (conversation, graphiques, historique, mobile)
P3  tableau de bord + analyse → back-office en lecture (vue d'ensemble, audit, évaluation, sécurité)
P4  back-office en écriture (utilisateurs, KPI, sémantique, paramètres, signalements) + récupération d'accès
P5  PDF, cible Snowflake
```

Point de contrôle de chaque phase : SRS §12. Je propose de reprendre par P0 : elle fige les 40 réponses de référence.

## 5. Comment les sous-agents ont été utilisés pour la maquette

`gan-generator` (×4) : pages d'authentification, coque du back-office et ses trois premières vues, six autres vues du back-office. `a11y-architect` : deux audits WCAG 2.2 AA puis deux séries de corrections. Un contrôleur statique (`check2.js`) vérifiait chaque composant dans tous ses états avant publication. Aucun rendu navigateur n'a encore eu lieu.

## 6. Points à trancher

| Sujet | Question |
|---|---|
| Back-office de l'analyste | Quelles entrées garde-t-il : KPI, couche sémantique, audit technique, évaluation, signalements ? |
| Fournisseur LLM | Quel modèle pour l'agent ? Proposition : un modèle Claude, derrière une interface `LLMClient` |
| Rapport PDF (C) | Génération côté API ou côté navigateur ? À décider en P5 |
| Mémoire | Sur quelles sections du mémoire aligne-t-on le vocabulaire (étoile, couche sémantique, MCP, chaîne de preuve) ? |
