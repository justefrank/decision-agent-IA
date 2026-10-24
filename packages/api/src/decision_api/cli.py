"""Commandes d'administration : utilisateurs Keycloak et jetons de développement.

    python -m decision_api.cli create-user --email a@b.sn --role admin   # Keycloak (toute pile)
    python -m decision_api.cli dev-token --role admin                    # local, sans Keycloak
    python -m decision_api.cli purge-logs --days 90                      # rétention (app_owner)

`create-user` passe par l'API d'administration Keycloak (le realm reste la source unique des
utilisateurs, S13) : l'utilisateur reçoit un mot de passe temporaire affiché une seule fois et doit le
changer à la première connexion ; analyste et admin enrôlent leur OTP (rôle composite `mfa-requise`).

`dev-token` signe un JWT avec une clé locale (var/dev-auth/) et écrit le JWKS correspondant ; l'API le lit
si KEYCLOAK_JWKS_URL=file://…/var/dev-auth/jwks.json. Refusé en production.

`purge-logs` supprime les lignes de `app.query_log` plus anciennes que la rétention (90 jours) avec le
rôle propriétaire `app_owner` (OWNER_DATABASE_URL) : `app_rw`, le rôle de l'API, n'a pas DELETE.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import string
import sys
import time
from pathlib import Path
from typing import Any

import httpx

ROLES = ("decideur", "analyste", "admin")
DEV_AUTH_DIR = Path(os.environ.get("DEV_AUTH_DIR", "var/dev-auth"))


class CliError(Exception):
    pass


# --- Keycloak --------------------------------------------------------------------------------------


def _temp_password(n: int = 20) -> str:
    alphabet = string.ascii_letters + string.digits
    # au moins une majuscule, une minuscule, un chiffre et un symbole (politique de mot de passe courante)
    core = [secrets.choice(string.ascii_uppercase), secrets.choice(string.ascii_lowercase)]
    core += [secrets.choice(string.digits), secrets.choice("-_.!")]
    core += [secrets.choice(alphabet) for _ in range(n - len(core))]
    secrets.SystemRandom().shuffle(core)
    return "".join(core)


class KeycloakAdmin:
    """Client minimal de l'API d'administration Keycloak (realm cible, pas d'administration du realm)."""

    def __init__(self, base_url: str, realm: str, http: httpx.Client) -> None:
        self.base = base_url.rstrip("/")
        self.realm = realm
        self.http = http

    @classmethod
    def login(cls, base_url: str, realm: str, *, http: httpx.Client | None = None) -> KeycloakAdmin:
        """Jeton d'administration : compte de service ou administrateur du realm master."""
        http = http or httpx.Client(timeout=15.0)
        client_id = os.environ.get("KEYCLOAK_ADMIN_CLIENT_ID")
        client_secret = os.environ.get("KEYCLOAK_ADMIN_CLIENT_SECRET")
        if client_id and client_secret:
            url = f"{base_url.rstrip('/')}/realms/{realm}/protocol/openid-connect/token"
            data = {
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
            }
        else:
            user = os.environ.get("KEYCLOAK_ADMIN_USER") or os.environ.get("KC_BOOTSTRAP_ADMIN_USERNAME")
            password = os.environ.get("KEYCLOAK_ADMIN_PASSWORD") or os.environ.get(
                "KC_BOOTSTRAP_ADMIN_PASSWORD"
            )
            if not user or not password:
                raise CliError(
                    "Identifiants d'administration Keycloak absents : définir KEYCLOAK_ADMIN_USER et "
                    "KEYCLOAK_ADMIN_PASSWORD (ou KEYCLOAK_ADMIN_CLIENT_ID / _SECRET d'un compte de service)."
                )
            url = f"{base_url.rstrip('/')}/realms/master/protocol/openid-connect/token"
            data = {
                "grant_type": "password",
                "client_id": "admin-cli",
                "username": user,
                "password": password,
            }
        resp = http.post(url, data=data)
        if resp.status_code != 200:
            raise CliError(f"Connexion à Keycloak refusée ({resp.status_code}).")
        http.headers["Authorization"] = f"Bearer {resp.json()['access_token']}"
        return cls(base_url, realm, http)

    def _url(self, path: str) -> str:
        return f"{self.base}/admin/realms/{self.realm}{path}"

    def _check(self, resp: httpx.Response, what: str) -> httpx.Response:
        if resp.status_code >= 400:
            raise CliError(f"{what} : Keycloak a répondu {resp.status_code} {resp.text[:200]}")
        return resp

    def find_user(self, email: str) -> dict[str, Any] | None:
        resp = self._check(
            self.http.get(self._url("/users"), params={"email": email, "exact": "true"}), "recherche"
        )
        users = resp.json()
        return users[0] if users else None

    def client_uuid(self, client_id: str) -> str:
        resp = self._check(self.http.get(self._url("/clients"), params={"clientId": client_id}), "client")
        clients = resp.json()
        if not clients:
            raise CliError(f"Client {client_id} introuvable dans le realm {self.realm}.")
        return clients[0]["id"]

    def create_user(
        self,
        *,
        email: str,
        role: str,
        first_name: str | None,
        last_name: str | None,
        client_id: str,
        password: str | None = None,
        temporary: bool = True,
    ) -> tuple[str, str, bool]:
        """Crée (ou complète) l'utilisateur, fixe un mot de passe et attribue le rôle client.

        Renvoie (id, mot de passe, créé).
        """
        if role not in ROLES:
            raise CliError(f"Rôle inconnu : {role} (attendus : {', '.join(ROLES)}).")
        existing = self.find_user(email)
        created = existing is None
        if created:
            body = {
                "username": email,
                "email": email,
                "emailVerified": True,
                "enabled": True,
                "firstName": first_name or "",
                "lastName": last_name or "",
                "requiredActions": ["UPDATE_PASSWORD"] if temporary else [],
            }
            self._check(self.http.post(self._url("/users"), json=body), "création")
            existing = self.find_user(email)
            if existing is None:
                raise CliError("Utilisateur créé mais introuvable.")
        uid = existing["id"]
        password = password or _temp_password()
        self._check(
            self.http.put(
                self._url(f"/users/{uid}/reset-password"),
                json={"type": "password", "value": password, "temporary": temporary},
            ),
            "mot de passe",
        )
        cid = self.client_uuid(client_id)
        role_repr = self._check(
            self.http.get(self._url(f"/clients/{cid}/roles/{role}")), f"rôle {role}"
        ).json()
        self._check(
            self.http.post(self._url(f"/users/{uid}/role-mappings/clients/{cid}"), json=[role_repr]),
            "attribution du rôle",
        )
        return uid, password, created


def cmd_create_user(args: argparse.Namespace) -> int:
    from decision_core.settings import get_settings

    settings = get_settings()
    base = args.keycloak_url or os.environ.get("KEYCLOAK_URL")
    if not base:
        # issuer = {base}/realms/{realm}
        base = settings.keycloak_issuer.split("/realms/")[0]
    realm = args.realm or settings.keycloak_issuer.rstrip("/").rsplit("/", 1)[-1]
    if args.password and settings.environment.lower() in {"prod", "production"}:
        raise CliError("--password est refusé en production : laissez générer un mot de passe temporaire.")
    kc = KeycloakAdmin.login(base, realm)
    uid, password, created = kc.create_user(
        email=args.email,
        role=args.role,
        first_name=args.first_name,
        last_name=args.last_name,
        client_id=settings.keycloak_client_id,
        password=args.password,
        temporary=not args.password,
    )
    print(f"{'Créé' if created else 'Déjà présent, mis à jour'} : {args.email} (id {uid}), rôle {args.role}.")
    if args.password:
        print("Mot de passe : celui fourni (non temporaire, développement seulement).")
    else:
        print(f"Mot de passe temporaire (affiché une seule fois) : {password}")
        print("À changer à la première connexion.", end=" ")
    if args.role in ("analyste", "admin"):
        print("Enrôlement OTP obligatoire à la première connexion.")
    else:
        print()
    return 0


# --- Jeton de développement -------------------------------------------------------------------------


def _dev_key() -> Any:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from jwt.algorithms import RSAAlgorithm

    DEV_AUTH_DIR.mkdir(parents=True, exist_ok=True)
    pem = DEV_AUTH_DIR / "private.pem"
    if pem.exists():
        key = serialization.load_pem_private_key(pem.read_bytes(), password=None)
    else:
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        old = os.umask(0o077)
        try:
            pem.write_bytes(
                key.private_bytes(
                    serialization.Encoding.PEM,
                    serialization.PrivateFormat.PKCS8,
                    serialization.NoEncryption(),
                )
            )
        finally:
            os.umask(old)
    jwk = json.loads(RSAAlgorithm.to_jwk(key.public_key()))
    jwk.update(kid="dev-1", alg="RS256", use="sig")
    (DEV_AUTH_DIR / "jwks.json").write_text(json.dumps({"keys": [jwk]}, indent=2))
    return key


def cmd_dev_token(args: argparse.Namespace) -> int:
    import jwt
    from decision_core.settings import get_settings

    settings = get_settings()
    if settings.environment.lower() in {"prod", "production"}:
        raise CliError("dev-token est refusé en production.")
    if args.role not in ROLES:
        raise CliError(f"Rôle inconnu : {args.role}.")
    key = _dev_key()
    now = int(time.time())
    claims = {
        "iss": settings.keycloak_issuer,
        "aud": settings.keycloak_audience,
        "sub": args.sub or f"dev-{args.role}",
        "preferred_username": args.sub or f"dev-{args.role}",
        "iat": now,
        "nbf": now - 5,
        "exp": now + args.ttl,
        "resource_access": {settings.keycloak_client_id: {"roles": [args.role]}},
        # Comme un jeton Keycloak après connexion avec OTP (mapper AMR) : REQUIRE_MFA_CLAIM=true testable.
        "amr": ["pwd", "otp"],
    }
    token = jwt.encode(claims, key, algorithm="RS256", headers={"kid": "dev-1"})
    if args.quiet:
        print(token)
    else:
        jwks = (DEV_AUTH_DIR / "jwks.json").resolve()
        print(
            f"# Jeton {args.role} valable {args.ttl // 60} min ; l'API doit lire KEYCLOAK_JWKS_URL=file://{jwks}"
        )
        print(token)
    return 0


# --- Rétention du journal ----------------------------------------------------------------------------

RETENTION_DAYS = 90


async def purge_query_log(owner_dsn: str, days: int) -> int:
    """Supprime les lignes de app.query_log plus anciennes que `days` jours ; renvoie leur nombre."""
    import asyncpg

    dsn = owner_dsn.replace("postgresql+asyncpg://", "postgresql://", 1)
    conn = await asyncpg.connect(dsn, server_settings={"application_name": "decision-purge"})
    try:
        status = await conn.execute(
            "DELETE FROM app.query_log WHERE ts < now() - make_interval(days => $1)", days
        )
    finally:
        await conn.close()
    return int(status.split()[-1])


def cmd_purge_logs(args: argparse.Namespace) -> int:
    import asyncio

    import asyncpg

    if args.days < 1:
        raise CliError("--days doit être ≥ 1.")
    dsn = os.environ.get("OWNER_DATABASE_URL")
    if not dsn:
        from decision_core.settings import get_settings

        secret = get_settings().owner_database_url
        dsn = secret.get_secret_value() if secret else None
    if not dsn:
        raise CliError("OWNER_DATABASE_URL (rôle app_owner) non défini.")
    try:
        n = asyncio.run(purge_query_log(dsn, args.days))
    except asyncpg.InsufficientPrivilegeError as e:
        raise CliError("droit DELETE refusé : la purge s'exécute avec app_owner (OWNER_DATABASE_URL).") from e
    except (OSError, asyncpg.PostgresError) as e:
        raise CliError(f"purge impossible ({type(e).__name__}).") from e
    print(f"query_log : {n} ligne(s) de plus de {args.days} jours supprimée(s).")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="decision-admin", description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser(
        "create-user", help="Crée un utilisateur Keycloak avec un rôle (admin, analyste, decideur)"
    )
    c.add_argument("--email", required=True)
    c.add_argument("--role", choices=ROLES, default="admin")
    c.add_argument("--first-name")
    c.add_argument("--last-name")
    c.add_argument("--password", help="Mot de passe fixe (développement seulement ; sinon temporaire généré)")
    c.add_argument("--keycloak-url", help="URL interne de Keycloak (défaut : KEYCLOAK_URL ou l'issuer)")
    c.add_argument("--realm", help="Realm (défaut : tiré de KEYCLOAK_ISSUER)")
    c.set_defaults(func=cmd_create_user)

    t = sub.add_parser("dev-token", help="Jeton JWT local signé (sans Keycloak), refusé en production")
    t.add_argument("--role", choices=ROLES, default="admin")
    t.add_argument("--sub", help="Identifiant (claim sub) ; défaut dev-<rôle>")
    t.add_argument("--ttl", type=int, default=3600, help="Durée de validité en secondes")
    t.add_argument("--quiet", action="store_true", help="N'imprime que le jeton")
    t.set_defaults(func=cmd_dev_token)

    g = sub.add_parser("purge-logs", help="Purge de app.query_log au-delà de la rétention (rôle app_owner)")
    g.add_argument("--days", type=int, default=RETENTION_DAYS, help="Rétention en jours (défaut 90)")
    g.set_defaults(func=cmd_purge_logs)

    args = p.parse_args(argv)
    try:
        return args.func(args)
    except CliError as e:
        print(f"erreur : {e}", file=sys.stderr)
        return 2
    except httpx.HTTPError as e:
        print(f"erreur : Keycloak injoignable ({type(e).__name__}).", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
