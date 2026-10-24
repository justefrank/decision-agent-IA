#!/bin/sh
# Conteneur « outils » : lit les secrets Docker et les expose sous les noms attendus par le Makefile,
# puis lance la commande. `make …` est exécuté avec -e : l'environnement du conteneur (hôte postgres,
# mots de passe des secrets) l'emporte sur un éventuel .env de l'hôte monté avec le dépôt.
set -eu
SECRETS_DIR=${SECRETS_DIR:-/run/secrets}
s() { [ -f "$SECRETS_DIR/$1" ] && tr -d '\r\n' < "$SECRETS_DIR/$1"; }

if v=$(s dbt_owner_password); then export DBT_PG_PASSWORD="$v"; fi
if v=$(s app_owner_password); then export APP_OWNER_PASSWORD="$v"; fi
if v=$(s app_rw_password); then export APP_RW_PASSWORD="$v"; fi
if v=$(s agent_ro_password); then export AGENT_RO_PASSWORD="$v"; fi
if v=$(s keycloak_admin_password); then export KEYCLOAK_ADMIN_PASSWORD="$v"; fi
if v=$(s anthropic_api_key) && [ -n "$v" ]; then export ANTHROPIC_API_KEY="$v"; fi
unset v

export PG_HOST="${PG_HOST:-postgres}" PG_PORT="${PG_PORT:-5432}" DBT_PG_HOST="${PG_HOST:-postgres}" \
       DBT_PG_PORT="${PG_PORT:-5432}"

if [ "${1:-}" = "make" ]; then
  shift
  exec make -e "$@"
fi
exec "$@"
