"""Validation des jetons d'accès Keycloak (SYSTEM_DESIGN §6, SRS §10.1).

- RS256 uniquement : `none`, HS* et tout autre algorithme sont refusés avant la recherche de clé ;
- `iss`, `aud` (decision-api), `exp`, `nbf` vérifiés ; `sub` obligatoire ;
- clé choisie par `kid` dans un JWKS en cache ; un `kid` inconnu déclenche un rechargement,
  limité à un par `refresh_min_interval_s` (rotation des clés sans ouvrir une amplification) ;
- rôles lus seulement dans `resource_access[keycloak_client_id].roles`.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from typing import Any, get_args

import httpx
import jwt
from decision_core.models import Role
from fastapi import Depends, Request

from decision_api.config import ApiSettings
from decision_api.errors import ApiError

log = logging.getLogger("decision_api.auth")

KNOWN_ROLES: tuple[str, ...] = get_args(Role)  # ("decideur", "analyste", "admin")
_ROLE_RANK = {"decideur": 0, "analyste": 1, "admin": 2}
ALLOWED_ALGORITHMS = ["RS256"]


@dataclass(frozen=True)
class User:
    sub: str
    roles: frozenset[str]
    name: str | None = None
    email: str | None = None
    claims: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)

    @property
    def role(self) -> Role:
        """Rôle effectif pour l'agent : le plus élevé (admin > analyste > decideur)."""
        best = max(self.roles, key=lambda r: _ROLE_RANK[r])
        return best  # type: ignore[return-value]

    @property
    def sees_sql(self) -> bool:
        return self.role != "decideur"


class JWKSCache:
    """Cache des clés publiques par `kid`, rechargé à l'expiration ou sur `kid` inconnu (limité)."""

    def __init__(
        self,
        url: str,
        *,
        ttl_s: float = 600.0,
        refresh_min_interval_s: float = 30.0,
        http: httpx.AsyncClient | None = None,
        timeout_s: float = 5.0,
    ) -> None:
        self.url = url
        self.ttl_s = ttl_s
        self.refresh_min_interval_s = refresh_min_interval_s
        self._http = http
        self._timeout_s = timeout_s
        self._keys: dict[str, Any] = {}
        self._loaded_at = 0.0
        self._last_attempt = float("-inf")
        self._lock = asyncio.Lock()

    async def _fetch(self) -> None:
        self._last_attempt = time.monotonic()
        client = self._http or httpx.AsyncClient(timeout=self._timeout_s)
        try:
            resp = await client.get(self.url)
            resp.raise_for_status()
            data = resp.json()
        finally:
            if self._http is None:
                await client.aclose()
        keys: dict[str, Any] = {}
        for jwk in data.get("keys", []):
            if jwk.get("kty") != "RSA" or not jwk.get("kid"):
                continue
            if jwk.get("use") not in (None, "sig") or jwk.get("alg") not in (None, "RS256"):
                continue
            try:
                keys[jwk["kid"]] = jwt.PyJWK(jwk, algorithm="RS256").key
            except jwt.PyJWKError:
                log.warning("clé JWKS ignorée (format invalide)")
        self._keys = keys
        self._loaded_at = time.monotonic()

    async def get_key(self, kid: str) -> Any | None:
        now = time.monotonic()
        expired = now - self._loaded_at > self.ttl_s
        if kid in self._keys and not expired:
            return self._keys[kid]
        async with self._lock:
            now = time.monotonic()
            expired = now - self._loaded_at > self.ttl_s
            if kid in self._keys and not expired:
                return self._keys[kid]
            if expired or now - self._last_attempt >= self.refresh_min_interval_s:
                try:
                    await self._fetch()
                except (httpx.HTTPError, ValueError):
                    log.error("JWKS indisponible")
            return self._keys.get(kid)


class TokenValidator:
    def __init__(self, settings: ApiSettings, jwks: JWKSCache | None = None) -> None:
        self.issuer = settings.keycloak_issuer
        self.audience = settings.keycloak_audience
        self.client_id = settings.keycloak_client_id
        self.jwks = jwks or JWKSCache(settings.jwks_url)
        self.leeway_s = 10

    async def validate(self, token: str) -> User:
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as exc:
            raise _unauthorized("Jeton illisible.") from exc
        if header.get("alg") not in ALLOWED_ALGORITHMS:
            raise _unauthorized("Algorithme de signature refusé.")
        kid = header.get("kid")
        if not isinstance(kid, str) or not kid:
            raise _unauthorized("Jeton sans identifiant de clé.")
        key = await self.jwks.get_key(kid)
        if key is None:
            raise _unauthorized("Clé de signature inconnue.")
        try:
            claims = jwt.decode(
                token,
                key=key,
                algorithms=ALLOWED_ALGORITHMS,
                audience=self.audience,
                issuer=self.issuer,
                leeway=self.leeway_s,
                options={"require": ["exp", "iss", "aud", "sub"], "verify_nbf": True},
            )
        except jwt.ExpiredSignatureError as exc:
            raise _unauthorized("Jeton expiré.") from exc
        except jwt.PyJWTError as exc:
            raise _unauthorized("Jeton invalide.") from exc
        access = claims.get("resource_access") or {}
        client = access.get(self.client_id) if isinstance(access, dict) else None
        raw_roles = client.get("roles", []) if isinstance(client, dict) else []
        roles = frozenset(r for r in raw_roles if r in KNOWN_ROLES)
        return User(
            sub=str(claims["sub"]),
            roles=roles,
            name=claims.get("name") or claims.get("preferred_username"),
            email=claims.get("email"),
            claims=claims,
        )


def _unauthorized(message: str) -> ApiError:
    return ApiError(
        401, "unauthorized", message, headers={"WWW-Authenticate": 'Bearer error="invalid_token"'}
    )


def _bearer(request: Request) -> str:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise ApiError(
            401, "unauthorized", "Authentification requise.", headers={"WWW-Authenticate": "Bearer"}
        )
    return token.strip()


async def authenticated_user(request: Request) -> User:
    """Jeton valide, quel que soit le rôle (utilisé par /me)."""
    validator: TokenValidator = request.app.state.token_validator
    user = await validator.validate(_bearer(request))
    request.state.user_sub = user.sub
    return user


async def current_user(user: User = Depends(authenticated_user)) -> User:  # noqa: B008
    """Utilisateur authentifié ayant au moins un rôle applicatif."""
    if not user.roles:
        raise ApiError(403, "forbidden", "Aucun rôle applicatif.")
    return user


def require_roles(*roles: str) -> Callable[..., Coroutine[Any, Any, User]]:
    allowed = frozenset(roles)
    unknown = allowed - set(KNOWN_ROLES)
    if unknown:
        raise ValueError(f"rôles inconnus : {sorted(unknown)}")

    async def _dep(user: User = Depends(current_user)) -> User:  # noqa: B008
        if not (user.roles & allowed):
            raise ApiError(403, "forbidden", "Rôle insuffisant.")
        return user

    return _dep
