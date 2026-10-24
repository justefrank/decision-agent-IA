#!/bin/sh
# Construit les DSN à partir des secrets Docker (/run/secrets) puis lance la commande.
# Chaque DSN n'est exporté que si le secret correspondant est monté dans ce conteneur.
set -eu
s() { [ -f "/run/secrets/$1" ] && tr -d '\r\n' < "/run/secrets/$1"; }
enc() { python -c 'import sys, urllib.parse; print(urllib.parse.quote(sys.argv[1], safe=""))' "$1"; }
host=${PG_HOST:-postgres}; port=${PG_PORT:-5432}; db=${PG_DATABASE:-warehouse}

if pw=$(s app_rw_password); then
  export APP_DATABASE_URL="postgresql://app_rw:$(enc "$pw")@$host:$port/$db"
fi
if pw=$(s app_owner_password); then
  export OWNER_DATABASE_URL="postgresql://app_owner:$(enc "$pw")@$host:$port/$db"
fi
if pw=$(s agent_ro_password); then
  # Transmis par l'API au seul sous-processus MCP (decision_agent.tools.McpToolClient).
  export AGENT_RO_DSN="postgresql://agent_ro:$(enc "$pw")@$host:$port/$db"
fi
if v=$(s anthropic_api_key); then export ANTHROPIC_API_KEY="$v"; fi
if v=$(s log_pseudonym_key); then export LOG_PSEUDONYM_KEY="$v"; fi
unset pw v
exec "$@"
