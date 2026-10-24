#!/usr/bin/env bash
# Rôles, bases et schémas (exécuté une fois par l'image postgres à la création du volume).
# Les droits sur les tables applicatives sont posés par les migrations Alembic (rôle app_owner),
# pas ici : les tables n'existent pas encore (revue v5, constat 15).
# Mots de passe lus depuis les secrets Docker (/run/secrets/*) ou l'environnement.
set -euo pipefail

secret() { local f="/run/secrets/$1"; if [[ -f "$f" ]]; then cat "$f"; else printenv "$2"; fi; }

DBT_PW=$(secret dbt_owner_password DBT_OWNER_PASSWORD)
OWNER_PW=$(secret app_owner_password APP_OWNER_PASSWORD)
APP_PW=$(secret app_rw_password APP_RW_PASSWORD)
AGENT_PW=$(secret agent_ro_password AGENT_RO_PASSWORD)
KC_PW=$(secret keycloak_db_password KEYCLOAK_DB_PASSWORD)

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres \
  -v dbt_pw="$DBT_PW" -v owner_pw="$OWNER_PW" -v app_pw="$APP_PW" \
  -v agent_pw="$AGENT_PW" -v kc_pw="$KC_PW" -f /docker-entrypoint-initdb.d/sql/01-roles.sql
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname warehouse \
  -f /docker-entrypoint-initdb.d/sql/02-warehouse.sql
