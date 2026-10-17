# Spécification — Agent conversationnel d'aide à la décision (Wave)

Version 4 · back-office complet, authentification, analyse du tableau de bord · 2026-10-17

> Documents liés : [docs/SYSTEM_DESIGN.md](docs/SYSTEM_DESIGN.md), [docs/AGENTIC_DESIGN.md](docs/AGENTIC_DESIGN.md), [docs/DESIGN_SYSTEM.md](docs/DESIGN_SYSTEM.md), [docs/FEATURES_RESOURCES.md](docs/FEATURES_RESOURCES.md).
> Maquette de référence : 45 écrans interactifs (authentification, application, mobile, back-office), listés dans FEATURES_RESOURCES. L'historique des changements est en section 14.

## 1. Contexte et objectifs

Un décideur de Wave Sénégal interroge en langage naturel un data warehouse et obtient des réponses chiffrées, des graphiques et des rapports, sans passer par un analyste. Un back-office permet de gouverner l'agent : utilisateurs, catalogue de KPI, couche sémantique, paramètres, évaluation, sécurité et audit.

Hypothèse : obtenir un indicateur non prévu dans un tableau de bord suppose aujourd'hui de solliciter un analyste, ce qui ralentit la décision.

| Réf. | Objectif | Mesure |
|---|---|---|
| O1 | Justesse | Point estimé ≥ 80 % sur l'ensemble dev + test, **intervalle de Wilson à 95 % publié** ; comptes bruts par catégorie. Avec 40 questions de test, 32/40 donne un intervalle d'environ [65 %, 90 %] : la limite est assumée dans le mémoire |
| O2 | Rapidité | Latence médiane < 15 s, p90 < 30 s, mesurées de bout en bout par l'API, sans cache |
| O3 | Sûreté | 0 écriture exécutée ; 100 % des payloads hostiles du jeu de sécurité rejetés (section 10) |
| O4 | Couverture | Tous les RF « Must » et « Should » (section 4) réalisés |

## 2. Périmètre

Inclus
- Données synthétiques (Python) vers un schéma brut, puis dbt vers un modèle en étoile.
- Serveur MCP en lecture seule (sous-processus de l'API) et agent IA avec appel d'outils.
- Application web React : accueil, conversation, historique, tableau de bord avec analyse de l'agent, version mobile.
- **Authentification complète via Keycloak**, avec pages au thème du produit.
- **Back-office** : vue d'ensemble, utilisateurs et rôles, catalogue de KPI, couche sémantique, journal d'audit, sécurité, évaluation, signalements, paramètres.
- Évaluation de l'agent (jeux dev et test, ablations).

Exclu
- Données réelles de Wave et toute donnée personnelle réelle.
- Écriture dans l'entrepôt par l'agent. Temps réel. Application mobile native.
- Orchestration multi-agents, RAG, cache SQL (voir AGENTIC_DESIGN).

Reporté (Could)
- Cible Snowflake (second target dbt ; la portabilité concerne dbt, pas le SQL ni les prompts de l'agent).
- Export PDF.

Hypothèses
- Données synthétiques. Le LLM est un service externe qui reçoit les questions et les résultats de requêtes ; ce flux est documenté et devra être revu avant toute bascule vers des données réelles.
- `REFERENCE_DATE` (configurable) tient lieu de « aujourd'hui » pour des tests reproductibles.

## 3. Acteurs et rôles

| Acteur | Rôle Keycloak | Droits principaux |
|---|---|---|
| Décideur | `decideur` | Interroger l'agent, tableau de bord et analyse, historique personnel, signaler une réponse ; voit tables, période et périmètre, **pas le SQL** |
| Analyste | `analyste` | Tout ce que fait le décideur, plus SQL et tables utilisées ; back-office restreint : catalogue de KPI, couche sémantique, journal d'audit technique, évaluation, signalements |
| Administrateur | `admin` | Back-office complet, y compris utilisateurs, sécurité et paramètres ; aucun accès aux conversations d'autrui |
| Data warehouse | — | Lecture seule via le rôle Postgres `agent_ro` |

Décision ouverte : la maquette montre le back-office vu par l'administrateur ; la variante restreinte de l'analyste (navigation filtrée) reste à dessiner.

## 4. Exigences fonctionnelles

| Réf. | Acteur | Exigence | Priorité |
|---|---|---|---|
| RF1 | Décideur | Poser une question en langage naturel, en français | **Must** |
| RF2 | Décideur | Réponse chiffrée rappelant période et périmètre | **Must** |
| RF14 | Tous | Précision demandée si ambigu ; refus motivé si hors périmètre | **Must** |
| RF8 | Analyste | Afficher le SQL généré et les tables utilisées | **Must** |
| RF3 | Décideur | Graphique adapté (courbe, barres, répartition, tableau, chiffre clé) | **Must** |
| RF15 | Tous | Se connecter : SSO ou e-mail et mot de passe, vérification en deux étapes, session expirée, déconnexion | **Must** |
| RF5 | Décideur | Question de suivi tenant compte de l'échange | Should |
| RF6 | Décideur | Consulter et relancer l'historique | Should |
| RF4 | Décideur | Tableau de bord des KPI clés (via `get_kpi`), par période et région | Should |
| RF17 | Décideur | Analyse automatique du tableau de bord par l'agent de données : constats sourcés, niveau de confiance, hypothèses étiquetées, questions d'approfondissement | Should |
| RF16 | Tous | Récupérer son accès : mot de passe oublié, réinitialisation, première connexion, compte verrouillé | Should |
| RF10 | Tous | Signaler une réponse incorrecte | Should |
| RF13 | Analyste, admin | Journal d'audit technique des appels d'outils, avec détail par appel ; la consultation du journal est elle-même journalisée | Should |
| RF11 | Admin | Gérer utilisateurs et rôles (invitation, rôle, MFA, sessions, désactivation), synchronisés avec Keycloak | Should |
| RF9 | Analyste, admin | Gérer le catalogue de KPI : éditeur, validations, soumission pour revue | Should |
| RF18 | Analyste, admin | Faire évoluer la couche sémantique : tables, glossaire, exemples, contrôle anti-fuite | Should |
| RF12 | Admin | Paramétrer le système, avec aperçu des changements et revue avant application | Should |
| RF19 | Analyste, admin | Piloter l'évaluation : scores, comptes bruts, ablations, historique, lancement limité | Should |
| RF20 | Admin | Surveiller l'exploitation (santé, coûts, latence) et la sécurité (blocages du garde SQL, test de droits, sessions) | Should |
| RF7 | Décideur | Exporter un rapport PDF | Could |

Changements par rapport à la v3 : RF11, RF12, RF9 passent de « délégué » ou « fichier » à des écrans du back-office, avec revue ; RF10 passe de Could à Should ; RF15 à RF20 sont nouveaux.

## 5. Exigences non fonctionnelles

| Réf. | Catégorie | Exigence | Critère de vérification |
|---|---|---|---|
| ENF1 | Performance | Réponse rapide | Médiane < 15 s, p90 < 30 s ; budget 30 s par question ; `statement_timeout` 10 s |
| ENF2 | Fiabilité | Réponses justes et stables | Température 0 ; 3 passes en évaluation ; questions KPI à 3/3 ; **pas de cache SQL** |
| ENF3 | Sécurité | Aucune écriture, aucun accès hors `analytics` | Garde SQL par liste blanche + rôle `agent_ro` durci ; ≥ 25 payloads hostiles |
| ENF4 | Sécurité | Secrets hors du code | `.env` non versionné, secrets Docker, masquage dans les journaux, scan en pré-commit et CI |
| ENF5 | Traçabilité | Chaque appel d'outil tracé | `app.query_log` écrit par l'API seule ; versions de prompt, de couche sémantique, de modèle |
| ENF6 | Transparence | Chiffres explicables | Analyste : SQL et tables ; décideur : chaîne de preuve (table, filtre, période, opération), sans SQL ; filtrage côté serveur |
| ENF7 | Accessibilité | **WCAG 2.2 AA** sur toutes les pages | Navigation clavier complète ; focus géré dans tiroirs et dialogues ; contrastes mesurés dans les deux thèmes ; mouvement réduit respecté ; audit par agent d'accessibilité avant chaque jalon |
| ENF8 | Maintenabilité | Pipeline reproductible | Tests dbt verts ; `docker compose up` ; README par composant |
| ENF9 | Coût | Consommation maîtrisée | 1 000 lignes max, rejet des plans coûteux, quota par utilisateur, budget de coût par question après la première mesure |
| ENF10 | Authentification | Session sûre | Jeton d'accès 5 min ; avertissement 20 s avant expiration avec prolongation ; verrouillage 15 min après 3 échecs ; MFA obligatoire pour analyste et admin ; aucun minuteur automatique sans moyen de l'arrêter |
| ENF11 | Gouvernance | Tout changement de configuration est relu | KPI, couche sémantique et paramètres passent par une demande de changement (diff affiché, relecteur différent de l'auteur) ; aucun changement direct en production |
| ENF12 | Ergonomie | Interface claire en français, responsive | Question → graphique en ≤ 3 clics ; utilisable de 320 à 1440 px ; 45 écrans de référence couverts |

## 6. Architecture

Voir [docs/SYSTEM_DESIGN.md](docs/SYSTEM_DESIGN.md). Générateur → Postgres (`raw`, `analytics`, `app`) via dbt ; API FastAPI qui lance le serveur MCP en sous-processus (stdio) et héberge l'agent ; application React avec routes utilisateur et routes `/admin` ; Keycloak pour l'identité (pages d'authentification au thème du produit, API d'administration pour le back-office). L'agent n'accède aux données que par le serveur MCP.

## 7. Modèle de données

Étoile : un fait, quatre dimensions. XOF sans décimales ; montants en `numeric`, jamais `float`.

| Table | Grain | Colonnes principales |
|---|---|---|
| `fact_transaction` | une transaction | `transaction_id` bigint, `client_id`, `agent_id` **NOT NULL** (membre « Hors agent » = −1), `region_client_id`, `region_agent_id`, `date_id` (int AAAAMMJJ), `txn_ts` timestamptz, `type` (dépôt, retrait, transfert, paiement), `montant_xof` numeric(14,0) > 0, `frais_xof` numeric(12,0) ≥ 0 et ≤ montant, `statut` (réussie, échouée ; CHECK) |
| `dim_client` | un client | `client_id`, `date_inscription`, `region_client_id`, `segment` |
| `dim_agent` | un point de service | `agent_id`, `nom`, `ville`, `region_agent_id`, `date_activation`, `statut_agent` (ouvert/fermé) ; ligne −1 « Hors agent » |
| `dim_region` | une région | `region_id`, `region`, `pays` |
| `dim_date` | un jour | `date_id`, `date`, `jour_semaine`, `semaine_iso`, `mois`, `nom_mois`, `trimestre`, `annee`, `est_weekend`, `jour_ferie`, `debut_mois`, `fin_mois` |

SCD1 acté. Transfert et paiement ont l'agent −1 (test dbt). Pas de destinataire dans le fait : limite documentée.

Glossaire (source unique : `agent/semantic/glossary.yaml`, éditable via le back-office par demande de changement) :
- « région » seule est ambiguë : l'agent précise `region_agent` ou `region_client` ; défaut `region_agent` pour agents et frais, `region_client` pour clients.
- « agent actif » (≥ 1 transaction réussie) ≠ `statut_agent`.
- « aujourd'hui » = `REFERENCE_DATE`.

**KPI** (source unique : `agent/semantic/kpis.yaml` ; le tableau ci-dessous en est dérivé) :

| KPI | Définition |
|---|---|
| Volume de transactions | `COUNT(*)` des transactions réussies sur la période |
| Valeur transférée | `SUM(montant_xof)` des transactions réussies, tous types, filtrable par `type` |
| Revenus de frais | `SUM(frais_xof)` des transactions réussies |
| Clients actifs | `COUNT(DISTINCT client_id)` avec ≥ 1 transaction réussie sur `]as_of − N jours, as_of]`, N = 30 par défaut |
| Agents actifs | Idem avec `agent_id` ≠ −1 |
| Taux d'échec | échouées / (réussies + échouées) sur la période |

Tables applicatives (`app`) : `conversation`, `message`, `query_log`, **`feedback`**, **`change_request`**, **`eval_run`**, **`eval_result`**, **`audit_access_log`**, **`analysis`** (voir SYSTEM_DESIGN §3).

## 8. Serveur MCP

Sous-processus stdio de l'API. Il renvoie `(sql, lignes, durée, truncated)` et écrit des journaux JSON ; **l'API écrit `query_log`**.

| Outil | Rôle | Priorité |
|---|---|---|
| `get_kpi` | KPI défini dans `kpis.yaml` ; paramètres liés, typés, validés par énumération ; **seul outil utilisé par l'analyse du tableau de bord** | **Must** |
| `list_tables`, `describe_table` | Schéma de `analytics` uniquement ; métadonnées normalisées | Must |
| `run_query` | SELECT généré ; passe par le garde SQL | Must |

Garde SQL (liste blanche) : AST complet y compris CTE ; 5 tables `analytics.*` ; fonctions d'une liste fermée ; réécriture du SQL depuis l'AST validé ; `LIMIT` imposé (1 001 en interne) ; plan `EXPLAIN` borné.

## 9. Agent IA

Voir [docs/AGENTIC_DESIGN.md](docs/AGENTIC_DESIGN.md). Un agent à boucle d'outils ; intention en premier tour ; couche sémantique versionnée ; 2 corrections SQL ; sortie structurée validée ; graphique calculé par le code. **Mode analyse** (tableau de bord) : l'agent n'utilise que `get_kpi`, produit des constats avec source et niveau de confiance, et étiquette les hypothèses.

Règles : ne jamais inventer un chiffre absent des résultats ; signaler résultats vides ou incomplets ; ne jamais exécuter de requête de modification ; **ne jamais présenter une cause comme établie quand elle est seulement une hypothèse**.

## 10. Sécurité et gouvernance

1. **Keycloak** : client public, Authorization Code + PKCE, jeton d'accès de 5 min en mémoire, MFA obligatoire pour analyste et admin, verrouillage après 3 échecs. L'API vérifie `iss`, `aud`, `exp`, `nbf`, algorithme RS256, clé par `kid`, rôles du seul client attendu.
2. **API** : filtre `user_id = sub` ; 404 sur la conversation d'autrui ; routes `/admin` réservées aux rôles autorisés, vérifiées côté serveur ; actions sensibles du back-office (désactiver un compte, réinitialiser la MFA, révoquer une session) avec ré-authentification récente ; quotas ; CORS en liste blanche ; jeton en en-tête.
3. **Serveur MCP / garde SQL** : voir section 8.
4. **Postgres** : trois rôles (`dbt_owner`, `app_rw`, `agent_ro`), `agent_ro` durci ; journal en ajout seul.
5. **Back-office** : l'administrateur ne lit pas les conversations ; le journal d'audit n'affiche pas le texte des questions (condensat seulement) ; la **consultation du journal est elle-même journalisée** (`audit_access_log`) ; le texte d'une question n'est visible que dans un signalement, avec le consentement de l'utilisateur.
6. **Changements de configuration** : toute modification de KPI, de couche sémantique ou de paramètre produit une `change_request` avec diff ; l'auteur ne peut pas la valider ; l'application se fait par commit sur les fichiers versionnés.

Autres exigences : résultats d'outils injectés comme données non fiables ; rendu en texte brut ou Markdown assaini ; erreurs Postgres normalisées ; rétention du journal 90 jours, `user_id` pseudonymisé ; Keycloak en mode production, realm sans secret ni compte à mot de passe fixe.

## 11. Évaluation et critères d'acceptation

| Jeu | Taille | Usage |
|---|---|---|
| Dev | ~30 | Itérations sur prompts et exemples ; calibration de l'intention ; reçoit les signalements validés |
| Test | 40 | Une exécution par jalon, au plus 5 par jalon, journalisées dans `eval_run` ; jamais alimenté par les signalements |

| Catégorie | Nombre (test) |
|---|---|
| KPI simple | 8 |
| Comparaison de périodes | 6 |
| Classement | 6 |
| Clients et agents | 4 |
| Ambiguë ou hors périmètre (dont tentatives d'écriture ou d'injection) | 6 |
| Suivi de conversation | 4 |
| Pièges du glossaire (région client/agent, hors agent, résultat vide, jour férié, dénominateur du taux d'échec) | 6 |

Règles inchangées : jeu de test écrit avant l'agent, hash figé ; comparateur `eval/compare.py` (résultat exécuté **et** chiffre cité, période et périmètre justes ; entiers exacts, ratios en tolérance relative 10⁻⁴) ; anti-fuite par SQL normalisé ; 3 passes sans cache ; ablations (sans couche sémantique, sans exemples, sans `get_kpi`, sans validateur) ; traçabilité complète des rapports.

Le **back-office d'évaluation** (RF19) affiche : score avec intervalle de Wilson et phrase honnête quand la cible n'est pas démontrée, comptes bruts par catégorie, cohérence 3/3·2/3·1/3, matrice de confusion de l'intention, ablations, latence, coût, historique et échecs détaillés.

**Évaluation de l'analyse du tableau de bord (RF17)** : 12 cas de dev (période × région) ; chaque nombre cité doit se retrouver dans les sorties de `get_kpi` ou être un dérivé calculé par le code (taux de constats vérifiables = 100 % exigé) ; toute cause avancée doit porter l'étiquette « hypothèse » ; le niveau de confiance suit les règles de AGENTIC §14.

Acceptation : O1 à O4 atteints, tests dbt verts, tests de sécurité verts, audit d'accessibilité sans point bloquant.

## 12. Phases et livrables

| Phase | Contenu | Point de contrôle |
|---|---|---|
| P0 Fondations | Dépôt, compose (Postgres, Keycloak), rôles et droits, générateur, dbt + tests, jeux dev/test et comparateur | Tests dbt verts, références recalculées, hash figé |
| P1 Tranche verticale | MCP (`get_kpi`, `list_tables`, `describe_table`, `run_query`), garde SQL, agent (RF1, RF2, RF14, RF8), `make eval`, `query_log` | Première évaluation avec intervalle et ablations |
| P2 Produit | Interface React : accueil, conversation, graphiques (RF3), RF5, RF6, **authentification (RF15)**, version mobile | Parcours complet connexion → question → graphique |
| P3 Pilotage (lecture) | Tableau de bord (RF4) et **analyse de l'agent (RF17)**, back-office en lecture : vue d'ensemble, journal d'audit (RF13), évaluation (RF19), sécurité (RF20) | O1 à O3 mesurés et visibles dans le back-office |
| P4 Gouvernance (écriture) | Utilisateurs (RF11), catalogue de KPI (RF9), couche sémantique (RF18), paramètres (RF12), signalements (RF10), **récupération d'accès (RF16)**, demandes de changement | Un changement de KPI traverse la revue de bout en bout |
| P5 Extensions (Could) | PDF (RF7), cible Snowflake | Selon le temps |

## 13. Risques

| Risque | Effet | Mesure |
|---|---|---|
| SQL faux mais plausible | Décision sur un mauvais chiffre | `get_kpi` en priorité, couche sémantique, SQL visible à l'analyste, évaluation avec ablations |
| **Périmètre élargi (back-office de 13 écrans)** | Retard sur le cœur | Lecture avant écriture (P3 puis P4) ; P1 et P2 ne dépendent pas du back-office ; les écrans d'écriture passent par fichiers versionnés plutôt que par une base d'administration |
| **Analyse du tableau de bord qui affirme des causes** | Fausse certitude | Constats limités à `get_kpi`, étiquette « hypothèse », niveaux de confiance, évaluation dédiée |
| **Back-office comme cible d'attaque** | Prise de contrôle de la configuration | Rôles vérifiés côté serveur, ré-authentification pour actions sensibles, demandes de changement relues, accès au journal audité |
| Évaluation trop petite | Seuil non démontré | Intervalle de Wilson, agrégation dev + test, comptes bruts, exécutions du test limitées |
| Fuite exemples → test, ou signalements → test | Score gonflé | Contrôle SQL normalisé, hash figé, signalements vers le dev uniquement |
| `dbt run` supprime les droits de `agent_ro` | Agent sans accès | `ALTER DEFAULT PRIVILEGES` + test de droits (visible dans le back-office, RF20) |
| Contournement du garde SQL | Lecture de fichiers, DoS | Liste blanche d'AST et de fonctions, rôle durci, `EXPLAIN`, jeu de payloads |
| Injection indirecte via données | Réponse fausse ou fuite | Données encadrées, colonnes texte minimisées, rendu assaini, validateur de sortie |
| Complexité Keycloak (thème, pages, API d'administration) | Temps perdu | Realm versionné sans secret, un client public, un compte de service limité pour le back-office |
| Accessibilité des tiroirs et menus | Parcours clavier cassé | Patterns partagés (focus piégé, retour au déclencheur), audit avant chaque jalon |
| Coût ou latence du LLM | Lenteur, budget | Mesure par étape, préfixe de prompt stable, 2 corrections max |

## 14. Journal des changements

**v1 → v2** : O4 redéfini ; garde SQL par parseur ; ENF2 reformulé ; `REFERENCE_DATE` ; glossaire région ; jeux dev/test séparés ; RF8 en Must ; RF11 délégué à Keycloak ; pipeline allégé.

**v2 → v3 (relecture croisée)** : `query_log` écrit par l'API ; MCP en sous-processus ; cache SQL supprimé ; `get_kpi` en Must ; SQL filtré côté serveur ; garde SQL en liste blanche ; rôles Postgres explicites ; modèle de données corrigé ; évaluation avec intervalle de Wilson, 40 questions, ablations ; sécurité JWT complète.

**v3 → v4 (maquette complète et back-office)** :
1. Back-office complet retenu : 13 écrans, RF9, RF11, RF12, RF13 portés par des écrans, nouveaux RF18 à RF20.
2. Authentification complète (RF15, RF16) avec pages au thème du produit ; ENF10 (session, verrouillage, MFA, minuteurs).
3. Analyse du tableau de bord par l'agent de données (RF17) : mode analyse limité à `get_kpi`, hypothèses étiquetées, évaluation dédiée.
4. RF10 (signalement) promu en Should ; les signalements alimentent le jeu de dev, jamais le test.
5. ENF7 renforcé en WCAG 2.2 AA vérifié par audit ; ENF11 (toute configuration relue) ; ENF12 (45 écrans).
6. Sécurité : routes `/admin` vérifiées côté serveur, ré-authentification pour actions sensibles, consultation du journal journalisée, demandes de changement.
7. Phases : P2 inclut l'authentification ; P3 pilotage en lecture ; P4 gouvernance en écriture ; P5 extensions.
8. Décision ouverte : navigation restreinte du back-office pour l'analyste.
