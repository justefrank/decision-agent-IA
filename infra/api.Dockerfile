# syntax=docker/dockerfile:1.7
# Image de l'API (FastAPI + agent + serveur MCP lancé en sous-processus), construite avec uv.
#   docker build -f infra/api.Dockerfile -t decision-api:local .
ARG PYTHON_IMAGE=python:3.12.12-slim-bookworm

FROM ghcr.io/astral-sh/uv:0.11.32 AS uv

# ---------- étape 1 : dépendances et paquets de l'espace de travail dans /app/.venv
FROM ${PYTHON_IMAGE} AS build
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /src
# Dépendances tierces d'abord (couche mise en cache tant que uv.lock ne change pas).
COPY pyproject.toml uv.lock ./
COPY packages/core/pyproject.toml packages/core/pyproject.toml
COPY packages/sql_guard/pyproject.toml packages/sql_guard/pyproject.toml
COPY packages/mcp_server/pyproject.toml packages/mcp_server/pyproject.toml
COPY packages/agent/pyproject.toml packages/agent/pyproject.toml
COPY packages/api/pyproject.toml packages/api/pyproject.toml
COPY packages/data_gen/pyproject.toml packages/data_gen/pyproject.toml
COPY packages/eval/pyproject.toml packages/eval/pyproject.toml
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-workspace \
      --package decision-api --package decision-mcp-server
# Puis le code (installé en mode non éditable : /src n'est pas copié dans l'image finale).
COPY packages ./packages
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable \
      --package decision-api --package decision-mcp-server

# ---------- étape 2 : exécution, utilisateur non root, sans uv ni sources
FROM ${PYTHON_IMAGE} AS runtime
RUN groupadd --system --gid 10001 app && useradd --system --uid 10001 --gid app --home /app app
WORKDIR /app
COPY --from=build /app/.venv /app/.venv
COPY semantic /app/semantic
# alembic.ini et migrations (service « migrate » du compose).
COPY packages/api/alembic.ini /app/packages/api/alembic.ini
COPY packages/api/src/decision_api/migrations /app/packages/api/src/decision_api/migrations
COPY infra/api-entrypoint.sh /usr/local/bin/api-entrypoint
ENV PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    SEMANTIC_DIR=/app/semantic \
    MCP_COMMAND=python \
    MCP_ARGS="-m decision_mcp_server"
USER app
EXPOSE 8000
ENTRYPOINT ["/usr/local/bin/api-entrypoint"]
# Un seul worker : un sous-processus MCP durable par worker (D3).
CMD ["uvicorn", "decision_api.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips", "*", "--workers", "1"]
