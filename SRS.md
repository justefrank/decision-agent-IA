Spécification — Agent conversationnel d'aide à la décision (Wave)
Oct 17, 2026 · @frank
1. Contexte et objectifs
Le système permet à un décideur de Wave Sénégal d'interroger en langage naturel un data warehouse et d'obtenir des réponses chiffrées, des graphiques et des rapports, sans passer par un analyste.
Hypothèse de départ : obtenir un indicateur non prévu dans un tableau de bord suppose aujourd'hui de solliciter un analyste, ce qui ralentit la décision. L'agent réduit cette dépendance tout en gardant les données sous contrôle.
Objectifs mesurables (cibles proposées, à confirmer) :
• O1 – Justesse : au moins 80 % de réponses correctes sur le jeu de questions de test (section 11).
• O2 – Rapidité : temps de réponse médian inférieur à 15 secondes.
• O3 – Sûreté : 100 % des requêtes exécutées en lecture seule.
• O4 – Couverture : les 8 cas d'utilisation du diagramme de cas d'utilisation sont réalisés.
2. Périmètre
Le projet couvre la chaîne complète, des sources opérationnelles jusqu'à l'agent conversationnel, sur des données synthétiques réalistes.
Inclus
• Sources MySQL/PostgreSQL simulées et script d'extraction et de chargement vers Snowflake.
• Transformations dbt et modèle en étoile (dim_client, dim_date, dim_agent, fact_transaction).
• Serveur MCP en lecture seule et agent IA avec appel d'outils.
• Interface web (chat, historique, KPI, rapports, administration) reliée au back-end.
• Évaluation de l'agent sur un jeu de questions de test.
Exclu
• Accès aux données réelles de Wave et toute donnée personnelle réelle.
• Écriture dans le data warehouse par l'agent.
• Alimentation en temps réel (le chargement se fait par lots).
• Application mobile.
Hypothèses
• Les données sont générées de façon synthétique (Python) ; ce choix est justifié dans le mémoire par la confidentialité des données de Wave.
• Un compte d'essai Snowflake suffit pour le volume traité.
3. Acteurs et rôles
Trois acteurs humains utilisent le système ; le data warehouse est un système externe qu'il interroge.
Acteur
Rôle
Droits principaux
Décideur stratégique
Pose des questions, consulte KPI et rapports
Interroger l'agent, consulter dashboards, historique personnel, exporter un rapport
Analyste métier
Valide les résultats, définit les indicateurs
Tout ce que fait le décideur, plus consulter le SQL généré, gérer les KPI et les modèles de rapports
Administrateur système
Exploite et sécurise la plateforme
Gérer utilisateurs et rôles, paramètres, journaux d'audit ; aucun accès aux réponses des autres utilisateurs par défaut
Data warehouse (externe)
Fournit les données
Accès en lecture seule via un rôle Snowflake dédié à l'agent
4. Exigences fonctionnelles
Quatorze exigences, dont six de priorité haute, forment le socle à livrer en premier.
Réf.
Acteur
Exigence
Priorité
RF1
Décideur
Poser une question en langage naturel, en français
Haute
RF2
Décideur
Recevoir une réponse chiffrée qui rappelle la période et le périmètre utilisés
Haute
RF3
Décideur
Obtenir un graphique adapté à la question (courbe, barres, répartition)
Haute
RF4
Décideur
Consulter les KPI clés sur un tableau de bord
Haute
RF5
Décideur
Poser une question de suivi qui tient compte de l'échange précédent
Moyenne
RF6
Décideur
Consulter et relancer l'historique de ses conversations
Moyenne
RF7
Décideur
Générer et exporter un rapport (PDF)
Moyenne
RF8
Analyste
Afficher le SQL généré et les tables utilisées pour chaque réponse
Moyenne
RF9
Analyste
Définir et modifier un KPI (libellé, formule, périmètre)
Moyenne
RF10
Décideur, analyste
Signaler une réponse incorrecte
Basse
RF11
Administrateur
Gérer les utilisateurs et leurs rôles
Haute
RF12
Administrateur
Paramétrer le système (modèle de langage, limites de requête)
Basse
RF13
Administrateur
Consulter le journal d'audit des requêtes
Moyenne
RF14
Tous
Recevoir une demande de précision quand la question est ambiguë ou hors périmètre, plutôt qu'une réponse devinée
Haute
5. Exigences non fonctionnelles
Chaque exigence a un critère vérifiable ; les seuils sont des cibles proposées à valider.
Réf.
Catégorie
Exigence
Critère de vérification
ENF1
Performance
Réponse rapide à une question courante
Médiane < 15 s, 90e centile < 30 s
ENF2
Fiabilité
Réponses justes et reproductibles
≥ 80 % de réponses correctes sur le jeu de test ; même question, même résultat chiffré
ENF3
Sécurité
Aucune écriture ni accès hors du schéma analytique
Rôle Snowflake en lecture seule ; requêtes autres que SELECT rejetées
ENF4
Sécurité
Secrets hors du code
Identifiants dans .env, jamais versionnés
ENF5
Traçabilité
Chaque question et chaque requête SQL conservées
Journal horodaté avec utilisateur, question, SQL, durée, statut
ENF6
Transparence
Les chiffres sont explicables
Toute réponse peut afficher la requête et les tables sources
ENF7
Ergonomie
Interface claire en français
Parcours d'une question à son graphique en moins de 3 clics
ENF8
Maintenabilité
Pipeline reproductible
Tests dbt réussis ; installation documentée dans les README
ENF9
Coût
Consommation maîtrisée
Limite de lignes et de temps par requête ; coût par question mesuré
6. Architecture technique
La chaîne compte huit éléments, de la source à l'utilisateur, et l'agent n'accède aux données que par le serveur MCP.
Les données avancent par lots jusqu'au schéma ANALYTICS de Snowflake ; l'agent appelle ensuite le serveur MCP, qui exécute les requêtes en lecture seule. L'interface web (HTML/CSS/JS) s'appuie sur un back-end Python (FastAPI, proposé) qui relaie les questions à l'agent.
7. Modèle de données
Le modèle en étoile compte une table de faits et trois dimensions ; les colonnes sont proposées et seront ajustées à la génération des données.
Table
Type
Grain
Colonnes principales
fact_transaction
Fait
une transaction
transaction_id, client_id, agent_id (vide si hors agent), date_id, type (dépôt, retrait, transfert, paiement), montant_xof, frais_xof, statut (réussie, échouée)
dim_client
Dimension
un client
client_id, date_inscription, region, segment
dim_agent
Dimension
un agent (point de service)
agent_id, nom, ville, region, date_activation, statut
dim_date
Dimension
un jour
date_id, date, jour_semaine, semaine, mois, trimestre, annee, jour_ferie
Indicateurs de départ, calculés uniquement à partir de fact_transaction et des dimensions :
KPI
Définition
Volume de transactions
Nombre de transactions réussies sur la période
Valeur transférée
Somme de montant_xof des transactions réussies
Revenus de frais
Somme de frais_xof des transactions réussies
Clients actifs
Clients distincts ayant au moins une transaction réussie sur les 30 derniers jours
Agents actifs
Agents distincts ayant au moins une transaction réussie sur les 30 derniers jours
Taux d'échec
Transactions échouées divisées par le total des transactions
8. Serveur MCP
Le serveur MCP est la seule porte d'accès de l'agent au data warehouse : il n'expose que quelques outils, tous en lecture seule et bornés.
Outil
Rôle
Entrées
Sortie
list_tables
Lister les tables du schéma analytique
aucune
noms et descriptions
describe_table
Décrire une table
nom de table
colonnes, types, exemples de valeurs
run_query
Exécuter une requête SQL
requête SELECT
lignes (limitées) et durée
get_kpi
Calculer un KPI défini
nom du KPI, période, filtres
valeur et requête utilisée
Garanties imposées par le serveur, indépendamment de l'agent :
• Seules les requêtes SELECT sont acceptées ; toute autre instruction est rejetée.
• Accès limité au schéma ANALYTICS, via un rôle Snowflake en lecture seule.
• Limite de lignes retournées (valeur de départ : 1 000) et délai maximal par requête (valeur de départ : 30 s).
• Chaque appel est journalisé : utilisateur, outil, requête, durée, statut.
9. Agent IA
L'agent transforme une question en langage naturel en requête SQL vérifiée, puis en réponse lisible ; il s'appuie sur une couche sémantique plutôt que de deviner le schéma.
Déroulé d'une question
1. L'agent reçoit la question et l'historique de la conversation.
2. Il décide s'il doit demander une précision (période, périmètre ou KPI absents) ou refuser une question hors périmètre.
3. Il consulte le schéma et les définitions de KPI via le serveur MCP.
4. Il génère la requête SQL, ou appelle get_kpi quand le KPI existe déjà.
5. Il exécute la requête ; en cas d'erreur, il corrige et relance, deux tentatives au maximum.
6. Il formule la réponse en français, rappelle période et périmètre, et propose un graphique ou un tableau.
7. Il enregistre la question, le SQL et le résultat dans le journal.
Couche sémantique (fichier versionné dans agent/) : description des tables et colonnes, définitions des KPI, glossaire métier (par exemple le sens d'« agent » ou de « client actif »), et une vingtaine d'exemples question → SQL.
Formats de réponse : phrase avec chiffre clé, tableau, graphique (courbe, barres, répartition), rapport structuré exportable.
Règles de comportement : ne jamais inventer un chiffre absent des résultats ; signaler quand les données sont vides ou incomplètes ; ne jamais exécuter de requête de modification.
10. Sécurité et gouvernance
La sécurité repose sur trois couches indépendantes (droits Snowflake, garde-fous du serveur MCP, contrôle d'accès de l'application), complétées par la gestion des secrets, des données et de l'audit.
• Droits Snowflake : un rôle dédié à l'agent, limité à la lecture du schéma ANALYTICS, sur un warehouse de petite taille avec arrêt automatique.
• Serveur MCP : validation des requêtes (SELECT seulement), limites de lignes et de durée, journalisation.
• Application : authentification, trois rôles (décideur, analyste, administrateur) et vérification des droits à chaque appel.
• Secrets : variables d'environnement (.env, exclu du dépôt), jamais dans le code ni dans les journaux.
• Données : uniquement synthétiques ; aucune donnée personnelle réelle n'entre dans le dépôt ni dans les requêtes envoyées au modèle de langage.
• Audit : le journal est consultable par l'administrateur et conservé pour l'évaluation de l'agent.
11. Évaluation et critères d'acceptation
L'agent est évalué sur 30 questions dont la réponse de référence est calculée à la main en SQL ; une réponse est juste si son résultat chiffré est identique à la référence.
Catégorie
Exemple de question
Nombre
KPI simple
Quel est le volume de transactions ce mois-ci ?
8
Comparaison de périodes
Compare la valeur transférée de septembre à août
6
Classement
Quelles sont les 5 régions aux revenus de frais les plus élevés ?
6
Clients et agents
Combien d'agents sont actifs à Dakar ?
4
Ambiguë ou hors périmètre
Comment vont les ventes ?
4
Suivi de conversation
Et pour le mois précédent ?
2
Métriques relevées : taux de réponses justes, taux de bonne gestion des questions ambiguës (précision demandée ou refus motivé), latence médiane et au 90e centile, coût par question, proportion de requêtes corrigées après une première erreur.
Le système est accepté quand les objectifs O1 à O4 de la section 1 sont atteints et que les tests dbt passent sans échec.
12. Planning et livrables
Le projet avance en quatre phases ; chacune se termine par un point de contrôle qui conditionne la suivante.
La première phase livre une tranche fonctionnelle de bout en bout avant d'élargir le périmètre. Les dates restent à fixer avec le calendrier de remise du mémoire.
13. Risques et mesures d'atténuation
Le risque principal est un SQL faux mais plausible ; il est traité par la couche sémantique, l'affichage du SQL et le jeu de test.
Risque
Effet
Mesure d'atténuation
SQL incorrect mais vraisemblable
Décision prise sur un mauvais chiffre
Couche sémantique, outil get_kpi pour les KPI critiques, SQL affiché, évaluation sur jeu de test
Données synthétiques peu réalistes
Résultats peu convaincants devant le jury
Distributions inspirées d'usages plausibles, saisonnalité, valeurs aberrantes ; hypothèses décrites dans le mémoire
Limites du compte d'essai Snowflake
Blocage en cours de projet
Petit volume, warehouse à arrêt automatique, surveillance des crédits, plan B PostgreSQL local
Coût ou latence du modèle de langage
Réponses lentes ou budget dépassé
Mesure par question, cache des schémas, limite de tentatives
Question ambiguë
Réponse devinée
Règle de précision demandée (RF14)
Retard du planning
Livrable incomplet
Tranche verticale minimale d'abord, élargissement ensuite
