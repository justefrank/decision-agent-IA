# Spécification — Agent conversationnel d'aide à la décision (Wave)

Version 3 · après relecture croisée (architecture, sécurité, base de données, évaluation) · 2026-10-17

> Documents liés : [docs/SYSTEM_DESIGN.md](docs/SYSTEM_DESIGN.md), [docs/AGENTIC_DESIGN.md](docs/AGENTIC_DESIGN.md), [docs/DESIGN_SYSTEM.md](docs/DESIGN_SYSTEM.md), [docs/FEATURES_RESOURCES.md](docs/FEATURES_RESOURCES.md).
> L'historique des changements est en section 14.

## 1. Contexte et objectifs

Un décideur de Wave Sénégal interroge en langage naturel un data warehouse et obtient des réponses chiffrées, des graphiques et des rapports, sans passer par un analyste.

Hypothèse : obtenir un indicateur non prévu dans un tableau de bord suppose aujourd'hui de solliciter un analyste, ce qui ralentit la décision.

| Réf. | Objectif | Mesure |
|---|---|---|
| O1 | Justesse | Point estimé ≥ 80 % sur l'ensemble dev + test, **intervalle de Wilson à 95 % publié** ; comptes bruts par catégorie. Avec 40 questions de test, 32/40 donne un intervalle d'environ [65 %, 90 %] : la limite est assumée dans le mémoire |
| O2 | Rapidité | Latence médiane < 15 s, p90 < 30 s, **mesurées de bout en bout par l'API, cache froid** |
| O3 | Sûreté | 0 écriture exécutée ; 100 % des payloads hostiles du jeu de sécurité rejetés (section 10) |
| O4 | Couverture | Tous les RF Must et Should réalisés |

## 2. Périmètre

Inclus
- Génération de données synthétiques (Python) vers un schéma brut, puis dbt vers un modèle en étoile.
- Serveur MCP en lecture seule (lancé en sous-processus de l'API) et agent IA avec appel d'outils.
- Interface web React et back-end FastAPI.
- Authentification et rôles via Keycloak.
- Évaluation de l'agent (jeux dev et test, comparaisons de référence).

Exclu
- Données réelles de Wave et toute donnée personnelle réelle.
- Écriture dans l'entrepôt par l'agent. Temps réel. Application mobile.
- Écrans d'administration sur mesure (console Keycloak).
- Orchestration multi-agents, RAG, cache SQL (voir AGENTIC_DESIGN).

Reporté (Could)
- Cible Snowflake (second target dbt ; la portabilité concerne dbt, pas le SQL ni les prompts de l'agent, propres à Postgres).
- Export PDF, signalement de réponse.

Hypothèses
- Données synthétiques, justifiées par la confidentialité. Le LLM est un service externe qui reçoit les questions et les résultats de requêtes ; ce flux est documenté et devra être revu avant toute bascule vers des données réelles.
- `REFERENCE_DATE` (configurable) tient lieu de « aujourd'hui » pour des tests reproductibles.

## 3. Acteurs et rôles

| Acteur | Rôle Keycloak | Droits principaux |
|---|---|---|
| Décideur | `decideur` | Interroger l'agent, consulter KPI et son historique ; voit tables, période et périmètre, **pas le SQL** |
| Analyste | `analyste` | Tout ce que fait le décideur, plus SQL et tables utilisées ; consulte le journal d'audit **technique** (sans texte des questions des autres) |
| Administrateur | `admin` Keycloak | Utilisateurs et rôles via la console Keycloak ; aucun accès aux conversations |
| Data warehouse | — | Lecture seule via le rôle Postgres `agent_ro` |

## 4. Exigences fonctionnelles

| Réf. | Acteur | Exigence | v1 | v3 |
|---|---|---|---|---|
| RF1 | Décideur | Question en langage naturel, en français | Haute | **Must** |
| RF2 | Décideur | Réponse chiffrée rappelant période et périmètre | Haute | **Must** |
| RF14 | Tous | Précision demandée si ambigu ; refus motivé si hors périmètre | Haute | **Must** |
| RF8 | Analyste | Afficher le SQL généré et les tables utilisées | Moyenne | **Must** |
| RF3 | Décideur | Graphique adapté (courbe, barres, répartition) | Haute | **Must** |
| RF5 | Décideur | Question de suivi tenant compte de l'échange | Moyenne | **Should** |
| RF6 | Décideur | Consulter et relancer l'historique | Moyenne | **Should** |
| RF4 | Décideur | Tableau de bord des KPI clés (via `get_kpi`) | Haute | **Should** |
| RF13 | Analyste | Journal d'audit technique des requêtes | Moyenne | **Should** |
| RF11 | Admin | Gérer utilisateurs et rôles | Haute | **Délégué à Keycloak** |
| RF7 | Décideur | Exporter un rapport PDF | Moyenne | **Could** |
| RF9 | Analyste | Définir un KPI | Moyenne | **Could** via `kpis.yaml` versionné, avec revue de code obligatoire (il modifie du SQL exécuté) |
| RF10 | Tous | Signaler une réponse incorrecte | Basse | **Could** |
| RF12 | Admin | Paramétrer le système | Basse | **Won't en UI** (fichier de configuration) |

## 5. Exigences non fonctionnelles

| Réf. | Catégorie | Exigence | Critère de vérification |
|---|---|---|---|
| ENF1 | Performance | Réponse rapide | Médiane < 15 s, p90 < 30 s ; budget global 30 s par question ; `statement_timeout` 10 s par requête |
| ENF2 | Fiabilité | Réponses justes et stables | Température 0 ; 3 passes par question en évaluation ; les questions KPI exigent 3/3 ; même question, même chiffre (le texte peut varier). **Pas de cache SQL** |
| ENF3 | Sécurité | Aucune écriture, aucun accès hors `analytics` | Garde SQL par liste blanche + rôle `agent_ro` durci (section 10) ; jeu de ≥ 25 payloads hostiles nommés |
| ENF4 | Sécurité | Secrets hors du code | `.env` non versionné, secrets Docker, filtre de masquage dans les journaux, scan de secrets en pré-commit et CI |
| ENF5 | Traçabilité | Chaque appel d'outil tracé | Table `app.query_log` écrite **par l'API seule** : horodatage, utilisateur, étape, SQL, durée, statut, jetons, coût, versions de prompt et de couche sémantique ; refus du garde inclus |
| ENF6 | Transparence | Chiffres explicables | Pour l'analyste : SQL et tables de chaque réponse. Pour le décideur : tables, période, périmètre. Le filtrage du SQL est fait **côté serveur** |
| ENF7 | Ergonomie | Interface claire en français, accessible | Question → graphique en ≤ 3 clics ; WCAG 2.2 AA sur les écrans principaux |
| ENF8 | Maintenabilité | Pipeline reproductible | Tests dbt verts ; `docker compose up` ; README par composant |
| ENF9 | Coût | Consommation maîtrisée | 1 000 lignes max, rejet des plans coûteux (`EXPLAIN`), quota par utilisateur, **budget de coût par question** défini après la première mesure |

## 6. Architecture

Voir [docs/SYSTEM_DESIGN.md](docs/SYSTEM_DESIGN.md). Résumé : générateur → Postgres (`raw`, `analytics`, `app`) via dbt ; API FastAPI qui lance le serveur MCP en sous-processus (stdio) et héberge l'agent ; interface React ; Keycloak pour l'identité. L'agent n'accède aux données que par le serveur MCP.

## 7. Modèle de données

Étoile : un fait, quatre dimensions. XOF sans décimales ; montants en `numeric`, jamais `float`.

| Table | Grain | Colonnes principales |
|---|---|---|
| `fact_transaction` | une transaction | `transaction_id` bigint, `client_id`, `agent_id` **NOT NULL** (membre « Hors agent » = −1), `region_client_id`, `region_agent_id`, `date_id` (int AAAAMMJJ), `txn_ts` timestamptz, `type` (dépôt, retrait, transfert, paiement), `montant_xof` numeric(14,0) > 0, `frais_xof` numeric(12,0) ≥ 0 et ≤ montant, `statut` (réussie, échouée ; CHECK) |
| `dim_client` | un client | `client_id`, `date_inscription`, `region_client_id`, `segment` |
| `dim_agent` | un point de service | `agent_id`, `nom`, `ville`, `region_agent_id`, `date_activation`, `statut_agent` (ouvert/fermé) ; ligne −1 « Hors agent » |
| `dim_region` | une région | `region_id`, `region`, `pays` |
| `dim_date` | un jour | `date_id`, `date`, `jour_semaine`, `semaine_iso`, `mois` (AAAA-MM), `nom_mois` (français), `trimestre`, `annee`, `est_weekend`, `jour_ferie`, `debut_mois`, `fin_mois` ; couvre toute la plage jusqu'à `REFERENCE_DATE` |

Choix actés : dimensions en SCD1 (régions et statuts supposés stables, à écrire dans le mémoire). Les types de transaction avec agent sont dépôt et retrait ; transfert et paiement ont l'agent −1 (test dbt). Pas de destinataire dans le fait : limite documentée.

Glossaire (source unique : `agent/semantic/glossary.yaml`) :
- « région » seule est ambiguë pour les transactions : l'agent précise `region_agent` ou `region_client` dans sa réponse. Pour les agents et les revenus de frais, défaut `region_agent` ; pour les clients, défaut `region_client`.
- « agent actif » (KPI : ≥ 1 transaction réussie) ≠ `statut_agent` (ouvert/fermé).
- « aujourd'hui » = `REFERENCE_DATE`.

**KPI** (source unique : `agent/semantic/kpis.yaml` ; ce tableau en est dérivé) :

| KPI | Définition |
|---|---|
| Volume de transactions | `COUNT(*)` des transactions réussies sur la période |
| Valeur transférée | `SUM(montant_xof)` des transactions réussies, tous types, filtrable par `type` (limite : pas de double comptage possible sans destinataire) |
| Revenus de frais | `SUM(frais_xof)` des transactions réussies |
| Clients actifs | `COUNT(DISTINCT client_id)` ayant ≥ 1 transaction réussie sur `]as_of − N jours, as_of]`, N = 30 par défaut, paramétrable ; ou sur un mois civil |
| Agents actifs | Idem avec `agent_id` ≠ −1 |
| Taux d'échec | échouées / (réussies + échouées) sur la période |

## 8. Serveur MCP

Sous-processus stdio de l'API. Il ne journalise pas en base : il renvoie `(sql, lignes, durée, truncated)` et écrit des journaux JSON ; **l'API écrit `query_log`**.

| Outil | Rôle | Priorité |
|---|---|---|
| `get_kpi` | KPI défini dans `kpis.yaml` ; paramètres liés, typés, validés par énumération (jamais interpolés) | **Must** (chemin principal des questions KPI) |
| `list_tables`, `describe_table` | Schéma de `analytics` uniquement ; métadonnées normalisées | Must |
| `run_query` | SELECT généré ; passe par le garde SQL | Must |

Garde SQL (liste blanche, détail en SYSTEM_DESIGN §6) : AST complet y compris CTE et sous-requêtes ; seules les 5 tables `analytics.*` ; seules des fonctions d'une liste fermée ; réécriture du SQL depuis l'AST validé ; `LIMIT` imposé (1 001 en interne pour détecter `truncated`) ; plan `EXPLAIN` borné.

## 9. Agent IA

Voir [docs/AGENTIC_DESIGN.md](docs/AGENTIC_DESIGN.md). Un agent à boucle d'outils ; la décision répondre / préciser / refuser est le premier tour de la même boucle ; couche sémantique versionnée ; 2 corrections SQL maximum ; sortie structurée validée ; graphique calculé par le code.

## 10. Sécurité et gouvernance

1. **Keycloak** : client public, Authorization Code + PKCE, jeton d'accès de 5 min stocké en mémoire. L'API vérifie `iss`, `aud`, `exp`, `nbf`, l'algorithme (RS256 uniquement), la clé par `kid` (JWKS en cache), et lit les rôles du seul client attendu.
2. **API** : filtre `user_id = sub` du jeton sur chaque requête ; 404 sur la conversation d'autrui ; quotas et limitation de débit ; CORS en liste blanche d'origines exactes, jeton en en-tête `Authorization` (pas de cookie, donc pas de CSRF) ; en-têtes de sécurité et CSP stricte.
3. **Serveur MCP / garde SQL** : voir section 8.
4. **Postgres** : trois rôles (`dbt_owner`, `app_rw`, `agent_ro`), `agent_ro` durci (droits, `search_path`, lecture seule, timeouts), sans extension `dblink` ni `file_fdw`.

Autres exigences : résultats d'outils injectés comme données non fiables (voir AGENTIC §6), rendu React en texte brut ou Markdown assaini sans HTML, images ni liens externes ; messages d'erreur Postgres normalisés avant retour à l'agent ou à l'utilisateur ; journal `query_log` en ajout seul (`REVOKE UPDATE, DELETE`), durée de rétention définie, `user_id` pseudonymisé dans les exports ; Keycloak en mode production (HTTPS, pas de `start-dev`, mot de passe admin changé, aucun secret ni compte de démonstration à mot de passe fixe dans le realm versionné).

## 11. Évaluation et critères d'acceptation

| Jeu | Taille | Usage |
|---|---|---|
| Dev | ~30 | Itérations sur prompts et exemples ; calibration de la porte d'intention |
| Test | 40 | Exécuté à chaque jalon (exécutions journalisées), jamais lu pour modifier les exemples |

Chaque question porte une catégorie, un SQL de référence et, le cas échéant, un **piège** couvert.

| Catégorie | Nombre (test) |
|---|---|
| KPI simple | 8 |
| Comparaison de périodes | 6 |
| Classement | 6 |
| Clients et agents | 4 |
| Ambiguë ou hors périmètre (dont tentatives d'écriture ou d'injection) | 6 |
| Suivi de conversation | 4 |
| Pièges du glossaire : région client/agent, transactions hors agent, résultat vide, jour férié, dénominateur du taux d'échec | 6 |

Règles :
- Jeu de test écrit **avant** l'agent ; références recalculées automatiquement depuis les données seedées ; hash du fichier de test figé avant P1.
- Comparateur `eval/compare.py` (testé unitairement) : une réponse est juste si **le résultat exécuté et le chiffre cité** dans le message correspondent à la référence, avec période et périmètre corrects. Entiers (XOF, comptes) : égalité exacte ; ratios : tolérance relative de 10⁻⁴ ; classements : ordre pris en compte, ex æquo départagés explicitement ; résultat vide : réponse « aucune donnée » attendue.
- Ambiguïté réussie si précision demandée ou refus motivé ; porte d'intention évaluée par matrice de confusion (faux refus ≤ 5 %).
- Anti-fuite : aucun SQL normalisé (sqlglot) ni squelette de requête commun entre `examples.yaml` et `eval/test.yaml`, sauf déclaration explicite ; `make eval` échoue sinon.
- 3 passes par question, **sans cache** ; score = moyenne des passes (min/max affichés) ; cohérence par question (3/3, 2/3, 1/3).
- Comparaisons de référence (ablations) : modèle seul avec schéma brut ; sans exemples ; sans `get_kpi` ; sans validateur de sortie. Delta rapporté avec intervalle.
- Chaque rapport consigne : identifiant daté du modèle, température, hash des prompts, de la couche sémantique et des exemples, SHA git, graine et hash des données, `REFERENCE_DATE`, versions dbt et Postgres.
- Métriques : justesse globale et par catégorie (comptes bruts), cohérence entre passes, précision/rappel de la porte, taux de repli, taux de rejet du validateur, taux d'usage de `get_kpi` quand un KPI existe, erreurs de période/périmètre, nombre d'étapes et taux d'atteinte du plafond, latence p50/p90/max (agent seul et bout en bout, par étape), jetons (mis en cache à part) et coût par question, blocage des payloads hostiles.

Acceptation : O1 à O4 atteints, tests dbt verts, tests de sécurité verts.

## 12. Phases et livrables

| Phase | Contenu | Point de contrôle |
|---|---|---|
| P0 Fondations | Dépôt, compose (Postgres, Keycloak), rôles et droits, générateur, dbt `raw` → étoile + tests, jeux dev/test et comparateur | Tests dbt verts, références recalculées, hash figé |
| P1 Tranche verticale | MCP (`get_kpi`, `list_tables`, `describe_table`, `run_query`) avec `kpis.yaml`, garde SQL, agent (RF1, RF2, RF14, RF8), `make eval` sans Keycloak, `query_log` | Première évaluation avec intervalle et ablations |
| P2 Produit | Interface React + graphiques (RF3), Keycloak branché, RF5, RF6 | Parcours complet question → graphique |
| P3 Consolidation | RF4, RF13, itérations d'évaluation, jeu de sécurité complet | O1 à O3 atteints |
| P4 Extensions (Could) | PDF, signalement, cible Snowflake | Selon le temps |

## 13. Risques

| Risque | Effet | Mesure |
|---|---|---|
| SQL faux mais plausible | Décision sur un mauvais chiffre | `get_kpi` en priorité, couche sémantique, SQL visible à l'analyste, évaluation avec ablations |
| Évaluation trop petite | Seuil non démontré | Intervalle de Wilson, agrégation dev + test, comptes bruts |
| Fuite exemples → test | Score gonflé | Contrôle SQL normalisé, hash figé, exécutions du test limitées et journalisées |
| `dbt run` recrée les tables et supprime les droits de `agent_ro` | Agent sans accès ou accès incohérent | `ALTER DEFAULT PRIVILEGES` + `grants` dbt + test de droits |
| Timeout trop proche du budget | Pas de marge pour la correction SQL | `statement_timeout` 10 s, budget 30 s par question |
| Contournement du garde SQL | Lecture de fichiers, DoS | Liste blanche d'AST et de fonctions, rôle durci, `EXPLAIN`, jeu de payloads |
| Injection indirecte via données | Réponse fausse ou fuite par rendu | Données encadrées, colonnes texte minimisées, rendu assaini, validateur de sortie |
| Données synthétiques irréalistes | Résultats peu convaincants | Volumétrie cible (50 000 clients, 2 000 agents, 18 mois, ~2 M de transactions), saisonnalité, jours fériés, aberrations |
| Complexité Keycloak | Temps perdu | Realm versionné sans secret, un seul client public |
| Coût ou latence du LLM | Lenteur, budget | Mesure par étape, préfixe de prompt stable, 2 corrections max |

## 14. Journal des changements

**v1 → v2** : O4 redéfini ; garde SQL par parseur ; ENF2 reformulé ; `REFERENCE_DATE` ; glossaire région ; jeux dev/test séparés ; RF8 en Must ; RF11 délégué à Keycloak ; pipeline allégé.

**v2 → v3 (relecture croisée)** :
1. `query_log` écrit par l'API seule ; MCP en sous-processus stdio, conteneur `mcp` supprimé.
2. Cache SQL supprimé (faux résultats en suivi de conversation, variance masquée).
3. `get_kpi` en Must P1 ; `kpis.yaml` source unique, SRS dérivé.
4. Visibilité du SQL filtrée côté serveur ; audit sans texte des questions.
5. Garde SQL en liste blanche, rôles et droits Postgres explicites, `statement_timeout` 10 s.
6. Modèle : agent −1 NOT NULL, `dim_region`, régions client/agent dans le fait, `numeric(14,0)`, `txn_ts`, `dim_date` enrichie, SCD1 acté, `statut_agent`.
7. KPI : taux d'échec défini, fenêtre des clients actifs paramétrée, limites de la valeur transférée documentées.
8. Évaluation : intervalle de Wilson, test à 40 questions, 3 passes sans cache, comparateur, anti-fuite SQL, ablations, traçabilité complète, métriques étendues.
9. Sécurité : validation JWT complète, client public PKCE, CORS, injection indirecte, requêtes coûteuses, journal en ajout seul.
