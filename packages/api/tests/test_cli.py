"""Commandes d'administration : jeton de développement, JWKS local, création d'utilisateur Keycloak."""

from __future__ import annotations

import json

import httpx
import pytest
from decision_api import cli
from decision_api.auth import TokenValidator
from decision_api.config import ApiSettings


@pytest.fixture
def dev_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "DEV_AUTH_DIR", tmp_path)
    monkeypatch.setenv("ENVIRONMENT", "dev")
    from decision_core.settings import get_settings

    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()


async def test_dev_token_validated_by_file_jwks(dev_dir, capsys):
    assert cli.main(["dev-token", "--role", "analyste", "--quiet"]) == 0
    token = capsys.readouterr().out.strip()
    settings = ApiSettings(keycloak_jwks_url=f"file://{dev_dir / 'jwks.json'}", environment="dev")
    user = await TokenValidator(settings).validate(token)
    assert user.sub == "dev-analyste" and set(user.roles) == {"analyste"}
    # la clé est réutilisée : un second jeton reste valide avec le même JWKS
    assert cli.main(["dev-token", "--role", "admin", "--quiet"]) == 0
    assert set((await TokenValidator(settings).validate(capsys.readouterr().out.strip())).roles) == {"admin"}


def test_dev_token_refused_in_production(dev_dir, monkeypatch, capsys):
    from decision_core.settings import get_settings

    monkeypatch.setenv("ENVIRONMENT", "production")
    get_settings.cache_clear()
    assert cli.main(["dev-token"]) == 2
    assert "refusé en production" in capsys.readouterr().err


def test_file_jwks_forbidden_in_production(tmp_path):
    settings = ApiSettings(keycloak_jwks_url=f"file://{tmp_path}/jwks.json", environment="production")
    with pytest.raises(RuntimeError):
        TokenValidator(settings)


class FakeKeycloak:
    """API d'administration Keycloak simulée (httpx.MockTransport)."""

    def __init__(self):
        self.users: dict[str, dict] = {}
        self.passwords: dict[str, dict] = {}
        self.mappings: dict[str, list] = {}

    def handler(self, request: httpx.Request) -> httpx.Response:
        path, method = request.url.path, request.method
        if path.endswith("/protocol/openid-connect/token"):
            return httpx.Response(200, json={"access_token": "adm"})
        assert request.headers["Authorization"] == "Bearer adm"
        base = "/admin/realms/decision"
        if path == f"{base}/users" and method == "GET":
            email = request.url.params["email"]
            return httpx.Response(200, json=[u for u in self.users.values() if u["email"] == email])
        if path == f"{base}/users" and method == "POST":
            body = json.loads(request.content)
            uid = f"u{len(self.users) + 1}"
            self.users[uid] = {**body, "id": uid}
            return httpx.Response(201)
        if path.endswith("/reset-password"):
            self.passwords[path.split("/")[-2]] = json.loads(request.content)
            return httpx.Response(204)
        if path == f"{base}/clients":
            return httpx.Response(200, json=[{"id": "c-web", "clientId": "decision-web"}])
        if path.startswith(f"{base}/clients/c-web/roles/"):
            return httpx.Response(200, json={"id": "r1", "name": path.rsplit("/", 1)[-1]})
        if "/role-mappings/clients/c-web" in path:
            self.mappings.setdefault(path.split("/")[-4], []).extend(json.loads(request.content))
            return httpx.Response(204)
        return httpx.Response(404)


def test_create_admin_user(monkeypatch):
    fake = FakeKeycloak()
    http = httpx.Client(transport=httpx.MockTransport(fake.handler))
    monkeypatch.setenv("KEYCLOAK_ADMIN_USER", "boot")
    monkeypatch.setenv("KEYCLOAK_ADMIN_PASSWORD", "x")
    kc = cli.KeycloakAdmin.login("http://kc", "decision", http=http)
    uid, password, created = kc.create_user(
        email="a@b.sn", role="admin", first_name=None, last_name=None, client_id="decision-web"
    )
    assert created and fake.users[uid]["requiredActions"] == ["UPDATE_PASSWORD"]
    assert fake.passwords[uid] == {"type": "password", "value": password, "temporary": True}
    assert len(password) >= 16
    assert [r["name"] for r in fake.mappings[uid]] == ["admin"]
    # idempotent : relancer ne recrée pas l'utilisateur
    uid2, _, created2 = kc.create_user(
        email="a@b.sn", role="admin", first_name=None, last_name=None, client_id="decision-web"
    )
    assert uid2 == uid and not created2 and len(fake.users) == 1


def test_create_user_requires_admin_credentials(monkeypatch):
    for v in (
        "KEYCLOAK_ADMIN_USER",
        "KEYCLOAK_ADMIN_PASSWORD",
        "KEYCLOAK_ADMIN_CLIENT_ID",
        "KEYCLOAK_ADMIN_CLIENT_SECRET",
        "KC_BOOTSTRAP_ADMIN_USERNAME",
        "KC_BOOTSTRAP_ADMIN_PASSWORD",
    ):
        monkeypatch.delenv(v, raising=False)
    with pytest.raises(cli.CliError, match="KEYCLOAK_ADMIN_USER"):
        cli.KeycloakAdmin.login("http://kc", "decision", http=httpx.Client())
