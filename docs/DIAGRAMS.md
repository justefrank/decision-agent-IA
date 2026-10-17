# Diagrammes

Générés depuis `docs/diagrams/*.mmd` (Mermaid). Les rendus `svg/` et `png/` sont dans le même dossier. Sources : [SRS.md](../SRS.md), [SYSTEM_DESIGN.md](SYSTEM_DESIGN.md), [AGENTIC_DESIGN.md](AGENTIC_DESIGN.md).

Régénérer : `npx @mermaid-js/mermaid-cli -i docs/diagrams/NN-nom.mmd -o docs/diagrams/svg/NN-nom.svg`.

## 1. Architecture d'ensemble

```mermaid
flowchart LR
  subgraph Client
    UI["Web React + Vite"]
  end
  KC["Keycloak OIDC"]
  subgraph API["API FastAPI (un processus)"]
    R["Routes + auth JWT"]
    AG["Agent"]
    MCP["Serveur MCP (sous-processus stdio)"]
  end
  subgraph PG["Postgres 16"]
    RAW["schéma raw"]
    ANA["schéma analytics"]
    APP["schéma app"]
  end
  GEN["Générateur Python"] --> RAW
  RAW -- "dbt (dbt_owner)" --> ANA
  UI -- "Code + PKCE" --> KC
  UI -- "Bearer JWT, fetch + flux" --> R
  R -- JWKS --> KC
  R --> AG
  AG -- outils --> MCP
  MCP -- "agent_ro (lecture)" --> ANA
  R -- "app_rw" --> APP
  AG <--> LLM["API LLM externe"]
```

## 2. Acteurs et droits

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
  BASE["Socle applicatif<br/>Poser une question (RF1, RF2, RF14)<br/>Graphiques (RF3)<br/>Historique et suivi (RF5, RF6)<br/>Tableau de bord et analyse (RF4, RF17)<br/>Signaler une réponse (RF10)<br/>Connexion et récupération d'accès (RF15, RF16)"]
  SQLV["Voir le SQL et les tables (RF8)"]
  BOR["Back-office analyste<br/>Catalogue KPI (RF9)<br/>Couche sémantique (RF18)<br/>Journal d'audit (RF13)<br/>Évaluation (RF19)<br/>Signalements"]
  BOA["Back-office administrateur seul<br/>Utilisateurs et rôles (RF11)<br/>Sécurité et exploitation (RF20)<br/>Paramètres (RF12)"]
```

## 3. Modèle analytique en étoile

```mermaid
erDiagram
  dim_client ||--o{ fact_transaction : "client_id"
  dim_agent ||--o{ fact_transaction : "agent_id (-1 = hors agent)"
  dim_region ||--o{ dim_client : "region_client_id"
  dim_region ||--o{ dim_agent : "region_agent_id"
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
    text segment
  }
  dim_agent {
    int agent_id PK
    text nom
    text ville
    int region_agent_id FK
    date date_activation
    text statut_agent
  }
  dim_region {
    int region_id PK
    text region
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
  }
```

## 4. Tables applicatives

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
    text role
    text content
    jsonb structured_json
    timestamptz created_at
  }
  query_log {
    bigint id PK
    text trace_id
    int step
    int attempt
    text user_id
    text tool
    text sql
    int row_count
    bool truncated
    int duration_ms
    text status "ok error blocked"
    numeric cost_usd
    text prompt_version
    text semantic_version
    text model_id
  }
  feedback {
    bigint id PK
    uuid message_id FK
    text category
    bool consent_question
    text status
    bool promoted_to_dev
  }
  change_request {
    bigint id PK
    text kind "kpi semantic settings"
    text author_id
    text reviewer_id
    text status
    text diff_text
    text commit_sha
  }
  eval_run {
    bigint id PK
    text split "dev test"
    text prompt_version
    text semantic_version
    text model_id
    text git_sha
    int n
    int n_correct
    numeric ci_low
    numeric ci_high
  }
  eval_result {
    bigint run_id FK
    text question_id
    text category
    int passes
  }
  audit_access_log {
    bigint id PK
    text admin_id
    text action
    text target_trace_id
  }
  analysis {
    bigint id PK
    text period
    text region
    text semantic_version
    jsonb payload
  }
```

## 5. Flux d'une question

```mermaid
sequenceDiagram
  participant W as Web React
  participant A as API
  participant G as Agent
  participant M as MCP (stdio)
  participant D as Postgres
  W->>A: POST /conversations/{id}/messages (Bearer)
  A->>A: JWT, rôle, propriété (user_id = sub), quota
  A->>G: question + état résolu + 6 derniers échanges
  loop boucle d'outils (6 étapes max, 30 s)
    G->>M: get_kpi / describe_table / run_query
    M->>M: garde SQL (AST, liste blanche), EXPLAIN borné
    M->>D: SELECT (agent_ro, 10 s)
    D-->>M: lignes (1 001 max)
    M-->>G: lignes, durée, truncated
    A->>A: écrit query_log (étape, tentative)
  end
  G-->>A: AssistantMessage (validé)
  A->>A: retire le SQL si rôle décideur
  A-->>W: événements d'étape puis message final
```

## 6. Authentification (OIDC + PKCE)

```mermaid
sequenceDiagram
  actor U as Utilisateur
  participant W as Web React
  participant K as Keycloak
  participant A as API
  U->>W: ouvre l'application
  W->>K: redirection Authorization Code + PKCE
  K->>U: page de connexion (SSO ou e-mail + mot de passe)
  U->>K: identifiants
  K->>U: second facteur (MFA)
  U->>K: code
  K-->>W: code d'autorisation
  W->>K: échange code + verifier
  K-->>W: jeton d'accès (5 min, en mémoire)
  W->>A: requête avec Bearer
  A->>K: JWKS (en cache)
  A->>A: vérifie iss, aud, exp, RS256, rôle
  A-->>W: réponse
  Note over W,A: 20 s avant l'expiration, avertissement et prolongation
```

## 7. Boucle de l'agent

```mermaid
flowchart TD
  Q["Question + état résolu + historique"] --> L1["Tour 1 du modèle : intention"]
  L1 -- refuse --> R["Refus motivé"]
  L1 -- clarify --> C["Demande de précision"]
  L1 -- answer --> L["Boucle d'outils"]
  L -- get_kpi --> M[("MCP")]
  L -- "describe_table / run_query" --> M
  M --> G["Garde SQL + agent_ro"]
  G --> L
  L -- "erreur SQL, 2 corrections max" --> L
  L --> F["Formateur : graphique et dérivés calculés par le code"]
  F --> V["Validateur de sortie"]
  V --> A["AssistantMessage + query_log écrit par l'API"]
```

## 8. Garde SQL

```mermaid
flowchart TD
  S["SQL proposé par l'agent"] --> P{"Un seul SELECT ?"}
  P -- non --> X["Refus (status = blocked)"]
  P -- oui --> T{"Tables autorisées, qualifiées ?"}
  T -- non --> X
  T -- oui --> F{"Fonctions dans la liste fermée ?"}
  F -- non --> X
  F -- oui --> LI["LIMIT imposé sur l'AST"]
  LI --> E{"EXPLAIN : coût et jointures bornés ?"}
  E -- non --> X
  E -- oui --> R["Réécriture du SQL depuis l'AST validé"]
  R --> DB[("Postgres, rôle agent_ro, lecture seule, 10 s")]
  DB --> N["Erreurs normalisées, résultats lus en flux"]
```

## 9. Analyse du tableau de bord (RF17)

```mermaid
sequenceDiagram
  actor D as Décideur
  participant W as Web React
  participant A as API
  participant G as Agent (mode analyse)
  participant M as MCP
  D->>W: choisit période et région
  W->>A: GET /dashboard
  A->>M: get_kpi x 6 (période courante et précédente)
  M-->>A: valeurs
  A-->>W: tuiles des KPI
  W->>A: POST /dashboard/analysis
  A->>G: valeurs + dérivés calculés par le code
  Note over G: outil unique get_kpi, pas de SQL libre
  G-->>A: lead, constats (3 max), questions
  A->>A: validateur : chaque nombre a une source
  A->>A: enregistre app.analysis (version sémantique)
  A-->>W: constats avec confiance élevée, moyenne ou hypothèse
  D->>W: clique une question d'approfondissement
  W->>A: ouvre une conversation pré-remplie
```

## 10. Demande de changement (états)

```mermaid
stateDiagram-v2
  [*] --> brouillon
  brouillon --> en_revue: soumettre (validations automatiques)
  en_revue --> brouillon: validations échouées
  en_revue --> valide: relecteur différent de l'auteur
  en_revue --> rejete: relecteur
  valide --> applique: commit (sha enregistré)
  rejete --> [*]
  applique --> [*]
```

## 11. Signalement (états)

```mermaid
stateDiagram-v2
  [*] --> nouveau: l'utilisateur signale (RF10)
  nouveau --> en_analyse: l'analyste reproduit
  en_analyse --> corrige: correction livrée
  en_analyse --> rejete: motif obligatoire
  corrige --> dev_set: ajout au jeu de dev
  rejete --> [*]
  dev_set --> [*]
  note right of dev_set
    Jamais le jeu de test
  end note
```

## 12. Pipeline d'évaluation

```mermaid
flowchart LR
  GEN["Générateur de données (graine, REFERENCE_DATE)"] --> DBT["dbt + tests"]
  DBT --> REF["Références recalculées depuis les données"]
  DEV["eval/dev.yaml (~30)"] --> RUN
  TEST["eval/test.yaml (40, 5 exécutions max par jalon)"] --> RUN
  RUN["make eval : module agent direct, cache absent, 3 passes"] --> CMP["compare.py : résultat exécuté et chiffre cité"]
  REF --> CMP
  CMP --> STAT["Wilson 95 % + comptes bruts par catégorie"]
  STAT --> ABL["Ablations : sans exemples, sans get_kpi, sans validateur, modèle seul"]
  STAT --> BO["eval_run / eval_result : back-office Évaluation"]
  FB["Signalements validés"] -- "jamais vers le test" --> DEV
```

## 13. Déploiement

```mermaid
flowchart TB
  subgraph H["Hôte : docker compose"]
    web["web (React, CSP stricte)"]
    api["api (FastAPI + agent + MCP)"]
    kc["keycloak (realm versionné)"]
    pg[("postgres : raw / analytics / app")]
  end
  user(("Navigateur")) --> web
  user --> kc
  web --> api
  api --> kc
  api --> pg
  api --> llm["API LLM externe"]
  seed["make seed : générateur, chargement, dbt"] --> pg
  ev["make eval"] --> api
```
