"""The app's own sign-in form, checked on a fake Authentik flow executor that behaves like the live one:
identification, then password, CSRF cookie and header, then /core/users/me/."""

import json

import httpx
import pytest

from nutri import auth

from .test_api import make

ISSUER = "https://id.test/application/o/everfit/"
FLOW = "/api/v3/flows/executor/default-authentication-flow/"


class FakeAuthentik:
    def __init__(self, password="giusta-2026", email="owner@test.it", groups=("app-fit",), mfa=False):
        self.password, self.email, self.groups, self.mfa = password, email, list(groups), mfa
        self.calls: list[str] = []
        self.next = {"component": "ak-stage-identification"}

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.calls.append(f"{request.method} {path}")
        cookies = {"set-cookie": "authentik_csrf=tok; Path=/"}
        if path == FLOW:
            # like the live executor: a POST answers 302 to the GET that returns the next step
            if request.method == "GET":
                return httpx.Response(200, json=self.next, headers=cookies)
            assert request.headers.get("x-authentik-csrf") == "tok"
            body = json.loads(request.content)
            extra = {}
            if body.get("password") != self.password:
                self.next = {"component": body["component"], "response_errors": {}}
            elif body["component"] == "ak-stage-identification" and self.mfa:
                self.next = {"component": "ak-stage-authenticator-validate"}
            else:
                self.next = {"component": "xak-flow-redirect", "to": "/"}
                extra = {"set-cookie": "authentik_session=s1; Path=/"}
            return httpx.Response(302, headers={"location": FLOW + "?query=", **extra})
        if path == "/api/v3/core/users/me/":
            if "authentik_session=s1" not in request.headers.get("cookie", ""):
                return httpx.Response(403, json={})
            return httpx.Response(
                200,
                json={
                    "user": {
                        "uid": "u1",
                        "email": self.email,
                        "name": "Owner",
                        "username": "owner",
                        "is_active": True,
                        "groups": [{"name": g} for g in self.groups],
                    }
                },
            )
        if path.startswith("/api/v3/flows/executor/default-invalidation-flow/"):
            return httpx.Response(200, json={"component": "xak-flow-redirect"})
        return httpx.Response(404)


@pytest.fixture(autouse=True)
def reset_attempts():
    auth._failed.clear()


def client(tmp_path, fake: FakeAuthentik):
    c = make(
        tmp_path,
        auth="oidc",
        public_url="https://fit.test",
        oidc_issuer=ISSUER,
        oidc_client_id="everfit",
        oidc_client_secret="s3cret",
        owner_email="owner@test.it",
    )
    c.app.state.everid_transport = httpx.MockTransport(fake.handler)
    c.base_url = "https://testserver"  # the session cookie is Secure
    return c


def login(c, user="owner", password="giusta-2026", ip="1.2.3.4"):
    return c.post("/api/auth/login", json={"username": user, "password": password}, headers={"x-real-ip": ip})


def test_right_password_opens_a_session(tmp_path):
    fake = FakeAuthentik()
    with client(tmp_path, fake) as c:
        assert c.get("/api/today").status_code == 401
        r = login(c)
        assert r.status_code == 200 and r.json()["user"]["email"] == "owner@test.it"
        assert c.get("/api/today").status_code == 200
        assert "GET /api/v3/flows/executor/default-invalidation-flow/" in fake.calls
        assert c.post("/api/auth/logout").json()["ok"]
        c.cookies.clear()
        assert c.get("/api/today").status_code == 401


def test_wrong_password_and_rate_limit(tmp_path):
    with client(tmp_path, FakeAuthentik()) as c:
        for _ in range(auth.ATTEMPTS):
            r = login(c, password="sbagliata")
            assert r.status_code == 401 and r.json()["detail"] == auth.WRONG
        assert login(c).status_code == 429
        assert login(c, ip="5.6.7.8").status_code == 200


def test_account_without_the_group_or_another_person(tmp_path):
    with client(tmp_path, FakeAuthentik(groups=["app-drive"])) as c:
        assert login(c).status_code == 403
    with client(tmp_path, FakeAuthentik(email="altro@test.it")) as c:
        assert login(c).status_code == 403


def test_second_factor_is_not_handled_by_the_form(tmp_path):
    with client(tmp_path, FakeAuthentik(mfa=True)) as c:
        assert login(c).status_code == 401


def test_everid_down(tmp_path):
    with client(tmp_path, FakeAuthentik()) as c:

        def boom(request):
            raise httpx.ConnectError("down")

        c.app.state.everid_transport = httpx.MockTransport(boom)
        assert login(c).status_code == 502
