"""Configuration de l'API : `decision_core.settings` étendu de deux champs propres à l'API.

Les paramètres fonctionnels (quota, longueur des questions…) viennent de `semantic/config.yaml`
(modifié par PR Git) ; les secrets et adresses viennent de l'environnement.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from decision_core.semantic import SemanticLayer
from decision_core.settings import Settings


class ApiSettings(Settings):
    # Rapport JSON produit par `make rights-test` (test de droits de agent_ro, exécuté hors API).
    rights_test_report: str = "var/rights-test.json"
    # Procédure de modification de la configuration (PR Git relue par une autre personne).
    settings_procedure_url: str = "docs/EVALUATION_V5.md#6-périmètre--mvp-proposé-environ-60-75-j-p"

    @property
    def is_production(self) -> bool:
        return self.environment.lower() in {"prod", "production"}

    @property
    def cors_origin_list(self) -> list[str]:
        origins = [o.strip() for o in self.cors_origins.split(",") if o.strip()]
        return [o for o in origins if o != "*"]  # jamais de joker

    @property
    def jwks_url(self) -> str:
        return self.keycloak_jwks_url or f"{self.keycloak_issuer.rstrip('/')}/protocol/openid-connect/certs"


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
