# Tâches du projet (espace de travail uv, Postgres local, dbt, compose).
# Variables surchargeables : make seed SCALE=0.02 PG_PORT=55410
# Un fichier .env (copie de .env.example) est lu s'il existe.
-include .env
export

SHELL := /bin/bash
.DEFAULT_GOAL := help

PG_PORT ?= 55432
PG_HOST ?= localhost
PG_DATABASE ?= warehouse
SCALE ?= 1.0
SEED ?= 42

# Postgres de développement (scripts/dev_pg.sh) : mot de passe de chaque rôle = son nom.
# Seuls les COMPOSANTS sont surchargeables (.env, ligne de commande) ; les DSN en sont toujours
# calculés (affectation simple « = » : un DSN figé dans .env ne masque pas `make seed PG_PORT=…`).
APP_RW_PASSWORD ?= app_rw
APP_OWNER_PASSWORD ?= app_owner
AGENT_RO_PASSWORD ?= agent_ro
DBT_PG_USER ?= dbt_owner
DBT_PG_PASSWORD ?= dbt_owner
DBT_PG_HOST = $(PG_HOST)
DBT_PG_PORT = $(PG_PORT)
DBT_PG_DBNAME = $(PG_DATABASE)
DBT_OWNER_DSN = postgresql://$(DBT_PG_USER):$(DBT_PG_PASSWORD)@$(DBT_PG_HOST):$(DBT_PG_PORT)/$(DBT_PG_DBNAME)
AGENT_RO_DSN = postgresql://agent_ro:$(AGENT_RO_PASSWORD)@$(PG_HOST):$(PG_PORT)/$(PG_DATABASE)
OWNER_DATABASE_URL = postgresql://app_owner:$(APP_OWNER_PASSWORD)@$(PG_HOST):$(PG_PORT)/$(PG_DATABASE)
APP_DATABASE_URL = postgresql://app_rw:$(APP_RW_PASSWORD)@$(PG_HOST):$(PG_PORT)/$(PG_DATABASE)
RETENTION_DAYS ?= 90

# dbt isolé de l'espace de travail (versions figées dans warehouse/requirements.txt).
DBT_PROFILES_DIR := $(CURDIR)/warehouse
DBT_CORE := $(shell grep -E '^dbt-core==' warehouse/requirements.txt)
DBT ?= uvx --python 3.12 --with-requirements warehouse/requirements.txt --from '$(DBT_CORE)' dbt
DBT_FLAGS := --project-dir warehouse
RIGHTS_REPORT ?= var/reports/rights-test.json
COMPOSE := docker compose -f infra/compose.yaml

.PHONY: help sync db-up db-down seed generate dbt-build dbt-run rights-test migrate api eval test \
        lint secrets compose-up compose-down init reset dev-token api-dev create-admin create-user \
        web-install web-dev web-dev-dc web-build web-check dc-web-build up dev-up down logs ps restart dc-build dc-init dc-seed dc-rights-test dc-migrate dc-admin dc-user \
        dc-token dc-eval dc-shell dc-reset \
        purge-logs

help: ## Liste des cibles
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-14s %s\n", $$1, $$2}'

sync: ## Installe tous les paquets Python (uv)
	uv sync --all-packages

db-up: ## Démarre un Postgres local jetable sur PG_PORT (sans Docker)
	scripts/dev_pg.sh start $(PG_PORT)

db-down: ## Arrête le Postgres local
	scripts/dev_pg.sh stop /tmp/decision-pg/$(PG_PORT)

generate: ## Génère et charge raw (SCALE, SEED) ; imprime data_hash
	uv run python -m decision_data_gen --scale $(SCALE) --seed $(SEED) --dsn '$(DBT_OWNER_DSN)'

dbt-build: ## dbt build : modèles analytics + tests (données, unitaires KPI)
	$(DBT) build $(DBT_FLAGS)

dbt-run: ## dbt run seul
	$(DBT) run $(DBT_FLAGS)

seed: generate dbt-build ## Générateur → raw → dbt build

rights-test: ## Droits de agent_ro, avant puis après un second dbt run (rapport var/reports/)
	uv run python warehouse/scripts/check_agent_ro_rights.py --dsn '$(AGENT_RO_DSN)' \
	  --phase avant --report $(RIGHTS_REPORT)
	$(DBT) run $(DBT_FLAGS)
	uv run python warehouse/scripts/check_agent_ro_rights.py --dsn '$(AGENT_RO_DSN)' \
	  --phase apres_dbt_run --report $(RIGHTS_REPORT) --merge

migrate: ## Migrations Alembic du schéma app (rôle app_owner)
	uv run alembic -c packages/api/alembic.ini upgrade head

purge-logs: ## Purge app.query_log au-delà de RETENTION_DAYS (90 j) avec app_owner (tâche planifiée)
	uv run python -m decision_api.cli purge-logs --days $(RETENTION_DAYS)

api: ## API en développement (uvicorn, rechargement)
	uv run uvicorn decision_api.main:app --reload --host 127.0.0.1 --port 8000

SPLIT ?= test
eval: ## Évaluation (agent appelé directement) ; SPLIT=test|dev|intent|followup, PASSES=3
	EVAL_META_DSN='$(DBT_OWNER_DSN)' uv run python -m decision_eval run --split $(SPLIT) --passes $(or $(PASSES),3)

test: ## Tests pytest de tous les paquets
	uv run pytest -q

lint: ## Ruff sur les paquets et scripts
	uv run ruff check packages warehouse/scripts

secrets: ## Crée les secrets Docker manquants (infra/secrets/*.txt, aléatoires)
	@# Dossier 700 (protège les secrets sur l'hôte) ; fichiers 644 : Compose (hors Swarm) les monte
	@# tels quels et Postgres, Keycloak et l'API les lisent sous d'autres UID que le vôtre.
	@mkdir -p infra/secrets && chmod 700 infra/secrets
	@for s in postgres_password dbt_owner_password app_owner_password app_rw_password \
	          agent_ro_password keycloak_db_password keycloak_admin_password log_pseudonym_key; do \
	  f=infra/secrets/$$s.txt; \
	  if [ ! -f $$f ]; then openssl rand -hex 24 > $$f; echo "créé $$f"; fi; \
	done
	@f=infra/secrets/anthropic_api_key.txt; if [ ! -f $$f ]; then : > $$f; \
	  echo "créé $$f (vide : y mettre la clé API Claude)"; fi
	@chmod 644 infra/secrets/*.txt

compose-up: up ## Alias de make up

compose-down: down ## Alias de make down

# --- Démarrage rapide en local (sans Docker) ------------------------------------------------------
INIT_SCALE ?= 0.05
ROLE ?= admin
EMAIL ?=
DEV_JWKS := file://$(CURDIR)/var/dev-auth/jwks.json

init: ## Tout en une commande : Postgres local, données factices (INIT_SCALE), dbt, droits, migrations
	uv sync --all-packages --frozen
	$(MAKE) --no-print-directory db-up
	$(MAKE) --no-print-directory seed SCALE=$(INIT_SCALE)
	$(MAKE) --no-print-directory rights-test
	$(MAKE) --no-print-directory migrate
	uv run python -m decision_api.cli dev-token --role admin --quiet > /dev/null
	@echo ""
	@echo "Prêt. Données factices à l'échelle $(INIT_SCALE) sur le port $(PG_PORT)."
	@echo "  make api-dev                 API locale (jetons de développement, sans Keycloak)"
	@echo "  make dev-token ROLE=admin    jeton administrateur (ou analyste, decideur)"

reset: ## Supprime le Postgres local puis relance init (données régénérées)
	-$(MAKE) --no-print-directory db-down
	rm -rf /tmp/decision-pg/$(PG_PORT)
	$(MAKE) --no-print-directory init

dev-token: ## Jeton JWT local signé pour ROLE (admin | analyste | decideur), sans Keycloak
	@uv run python -m decision_api.cli dev-token --role $(ROLE)

api-dev: ## API locale qui accepte les jetons de développement (make dev-token)
	@test -f var/dev-auth/jwks.json || uv run python -m decision_api.cli dev-token --quiet > /dev/null
	ENVIRONMENT=dev KEYCLOAK_JWKS_URL='$(DEV_JWKS)' AGENT_RO_DSN='$(AGENT_RO_DSN)' \
	  APP_DATABASE_URL='$(APP_DATABASE_URL)' \
	  uv run uvicorn decision_api.main:app --reload --host 127.0.0.1 --port 8000

create-admin: ## Crée un administrateur dans Keycloak : make create-admin EMAIL=prenom.nom@exemple.sn
	@test -n "$(EMAIL)" || (echo "EMAIL requis : make create-admin EMAIL=..." && exit 2)
	uv run python -m decision_api.cli create-user --email '$(EMAIL)' --role admin

create-user: ## Crée un utilisateur Keycloak : make create-user EMAIL=... ROLE=decideur|analyste|admin
	@test -n "$(EMAIL)" || (echo "EMAIL requis" && exit 2)
	uv run python -m decision_api.cli create-user --email '$(EMAIL)' --role $(ROLE)

# --- Mode conteneurs (Docker sur votre machine) ---------------------------------------------------
# Les cibles dc-* lancent les cibles ci-dessus dans le conteneur « tools » (réseau Docker, secrets) :
# même Makefile, mêmes commandes, mais Postgres et Keycloak joints par leur nom de service.
DC_FILES := -f infra/compose.yaml
DEV ?=
ifeq ($(DEV),1)
DC_FILES += -f infra/compose.dev.yaml
endif
DC := HOST_UID=$$(id -u) HOST_GID=$$(id -g) docker compose $(DC_FILES) --profile dev
DC_TOOLS := $(DC) --profile tools run --rm -T tools   # -T : sans terminal (appelable par un script)

up: secrets ## Conteneurs : lance la pile (Postgres, Keycloak, migrations, API, Caddy, Mailpit)
	@mkdir -p var/reports var/dev-auth
	@test -f web/dist/index.html || echo "Interface non construite : make dc-web-build (ou make web-build) puis make restart S=proxy"
	$(DC) up -d --build

dev-up: ## Conteneurs, développement : API sur 127.0.0.1:8000 avec jetons locaux et Swagger
	@$(MAKE) --no-print-directory up DEV=1
	@$(MAKE) --no-print-directory dc-token DEV=1 ROLE=admin >/dev/null
	@echo "API : http://127.0.0.1:8000/api/docs ; jeton : make dc-token ROLE=admin"

down: ## Conteneurs : arrête la pile (les données restent dans le volume pgdata)
	$(DC) --profile tools down

logs: ## Conteneurs : suit les journaux (make logs S=api pour un seul service)
	$(DC) logs -f --tail=100 $(S)

restart: ## Conteneurs : redémarre un service (make restart S=api, après un changement de secret)
	$(DC) restart $(S)

ps: ## Conteneurs : état des services
	$(DC) ps

dc-build: ## Conteneurs : reconstruit les images (API et outils), après un changement de uv.lock
	$(DC) --profile tools build

dc-init: up ## Conteneurs : pile + données factices (INIT_SCALE) + test de droits, en une commande
	$(DC_TOOLS) make seed SCALE=$(INIT_SCALE)
	$(DC_TOOLS) make rights-test
	@echo ""
	@echo "Prêt. Données factices à l'échelle $(INIT_SCALE) dans le Postgres des conteneurs."
	@echo "  make dc-admin EMAIL=prenom.nom@exemple.sn   administrateur Keycloak"
	@echo "  make dev-up && make dc-token ROLE=admin      API de développement avec jeton local"

dc-seed: ## Conteneurs : (re)génère les données factices (SCALE, défaut 1.0) et lance dbt
	$(DC_TOOLS) make seed SCALE=$(SCALE)

dc-rights-test: ## Conteneurs : test de droits de agent_ro (rapport lu par /api/admin/security)
	$(DC_TOOLS) make rights-test

dc-migrate: ## Conteneurs : migrations Alembic (déjà lancées à chaque make up)
	$(DC) run --rm migrate

dc-admin: ## Conteneurs : crée un administrateur Keycloak : make dc-admin EMAIL=...
	@test -n "$(EMAIL)" || (echo "EMAIL requis : make dc-admin EMAIL=..." && exit 2)
	$(DC_TOOLS) python -m decision_api.cli create-user --email '$(EMAIL)' --role admin

dc-user: ## Conteneurs : crée un utilisateur Keycloak : make dc-user EMAIL=... ROLE=decideur
	@test -n "$(EMAIL)" || (echo "EMAIL requis" && exit 2)
	$(DC_TOOLS) python -m decision_api.cli create-user --email '$(EMAIL)' --role $(ROLE)

dc-token: ## Conteneurs : jeton local pour ROLE (accepté seulement par make dev-up)
	@$(DC_TOOLS) python -m decision_api.cli dev-token --role $(ROLE) --quiet

dc-eval: ## Conteneurs : évaluation (clé dans infra/secrets/anthropic_api_key.txt) ; SPLIT, PASSES
	$(DC_TOOLS) make eval SPLIT=$(SPLIT) PASSES=$(or $(PASSES),3)

dc-shell: ## Conteneurs : shell dans le conteneur outils (make, uv, dbt, psql)
	$(DC) --profile tools run --rm tools bash

dc-reset: ## Conteneurs : supprime TOUTES les données (volumes) puis relance dc-init
	$(DC) --profile tools down -v
	@$(MAKE) --no-print-directory dc-init

# --- Interface web (web/ : Vite + React + TypeScript) ---------------------------------------------
NODE_IMAGE ?= node:22.22-bookworm-slim

web-install: ## Interface : installe les dépendances (npm ci)
	cd web && npm ci --no-audit --no-fund

web-dev: ## Interface : serveur de développement http://localhost:5173 (jetons locaux ; API : make api-dev ou dev-up)
	cd web && npm run dev

web-dev-dc: ## Interface : serveur de développement avec les jetons et l'API des conteneurs (make dev-up)
	cd web && DEV_TOKEN_CMD="make -s dc-token ROLE={role}" npm run dev

web-check: ## Interface : types, lint et tests
	cd web && npm run typecheck && npm run lint && npm run test

web-build: ## Interface : construit web/dist (servi par Caddy, make up)
	cd web && npm ci --no-audit --no-fund && npm run build

dc-web-build: ## Interface en conteneur : construit web/dist avec Node dans Docker (sans Node sur l'hôte)
	docker run --rm -u $$(id -u):$$(id -g) -e HOME=/tmp -v "$(CURDIR)/web:/app" -w /app $(NODE_IMAGE) \
	  sh -c "npm ci --no-audit --no-fund && npm run build"
