"""Configuration de l'API : `decision_core.settings` étendu des champs propres à l'API.

Les paramètres fonctionnels (quota, longueur des questions…) viennent de `semantic/config.yaml`
(modifié par PR Git) ; les secrets et adresses viennent de l'environnement.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import quote

from decision_core.semantic import SemanticLayer
from decision_core.settings import Settings
from pydantic import SecretStr, model_validator

DEFAULT_PSEUDONYM_KEY = "dev-only-change-me"


class ApiSettings(Settings):
    # Rapport JSON produit par `make rights-test` (test de droits de agent_ro, exécuté hors API).
    rights_test_report: str = "var/reports/rights-test.json"
    # Procédure de modification de la configuration (PR Git relue par une autre personne).
    settings_procedure_url: str = "docs/EVALUATION_V5.md#6-périmètre--mvp-proposé-environ-60-75-j-p"

    # MFA : pour analyste et admin, exiger un jeton portant la preuve d'OTP (`amr` contient « otp »
    # ou `acr` numérique ≥ mfa_min_acr). Vide : actif en production seulement.
    require_mfa_claim: bool | None = None
    mfa_min_acr: int = 2

    # Compose : le DSN agent_ro est construit à partir du secret Docker (fichier) au lieu d'être
    # exporté dans l'environnement du processus ; il n'est transmis qu'au sous-processus MCP.
    agent_ro_password_file: str | None = None
    pg_host: str = "localhost"
    pg_port: int = 5432
    pg_database: str = "warehouse"

    # Sous-processus MCP : sonde (list_tools) et relance supervisée.
    mcp_probe_timeout_s: float = 2.0
    mcp_probe_interval_s: float = 15.0
    mcp_max_restarts: int = 5
    mcp_backoff_initial_s: float = 1.0
    mcp_backoff_max_s: float = 30.0

    # Tableau de bord : cache mémoire des tuiles (ce n'est pas un cache de réponses de l'agent).
    dashboard_cache_ttl_s: float = 300.0
    # Délai minimal entre deux générations d'analyse pour la même période, région et données.
    analysis_regenerate_min_interval_s: float = 60.0

    # Taille maximale d'un corps de requête /api/* (octets), vérifiée avant toute lecture complète.
    max_body_bytes: int = 64 * 1024

    @model_validator(mode="after")
    def _agent_ro_from_file(self) -> ApiSettings:
        if self.agent_ro_dsn is None and self.agent_ro_password_file:
            path = Path(self.agent_ro_password_file)
            if path.is_file():
                pw = path.read_text(encoding="utf-8").strip()
                dsn = (
                    f"postgresql://agent_ro:{quote(pw, safe='')}@{self.pg_host}:{self.pg_port}/"
                    f"{self.pg_database}"
                )
                self.agent_ro_dsn = SecretStr(dsn)
        return self

    @property
    def is_production(self) -> bool:
        return self.environment.lower() in {"prod", "production"}

    @property
    def mfa_required(self) -> bool:
        return self.is_production if self.require_mfa_claim is None else self.require_mfa_claim

    @property
    def cors_origin_list(self) -> list[str]:
        origins = [o.strip() for o in self.cors_origins.split(",") if o.strip()]
        return [o for o in origins if o != "*"]  # jamais de joker

    @property
    def jwks_url(self) -> str:
        return self.keycloak_jwks_url or f"{self.keycloak_issuer.rstrip('/')}/protocol/openid-connect/certs"

    def check_production(self) -> None:
        """Refuse une configuration de production dangereuse (appelé au démarrage)."""
        if not self.is_production:
            return
        key = self.log_pseudonym_key.get_secret_value()
        if not key or key == DEFAULT_PSEUDONYM_KEY or len(key) < 16:
            raise RuntimeError(
                "LOG_PSEUDONYM_KEY absente ou valeur par défaut : démarrage refusé en production."
            )


def scrub_agent_ro_env() -> None:
    """Retire AGENT_RO_DSN de l'environnement du processus API une fois les réglages lus.

    Le DSN reste dans `settings.agent_ro_dsn` (SecretStr) et n'est transmis qu'au sous-processus MCP
    (`McpToolClient.server_env`, environnement restreint) : ni les autres sous-processus ni un
    vidage de `os.environ` ne le voient.
    """
    os.environ.pop("AGENT_RO_DSN", None)


@lru_cache(maxsize=1)
def get_api_settings() -> ApiSettings:
    return ApiSettings()


def cfg(semantic: SemanticLayer, path: str, default: Any) -> Any:
    """Lit une valeur pointée (`quota.questions_per_user_per_day`) dans semantic/config.yaml."""
    node: Any = semantic.config
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node
