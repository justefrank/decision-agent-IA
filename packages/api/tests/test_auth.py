"""Validation JWT : clé RSA générée, JWKS simulé, sans base de données."""

from __future__ import annotations

import base64
import json
import time

import jwt
from cryptography.hazmat.primitives import serialization


def _b64(data: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b"=").decode()


def _claims(**over):
    now = int(time.time())
    c = {
        "sub": "u",
        "iss": "https://kc.test/auth/realms/decision",
        "aud": "decision-api",
        "exp": now + 300,
        "resource_access": {"decision-web": {"roles": ["admin"]}},
    }
    c.update(over)
    return c


async def test_valid_token_me(ctx_nodb):
    r = await ctx_nodb.client.get("/api/me", headers=ctx_nodb.h("alice", ["analyste"]))
    assert r.status_code == 200
    body = r.json()
    assert body["sub"] == "alice" and body["roles"] == ["analyste"] and body["sees_sql"] is True


async def test_me_exposes_reference_date_and_question_limit(ctx_nodb):
    r = await ctx_nodb.client.get("/api/me", headers=ctx_nodb.h("alice", ["decideur"]))
    body = r.json()
    assert body["reference_date"] == "2026-09-30"
    assert (
        body["question_max_chars"]
        == ctx_nodb.app.state.runtime.semantic.config["agent"]["max_question_chars"]
    )


async def test_missing_token_uniform_error(ctx_nodb):
    r = await ctx_nodb.client.get("/api/me")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "unauthorized"
    assert "request_id" in r.json()["error"]
    assert r.headers["www-authenticate"].startswith("Bearer")


async def test_expired_token(ctx_nodb):
    r = await ctx_nodb.client.get("/api/me", headers=ctx_nodb.h(exp_in=-120))
    assert r.status_code == 401 and r.json()["error"]["message"] == "Jeton expiré."


async def test_not_yet_valid_token(ctx_nodb):
    r = await ctx_nodb.client.get("/api/me", headers=ctx_nodb.h(nbf_in=600))
    assert r.status_code == 401


async def test_wrong_audience(ctx_nodb):
    r = await ctx_nodb.client.get("/api/me", headers=ctx_nodb.h(aud="account"))
    assert r.status_code == 401


async def test_audience_list_accepted(ctx_nodb):
    r = await ctx_nodb.client.get("/api/me", headers=ctx_nodb.h(aud=["account", "decision-api"]))
    assert r.status_code == 200


async def test_wrong_issuer(ctx_nodb):
    r = await ctx_nodb.client.get("/api/me", headers=ctx_nodb.h(iss="https://evil/realms/decision"))
    assert r.status_code == 401


async def test_alg_none_refused(ctx_nodb):
    token = f"{_b64({'alg': 'none', 'typ': 'JWT', 'kid': 'k1'})}.{_b64(_claims())}."
    r = await ctx_nodb.client.get("/api/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401
    assert ctx_nodb.jwks.fetches == 0  # refusé avant toute recherche de clé


async def test_hs256_with_public_key_refused(ctx_nodb):
    # Attaque classique : signer en HS256 avec la clé publique RSA comme secret.
    pub = (
        ctx_nodb.jwks.keys["k1"]
        .public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    )
    import hashlib
    import hmac

    header, payload = _b64({"alg": "HS256", "typ": "JWT", "kid": "k1"}), _b64(_claims())
    sig = hmac.new(pub, f"{header}.{payload}".encode(), hashlib.sha256).digest()
    token = f"{header}.{payload}.{base64.urlsafe_b64encode(sig).rstrip(b'=').decode()}"
    r = await ctx_nodb.client.get("/api/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401


async def test_bad_signature_refused(ctx_nodb):
    from cryptography.hazmat.primitives.asymmetric import rsa

    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    token = jwt.encode(_claims(), other, algorithm="RS256", headers={"kid": "k1"})
    r = await ctx_nodb.client.get("/api/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401


async def test_unknown_kid_refetch_is_rate_limited(ctx_nodb):
    c = ctx_nodb
    assert (await c.client.get("/api/me", headers=c.h())).status_code == 200
    assert c.jwks.fetches == 1
    from cryptography.hazmat.primitives.asymmetric import rsa

    rogue = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    for _ in range(5):
        token = jwt.encode(_claims(), rogue, algorithm="RS256", headers={"kid": "inconnu"})
        r = await c.client.get("/api/me", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 401
    # Premier kid inconnu : au plus un rechargement, puis plus rien pendant l'intervalle minimal.
    assert c.jwks.fetches <= 2


async def test_key_rotation(ctx_nodb, monkeypatch):
    c = ctx_nodb
    assert (await c.client.get("/api/me", headers=c.h())).status_code == 200
    c.jwks.rotate("k2")
    validator = c.app.state.token_validator
    validator.jwks._last_attempt = float("-inf")  # intervalle minimal écoulé
    r = await c.client.get("/api/me", headers=c.h(kid="k2"))
    assert r.status_code == 200
    assert c.jwks.fetches == 2


async def test_roles_only_from_expected_client(ctx_nodb):
    c = ctx_nodb
    # Rôle admin porté par un autre client : ignoré.
    h = c.h("mallory", ["admin"], client="autre-client")
    me = (await c.client.get("/api/me", headers=h)).json()
    assert me["roles"] == [] and me["role"] is None
    assert (await c.client.get("/api/admin/kpis", headers=h)).status_code == 403
    # Rôle de royaume (realm_access) : ignoré aussi.
    h2 = c.h("mallory", [], extra={"realm_access": {"roles": ["admin"]}})
    assert (await c.client.get("/api/admin/kpis", headers=h2)).status_code == 403


async def test_unknown_role_names_ignored(ctx_nodb):
    me = (await ctx_nodb.client.get("/api/me", headers=ctx_nodb.h(roles=["superuser", "decideur"]))).json()
    assert me["roles"] == ["decideur"] and me["sees_sql"] is False


async def test_admin_routes_role_checks_without_db(ctx_nodb):
    c = ctx_nodb
    assert (await c.client.get("/api/admin/kpis", headers=c.h(roles=["decideur"]))).status_code == 403
    r = await c.client.get("/api/admin/kpis", headers=c.h(roles=["analyste"]))
    assert r.status_code == 200 and r.json()["metrics"]
    assert (await c.client.get("/api/admin/settings", headers=c.h(roles=["analyste"]))).status_code == 403
    s = await c.client.get("/api/admin/settings", headers=c.h(roles=["admin"]))
    assert s.status_code == 200
    body = s.json()
    assert body["semantic_version"] and "url" in body["change_procedure"]
    assert "anthropic_api_key" not in json.dumps(body)
    for name in ("tables", "glossary", "examples"):
        assert (
            await c.client.get(f"/api/admin/semantic/{name}", headers=c.h(roles=["analyste"]))
        ).status_code == 200
    assert (await c.client.get("/api/admin/semantic/config", headers=c.h(roles=["admin"]))).status_code == 422


async def test_security_headers(ctx_nodb):
    r = await ctx_nodb.client.get("/api/me", headers=ctx_nodb.h())
    assert r.headers["x-content-type-options"] == "nosniff"
    assert "default-src 'none'" in r.headers["content-security-policy"]
    assert "strict-transport-security" not in r.headers  # pas en dev/test
    assert "access-control-allow-origin" not in r.headers


async def test_hsts_and_cors_in_prod(jwks, builder):
    async with builder(jwks, None, environment="production", cors_origins="https://app.test, *") as c:
        r = await c.client.get("/api/me", headers={**c.h(), "Origin": "https://app.test"})
        assert r.headers["strict-transport-security"].startswith("max-age=")
        assert r.headers["access-control-allow-origin"] == "https://app.test"
        r2 = await c.client.get("/api/me", headers={**c.h(), "Origin": "https://evil.test"})
        assert "access-control-allow-origin" not in r2.headers
        assert (await c.client.get("/api/docs")).status_code == 404


def test_redaction():
    from decision_api.logging_setup import redact

    text = redact(
        "Authorization: Bearer eyJabc.eyJdef.sig api_key=sk-ant-abcdefghijkl "
        "postgresql://app_rw:motdepasse@db:5432/warehouse password=hunter2"
    )
    for secret in ("eyJabc", "sk-ant-abcdefghijkl", "motdepasse", "hunter2"):
        assert secret not in text
