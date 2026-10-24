#!/usr/bin/env bash
# Postgres local jetable pour le développement et les tests, sans Docker.
# Usage : scripts/dev_pg.sh start <port> [dossier] | stop <dossier>
# Dossier par défaut : /tmp/decision-pg/<port> (doit être accessible à l'utilisateur postgres si root).
# Crée les mêmes rôles, bases et schémas que infra/postgres/init, mots de passe = nom du rôle.
set -euo pipefail
PGBIN=${PGBIN:-$(ls -d /usr/lib/postgresql/*/bin 2>/dev/null | sort -V | tail -1)}
ROOT=$(cd "$(dirname "$0")/.." && pwd)
cmd=${1:?start|stop}
case "$cmd" in
  start)
    port=${2:?port}; dir=${3:-/tmp/decision-pg/$port}
    if [[ ! -f "$dir/PG_VERSION" ]]; then
      mkdir -p "$dir"; chmod 755 "$(dirname "$dir")" 2>/dev/null || true
      [[ $(id -u) -eq 0 ]] && chown -R postgres "$dir" 2>/dev/null || true
      run() { if [[ $(id -u) -eq 0 ]]; then su postgres -c "$*"; else bash -c "$*"; fi; }
      run "$PGBIN/initdb -D '$dir' -U postgres --auth=trust -E UTF8 --locale=C.UTF-8" >/dev/null
      run "$PGBIN/pg_ctl -D '$dir' -o '-p $port -k /tmp -c listen_addresses=localhost' -l '$dir/log' -w start" >/dev/null
      psql -h localhost -p "$port" -U postgres -d postgres -q -v ON_ERROR_STOP=1 \
        -v dbt_pw=dbt_owner -v owner_pw=app_owner -v app_pw=app_rw -v agent_pw=agent_ro -v kc_pw=keycloak \
        -f "$ROOT/infra/postgres/init/sql/01-roles.sql"
      psql -h localhost -p "$port" -U postgres -d warehouse -q -v ON_ERROR_STOP=1 \
        -f "$ROOT/infra/postgres/init/sql/02-warehouse.sql"
    else
      run() { if [[ $(id -u) -eq 0 ]]; then su postgres -c "$*"; else bash -c "$*"; fi; }
      run "$PGBIN/pg_ctl -D '$dir' -o '-p $port -k /tmp -c listen_addresses=localhost' -l '$dir/log' -w start" >/dev/null || true
    fi
    echo "postgresql://postgres@localhost:$port/warehouse"
    ;;
  stop)
    dir=${2:?dossier}
    if [[ $(id -u) -eq 0 ]]; then su postgres -c "$PGBIN/pg_ctl -D '$dir' -m fast stop"; else "$PGBIN/pg_ctl" -D "$dir" -m fast stop; fi
    ;;
esac
