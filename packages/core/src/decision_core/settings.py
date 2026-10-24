"""Paramètres d'exécution lus dans l'environnement (.env non versionné, secrets Docker)."""

from __future__ import annotations

from datetime import date
from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", secrets_dir=None)

    environment: str = "dev"
    reference_date: date = date(2026, 9, 30)

    # Postgres : chaque composant ne reçoit que le DSN de son rôle.
    app_database_url: SecretStr | None = None  # app_rw (API)
    owner_database_url: SecretStr | None = None  # app_owner (migrations Alembic)
    agent_ro_dsn: SecretStr | None = None  # agent_ro : transmis SEULEMENT au sous-processus MCP

    # Claude
    anthropic_api_key: SecretStr | None = None
    llm_model: str = "claude-sonnet-5-5"
    llm_effort: str = "medium"
    llm_fallbacks: bool = False  # désactivé en évaluation pour ne pas mélanger les modèles

    # Keycloak (OIDC)
    keycloak_issuer: str = "https://localhost/auth/realms/decision"
    keycloak_jwks_url: str | None = None  # défaut : {issuer}/protocol/openid-connect/certs
    keycloak_audience: str = "decision-api"
    keycloak_client_id: str = "decision-web"  # les rôles sont lus dans resource_access[client].roles

    # Pseudonymisation du sub dans les journaux (HMAC-SHA256)
    log_pseudonym_key: SecretStr = SecretStr("dev-only-change-me")

    semantic_dir: str | None = None
    mcp_command: str = "python"
    mcp_args: str = "-m decision_mcp_server"
    cors_origins: str = ""  # vide : même origine derrière le proxy


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
