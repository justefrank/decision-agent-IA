# Diagrammes

Version 5. Générés depuis `docs/diagrams/*.mmd` (Mermaid) ; rendus `svg/` et `png/` **régénérés le 2026-10-24** à partir des sources v5. Sources : [SRS.md](../SRS.md), [SYSTEM_DESIGN.md](SYSTEM_DESIGN.md), [AGENTIC_DESIGN.md](AGENTIC_DESIGN.md). Les blocs ci-dessous sont des copies des fichiers `.mmd`, qui font foi.

Régénérer (Chromium local) :

```
export PUPPETEER_EXECUTABLE_PATH=/chemin/vers/chrome
npx -y @mermaid-js/mermaid-cli -p puppeteer.json -i docs/diagrams/NN-nom.mmd -o docs/diagrams/svg/NN-nom.svg
npx -y @mermaid-js/mermaid-cli -p puppeteer.json -i docs/diagrams/NN-nom.mmd -o docs/diagrams/png/NN-nom.png -s 2 -b white
```

`puppeteer.json` : `{"args": ["--no-sandbox", "--disable-gpu"]}` dans un conteneur.

| N° | Fichier | Changement v4 → v5 |
|---|---|---|
| 1 | `01-architecture` | Proxy Caddy, bases `warehouse` et `keycloak`, analyse en workflow, MCP seul détenteur de `agent_ro` |
| 2 | `02-acteurs-droits` | Back-office MVP en lecture, console Keycloak, PR Git |
| 3 | `03-modele-etoile` | Valeurs ASCII précisées, membre « Non applicable » |
| 4 | `04-tables-applicatives` | `change_request` retirée ; champs LLM de `query_log` ; états de `feedback` ; `eval_run` en pass^3 |
| 5 | `05-sequence-question` | Claude explicite, outils v5, outils terminaux, SSE |
| 6 | `06-sequence-authentification` | MFA conditionnelle, force brute, Audience, session SSO |
| 7 | `07-agent-boucle` | Boucle v5 (outils terminaux, faits, validateur, gabarit) |
| 8 | `08-garde-sql` | Garde renforcé |
| 9 | `09-analyse-tableau-de-bord` | Workflow sans outil, routes `/api/dashboard` |
| 10 | `10-changement-configuration-pr` | **Remplace** `10-demande-de-changement` |
| 11 | `11-signalement` | 3 états |
| 12 | `12-evaluation` | Jeux v5, pass^3, McNemar, banc HTTP |
| 13 | `13-deploiement` | Proxy, Mailpit, `make migrate`, `make bench` |

## 1. Architecture d'ensemble

SPA derrière un proxy Caddy de même origine ; le sous-processus MCP est le seul détenteur du DSN `agent_ro`. Voir [SYSTEM_DESIGN §2](SYSTEM_DESIGN.md#2-vue-densemble-et-composants).

Rendu : [svg](diagrams/svg/01-architecture.svg) · [png](diagrams/png/01-architecture.png)

```mermaid
flowchart LR
  subgraph Navigateur
    SPA["SPA Vite + React<br/>(jeton en mémoire)"]
  end
  subgraph Edge["Proxy Caddy (TLS, même origine)"]
    P1["/ : fichiers statiques"]
    P2["/api : API"]
    P3["/auth : Keycloak"]
  end
  KC["Keycloak 26.x<br/>(thème connexion + OTP, événements)"]
  subgraph API["API FastAPI (un worker)"]
    R["Routes /api, JWT (iss, aud, exp, RS256, kid), quota"]
    AG["Agent (SDK anthropic)<br/>boucle, faits, validateur"]
    AN["Analyse du tableau de bord<br/>(workflow, sans outil)"]
    MC["Client MCP v2"]
  end
  MCP["Sous-processus MCPServer (stdio)<br/>garde SQL, query_metric, run_query, describe_schema<br/>seul détenteur du DSN agent_ro"]
  subgraph PG["Postgres 17"]
    W[("base warehouse<br/>raw / analytics / app")]
    K[("base keycloak")]
  end
  LLM["API Claude"]
  GEN["Générateur + dbt (dbt_owner)"]
  SPA --> Edge
  P3 --> KC
  P2 --> R
  R --> AG
  R --> AN
  AG <--> LLM
  AN <--> LLM
  AG --> MC
  AN --> MC
  MC -- stdio --> MCP
  MCP -- "agent_ro, BEGIN READ ONLY" --> W
  R -- "app_rw" --> W
  R -- JWKS --> KC
  KC --> K
  GEN --> W
```

## 2. Acteurs et droits (MVP)

Back-office en lecture ; utilisateurs dans la console Keycloak ; configuration par PR Git. Voir [SRS §3](../SRS.md#3-acteurs-et-rôles).

Rendu : [svg](diagrams/svg/02-acteurs-droits.svg) · [png](diagrams/png/02-acteurs-droits.png)

```mermaid
flowchart LR
  D(["Décideur"]) --> BASE
  A(["Analyste"]) --> BASE
  A --> SQLV
  A --> BOR
  M(["Administrateur"]) --> BASE
  M --> SQLV
  M --> BOR
  M --> BOA
  M -.-> KCC
  BASE["Socle applicatif<br/>Poser une question (RF1, RF2, RF14)<br/>Graphiques (RF3)<br/>Historique et suivi (RF5, RF6)<br/>Tableau de bord et analyse (RF4, RF17)<br/>Signaler une réponse (RF10)<br/>Connexion et récupération d'accès (RF15, RF16)"]
  SQLV["Voir le SQL et les tables (RF8)"]
  BOR["Back-office en lecture, analyste<br/>B05 KPI et couche sémantique (RF9, RF18)<br/>B08 Journal d'audit (RF13)<br/>B11 Évaluation (RF19)<br/>B12 Signalements (RF10)"]
  BOA["Back-office, administrateur seul<br/>B01 Exploitation et sécurité (RF20)<br/>B05 onglet Paramètres (RF12)"]
  KCC["Console Keycloak<br/>Utilisateurs et rôles (RF11)"]
  PR["PR Git relue<br/>(KPI, sémantique, paramètres)"]
  A -.-> PR
  M -.-> PR
```

## 3. Modèle analytique en étoile

Valeurs codées en ASCII ; membres −1 « Hors agent » et « Non applicable ». Voir [SRS §7](../SRS.md#7-modèle-de-données).

Rendu : [svg](diagrams/svg/03-modele-etoile.svg) · [png](diagrams/png/03-modele-etoile.png)

```mermaid
erDiagram
  dim_client ||--o{ fact_transaction : "client_id"
  dim_agent ||--o{ fact_transaction : "agent_id (-1 = hors agent)"
  dim_region ||--o{ dim_client : "region_client_id"
  dim_region ||--o{ dim_agent : "region_agent_id (-1 = non applicable)"
  dim_date ||--o{ fact_transaction : "date_id"
  fact_transaction {
    bigint transaction_id PK
    int client_id FK
    int agent_id FK
    int region_client_id FK
    int region_agent_id FK
    int date_id FK
    timestamptz txn_ts
    text type "depot retrait transfert paiement"
    numeric montant_xof
    numeric frais_xof
    text statut "reussie echouee"
  }
  dim_client {
    int client_id PK
    date date_inscription
    int region_client_id FK
    text segment "particulier commercant entreprise"
  }
  dim_agent {
    int agent_id PK
    text nom "texte libre, étiquette opaque"
    text ville "texte libre"
    int region_agent_id FK
    date date_activation
    text statut_agent "ouvert ferme"
  }
  dim_region {
    int region_id PK
    text region "14 régions + Non applicable"
    text pays
  }
  dim_date {
    int date_id PK
    date date
    int semaine_iso
    int mois
    int trimestre
    int annee
    bool est_weekend
    bool jour_ferie
    date debut_mois
  }
```

## 4. Tables applicatives

Huit tables du schéma `app` (plus de `change_request`), colonnes principales seulement. Liste complète et droits de `app_rw` : [SYSTEM_DESIGN §3](SYSTEM_DESIGN.md#3-base-de-données).

Rendu : [svg](diagrams/svg/04-tables-applicatives.svg) · [png](diagrams/png/04-tables-applicatives.png)

```mermaid
erDiagram
  conversation ||--o{ message : contient
  message ||--o{ feedback : "signalée par"
  conversation ||--o{ query_log : trace
  eval_run ||--o{ eval_result : détaille
  conversation {
    uuid id PK
    text user_id "claim sub"
    text title
    timestamptz created_at
  }
  message {
    uuid id PK
    uuid conversation_id FK
    text role "user assistant"
    text content
    jsonb structured_json "AssistantMessage"
    timestamptz created_at
  }
  query_log {
    bigint id PK
    text trace_id
    int step
    int attempt
    text user_id "HMAC du sub"
    text tool "query_metric run_query describe_schema llm"
    text status "ok error blocked"
    text error_class
    text sql
    int row_count
    bool truncated
    int duration_ms
    text model_served
    text effort
    int tokens_cache_read
    numeric cost_usd
    text semantic_version
  }
  feedback {
    bigint id PK
    uuid message_id FK
    text category
    bool consent_question
    text status "nouveau traite rejete"
    text reject_reason
    bool promoted_to_dev
  }
  eval_run {
    bigint id PK
    text split "test dev intent ..."
    text ablation "none a b c d e"
    text model_served
    text effort
    text semantic_version
    text git_sha
    int n
    numeric pass1
    numeric pass3
    numeric ci_low
    numeric ci_high
  }
  eval_result {
    bigint run_id FK
    text question_id
    text category
    int passes "0 a 3"
    text terminal_tool
  }
  audit_access_log {
    bigint id PK
    text actor_id
    text action
    text target_trace_id
  }
  analysis {
    bigint id PK
    date period_start
    date period_end
    text region
    text semantic_version
    jsonb payload "DashboardAnalysis"
  }
```

## 5. Flux d'une question

POST + SSE ; outils de données puis un outil terminal ; l'API écrit `query_log`. Voir [SYSTEM_DESIGN §4](SYSTEM_DESIGN.md#4-flux-dune-question).

Rendu : [svg](diagrams/svg/05-sequence-question.svg) · [png](diagrams/png/05-sequence-question.png)

```mermaid
sequenceDiagram
  participant W as SPA
  participant A as API (via proxy /api)
  participant G as Agent
  participant L as Claude
  participant M as MCP (stdio)
  participant D as Postgres
  W->>A: POST /api/conversations/{id}/messages (Bearer)
  A->>A: JWT, rôle, propriété (user_id = sub), quota
  A->>G: question, état résolu, 6 derniers échanges
  loop 6 appels LLM max, 8 outils max, 30 s
    G->>L: messages.stream (tool_choice auto, outils strict)
    L-->>G: tool_use de données
    G->>M: query_metric, run_query ou describe_schema (délai restant)
    M->>M: garde SQL, EXPLAIN borné
    M->>D: BEGIN READ ONLY puis SELECT (agent_ro)
    D-->>M: 1 001 lignes max
    M-->>G: ToolResult (sql réécrit, rows, duration_ms, truncated)
    G-->>A: QueryLogRecord (outil et LLM)
    A->>A: écrit query_log
    A-->>W: SSE step
  end
  L-->>G: outil terminal (submit_answer, ask_clarification ou refuse)
  G->>G: registre de faits, validateur, formateur (ou réponse gabarit)
  G-->>A: AssistantMessage
  A->>A: for_role : retire sql pour le décideur, écrit message
  A-->>W: SSE final (ou error)
```

## 6. Authentification (OIDC + PKCE)

MFA pour analyste et admin seulement ; Audience mapper ; avertissement sur la session SSO, pas sur le jeton. Voir [SYSTEM_DESIGN §6](SYSTEM_DESIGN.md#6-sécurité-en-profondeur).

Rendu : [svg](diagrams/svg/06-sequence-authentification.svg) · [png](diagrams/png/06-sequence-authentification.png)

```mermaid
sequenceDiagram
  actor U as Utilisateur
  participant W as SPA
  participant K as Keycloak (via proxy /auth)
  participant A as API (via proxy /api)
  U->>W: ouvre l'application
  W->>K: redirection Authorization Code + PKCE (S256)
  K->>U: page de connexion (thème Keycloakify)
  U->>K: e-mail et mot de passe
  alt rôle analyste ou admin
    K->>U: vérification en deux étapes (OTP)
    U->>K: code
  end
  Note over K: force brute : verrouillage temporaire, message neutre, événement enregistré
  K-->>W: code d'autorisation
  W->>K: échange code + verifier
  K-->>W: jeton d'accès 5 min (aud = decision-api), en mémoire
  W->>A: requête avec Bearer
  A->>K: JWKS (en cache)
  A->>A: vérifie iss, aud, exp, nbf, RS256, kid, rôles du client decision-web
  A-->>W: réponse
  Note over W,K: jeton renouvelé en silence, avertissement avant la fin de la session SSO avec prolongation
```

## 7. Boucle de l'agent (v5)

Plus de tour d'intention forcé : trois outils terminaux possibles à tout tour, citation par référence, validateur, réponse gabarit. Voir [AGENTIC_DESIGN §2-§7](AGENTIC_DESIGN.md#2-vue-densemble).

Rendu : [svg](diagrams/svg/07-agent-boucle.svg) · [png](diagrams/png/07-agent-boucle.png)

```mermaid
flowchart TD
  Q["Question"] --> PRE["Code : quota, longueur,<br/>clarification en attente résolue ?"]
  PRE -- "oui : patch appliqué, question d'origine rejouée" --> CTX
  PRE -- "non" --> CTX["Contexte : préfixe en cache (outils, système, sémantique)<br/>puis REFERENCE_DATE, rôle, état résolu, 6 échanges"]
  CTX --> LLM["Appel Claude<br/>(tool_choice auto, outils strict, effort medium)"]
  LLM -- "query_metric / run_query / describe_schema" --> MCP[("MCP : garde SQL + agent_ro")]
  MCP -- "ToolResult" --> REG["Registre de faits f… et dérivés d…<br/>vue réduite : 50 lignes, étiquettes opaques"]
  REG -- "erreur SQL ou avertissement sémantique : 2 corrections max" --> LLM
  REG --> LLM
  LLM -- "budget presque atteint" --> NOW["Message système : réponds maintenant"]
  NOW --> LLM
  LLM -- "ask_clarification" --> CLR["PendingClarification persistée"]
  LLM -- "refuse" --> REF["Refus motivé"]
  LLM -- "submit_answer ({{f}}, {{d}})" --> VAL{"Validateur :<br/>références, littéraux FR,<br/>tronqué / vide, causalité"}
  VAL -- "échec, 1 nouvel essai" --> LLM
  VAL -- "ok" --> FMT["Formateur : texte FR, tableau,<br/>graphique, chaîne de preuve, état résolu"]
  VAL -- "échec persistant" --> TPL["Réponse gabarit (simplified)"]
  FMT --> OUT["AssistantMessage + QueryLogRecord (API)"]
  TPL --> OUT
  CLR --> OUT
  REF --> OUT
```

## 8. Garde SQL

Bornes avant analyse, liste blanche des types de nœuds, noms de fonctions normalisés, portée extraite de l'AST, `BEGIN READ ONLY`. Voir [SYSTEM_DESIGN §6](SYSTEM_DESIGN.md#garde-sql-liste-blanche-serveur-mcp).

Rendu : [svg](diagrams/svg/08-garde-sql.svg) · [png](diagrams/png/08-garde-sql.png)

```mermaid
flowchart TD
  S["SQL proposé (run_query) ou compilé (query_metric)"] --> B{"Longueur et profondeur<br/>d'AST bornées ?"}
  B -- non --> X["Refus actionnable (status = blocked)"]
  B -- oui --> P{"Un seul SELECT ?"}
  P -- non --> X
  P -- oui --> N{"Types de nœuds<br/>dans la liste blanche ?"}
  N -- non --> X
  N -- oui --> T{"Tables analytics.* autorisées ?"}
  T -- non --> X
  T -- oui --> F{"Fonctions (noms normalisés)<br/>dans la liste fermée ?"}
  F -- non --> X
  F -- oui --> SC["Portée extraite de l'AST<br/>et règles de cohérence sémantique"]
  SC -- "écart avec declared_scope" --> WN["Avertissement actionnable (semantic_warning)"]
  SC --> LI["LIMIT imposé (1 001)"]
  LI --> R["Réécriture du SQL depuis l'AST validé"]
  R --> E{"EXPLAIN : coût sous max_plan_cost ?"}
  E -- non --> X
  E -- oui --> DB[("Postgres : BEGIN READ ONLY,<br/>agent_ro, statement_timeout ≤ délai")]
  DB --> NR["ToolResult : sql, rows, truncated,<br/>erreurs normalisées"]
```

## 9. Analyse du tableau de bord (RF17, en workflow)

Le code récupère les KPI et calcule les candidats ; un seul appel LLM sans outil les rédige. Voir [AGENTIC_DESIGN §9](AGENTIC_DESIGN.md#9-mode-analyse-du-tableau-de-bord-rf17-en-workflow).

Rendu : [svg](diagrams/svg/09-analyse-tableau-de-bord.svg) · [png](diagrams/png/09-analyse-tableau-de-bord.png)

```mermaid
sequenceDiagram
  actor D as Décideur
  participant W as SPA
  participant A as API
  participant C as Code (decision_agent.dashboard)
  participant M as MCP
  participant L as Claude
  D->>W: choisit période et région
  W->>A: GET /api/dashboard?period=&region=
  A->>C: fetch_dashboard
  C->>M: query_metric (6 KPI, compare_to previous_period, national et par région)
  M-->>C: ToolResult
  C-->>A: tuiles et dérivés
  A-->>W: tuiles des KPI
  W->>A: POST /api/dashboard/analysis
  A->>C: run_dashboard_analysis
  C->>C: constats candidats, confiance calculée, ordre déterministe
  C->>L: un appel, sortie structurée, aucun outil
  L-->>C: lead, 3 constats max (références f et d), questions
  C->>C: validateur (références, littéraux, causalité hors hypothèse)
  C-->>A: DashboardAnalysis (available)
  A->>A: écrit app.analysis (semantic_version, model_served)
  A-->>W: constats avec confiance élevée, moyenne ou hypothèse
  D->>W: clique une question d'approfondissement
  W->>A: ouvre une conversation pré-remplie (flux normal)
```

## 10. Changement de configuration par PR Git

Remplace la demande de changement v4 (`change_request` et commit par l'API). Voir [SRS ENF11](../SRS.md#5-exigences-non-fonctionnelles) et [SYSTEM_DESIGN S11](SYSTEM_DESIGN.md#10-décisions-adr).

Rendu : [svg](diagrams/svg/10-changement-configuration-pr.svg) · [png](diagrams/png/10-changement-configuration-pr.png)

```mermaid
flowchart LR
  AUT(["Analyste ou admin<br/>(auteur)"]) --> BR["Branche Git<br/>semantic/*.yaml"]
  BR --> PR["Pull request"]
  PR --> CI{"CI : validation des YAML,<br/>tests unitaires des KPI,<br/>anti-fuite exemples / test,<br/>tests de l'agent"}
  CI -- rouge --> BR
  CI -- verte --> REV{"Relecteur différent de l'auteur<br/>(branche protégée)"}
  REV -- "modifications demandées" --> BR
  REV -- approuvée --> MER["Fusion sur la branche principale"]
  MER --> DEP["Redéploiement de l'API"]
  DEP --> SV["Lecture des YAML au démarrage<br/>nouvelle semantic_version"]
  SV --> BO["B05 Configuration (lecture)<br/>et traces query_log / eval_run"]
```

## 11. Signalement (états réduits)

Trois états ; la promotion vers le dev est une option du traitement. Voir [AGENTIC_DESIGN §12](AGENTIC_DESIGN.md#12-retours-des-utilisateurs).

Rendu : [svg](diagrams/svg/11-signalement.svg) · [png](diagrams/png/11-signalement.png)

```mermaid
stateDiagram-v2
  [*] --> nouveau: l'utilisateur signale (RF10)
  nouveau --> traite: l'analyste reproduit et traite
  nouveau --> rejete: motif obligatoire
  traite --> [*]
  rejete --> [*]
  note right of traite
    Option : promoted_to_dev = vrai
    (ajout au jeu de dev, jamais au test)
  end note
```

## 12. Pipeline d'évaluation (v5)

Test seul pour O1, pass^3 de référence, ablations (a)-(e), banc HTTP pour O2. Voir [SRS §11](../SRS.md#11-évaluation-et-critères-dacceptation).

Rendu : [svg](diagrams/svg/12-evaluation.svg) · [png](diagrams/png/12-evaluation.png)

```mermaid
flowchart LR
  GEN["Générateur (graine, REFERENCE_DATE)"] --> DBT["dbt + tests"]
  DBT --> REF["Références recalculées<br/>(SQL relus par une seconde personne)"]
  TEST["test (40, hash figé,<br/>5 exécutions max par jalon)"] --> RUN
  DEV["dev (~40)"] --> RUN
  OTH["intent (~60), followup (~12),<br/>security (25 + 5 indirectes),<br/>regression, analysis (12 + 4)"] --> RUN
  RUN["make eval : Agent.answer direct,<br/>3 passes, sans cache de réponses ni de SQL,<br/>fallbacks désactivé"] --> CMP["compare.py : résultat exécuté,<br/>faits cités (registre), resolved_state,<br/>outil terminal"]
  REF --> CMP
  CMP --> STAT["pass^3 + Wilson (test seul)<br/>pass@1 + bootstrap groupé<br/>comptes bruts par catégorie"]
  STAT --> ABL["Ablations a-e appariées (McNemar),<br/>descriptives"]
  STAT --> BO["eval_run / eval_result :<br/>back-office B11"]
  BENCH["make bench : banc HTTP (O2)"] --> BO
  FB["Signalements promus"] -- "jamais vers le test" --> DEV
```

## 13. Déploiement (compose)

Le navigateur ne parle qu'au proxy ; `make eval` appelle l'agent directement. Voir [SYSTEM_DESIGN §7](SYSTEM_DESIGN.md#7-déploiement).

Rendu : [svg](diagrams/svg/13-deploiement.svg) · [png](diagrams/png/13-deploiement.png)

```mermaid
flowchart TB
  user(("Navigateur")) --> proxy
  subgraph H["Hôte : docker compose"]
    proxy["proxy : Caddy 2<br/>TLS, CSP, HSTS<br/>/ SPA statique, /api, /auth"]
    api["api : FastAPI + agent<br/>(MCP en sous-processus stdio)"]
    kc["keycloak 26.x<br/>(realm versionné, mode production)"]
    pg[("postgres 17<br/>warehouse + keycloak")]
    mail["mailpit (développement)"]
  end
  proxy --> api
  proxy --> kc
  api -- "app_rw ; agent_ro via MCP" --> pg
  api -- JWKS --> kc
  kc --> pg
  kc --> mail
  api --> llm["API Claude"]
  seed["make seed : générateur, dbt build, test de droits"] --> pg
  mig["make migrate : Alembic (app_owner)"] --> pg
  ev["make eval : Agent.answer direct (app_rw pour eval_run)"] --> pg
  ev --> llm
  bench["make bench : banc HTTP"] --> proxy
```
