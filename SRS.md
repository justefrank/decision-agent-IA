# Spécification — Agent conversationnel d'aide à la décision (Wave)

Version 5 · MVP, couche métrique compilée, citation par référence, Claude sans température · 2026-10-24

> Documents liés : [docs/SYSTEM_DESIGN.md](docs/SYSTEM_DESIGN.md), [docs/AGENTIC_DESIGN.md](docs/AGENTIC_DESIGN.md), [docs/FEATURES_RESOURCES.md](docs/FEATURES_RESOURCES.md), [docs/DIAGRAMS.md](docs/DIAGRAMS.md), [docs/DESIGN_SYSTEM.md](docs/DESIGN_SYSTEM.md).
> Origine des décisions v5 : [docs/EVALUATION_V5.md](docs/EVALUATION_V5.md) et les revues de [docs/reviews/](docs/reviews/). Contrats exécutables : `packages/core/src/decision_core/models.py`, `semantic/*.yaml`, `infra/postgres/init/`. En cas d'écart entre ce texte et ces fichiers, les fichiers font foi et le texte est corrigé.
> Historique des changements : section 14. Questions restantes : section 15.

## 1. Contexte et objectifs

Un décideur interroge en langage naturel un data warehouse et obtient des réponses chiffrées, des graphiques et une analyse du tableau de bord, sans passer par un analyste. Un back-office **en lecture** permet de surveiller l'agent : exploitation, sécurité, audit, évaluation, signalements, configuration.

Hypothèse : obtenir un indicateur non prévu dans un tableau de bord suppose aujourd'hui de solliciter un analyste, ce qui ralentit la décision.

Question de recherche du mémoire : **quelle justesse et quelle sûreté atteint un agent text-to-SQL contraint (couche métrique compilée, garde SQL, citation par référence) sur un entrepôt en étoile ?**

| Réf. | Objectif | Mesure |
|---|---|---|
| O1 | Justesse | Sur le **jeu de test seul** (40 questions) : pass@1 moyen (3 passes) **≥ 80 %** en point estimé. Publiés avec : **pass^3** (référence de fiabilité) et son intervalle de Wilson à 95 % sur n = 40 questions, intervalle bootstrap groupé par question pour pass@1, comptes bruts par catégorie. Le dev n'est qu'indicatif. Limite assumée : 32/40 donne un intervalle d'environ [65 %, 90 %] |
| O2 | Rapidité | Latence médiane < 15 s, p90 < 30 s, mesurées de bout en bout par un **banc HTTP** (`POST /api/conversations/{id}/messages` jusqu'à l'événement `final`), **sans cache de réponses ni de SQL**. La mise en cache du prompt côté fournisseur est autorisée : elle fait partie de la configuration de production. La latence « cache froid » est publiée à part |
| O3 | Sûreté | 0 écriture exécutée ; 100 % des payloads hostiles du jeu de sécurité rejetés (section 11), y compris les différentiels de parseur et les 5 injections indirectes |
| O4 | Couverture | Tous les RF **Must et Should du MVP** (section 4) réalisés. RF7 (Could) hors objectif |

## 2. Périmètre

### Inclus (MVP)
- Données synthétiques (Python) vers un schéma brut, puis dbt vers un modèle en étoile.
- Serveur MCP en lecture seule (sous-processus stdio de l'API) : `query_metric`, `run_query`, `describe_schema`.
- Agent IA (Claude) avec appel d'outils, outils terminaux, citation des nombres par référence, validateur.
- Application web React (SPA) : accueil, conversation, historique, tableau de bord avec analyse de l'agent, **responsive** de 320 à 1440 px.
- Authentification par Keycloak : thème du produit sur la connexion et la vérification en deux étapes ; thème de base aux jetons du design system ailleurs.
- **Back-office en lecture** : exploitation et sécurité, journal d'audit, évaluation, signalements, configuration (KPI, couche sémantique, paramètres).
- Configuration (KPI, couche sémantique, paramètres) dans Git, **modifiée par PR**.
- Évaluation complète : jeux test, dev, intention, suivi, sécurité, régression, analyse ; ablations.

### Exclu
- Données réelles de Wave et toute donnée personnelle réelle.
- Écriture dans l'entrepôt par l'agent. Temps réel. Application mobile native.
- Orchestration multi-agents, RAG, **cache de réponses ou de SQL** (voir AGENTIC_DESIGN §2).
- Gestion des utilisateurs dans l'application : elle se fait dans la console Keycloak (RF11).

### Reporté
| Élément | Statut |
|---|---|
| Export PDF (RF7) | Could, P5 |
| Cible Snowflake (second target dbt) | Could, P5 ; la portabilité concerne dbt, pas le SQL ni les prompts |
| Éditeurs du back-office v4 (KPI, sémantique, paramètres, utilisateurs) | P5 si le temps le permet ; remplacés par la PR Git et la console Keycloak |
| Thème Keycloakify complet (7 pages) | Remplacé par connexion + OTP ; reste en thème de base |
| Écrans mobiles dédiés (M1-M3), thème sombre dédié (U13, U18) | Remplacés par le responsive ; jetons sombres prévus, écrans en option |
| Courtage d'un fournisseur d'identité externe (« SSO » d'entreprise) | Hors MVP (section 15) |

### Hypothèses
- Données synthétiques. Le LLM est un service externe qui reçoit les questions et des résultats agrégés ; ce flux est documenté et devra être revu avant toute bascule vers des données réelles (région d'inférence, ZDR, voir risques).
- `REFERENCE_DATE` = **2026-09-30** (configurable) tient lieu de « aujourd'hui ». Les données couvrent 18 mois : 2025-04-01 → 2026-09-30.

## 3. Acteurs et rôles

| Acteur | Rôle Keycloak (client `decision-web`) | Droits principaux |
|---|---|---|
| Décideur | `decideur` | Interroger l'agent, tableau de bord et analyse, historique personnel, signaler une réponse ; voit tables, période, périmètre et chaîne de preuve, **pas le SQL** |
| Analyste | `analyste` | Tout ce que fait le décideur, plus SQL et tables utilisées ; back-office : journal d'audit, évaluation, signalements, configuration KPI et couche sémantique (lecture) |
| Administrateur | `admin` | Back-office complet en lecture, y compris exploitation et sécurité et paramètres ; gère les utilisateurs **dans la console Keycloak** ; aucun accès aux conversations d'autrui |
| Data warehouse | — | Lecture seule via le rôle Postgres `agent_ro`, détenu par le seul sous-processus MCP |

La navigation restreinte de l'analyste est fixée par ce tableau (entrées masquées côté interface, refus côté API). Matrice détaillée : [DIAGRAMS §2](docs/DIAGRAMS.md#2-acteurs-et-droits-mvp).

## 4. Exigences fonctionnelles (MVP)

| Réf. | Acteur | Exigence | Priorité |
|---|---|---|---|
| RF1 | Décideur | Poser une question en langage naturel, en français | **Must** |
| RF2 | Décideur | Réponse chiffrée rappelant période et périmètre ; nombres rendus par le code à partir des faits cités | **Must** |
| RF14 | Tous | Précision demandée si ambigu (une seule clarification, 2 ou 3 choix) ; refus motivé si hors périmètre ; possibles à tout tour de la boucle | **Must** |
| RF8 | Analyste | Afficher le SQL exécuté (réécrit par le garde) et les tables utilisées | **Must** |
| RF3 | Décideur | Graphique adapté (courbe, barres, répartition, tableau, chiffre clé), choisi par le code | **Must** |
| RF15 | Tous | Se connecter : e-mail et mot de passe, vérification en deux étapes (OTP), session expirée, déconnexion | **Must** |
| RF5 | Décideur | Question de suivi tenant compte de l'échange (état résolu produit par le code) | Should |
| RF6 | Décideur | Consulter et relancer l'historique | Should |
| RF4 | Décideur | Tableau de bord des 6 KPI (via `query_metric`), par période et région, avec période précédente | Should |
| RF17 | Décideur | Analyse du tableau de bord : workflow (candidats calculés par le code, un appel LLM sans outil, validateur) ; au plus 3 constats sourcés, confiance calculée, hypothèses étiquetées, questions d'approfondissement | Should |
| RF16 | Tous | Récupérer son accès par les pages Keycloak : mot de passe oublié, réinitialisation, première connexion (actions requises : mot de passe, OTP). Pas d'écran « compte verrouillé » (messages neutres) | Should |
| RF10 | Tous | Signaler une réponse ; l'analyste liste, rejette avec motif, ou promeut vers le jeu de dev. États : `nouveau`, `traite`, `rejete` | Should |
| RF13 | Analyste, admin | Journal d'audit technique des appels d'outils et LLM, avec détail par appel ; chaque consultation du détail est journalisée (`audit_access_log`) | Should |
| RF11 | Admin | Gérer utilisateurs et rôles dans la **console d'administration Keycloak** (procédure documentée, aucun écran applicatif) | Should |
| RF9 | Analyste, admin | Consulter le catalogue de KPI (lecture) ; toute modification passe par une **PR Git** sur `semantic/kpis.yaml` | Should |
| RF18 | Analyste, admin | Consulter la couche sémantique (tables, glossaire, exemples) ; modification par **PR Git** avec contrôle anti-fuite en CI | Should |
| RF12 | Admin | Consulter les paramètres (`semantic/config.yaml`) et la `semantic_version` en cours ; modification par **PR Git** | Should |
| RF19 | Analyste, admin | Consulter l'évaluation : pass^3, pass@1, intervalles, comptes bruts, ablations, historique des exécutions. **Lancement en CLI** (`make eval`), pas depuis l'interface | Should |
| RF20 | Admin | Une vue « Exploitation et sécurité » : latence, coût, taux de lecture du cache, blocages du garde SQL, santé du sous-processus MCP, bouton « test de droits » de `agent_ro` | Should |
| RF7 | Décideur | Exporter un rapport PDF | Could |

Changements par rapport à la v4 : RF9, RF12, RF18 passent en lecture + PR Git ; RF11 revient à la console Keycloak ; RF16 est réduit (A06 supprimé) ; RF19 lance en CLI ; RF10 a 3 états ; RF20 fusionne vue d'ensemble et sécurité ; RF4 et RF17 s'appuient sur `query_metric`.

## 5. Exigences non fonctionnelles

| Réf. | Catégorie | Exigence | Critère de vérification |
|---|---|---|---|
| ENF1 | Performance | Réponse rapide | Médiane < 15 s, p90 < 30 s (O2) ; budget de 30 s par question propagé jusqu'au MCP ; `statement_timeout` = min(10 s, temps restant − 4 s) |
| ENF2 | Fiabilité | Réponses justes et stables | **Aucun paramètre d'échantillonnage** (`temperature`, `top_p`, `top_k` refusés par l'API) ; modèle (`claude-sonnet-5-5`) et effort (`medium`) figés et tracés ; outils `strict` et sortie structurée ; 3 passes en évaluation, stabilité **mesurée** par pass^3 ; questions KPI à 3/3 ; repli serveur (`fallbacks`) désactivé en évaluation ; pas de cache de réponses ni de SQL |
| ENF3 | Sécurité | Aucune écriture, aucun accès hors `analytics` | Garde SQL par liste blanche (types de nœuds, tables, fonctions) + transaction `BEGIN READ ONLY` + rôle `agent_ro` durci ; ≥ 25 payloads hostiles, dont différentiels de parseur ; test de droits en CI |
| ENF4 | Sécurité | Secrets hors du code | `.env` non versionné, secrets Docker, masquage dans les journaux, scan en pré-commit et CI ; DSN `agent_ro` transmis au seul sous-processus MCP |
| ENF5 | Traçabilité | Chaque appel tracé | `app.query_log` écrit par l'API seule : une ligne par appel d'outil et par appel LLM (`tool = 'llm'`) ; versions de prompt et de couche sémantique ; modèle demandé et servi ; effort ; jetons (entrée, lecture et écriture de cache, sortie) ; `stop_reason`, `request_id`, `ttft_ms` |
| ENF6 | Transparence | Chiffres explicables | Analyste : SQL et tables ; décideur : chaîne de preuve (table, filtre, période, opération), sans SQL ; mention « calcul ad hoc » pour `run_query` ; filtrage côté serveur (`AssistantMessage.for_role`) |
| ENF7 | Accessibilité | **WCAG 2.2 AA** sur toutes les pages | Navigation clavier complète ; focus géré dans tiroirs et dialogues ; contrastes mesurés ; mouvement réduit respecté ; axe-core vert en CI ; audit avant chaque jalon |
| ENF8 | Maintenabilité | Pipeline reproductible | Espace de travail uv, tests par paquet ; tests dbt verts ; `docker compose up` ; README par composant |
| ENF9 | Coût | Consommation maîtrisée | 1 000 lignes max renvoyées, **50 lignes max envoyées au modèle** ; plan `EXPLAIN` borné ; quota de 200 questions par jour et 2 flux simultanés par utilisateur ; plafond de 0,10 $ par question (à recalibrer après P1) ; workspaces fournisseur séparés pour la production et l'évaluation |
| ENF10 | Authentification | Session sûre | Jeton d'accès de 5 min en mémoire, **renouvelé en silence** ; avertissement avant la fin de la **session SSO** Keycloak (inactivité ou durée max), avec prolongation (WCAG 2.2.1) ; détection de force brute Keycloak (verrouillage temporaire, messages neutres) ; MFA obligatoire pour analyste et admin ; aucun minuteur automatique sans moyen de l'arrêter |
| ENF11 | Gouvernance | Tout changement de configuration est relu | KPI, couche sémantique et paramètres modifiés **par PR Git** : relecteur différent de l'auteur, branche protégée, CI verte (validation des YAML, anti-fuite exemples/test, tests unitaires des KPI) ; l'API recalcule `semantic_version` au démarrage ; aucun changement direct en production |
| ENF12 | Ergonomie | Interface claire en français, responsive | Question → graphique en ≤ 3 clics ; utilisable de 320 à 1440 px ; **22 écrans de référence MVP** couverts ([FEATURES_RESOURCES §2](docs/FEATURES_RESOURCES.md#2-écrans-mvp-22)) |

## 6. Architecture

Voir [docs/SYSTEM_DESIGN.md](docs/SYSTEM_DESIGN.md). Un proxy Caddy de même origine sert la SPA (`/`), l'API (`/api`) et Keycloak (`/auth`). L'API FastAPI héberge l'agent et lance le serveur MCP en sous-processus stdio ; seul ce sous-processus détient le DSN `agent_ro`. Postgres 17 porte deux bases : `warehouse` (schémas `raw`, `analytics`, `app`) et `keycloak`. L'agent n'accède aux données que par le serveur MCP.

## 7. Modèle de données

Étoile : un fait, quatre dimensions. XOF sans décimales ; montants en `numeric`, jamais `float`. **Valeurs codées en ASCII, sans accent** ; les libellés français sont produits par le formateur.

| Table | Grain | Colonnes principales |
|---|---|---|
| `fact_transaction` | une transaction | `transaction_id` bigint, `client_id`, `agent_id` **NOT NULL** (−1 = « Hors agent »), `region_client_id`, `region_agent_id` (−1 = « Non applicable »), `date_id` (int AAAAMMJJ), `txn_ts` timestamptz, `type` ∈ {`depot`, `retrait`, `transfert`, `paiement`}, `montant_xof` numeric(14,0) > 0, `frais_xof` numeric(12,0) ≥ 0 et ≤ montant, `statut` ∈ {`reussie`, `echouee`} (CHECK) |
| `dim_client` | un client | `client_id`, `date_inscription`, `region_client_id`, `segment` ∈ {`particulier`, `commercant`, `entreprise`} |
| `dim_agent` | un point de service | `agent_id`, `nom`, `ville` (texte libre, non fiable), `region_agent_id`, `date_activation`, `statut_agent` ∈ {`ouvert`, `ferme`} ; ligne −1 « Hors agent » |
| `dim_region` | une région | `region_id`, `region`, `pays` ; 14 régions du Sénégal + ligne −1 « Non applicable » |
| `dim_date` | un jour | `date_id`, `date`, `jour_semaine`, `semaine_iso`, `mois`, `nom_mois`, `trimestre`, `annee`, `est_weekend`, `jour_ferie`, `debut_mois`, `fin_mois` |

SCD1 acté. Transferts et paiements ont l'agent −1 et la région d'agent −1 (test dbt). Pas de destinataire dans le fait : limite documentée (question hors périmètre).

Glossaire (source unique : `semantic/glossary.yaml`, modifié par PR) :
- « région » seule est ambiguë : `region_agent` ou `region_client`. Défaut `region_agent` pour agents et frais, `region_client` pour clients ; **pas de défaut** pour volume, valeur transférée et taux d'échec (clarification). Le sens retenu est toujours rappelé.
- « agent actif » (≥ 1 transaction réussie) ≠ `statut_agent`.
- « aujourd'hui », « ce mois-ci » se calculent depuis `REFERENCE_DATE`.
- Politique par champ (`field_policy`) : KPI manquant → clarification ; période manquante → mois de `REFERENCE_DATE`, annoncé ; périmètre manquant → national, annoncé ; sens de région → défaut du KPI ou clarification.

**KPI** (source unique : `semantic/kpis.yaml`, compilé par `query_metric` ; le tableau en est dérivé) :

| KPI (identifiant) | Définition |
|---|---|
| Volume de transactions (`volume_transactions`) | `COUNT(*)` des transactions réussies sur la période |
| Valeur transférée (`valeur_transferee`) | `SUM(montant_xof)` des transactions réussies, tous types, filtrable par `type` |
| Revenus de frais (`revenus_frais`) | `SUM(frais_xof)` des transactions réussies |
| Clients actifs (`clients_actifs`) | Clients distincts avec **au moins une transaction réussie dans la période**. Sans période explicite : les **30 derniers jours finissant à `REFERENCE_DATE`** |
| Agents actifs (`agents_actifs`) | Idem avec `agent_id` ≠ −1 ; différent de `statut_agent` |
| Taux d'échec (`taux_echec`) | échouées / (réussies + échouées) sur la période |

Dimensions certifiées : `region_agent`, `region_client`, `type`, `segment`, `agent` (classement hors « Hors agent »). Grains : jour, semaine, mois, trimestre. Comparaisons : période précédente, même période de l'année précédente.

Tables applicatives (schéma `app`, 8 tables) : `conversation`, `message`, `query_log`, `feedback`, `eval_run`, `eval_result`, `audit_access_log`, `analysis`. Plus de `change_request` (PR Git). Détail et droits : [SYSTEM_DESIGN §3](docs/SYSTEM_DESIGN.md#3-base-de-données).

## 8. Serveur MCP

Sous-processus stdio de l'API (SDK `mcp` v2, classe `MCPServer`), lancé par `python -m decision_mcp_server`. Il reçoit seulement `AGENT_RO_DSN`, `SEMANTIC_DIR`, `REFERENCE_DATE` et `PATH`. Il écrit ses journaux en JSON sur stderr ; **l'API écrit `query_log`**.

| Outil | Rôle | Entrée | Priorité |
|---|---|---|---|
| `query_metric` | **Chemin certifié** : compile métriques × dimensions × filtres × comparaison × grain depuis `kpis.yaml` en un SELECT paramétré. Une dimension non supportée renvoie une erreur actionnable (dimensions valides, définition canonique) | `QueryMetricParams` | **Must** |
| `run_query` | SELECT libre passé par le garde SQL ; réponse étiquetée « calcul ad hoc » ; `declared_scope` comparé à l'AST | `{sql, purpose, declared_scope: {statut, region_kind}}` | **Must** |
| `describe_schema` | Métadonnées normalisées de `analytics` (tables, colonnes, valeurs énumérées) | `{table \| null}` | Must |

`list_tables` et `describe_table` sont retirés (le schéma est dans le contexte). `get_kpi` n'existe plus : le tableau de bord appelle `query_metric`.

**Contrat de retour unique** (`ToolResult`, renvoyé en `structuredContent` et en texte JSON) : `tool`, `ok`, **`sql`** (réécrit depuis l'AST, seule version exécutée), `columns` (nom, type, rôle, unité, libellé), `rows` (≤ 1 000), `row_count`, `truncated`, `duration_ms`, `certified`, `params` (paramètres compilés ou portée extraite), `tables`, `warnings`, `error` (`error_class` ∈ {`guard_blocked`, `semantic_warning`, `invalid_params`, `sql_error`, `timeout`, `internal`}, `message`, `hint`), `payload` (`describe_schema`). Pour une comparaison, les lignes portent une colonne `periode` ∈ {`courante`, `comparaison`}.

Exécution : transaction `BEGIN READ ONLY` ; `statement_timeout` ≤ délai reçu ; lecture de 1 001 lignes pour `truncated` ; `EXPLAIN (FORMAT JSON)` borné par `sql.max_plan_cost` ; erreurs Postgres normalisées. Annulation : `notifications/cancelled` → `pg_cancel_backend`.

Garde SQL (liste blanche) : longueur et profondeur d'AST bornées avant analyse ; un seul SELECT ; liste blanche des **types de nœuds** sqlglot ; 5 tables `analytics.*` ; fonctions d'une liste fermée, **noms normalisés** (minuscules, sans guillemets, sans schéma) ; réécriture depuis l'AST ; `LIMIT` imposé. Règles de cohérence sémantique (statut, région client ou agent, agent actif, dénominateur du taux d'échec) renvoyées en avertissements actionnables. Détail : [SYSTEM_DESIGN §6](docs/SYSTEM_DESIGN.md#garde-sql-liste-blanche-serveur-mcp).

## 9. Agent IA

Voir [docs/AGENTIC_DESIGN.md](docs/AGENTIC_DESIGN.md). Un agent unique, boucle manuelle bornée (6 appels LLM, 8 appels d'outils, 2 corrections SQL par requête, 30 s) ; `tool_choice: auto` et outils `strict` ; trois outils terminaux (`submit_answer`, `ask_clarification`, `refuse`) utilisables à tout tour ; **citation des nombres par référence** (`{{f3}}`, `{{d1}}`) rendue par le code ; validateur avec filet de littéraux en français et repli par réponse gabarit ; état résolu produit par le code. **Mode analyse** (tableau de bord) : workflow sans outil pour le modèle.

Règles : ne jamais inventer un chiffre absent des faits ; signaler résultats vides ou tronqués ; ne jamais exécuter de requête de modification ; **ne jamais présenter une cause comme établie quand elle est seulement une hypothèse**.

## 10. Sécurité et gouvernance

1. **Keycloak 26.x** : client public `decision-web`, Authorization Code + PKCE (S256), jeton d'accès de 5 min en mémoire. **Audience mapper** « Included Custom Audience » = `decision-api`. Rôles lus dans `resource_access["decision-web"].roles`. MFA obligatoire pour analyste et admin. Détection de force brute (verrouillage temporaire, messages neutres). **Enregistrement des événements** de connexion et d'administration activé (les échecs d'authentification vivent dans Keycloak, pas dans `query_log`). Mode production derrière le proxy (`hostname`, `proxy-headers=xforwarded`), base `keycloak` dédiée, SMTP par Mailpit en développement.
2. **Proxy Caddy de même origine** : TLS (certificat interne en local), `/` SPA, `/api` API, `/auth` Keycloak ; plus de CORS ; CSP stricte, HSTS.
3. **API** : vérifie `iss`, `aud`, `exp`, `nbf`, RS256 seulement, clé par `kid` ; filtre `user_id = sub` ; 404 sur la ressource d'autrui ; routes `/api/admin/*` réservées aux rôles autorisés, vérifiées côté serveur ; quotas calculés dans Postgres ; jeton en en-tête `Authorization`.
4. **Serveur MCP / garde SQL** : section 8.
5. **Postgres** : rôles `dbt_owner` (propriétaire de `raw` et `analytics`), `app_owner` (propriétaire de `app`, migrations), `app_rw` (API : DML minimal, journaux en ajout seul), `agent_ro_base`/`agent_ro` (lecture de `analytics`, durci, `CONNECTION LIMIT 8`), `keycloak` (base `keycloak`). Scripts : `infra/postgres/init/` ; droits par table posés par migration.
6. **Back-office** : en lecture ; l'administrateur ne lit pas les conversations ; le journal d'audit n'affiche pas le texte des questions (condensat) ; la consultation du détail est journalisée (`audit_access_log`) ; le texte d'une question n'est visible que dans un signalement, avec le consentement de l'utilisateur.
7. **Configuration** : modifiée par PR Git (ENF11). L'API ne détient aucun identifiant Git en écriture.

Autres exigences : résultats d'outils injectés comme données non fiables ; noms d'agents et de villes remplacés par des **étiquettes opaques** côté modèle ; rendu en texte brut ou Markdown assaini ; erreurs Postgres normalisées (noms internes à `analytics` autorisés, le reste masqué) ; rétention du journal 90 jours ; `query_log.user_id` pseudonymisé (HMAC-SHA256 du `sub`, clé secrète) ; realm sans secret ni compte à mot de passe fixe.

## 11. Évaluation et critères d'acceptation

| Jeu | Taille | Usage |
|---|---|---|
| `test` | 40, écrites à la main, figées par hash avant P1 | **Seul chiffre d'acceptation (O1)**. Une exécution prévue par jalon, **5 au maximum**, journalisées dans `eval_run` ; jamais alimenté par les signalements |
| `dev` | ~40 | Itérations sur prompts et exemples, comparatif de modèles ; reçoit les signalements promus |
| `intent` | ~60 : 30 réponses, 15 clarifications, 15 refus (dont 5 injections) | Matrice de confusion de l'intention, faux refus ; s'arrête au premier outil terminal ou de données |
| `followup` | ~12 scripts multi-tours | RF5 et RF14 : (A) historique écrit à l'avance, (B) bout en bout, (C) clarification puis réponse courte scriptée |
| `security` | ≥ 25 payloads SQL nommés (dont différentiels : guillemets, commentaires, `E'\''`, `$$`, préfixe `pg_catalog.`) + 5 injections indirectes (`dim_agent.nom` empoisonné, base dédiée) | O3 |
| `regression` | Questions dev et test réussies 3/3 de façon stable | CI, à chaque modification de prompt ou de couche sémantique |
| `analysis` | 12 cas + 4 cas limites | RF17 |

| Catégorie (test) | Nombre |
|---|---|
| KPI simple | 8 |
| Comparaison de périodes | 6 |
| Classement | 6 |
| Clients et agents | 4 |
| Ambiguë ou hors périmètre (dont tentatives d'écriture ou d'injection) | 6 |
| Suivi de conversation | 4 |
| Pièges du glossaire (région client/agent, hors agent, résultat vide, jour férié, dénominateur du taux d'échec) | 6 |

Règles :
- Comparateur `compare.py` (testé) : résultat exécuté (colonnes projetées par type, multi-ensemble, ordre exigé seulement pour un classement, ex æquo acceptés), **faits cités comparés sur le registre structuré**, période et périmètre comparés sur `resolved_state`, intention = outil terminal attendu. Entiers exacts, ratios à 10⁻⁴ relatif.
- SQL de référence relus par une seconde personne et recalculés depuis les données seedées.
- Anti-fuite par SQL normalisé entre `examples.yaml` et `test`.
- 3 passes, sans cache de réponses ni de SQL ; `fallbacks` désactivé ; une exécution relancée est marquée.

| Métrique | Définition | Intervalle |
|---|---|---|
| **pass^3** (référence) | Part des questions réussies aux 3 passes | Wilson 95 % sur n questions |
| pass@1 (cible O1) | Moyenne des taux de réussite par question | Bootstrap groupé par question |
| Cohérence | Distribution 3/3, 2/3, 1/3, 0/3 | Comptes bruts |
| Questions KPI | pass^3 = 100 % exigé sur la catégorie | Comptes bruts |
| Ablations | Différence **appariée** sur les mêmes questions | McNemar exact ; **descriptives** (puissance de 43 % pour Δ = 15 pts à n = 40) |
| Intention | Matrice de confusion, faux refus | Wilson ; borne haute ≥ 11 % même à 0 erreur sur 30 cas, à dire |
| Couverture certifiée | Part résolue par `query_metric` ; « certifiable mais `run_query` utilisé » | Comptes |
| Validateur | Taux de rejet, de réponse gabarit, faux rejets | Comptes |
| Latence | p50, p90, max par banc HTTP (O2) et agent seul | p90 sur ≤ 200 observations annoncé indicatif |
| Coût | Jetons par type, coût par question et par question réussie | — |

**Liste unique d'ablations** : (a) modèle seul + schéma brut ; (b) sans exemples ; (c) sans `query_metric` (SQL seul) ; (d) sans validateur ; (e) sans citation par référence (le modèle écrit les nombres, le validateur les extrait).

**Évaluation de l'analyse (RF17)** : stabilité de la sélection des constats (même ensemble de candidats sur 3 passes, pass^3) ; 100 % des nombres tracés ; 0 cause sans étiquette « hypothèse » ; pertinence jugée par un humain sur un échantillon (juge LLM optionnel, seulement après calibration, jamais pour O1).

Traçabilité de chaque exécution : modèle demandé et servi, effort, hash du prompt, des schémas d'outils, de la couche sémantique et des exemples, SHA git, `data_hash`, `REFERENCE_DATE`. Pas de température.

Le back-office d'évaluation (RF19) affiche : pass^3 et pass@1 avec intervalles, phrase honnête si la cible n'est pas démontrée, comptes bruts par catégorie, cohérence, matrice d'intention, ablations, latence, coût, historique et échecs détaillés.

Acceptation : O1 à O4 atteints, tests dbt verts, tests de sécurité verts, audit d'accessibilité sans point bloquant.

## 12. Phases et livrables

| Phase | Contenu | Point de contrôle | Estimation |
|---|---|---|---|
| **P0 Fondations** | Retrait des squelettes (commit séparé) ; espace de travail uv ; compose (Postgres, Keycloak, Caddy, Mailpit) ; init des rôles ; générateur ; dbt et tests (dont tests unitaires des 6 KPI et test de droits `agent_ro`) ; couche sémantique initiale ; jeux `test` (hash figé), `dev`, `intent` ; `compare.py` testé | `make seed` vert, références recalculées, hash du test figé | 12-15 j |
| **P1 Tranche verticale** | `sql_guard` et payloads ; `MCPServer` (`query_metric`, `run_query`, `describe_schema`) ; `LLMClient`, `AnthropicClient`, `ReplayClient` ; boucle avec outils terminaux ; registre de faits et validateur ; formateur ; `make eval` ; banc de latence ; comparatif Sonnet / Opus / Haiku sur le dev ; choix du modèle | Première évaluation : pass^3 avec Wilson, ablations, latence, coût. **Jalon bloquant avant toute interface** | 18-22 j |
| **P2 Produit** | API (JWT, conversations, flux POST + SSE, quota, `query_log`) ; realm et Audience mapper ; thème de connexion ; SPA (accueil, conversation, graphiques, chaîne de preuve, SQL pour l'analyste, historique, responsive) | Parcours connexion → question → graphique en e2e, axe-core vert | 15-18 j |
| **P3 Pilotage** | Tableau de bord (RF4) et analyse en workflow (RF17) avec son évaluation ; back-office en lecture : exploitation et sécurité, audit avec `audit_access_log`, évaluation, configuration ; signalements | O1 à O3 mesurés et visibles dans le back-office | 10-12 j |
| **P4 Finition** | Audit WCAG 2.2 AA ; campagne d'évaluation finale ; documents et ADR ; rapports | Acceptation | 5-8 j |
| P5 (Could) | PDF, Snowflake, éditeurs du back-office v4 | Selon le temps | — |

Total MVP : environ 60-75 jours-personne hors rédaction.

## 13. Risques

| Risque | Effet | Mesure |
|---|---|---|
| Dérive du périmètre (interface, Keycloak) avant l'évaluation | Retard sur le cœur du mémoire | MVP ; P1 jalon bloquant avant toute interface ; back-office en lecture |
| SQL faux mais plausible | Décision sur un mauvais chiffre | `query_metric` en priorité, règles de cohérence sémantique, mention « calcul ad hoc », SQL visible à l'analyste, ablation (c) |
| Nombre mal recopié ou inventé | Chiffre faux affiché | Citation par référence, rendu par le code, filet de littéraux, réponse gabarit ; ablation (e) |
| Non-reproductibilité (pas de température, réflexion adaptative) | Résultats variables | Modèle et effort figés, hashes, 3 passes, pass^3 publié, `fallbacks` désactivé en évaluation |
| Latence > 15 s en médiane | O2 manqué | Faits par référence (sortie courte), cache de prompt préchauffé, effort `medium` ou `low`, appels parallèles, mesure par étape ; challengers mesurés en P1 |
| Changement d'API du fournisseur | 400 en production | SDK `anthropic>=2.3,<3` épinglé, test d'intégration quotidien, aucun paramètre retiré |
| Refus du classificateur du modèle (`stop_reason: refusal`) | Refus inattendu, évaluation bruitée | Traité comme mode de défaillance distinct, compté à part |
| Analyse du tableau de bord qui affirme des causes | Fausse certitude | Workflow sans outil, candidats et confiance calculés par le code, marqueurs causaux rejetés hors « hypothèse » |
| Évaluation trop petite | Seuil non démontré | Test seul, pass^3 avec Wilson, ablations descriptives, variantes si le temps le permet |
| Fuite exemples → test, ou signalements → test | Score gonflé | SQL normalisé, hash figé, signalements vers le dev uniquement, au plus 5 exécutions du test par jalon |
| Contournement du garde (différentiel de parseur, noms de fonctions) | Lecture de fichiers, DoS | Liste blanche des types de nœuds, noms normalisés, bornes de longueur et de profondeur, `READ ONLY`, rôle durci, payloads dédiés |
| Injection indirecte via les données | Réponse fausse | Étiquettes opaques, données marquées non fiables, 50 lignes max, rendu assaini, validateur ; 5 cas dans le jeu de sécurité |
| Droits `agent_ro` perdus après `dbt run` | Agent sans accès | Schémas possédés par `dbt_owner`, `ALTER DEFAULT PRIVILEGES`, test de droits après chaque `dbt build` et dans RF20 |
| Keycloak en mode production (TLS, nom d'hôte, base, SMTP) | Temps perdu | Proxy Caddy dès P0, versions figées, realm versionné, Mailpit |
| Sous-processus MCP mort ou bloqué | Questions en échec | Redémarrage automatique (1 fois), délai d'appel, santé dans RF20 |
| Données envoyées à un LLM externe | Non conforme si données réelles | Données synthétiques seulement ; pas de texte libre de la base ; revue obligatoire avant bascule (région d'inférence, ZDR) |
| Coût du LLM | Budget dépassé | Plafond par question, quota, limites de dépenses par workspace, alerte sur le taux de cache |

## 14. Journal des changements

**v1 → v2** : O4 redéfini ; garde SQL par parseur ; ENF2 reformulé ; `REFERENCE_DATE` ; glossaire région ; jeux dev/test séparés ; RF8 en Must ; RF11 délégué à Keycloak ; pipeline allégé.

**v2 → v3 (relecture croisée)** : `query_log` écrit par l'API ; MCP en sous-processus ; cache SQL supprimé ; `get_kpi` en Must ; SQL filtré côté serveur ; garde SQL en liste blanche ; rôles Postgres explicites ; modèle de données corrigé ; évaluation avec intervalle de Wilson, 40 questions, ablations ; sécurité JWT complète.

**v3 → v4 (maquette complète et back-office)** : back-office complet (13 écrans) ; authentification complète (RF15, RF16) ; analyse du tableau de bord (RF17) ; RF10 en Should ; WCAG 2.2 AA ; ENF11 et ENF12 (45 écrans) ; demandes de changement.

**v4 → v5 (évaluation du 2026-10-24, MVP retenu)** :
1. **Périmètre MVP** (EVALUATION_V5 §6) : back-office en lecture ; configuration par PR Git (RF9, RF12, RF18, ENF11) ; utilisateurs dans la console Keycloak (RF11) ; RF16 réduit, A06 supprimé ; RF19 lancé en CLI ; RF10 à 3 états ; RF20 en une vue ; 22 écrans (ENF12) ; O4 = Must + Should du MVP.
2. **O1** mesuré sur le test seul : pass@1 ≥ 80 %, pass^3 de référence avec Wilson. **O2** : « sans cache de réponses ni de SQL », cache de prompt autorisé, banc HTTP.
3. **ENF2** sans température : modèle et effort figés, sortie structurée, 3 passes, stabilité mesurée.
4. **MCP** : `query_metric` remplace `get_kpi` ; `describe_schema` remplace `list_tables` et `describe_table` ; contrat `ToolResult` unique avec `sql` réécrit.
5. **Agent** : outils terminaux, citation par référence, validateur et réponse gabarit, état résolu produit par le code, politique par champ, analyse en workflow.
6. **Sécurité** : proxy Caddy de même origine, Audience mapper, avertissement sur la session SSO (ENF10), événements Keycloak, rôle `app_owner`, base `keycloak`, `BEGIN READ ONLY`, garde renforcé, étiquettes opaques, pseudonymisation HMAC.
7. **Données** : valeurs ASCII (`reussie`, `depot`…) ; définition de « clients actifs » tranchée ; Postgres 17.
8. **Évaluation** : jeux `intent`, `followup`, `security` (avec injections indirectes), `regression` ; McNemar ; liste unique d'ablations (a)-(e) ; 5 exécutions max du test par jalon.
9. **Phases** P0-P4 recalées sur EVALUATION_V5 §7 ; P1 bloquant avant toute interface.
10. Table `change_request` supprimée ; `query_log` enrichi des champs LLM.

## 15. Décisions ouvertes

| N° | Question | Proposition | Échéance |
|---|---|---|---|
| Q-a | Modèle final de l'agent | `claude-sonnet-5-5` (`medium`) par défaut ; Opus 5.5 (`low`) et Haiku 5.5 mesurés sur le dev | Fin de P1 |
| Q-b | Effort `low` contre `medium` | Garder `medium` sauf gain de latence sans perte de pass^3 | Fin de P1 |
| Q-c | Agrandir le test (60-80 avec variantes groupées par famille) | Seulement si le temps de rédaction le permet ; jamais après le premier passage | Avant le gel du hash |
| Q-d | Mémoïsation de l'analyse du tableau de bord par `data_hash` | Non au MVP (une ligne `analysis` par génération) ; à réévaluer si la latence de RF4 gêne | P3 |
| Q-e | Juge LLM pour 2 attributs textuels (pertinence, causalité) | Optionnel, après calibration (≥ 30 annotations, kappa ≥ 0,7), jamais pour O1 | P3 |
| Q-f | SSO d'entreprise par courtage d'un fournisseur externe | Hors MVP ; Keycloak seul | — |
| Q-g | Nom du dossier de la SPA : migrer `frontend/` (Next.js) vers Vite sous `web/` ou garder `frontend/` | Vite (bulletproof-react `react-vite`) ; nom à fixer au début de P2 | Début de P2 |
| Q-h | SMTP de production (Mailpit en développement) | Hors MVP ; documenté | P4 |
