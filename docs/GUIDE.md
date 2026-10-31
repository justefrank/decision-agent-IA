# Guide d'utilisation et de lancement

Ce guide explique ce que fait l'application, comment elle est construite et comment la lancer, avec ou
sans Docker. Les choix de conception sont détaillés dans [SYSTEM_DESIGN.md](SYSTEM_DESIGN.md) et
[AGENTIC_DESIGN.md](AGENTIC_DESIGN.md) ; les exigences dans [SRS.md](../SRS.md).

## 1. L'application

Un décideur pose une question en français sur des transactions mobile money (Wave, Sénégal ; données
synthétiques) : « Quel est le chiffre d'affaires ce mois-ci ? », « Top 5 des régions par frais en
septembre », « Le taux d'échec a-t-il augmenté ? ». L'agent répond par un chiffre, une phrase, un
graphique et la **chaîne de preuve** du calcul : table, filtre, période, opération.

Ce qui rend les chiffres fiables :

- **Le modèle ne calcule pas.** Claude choisit un outil et ses paramètres ; les chiffres viennent de
  requêtes SQL exécutées sur l'entrepôt. Dans sa réponse, Claude cite des références (`{{f1}}`) que le code
  remplace par la valeur réelle, formatée en français.
- **Un chemin certifié pour les KPI.** Les six indicateurs (volume, valeur transférée, revenus de frais,
  clients actifs, agents actifs, taux d'échec) sont définis une fois dans `semantic/kpis.yaml` et compilés
  en SQL par le code (`query_metric`). Les autres questions passent par du SQL généré, contrôlé par un
  garde et étiqueté « calcul ad hoc ».
- **Lecture seule.** L'agent n'accède aux données que par un serveur MCP qui détient un rôle Postgres
  `agent_ro` sans aucun droit d'écriture ; chaque requête est analysée (liste blanche sur l'arbre SQL)
  avant d'être exécutée.
- **Tout est tracé.** Chaque appel d'outil et chaque appel au modèle est journalisé (`app.query_log`) avec
  son coût, sa durée et la version des règles utilisées.

### Les pages

| Page | Rôles | Contenu |
|---|---|---|
| Questions | tous | Fil de questions et réponses, historique, signalement d'une réponse fausse. L'analyste et l'admin voient aussi le SQL exécuté |
| Indicateurs | tous | Relevé des six KPI par mois et par région, et analyse de l'agent (constats sourcés, hypothèses étiquetées) |
| Administration | analyste, admin | Exploitation (latence, coût), journal d'audit, évaluation, signalements, catalogue de KPI, couche sémantique ; l'admin voit aussi Sécurité et Paramètres |

Trois rôles, gérés dans Keycloak : **décideur** (questions et indicateurs, jamais de SQL), **analyste**
(en plus : SQL, administration en lecture), **admin** (en plus : sécurité, paramètres). Analyste et admin
doivent utiliser un code de vérification (OTP).

### La date de référence

Les données s'arrêtent au **30 septembre 2026**, qui tient lieu d'« aujourd'hui » : « ce mois-ci » veut
dire septembre 2026, « le mois dernier » août 2026. Pour la changer : `reference_date` dans
`semantic/config.yaml` (et régénérer les données si besoin).

## 2. Architecture en bref

```
Navigateur ──► Caddy (https://localhost, même origine)
                 ├── /            interface web (React, web/dist)
                 ├── /api/*       API FastAPI ──► Claude (API Anthropic)
                 │                  └── serveur MCP (sous-processus) ──► Postgres, rôle agent_ro, lecture seule
                 └── /auth/*      Keycloak (connexion, OTP)
Postgres 17 : base warehouse (raw → analytics en étoile par dbt ; app : conversations, journaux) + base keycloak
```

| Composant | Rôle | Dossier |
|---|---|---|
| Générateur | Données synthétiques réalistes (jusqu'à 2,2 M de transactions) | `packages/data_gen` |
| dbt | Modèle en étoile et 53 tests de qualité, dont les six KPI figés | `warehouse/` |
| Couche sémantique | Tables, KPI, glossaire, exemples, paramètres (YAML, modifiés par PR) | `semantic/` |
| Garde SQL et serveur MCP | Seule porte d'accès aux données pour l'agent | `packages/sql_guard`, `packages/mcp_server` |
| Agent | Boucle Claude, validation des chiffres, état de la conversation | `packages/agent` |
| API | Authentification, conversations en flux, journaux, administration | `packages/api` |
| Interface | Questions, indicateurs, administration | `web/` |
| Évaluation | Jeux de questions, comparaison aux références, statistiques | `packages/eval`, `eval/` |
| Infrastructure | Compose, Caddy, Keycloak, scripts d'initialisation Postgres | `infra/` |

## 3. Choisir un mode de lancement

| | Avec Docker (recommandé) | Sans Docker |
|---|---|---|
| Prérequis | Docker et Compose v2 | uv, binaires Postgres 16+, Node 22 (pour l'interface) |
| Connexion | Keycloak réel (mot de passe, OTP), ou jetons de développement | Jetons de développement (boutons de rôle), sans Keycloak |
| Adresse | https://localhost | http://localhost:5173 (interface) et http://127.0.0.1:8000 (API) |
| Usage | Démonstration, essai complet, évaluation | Développement rapide du code |

Les deux modes utilisent les mêmes commandes `make` : en mode Docker, elles sont préfixées par `dc-` et
s'exécutent dans un conteneur « outils » qui contient Python, uv, dbt et psql. `make help` liste toutes les
commandes.

## 4. Lancer avec Docker

### Premier lancement

```bash
git clone https://github.com/justefrank/decision-agent-IA.git && cd decision-agent-IA
make dc-init           # 1. secrets, pile, migrations, données factices, dbt, test de droits (~3 min la 1re fois)
make dc-web-build      # 2. construit l'interface dans un conteneur Node
make restart S=proxy   #    et la fait servir par Caddy
```

`make dc-init` crée les secrets dans `infra/secrets/` (mots de passe aléatoires, jamais versionnés), lance
Postgres, Keycloak, l'API, Caddy et Mailpit, applique les migrations, génère les données à l'échelle 0,05
(110 000 transactions) et vérifie les droits du rôle `agent_ro`.

### Clé Claude

Sans clé, l'API démarre mais l'agent répond « service indisponible ». Mettez la clé **dans l'un des deux
endroits** (jamais dans un fichier versionné, jamais dans un chat) :

- `infra/secrets/anthropic_api_key.txt` (recommandé), sur une seule ligne ;
- ou `ANTHROPIC_API_KEY=sk-ant-…` dans le fichier `.env` à la racine (utilisé si le fichier secret est vide).

Puis `make up` (ou `make restart S=api` si vous avez modifié le fichier secret). Vérification :

```bash
docker compose -f infra/compose.yaml exec -T api python -c \
  "import urllib.request;print(urllib.request.urlopen('http://127.0.0.1:8000/api/health').read().decode())"
# attendu : "status":"ok", "agent":"ok"
```

### Premier compte

```bash
make dc-admin EMAIL=prenom.nom@exemple.sn           # administrateur
make dc-user EMAIL=decideur@exemple.sn ROLE=decideur # ou ROLE=analyste
```

La commande affiche un **mot de passe temporaire** une seule fois. Ouvrez https://localhost, acceptez
l'alerte de certificat (autorité locale de Caddy), connectez-vous, changez le mot de passe, puis (analyste et
admin) enrôlez une application d'authentification (Google Authenticator, Aegis…) en scannant le QR code.
Les courriels de Keycloak (mot de passe oublié) arrivent dans Mailpit : http://localhost:8025.

### Mode développement en conteneurs

Pour appeler l'API sans Keycloak (Swagger, jetons locaux, OTP non exigé) :

```bash
make dev-up                  # API sur http://127.0.0.1:8000/api/docs
make dc-token ROLE=admin     # jeton à coller dans « Authorize » de Swagger
make web-dev-dc              # interface en développement sur http://localhost:5173 (nécessite Node 22)
```

### Au quotidien

| Besoin | Commande |
|---|---|
| Arrêter / relancer (données conservées) | `make down` / `make up` |
| État des services, journaux | `make ps`, `make logs S=api` |
| Redémarrer un service | `make restart S=api` |
| Données à l'échelle de l'évaluation (2,2 M de transactions) | `make dc-seed SCALE=1.0` |
| Évaluer l'agent | `make dc-eval SPLIT=dev PASSES=1` (essai), `make dc-eval` (jeu de test, échelle 1.0 exigée) |
| Shell avec make, uv, dbt, psql | `make dc-shell` |
| Après une modification de dépendances (`uv.lock`) | `make dc-build` puis `make up` |
| Après une modification de `semantic/` ou du code de l'API | `make up` (l'image est reconstruite) |
| Après une modification de l'interface | `make dc-web-build` |
| Tout supprimer et recommencer | `make dc-reset` (**efface les données**) |

## 5. Lancer sans Docker

Prérequis : [uv](https://docs.astral.sh/uv/), les binaires Postgres 16 ou plus (paquet `postgresql`,
dans `/usr/lib/postgresql/*/bin`) et Node 22 pour l'interface.

```bash
make init                    # Postgres jetable (port 55432), données factices, dbt, droits, migrations (~20 s)
export ANTHROPIC_API_KEY=…   # ou dans .env
make api-dev                 # API sur http://127.0.0.1:8000, jetons de développement acceptés
```

Dans un second terminal :

```bash
make web-install             # une seule fois
make web-dev                 # interface sur http://localhost:5173
```

La page de connexion propose trois boutons (décideur, analyste, administrateur) : ce sont des jetons
signés localement, sans Keycloak, refusés en production. Pour appeler l'API directement :
`make dev-token ROLE=admin`.

| Besoin | Commande |
|---|---|
| Arrêter Postgres | `make db-down` |
| Repartir de zéro | `make reset` |
| Données complètes | `make seed SCALE=1.0` |
| Évaluer | `make eval SPLIT=dev PASSES=1` |
| Tests et lint (Python) | `make test lint` |
| Tests de l'interface | `make web-check`, `make web-e2e` (180 tests de bout en bout, sans backend) |
| Autre port | ajouter `PG_PORT=55410` à chaque commande |

## 6. Poser une question

1. Ouvrez **Questions** et tapez votre question (Entrée envoie, Maj+Entrée saute une ligne).
2. Les étapes du calcul s'affichent, puis la réponse : chiffre clé, phrase, graphique, et l'origine du
   calcul. Le badge indique **calcul certifié** (KPI du catalogue) ou **calcul ad hoc** (SQL généré).
3. Si la question est ambiguë, l'agent propose deux ou trois choix : cliquez sur l'un d'eux.
4. Une réponse vous paraît fausse : **Signaler la réponse**. L'analyste la retrouve dans
   Administration › Signalements.

Exemples de questions : « Quel est le chiffre d'affaires ce mois-ci ? », « Revenus de frais par région
en septembre », « Combien de clients actifs ce mois-ci ? », « Le taux d'échec a-t-il augmenté par rapport
au mois précédent ? ». Une réponse coûte environ 0,01 à 0,06 $ et prend 3 à 15 s.

## 7. Dépannage

| Symptôme | Cause et solution |
|---|---|
| L'agent répond « service indisponible » ; `/api/health` montre `"agent":"down"` | Clé Claude absente : voir §4, « Clé Claude » |
| `make dc-init` : `service "migrate" didn't complete successfully` et dans `docker logs decision-migrate-1` : `Temporary failure in name resolution` | Le conteneur Postgres s'est détaché du réseau Docker. `docker compose -f infra/compose.yaml up -d --force-recreate postgres` puis `make dc-init` (données conservées) |
| `Failed to initialize cache at /tmp/uv-cache … Permission denied` | Image outils ancienne : `make dc-build` |
| `make dc-web-build` : `EACCES … /app/dist` | `web/dist` appartient à root (créé par Docker). `docker run --rm -v "$PWD/web:/w" busybox chown $(id -u):$(id -g) /w/dist` |
| https://localhost affiche une page d'attente | Interface non construite : `make dc-web-build` puis `make restart S=proxy` |
| Alerte de certificat dans le navigateur | Normal : certificat de l'autorité locale de Caddy. Pour l'importer : `docker compose -f infra/compose.yaml cp proxy:/data/caddy/pki/authorities/local/root.crt .` |
| Connexion refusée : « vérification en deux étapes requise » | Rôle analyste ou admin : la session doit porter un code OTP. Se reconnecter et saisir le code |
| Erreur `invalid redirect URI` à la connexion Keycloak | Le realm a été importé avec un autre `PUBLIC_HOST`. `--import-realm` n'écrase pas un realm existant : supprimer le realm `decision` (ou `make dc-reset` en développement) |
| Port 80, 443 ou 5432 déjà utilisé | Arrêter le service qui l'occupe, ou `PG_PUBLISH_PORT=5433 make up` pour Postgres |
| Changement de mot de passe dans `infra/secrets/` sans effet | Les mots de passe Postgres ne sont lus qu'à la création du volume : `make dc-reset` |

Pour une réponse de l'agent qui semble fausse : Administration › Journal d'audit, filtrer par trace, et
ouvrir le détail (SQL réellement exécuté, résultats, coût).

## 8. Sécurité et données

- Aucun secret n'est versionné : `infra/secrets/*.txt` et `.env` sont ignorés par git ; la CI exécute un
  scan de secrets à chaque PR.
- Les données sont **synthétiques**. Les questions et les résultats agrégés sont envoyés à l'API Claude :
  à revoir avant tout usage sur des données réelles.
- Les journaux ne contiennent jamais le texte des questions (seulement une empreinte) ; l'identité des
  utilisateurs y est pseudonymisée. La lecture du détail d'un appel est elle-même journalisée.
- Les journaux de plus de 90 jours sont supprimés chaque jour par le service `logs-purge`.
