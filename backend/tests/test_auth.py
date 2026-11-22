"""EverID sign-in against a fake Authentik: the happy path, the owner check, and the closed default."""

import base64
import json
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from nutri import auth

from .test_api import make

ISSUER = "https://id.test/application/o/everfit/"
DOC = {
    "issuer": ISSUER,
    "authorization_endpoint": "https://id.test/application/o/authorize/",
    "token_endpoint": "https://id.test/application/o/token/",
    "userinfo_endpoint": "https://id.test/application/o/userinfo/",
    "end_session_endpoint": "https://id.test/application/o/everfit/end-session/",
}


def jwt(claims: dict) -> str:
    part = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"e30.{part}.sig"


@pytest.fixture
def idp(monkeypatch):
    state = {"email": "owner@test.it", "nonce": None}

    def fake_get(url, **kw):
        assert url == ISSUER + ".well-known/openid-configuration"
        return httpx.Response(200, json=DOC, request=httpx.Request("GET", url))

    def fake_post(url, data=None, auth=None, **kw):
        assert url == DOC["token_endpoint"] and auth == ("everfit", "s3cret")
        assert data["code"] == "good-code" and data["code_verifier"]
        claims = {
            "iss": ISSUER,
            "aud": "everfit",
            "sub": "abc",
            "email": state["email"],
            "name": "Owner",
            "nonce": state["nonce"],
        }
        return httpx.Response(
            200, json={"id_token": jwt(claims), "access_token": "at"}, request=httpx.Request("POST", url)
        )

    monkeypatch.setattr(auth.httpx, "get", fake_get)
    monkeypatch.setattr(auth.httpx, "post", fake_post)
    return state


def oidc_client(tmp_path):
    return make(
        tmp_path,
        auth="oidc",
        public_url="https://fit.test",
        oidc_issuer=ISSUER,
        oidc_client_id="everfit",
        oidc_client_secret="s3cret",
        owner_email="owner@test.it",
    )


def sign_in(c, idp):
    r = c.get("/oidc/login?next=/storico", follow_redirects=False)
    assert r.status_code == 302
    q = parse_qs(urlparse(r.headers["location"]).query)
    assert q["redirect_uri"] == ["https://fit.test/oidc/callback"] and q["code_challenge_method"] == ["S256"]
    idp["nonce"] = q["nonce"][0]
    flow = r.cookies.get(auth.FLOW) or c.cookies.get(auth.FLOW)
    c.cookies.set(auth.FLOW, flow)
    return c.get(f"/oidc/callback?code=good-code&state={q['state'][0]}", follow_redirects=False)


def test_api_is_closed_until_sign_in(tmp_path, idp):
    with oidc_client(tmp_path) as c:
        assert c.get("/api/today").status_code == 401
        assert c.get("/api/auth").json() == {"mode": "oidc", "ok": False, "user": None}
        assert c.get("/api/health").status_code == 200


def test_owner_signs_in_and_lands_where_they_were(tmp_path, idp):
    with oidc_client(tmp_path) as c:
        r = sign_in(c, idp)
        assert r.status_code == 302 and r.headers["location"] == "/storico"
        c.cookies.set(auth.SESSION, r.cookies.get(auth.SESSION))
        assert c.get("/api/auth").json()["user"]["email"] == "owner@test.it"
        assert c.get("/api/today").status_code == 200


def test_someone_else_in_everid_is_refused(tmp_path, idp):
    idp["email"] = "intruder@test.it"
    with oidc_client(tmp_path) as c:
        assert sign_in(c, idp).status_code == 403


def test_forged_state_is_refused(tmp_path, idp):
    with oidc_client(tmp_path) as c:
        c.get("/oidc/login", follow_redirects=False)
        assert c.get("/oidc/callback?code=good-code&state=forged", follow_redirects=False).status_code == 400


def test_without_everid_configured_nothing_opens(tmp_path):
    with make(tmp_path, auth="missing") as c:
        r = c.get("/api/today")
        assert r.status_code == 401 and "non configurato" in r.json()["detail"]


def test_auth_off_only_with_demo(monkeypatch):
    from nutri import config

    monkeypatch.setenv("NUTRI_AUTH", "off")
    assert config._auth("demo") == "off"
    with pytest.raises(SystemExit):
        config._auth("cronometer")
