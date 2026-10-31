# syntax=docker/dockerfile:1.7
# Conteneur « outils » (développement) : générateur, dbt, test de droits, migrations, évaluation,
# création d'utilisateurs Keycloak. Le code du dépôt est monté sur /workspace à l'exécution (les
# modifications sont prises en compte sans reconstruire) ; seules les dépendances sont dans l'image.
#   make dc-shell            # ouvre un shell dans ce conteneur
ARG PYTHON_IMAGE=python:3.12.12-slim-bookworm

FROM ghcr.io/astral-sh/uv:0.11.32 AS uv

FROM ${PYTHON_IMAGE}
COPY --from=uv /uv /uvx /usr/local/bin/
RUN apt-get update \
 && apt-get install -y --no-install-recommends make postgresql-client git ca-certificates \
 && rm -rf /var/lib/apt/lists/*
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_FROZEN=1 \
    UV_NO_SYNC=1 \
    UV_CACHE_DIR=/tmp/uv-cache \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOME=/tmp
WORKDIR /workspace

# Dépendances de tout l'espace de travail : paquets installés en mode éditable vers /workspace,
# dont le code réel viendra du montage (les sources copiées ici sont supprimées ensuite).
COPY pyproject.toml uv.lock ./
COPY packages ./packages
RUN uv sync --frozen --all-packages && rm -rf /workspace/packages /tmp/uv-cache

# dbt dans un environnement séparé (versions figées dans warehouse/requirements.txt).
COPY warehouse/requirements.txt /tmp/dbt-requirements.txt
RUN uv venv /opt/dbt && VIRTUAL_ENV=/opt/dbt uv pip install -r /tmp/dbt-requirements.txt \
 # cache de construction (root) supprimé : le conteneur tourne avec l'UID de l'hôte et recrée le sien dans /tmp
 && rm -rf /tmp/uv-cache

# Environnements figés : `uv run` ne resynchronise pas (après un changement de uv.lock : make dc-build).
# Lisibles par l'utilisateur de l'hôte, sous lequel tourne le conteneur (UID variable).
RUN chmod -R a+rX /opt/venv /opt/dbt

ENV PATH=/opt/venv/bin:$PATH \
    DBT=/opt/dbt/bin/dbt
COPY infra/tools-entrypoint.sh /usr/local/bin/tools-entrypoint
ENTRYPOINT ["/usr/local/bin/tools-entrypoint"]
CMD ["bash"]
