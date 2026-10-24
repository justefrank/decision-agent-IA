# Tâches du projet (espace de travail uv, Postgres local, dbt, compose).
# Variables surchargeables : make seed SCALE=0.02 PG_PORT=55410
# Un fichier .env (copie de .env.example) est lu s'il existe.
-include .env
export

SHELL := /bin/bash
.DEFAULT_GOAL := help

PG_PORT ?= 55432
PG_HOST ?= localhost
SCALE ?= 1.0
SEED ?= 42

# Postgres de développement (scripts/dev_pg.sh) : mot de passe de chaque rôle = son nom.
DBT_PG_HOST ?= $(PG_HOST)
DBT_PG_PORT ?= $(PG_PORT)
DBT_PG_USER ?= dbt_owner
DBT_PG_PASSWORD ?= dbt_owner
DBT_PG_DBNAME ?= warehouse
DBT_OWNER_DSN ?= postgresql://$(DBT_PG_USER):$(DBT_PG_PASSWORD)@$(DBT_PG_HOST):$(DBT_PG_PORT)/$(DBT_PG_DBNAME)
AGENT_RO_DSN ?= postgresql://agent_ro:agent_ro@$(PG_HOST):$(PG_PORT)/warehouse
OWNER_DATABASE_URL ?= postgresql://app_owner:app_owner@$(PG_HOST):$(PG_PORT)/warehouse
APP_DATABASE_URL ?= postgresql://app_rw:app_rw@$(PG_HOST):$(PG_PORT)/warehouse

# dbt isolé de l'espace de travail (versions figées dans warehouse/requirements.txt).
DBT_PROFILES_DIR := $(CURDIR)/warehouse
DBT_CORE := $(shell grep -E '^dbt-core==' warehouse/requirements.txt)
DBT := uvx --python 3.12 --with-requirements warehouse/requirements.txt --from '$(DBT_CORE)' dbt
DBT_FLAGS := --project-dir warehouse
RIGHTS_REPORT ?= var/rights-test.json
COMPOSE := docker compose -f infra/compose.yaml

.PHONY: help sync db-up db-down seed generate dbt-build dbt-run rights-test migrate api eval test \
        lint secrets compose-up compose-down init reset dev-token api-dev create-admin create-user

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

rights-test: ## Droits de agent_ro, avant puis après un second dbt run (rapport var/rights-test.json)
	uv run python warehouse/scripts/check_agent_ro_rights.py --dsn '$(AGENT_RO_DSN)' \
	  --phase avant --report $(RIGHTS_REPORT)
	$(DBT) run $(DBT_FLAGS)
	uv run python warehouse/scripts/check_agent_ro_rights.py --dsn '$(AGENT_RO_DSN)' \
	  --phase apres_dbt_run --report $(RIGHTS_REPORT) --merge

migrate: ## Migrations Alembic du schéma app (rôle app_owner)
	uv run alembic -c packages/api/alembic.ini upgrade head

api: ## API en développement (uvicorn, rechargement)
	uv run uvicorn decision_api.main:app --reload --host 127.0.0.1 --port 8000

eval: ## Évaluation sur le jeu de test (agent appelé directement)
	uv run python -m decision_eval run --split test

test: ## Tests pytest de tous les paquets
	uv run pytest -q

lint: ## Ruff sur les paquets et scripts
	uv run ruff check packages warehouse/scripts

secrets: ## Crée les secrets Docker manquants (infra/secrets/*.txt, aléatoires)
	@mkdir -p infra/secrets
	@for s in postgres_password dbt_owner_password app_owner_password app_rw_password \
	          agent_ro_password keycloak_db_password keycloak_admin_password log_pseudonym_key; do \
	  f=infra/secrets/$$s.txt; \
	  if [ ! -f $$f ]; then (umask 077; openssl rand -hex 24 > $$f); echo "créé $$f"; fi; \
	done
	@f=infra/secrets/anthropic_api_key.txt; if [ ! -f $$f ]; then (umask 077; : > $$f); \
	  echo "créé $$f (vide : y mettre la clé API Claude)"; fi

compose-up: secrets ## Lance la pile compose (profil dev : Mailpit)
	$(COMPOSE) --profile dev up -d --build

compose-down: ## Arrête la pile compose
	$(COMPOSE) --profile dev down

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
