"""Configuration de déploiement : compose, realm Keycloak, Caddyfile, .env.example, init Postgres.

Vérifications statiques (sans Docker) des correctifs de revue ; la validation dynamique a été faite
hors CI (Caddy 2.10.2 et Keycloak 26.8.1 locaux, voir le README).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
INFRA = ROOT / "infra"


def _compose() -> dict:
    return yaml.safe_load((INFRA / "compose.yaml").read_text(encoding="utf-8"))


def _realm() -> dict:
    return json.loads((INFRA / "keycloak" / "realm" / "decision-realm.json").read_text(encoding="utf-8"))


def test_compose_migrations_before_api_and_production_default():
    svc = _compose()["services"]
    assert "profiles" not in svc["migrate"]
    assert svc["migrate"]["build"] == svc["api"]["build"]
    assert svc["api"]["depends_on"]["migrate"] == {"condition": "service_completed_successfully"}
    env = svc["api"]["environment"]
    assert env["ENVIRONMENT"] == "${API_ENVIRONMENT:-production}"
    assert "AGENT_RO_DSN" not in env
    assert env["AGENT_RO_PASSWORD_FILE"] == "/run/secrets/agent_ro_password"  # noqa: S105 - chemin
    assert env["RIGHTS_TEST_REPORT"] == "/app/var/reports/rights-test.json"
    assert "../var/reports:/app/var/reports:ro" in svc["api"]["volumes"]
    assert "status" in " ".join(svc["api"]["healthcheck"]["test"])


def test_compose_healthchecks_and_ports():
    svc = _compose()["services"]
    assert "pg_isready -h 127.0.0.1" in svc["postgres"]["healthcheck"]["test"][1]
    assert svc["postgres"]["ports"] == ["127.0.0.1:${PG_PUBLISH_PORT:-5432}:5432"]
    kc = svc["keycloak"]
    probe = kc["healthcheck"]["test"][1]
    assert "/auth/health/ready" in probe and "' 200'" in probe and '"UP"' not in probe
    assert kc["environment"]["KC_HTTP_MANAGEMENT_RELATIVE_PATH"] == "/auth"
    assert kc["environment"]["PUBLIC_HOST"] == "${PUBLIC_HOST:-localhost}"
    assert all(p.startswith("127.0.0.1:") for p in kc["ports"])
    assert "./web-fallback:/srv/fallback:ro" in svc["proxy"]["volumes"]


def test_entrypoint_does_not_export_agent_ro_dsn():
    script = (INFRA / "api-entrypoint.sh").read_text(encoding="utf-8")
    assert "export AGENT_RO_DSN" not in script


def test_caddyfile_auth_subset_body_limit_and_no_sse_compression():
    caddy = (INFRA / "Caddyfile").read_text(encoding="utf-8")
    assert "handle /auth/* {" not in caddy.replace("handle /auth* {", "")  # plus de proxy global
    for path in ("/auth/realms/decision/*", "/auth/resources/*", "/auth/js/*"):
        assert f"handle {path} {{" in caddy
    for blocked in ("/auth/admin*", "/auth/realms/master*", "/auth*"):
        assert re.search(rf"handle {re.escape(blocked)} {{\s*respond 404", caddy)
    api_block = caddy[caddy.index("handle /api/* {") : caddy.index("handle /auth/realms/decision/*")]
    assert "max_size 64KB" in api_block and "encode" not in api_block
    assert not re.search(r"^\s*encode", caddy[: caddy.index("handle /api/*")], re.M)  # pas de encode global
    assert (INFRA / "web-fallback" / "index.html").is_file()


def test_realm_reset_flow_uses_role_conditional_otp():
    realm = _realm()
    assert realm["resetPasswordAllowed"] is True
    assert realm["resetCredentialsFlow"] == "decision-reset-credentials"
    flows = {f["alias"]: f for f in realm["authenticationFlows"]}
    reset = [
        e.get("authenticator") or e.get("flowAlias")
        for e in flows["decision-reset-credentials"]["authenticationExecutions"]
    ]
    assert reset[:3] == ["reset-credentials-choose-user", "reset-credential-email", "reset-password"]
    mandatory = flows["decision-reset-otp-obligatoire"]["authenticationExecutions"]
    assert [e["authenticator"] for e in mandatory] == ["conditional-user-role", "auth-otp-form"]
    configs = {c["alias"]: c["config"] for c in realm["authenticatorConfig"]}
    assert configs[mandatory[0]["authenticatorConfig"]] == {"condUserRole": "mfa-requise", "negate": "false"}
    authenticators = {e.get("authenticator") for f in flows.values() for e in f["authenticationExecutions"]}
    assert "reset-otp" not in authenticators  # jamais de suppression de l'OTP par simple courriel
    # toutes les références de flux et de configuration existent
    for f in realm["authenticationFlows"]:
        for e in f["authenticationExecutions"]:
            assert e.get("flowAlias") in (None, *flows)
            assert e.get("authenticatorConfig") in (None, *configs)


def test_realm_amr_mapper_and_references():
    realm = _realm()
    scopes = {s["name"]: s for s in realm["clientScopes"]}
    assert scopes["amr"]["protocolMappers"][0]["protocolMapper"] == "oidc-amr-mapper"
    assert "amr" in realm["clients"][0]["defaultClientScopes"]
    configs = {c["alias"]: c["config"] for c in realm["authenticatorConfig"]}
    for f in realm["authenticationFlows"]:
        for e in f["authenticationExecutions"]:
            ref = {"auth-otp-form": "otp", "auth-username-password-form": "pwd"}.get(e.get("authenticator"))
            if ref:
                assert configs[e["authenticatorConfig"]]["default.reference.value"] == ref


def test_realm_urls_from_public_host():
    client = _realm()["clients"][0]
    assert client["redirectUris"] == ["https://${PUBLIC_HOST}/*"]
    assert client["webOrigins"] == ["https://${PUBLIC_HOST}"]
    assert client["attributes"]["post.logout.redirect.uris"] == "https://${PUBLIC_HOST}/*"


def test_env_example_has_no_active_dsn_or_ports():
    active = {
        line.split("=", 1)[0]
        for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#") and "=" in line
    }
    forbidden = {
        "APP_DATABASE_URL",
        "OWNER_DATABASE_URL",
        "AGENT_RO_DSN",
        "DBT_OWNER_DSN",
        "PG_PORT",
        "PG_HOST",
        "DBT_PG_PORT",
        "DBT_PG_HOST",
        "ANTHROPIC_API_KEY",
        "WEB_DIST",
    }
    assert not active & forbidden, active & forbidden
    assert not [k for k in active if not re.fullmatch(r"[A-Z_]+", k)]


def test_postgres_maintenance_db_closed_to_public():
    sql = (INFRA / "postgres" / "init" / "sql" / "01-roles.sql").read_text(encoding="utf-8")
    assert "REVOKE CONNECT ON DATABASE postgres FROM PUBLIC;" in sql


def test_dockerignore_excludes_secrets_and_tests():
    lines = set((ROOT / ".dockerignore").read_text(encoding="utf-8").split())
    assert {"infra/secrets", "var/", ".git", ".venv", "**/__pycache__", "**/tests"} <= lines


def test_tools_service_runs_makefile_inside_docker_network():
    svc = _compose()["services"]["tools"]
    assert svc["profiles"] == ["tools"]
    assert svc["environment"]["PG_HOST"] == "postgres"
    assert "..:/workspace" in svc["volumes"]
    assert {"dbt_owner_password", "agent_ro_password", "app_owner_password"} <= set(svc["secrets"])
    entry = (INFRA / "tools-entrypoint.sh").read_text(encoding="utf-8")
    # make -e : l'environnement du conteneur l'emporte sur un .env de l'hôte monté avec le dépôt
    assert 'exec make -e "$@"' in entry


def test_dev_override_only_relaxes_api_for_local_tokens():
    dev = yaml.safe_load((INFRA / "compose.dev.yaml").read_text(encoding="utf-8"))
    assert set(dev["services"]) == {"api"}
    api = dev["services"]["api"]
    assert api["environment"]["ENVIRONMENT"] == "dev"
    assert api["environment"]["KEYCLOAK_JWKS_URL"].startswith("file://")
    assert all(p.startswith("127.0.0.1:") for p in api["ports"])


def test_secrets_readable_by_container_uids():
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    assert "chmod 700 infra/secrets" in makefile
    assert "chmod 644 infra/secrets/*.txt" in makefile
