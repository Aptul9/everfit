"""In-app login end to end against a fake central account service, with the server binary: silent authorization
(prompt=none), the app's own form checked through the service's flow executor, the app-fit group, accounts keyed by
`sub`, throttling per client address, logout, and the routes that must keep working without the service.
No page may show the service's name.

    python ci/prova_everid.py path/to/fit
"""
import base64
import hashlib
import http.client
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

ROOT = Path(__file__).resolve().parent.parent
HOST = "127.0.0.1"
SITE = "https://fit.test"
CLIENT_ID = "everfit"
CLIENT_SECRET = "fixture-client-secret"
OWNER = "owner@fixture.test"
CODE = "codiceprova12"
GOOD = "fixture-pw-1234"
failures = []


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else " -> %s" % str(detail)[:300]))
    if not ok:
        failures.append(name)


def b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def user(uid, username, email, groups=("app-fit",), name="Anna Rossi", active=True, mfa=False):
    return {"uid": uid, "username": username, "email": email, "groups": list(groups), "name": name,
            "active": active, "mfa": mfa, "pw": GOOD}


USERS = [
    user("uid-anna", "anna", "anna@fixture.test"),
    user("uid-drive", "drive", "drive@fixture.test", ("app-drive",), "Solo Drive"),
    user("uid-off", "off", "off@fixture.test", active=False),
    user("uid-mfa", "mfa", "mfa@fixture.test", mfa=True),
    user("uid-owner", "owner", OWNER, ("app-fit", "everid-admins"), "Owner"),
    user("uid-spoof", "spoof", OWNER, ("app-fit",), "Spoof"),
]


class Provider:
    """Discovery, authorization (also prompt=none), token and the flow executor, the way the service answers."""

    def __init__(self):
        self.codes = {}
        self.sso = None  # uid of the person signed in at the service in this "browser"
        self.server = ThreadingHTTPServer((HOST, 0), self.handler())
        self.base = "http://%s:%d" % (HOST, self.server.server_port)
        self.issuer = self.base + "/application/o/everfit/"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def find(self, who):
        who = (who or "").strip().lower()
        return next((u for u in USERS if who in (u["username"], u["email"])), None)

    def by_uid(self, uid):
        return next((u for u in USERS if u["uid"] == uid), None)

    def handler(self):
        provider = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def reply(self, status, body, headers=()):
                data = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                for k, v in headers:
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(data)

            def cookie(self, name):
                for part in (self.headers.get("Cookie") or "").split(";"):
                    k, _, v = part.strip().partition("=")
                    if k == name:
                        return v
                return ""

            def do_GET(self):
                path = urlsplit(self.path).path
                if path == "/application/o/everfit/.well-known/openid-configuration":
                    return self.reply(200, {
                        "issuer": provider.issuer,
                        "authorization_endpoint": provider.base + "/application/o/authorize/",
                        "token_endpoint": provider.base + "/application/o/token/",
                        "end_session_endpoint": provider.issuer + "end-session/",
                    })
                if path == "/api/v3/flows/executor/default-authentication-flow/":
                    return self.reply(200, {"component": "ak-stage-identification"},
                                      [("Set-Cookie", "authentik_csrf=csrf1; Path=/")])
                if path == "/api/v3/flows/executor/default-invalidation-flow/":
                    return self.reply(200, {"component": "xak-flow-redirect"})
                if path == "/api/v3/core/users/me/":
                    u = provider.by_uid(self.cookie("authentik_session").split(":")[-1]) if self.cookie("authentik_session").startswith("ok:") else None
                    if not u:
                        return self.reply(403, {})
                    return self.reply(200, {"user": {k: u[k] for k in ("uid", "username", "email", "name")}
                                            | {"is_active": u["active"], "groups": [{"name": g} for g in u["groups"]]}})
                self.reply(404, {})

            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(n).decode()
                path = urlsplit(self.path).path
                if path == "/api/v3/flows/executor/default-authentication-flow/":
                    if self.headers.get("X-authentik-CSRF") != "csrf1":
                        return self.reply(403, {})
                    body = json.loads(raw)
                    comp = body.get("component")
                    if comp == "ak-stage-identification":
                        u = provider.find(body.get("uid_field"))
                        who = u["uid"] if u else "nobody"
                        return self.reply(200, {"component": "ak-stage-password"},
                                          [("Set-Cookie", "authentik_session=id:%s; Path=/" % who)])
                    if comp == "ak-stage-password":
                        who = self.cookie("authentik_session").partition(":")[2]
                        u = provider.by_uid(who)
                        if not u or body.get("password") != u["pw"]:
                            return self.reply(200, {"component": "ak-stage-password", "response_errors": {"x": 1}})
                        if u["mfa"]:
                            return self.reply(200, {"component": "ak-stage-authenticator-validate"})
                        return self.reply(200, {"component": "xak-flow-redirect"},
                                          [("Set-Cookie", "authentik_session=ok:%s; Path=/" % who)])
                    return self.reply(400, {})
                form = {k: v[0] for k, v in parse_qs(raw).items()}
                grant = provider.codes.pop(form.get("code"), None)
                verifier = form.get("code_verifier", "")
                ok = (path == "/application/o/token/" and grant is not None
                      and form.get("grant_type") == "authorization_code"
                      and form.get("client_id") == CLIENT_ID and form.get("client_secret") == CLIENT_SECRET
                      and form.get("redirect_uri") == grant["redirect_uri"]
                      and b64(hashlib.sha256(verifier.encode()).digest()) == grant["challenge"])
                if not ok:
                    return self.reply(400, {"error": "invalid_grant"})
                u = grant["user"]
                now = int(time.time())
                claims = {"iss": provider.issuer, "aud": CLIENT_ID, "exp": now + 300, "iat": now, "nonce": grant["nonce"],
                          "sub": u["uid"], "email": u["email"], "name": u["name"], "preferred_username": u["username"],
                          "groups": u["groups"]}
                id_token = "%s.%s.sig" % (b64(b'{"alg":"RS256"}'), b64(json.dumps(claims).encode()))
                self.reply(200, {"access_token": "a", "token_type": "Bearer", "id_token": id_token})

        return Handler

    def authorize(self, location, user_uid):
        """The browser at the service: returns (query, callback query) as the service sends it back."""
        url = urlsplit(location)
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        assert location.startswith(self.base + "/application/o/authorize/"), location
        assert q["client_id"] == CLIENT_ID and q["response_type"] == "code", q
        assert q["code_challenge_method"] == "S256" and len(q["code_challenge"]) == 43, q
        assert set(q["scope"].split()) == {"openid", "email", "profile"}, q
        who = user_uid if user_uid else self.sso
        if q.get("prompt") == "none" and not who:
            return q, {"error": "login_required", "state": q["state"]}
        code = b64(os.urandom(16))
        self.codes[code] = {"challenge": q["code_challenge"], "nonce": q["nonce"], "redirect_uri": q["redirect_uri"],
                            "user": self.by_uid(who)}
        return q, {"code": code, "state": q["state"]}


def request(port, method, path, body=None, headers=None):
    c = http.client.HTTPConnection(HOST, port, timeout=20)
    try:
        c.request(method, path, body, headers or {})
        r = c.getresponse()
        return r.status, r.read(), r
    finally:
        c.close()


def cookies(response):
    jar = {}
    for k, v in response.getheaders():
        if k.lower() == "set-cookie":
            name, _, value = v.split(";")[0].partition("=")
            jar[name] = value
    return jar


def ck(jar):
    return "; ".join("%s=%s" % (k, v) for k, v in jar.items() if v)


def start(binary, data, provider, **extra):
    with socket.socket() as s:
        s.bind((HOST, 0))
        port = s.getsockname()[1]
    env = {k: v for k, v in os.environ.items() if not k.startswith("FIT_")}
    env.update(FIT_CODICE=CODE, FIT_LOG="warn", FIT_SITO=SITE, TZ="UTC", FIT_OIDC_ISSUER=provider.issuer,
               FIT_OIDC_CLIENT_ID=CLIENT_ID, FIT_OIDC_CLIENT_SECRET=CLIENT_SECRET, FIT_OWNER_EMAIL=OWNER,
               FIT_LOGIN_CODICE="0")
    env.update(extra)
    log = tempfile.TemporaryFile()
    p = subprocess.Popen([binary, "--root", str(ROOT / "app/public"), "--piani", str(ROOT / "app/server/piani"),
                          "--data", str(data), "--host", HOST, "--port", str(port)], env=env, stdout=log, stderr=log)
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and p.poll() is None:
        try:
            if request(port, "GET", "/api/health")[0] == 200:
                return p, port
        except OSError:
            time.sleep(0.05)
    p.kill()
    log.seek(0)
    raise SystemExit("server did not start:\n" + log.read().decode(errors="replace"))


def me(port, jar):
    status, body, _ = request(port, "GET", "/api/io", headers={"Cookie": ck(jar)})
    return status, (json.loads(body) if status == 200 else {})


def form(port, who, pw, ip="198.51.100.1", query=""):
    body = urlencode({"utente": who, "password": pw})
    status, page, r = request(port, "POST", "/accedi" + query, body=body,
                              headers={"Content-Type": "application/x-www-form-urlencoded", "X-Real-IP": ip})
    return status, page, cookies(r), r


def silent(port, provider, query="", extra=None):
    """Opening the app with no session: returns (status of the page, session cookies, location, page)."""
    jar = dict(extra or {})
    status, page, r = request(port, "GET", "/" + query, headers={"Cookie": ck(jar), "Accept": "text/html"})
    jar.update(cookies(r))
    if status != 302:
        return status, jar, r.getheader("Location"), page
    q, back = provider.authorize(r.getheader("Location"), None)
    status, page, r = request(port, "GET", "/oidc/callback?" + urlencode(back), headers={"Cookie": ck(jar)})
    jar.update(cookies(r))
    return status, jar, r.getheader("Location"), page


def login_page(port, query="", jar=None):
    status, page, r = request(port, "GET", "/accedi" + query, headers={"Cookie": ck(jar or {}), "Accept": "text/html"})
    return status, page, r


def named(text):
    low = text.lower()
    return b"everid" in low or b"authentik" in low


def main(binary):
    provider = Provider()
    with tempfile.TemporaryDirectory() as data:
        p, port = start(binary, data, provider)
        try:
            # --- the app shows its own form; the browser never goes to the service
            status, root, r = request(port, "GET", "/", headers={"Accept": "text/html"})
            check("root without session: 401 own form, no redirect", status == 401 and r.getheader("Location") is None and b'name="utente"' in root, status)
            status, page, r = login_page(port)
            check("login page: own form, no redirect", status == 200 and b'name="utente"' in page, status)
            check("page source never shows the service's name or a link to it", not named(page) and b"/oidc/" not in page and b"altre opzioni" not in page)
            status, page, r = request(port, "POST", "/accedi", body=urlencode({"utente": "anna", "password": GOOD}),
                                      headers={"Content-Type": "application/x-www-form-urlencoded", "Origin": "https://evil.example"})
            check("form posted from another site refused (403), no session", status == 403 and not cookies(r).get("fitk"), status)

            # --- form
            status, page, jar, _ = form(port, "anna", GOOD)
            st, info = me(port, jar)
            check("form with username: in, new empty account", status == 303 and st == 200 and info.get("id", 0) > 1
                  and info.get("capo") is False and info.get("utente", "").startswith("anna"), (status, st, info))
            anna = info.get("id")
            status, page, jar2, _ = form(port, "Anna@Fixture.Test", GOOD)
            check("form with e-mail: same account", status == 303 and me(port, jar2)[1].get("id") == anna, status)
            status, page, jar3, _ = form(port, "anna", GOOD)
            check("form login does not open a service session", provider.sso is None)

            status, page1, jar4, _ = form(port, "anna", "wrong", ip="198.51.100.2")
            status2, page2, jar5, _ = form(port, "nobody", "wrong", ip="198.51.100.2")
            e1 = page1.split(b'role="alert">')[1].split(b"<")[0]
            e2 = page2.split(b'role="alert">')[1].split(b"<")[0]
            check("wrong password and wrong user: 401, same generic message, no session",
                  status == 401 and status2 == 401 and e1 == e2 and e1 and not jar4.get("fitk") and not named(page1), (status, e1, e2))
            for _ in range(2):
                form(port, "anna", "wrong", ip="198.51.100.2")
            status, page, jar6, _ = form(port, "anna", "wrong", ip="198.51.100.2")
            check("5th failure still 401", status == 401, status)
            status, page, jar6, _ = form(port, "anna", GOOD, ip="198.51.100.2")
            check("6th attempt from the same address: 429 even with the right password", status == 429 and not jar6.get("fitk"), status)
            status, page, jar6, _ = form(port, "anna", GOOD, ip="198.51.100.3")
            check("another address is not throttled", status == 303 and jar6.get("fitk"), status)

            status, page, jar7, _ = form(port, "drive", GOOD, ip="198.51.100.4")
            check("user outside app-fit refused (403), no session", status == 403 and not jar7.get("fitk") and not named(page), status)
            status, page, jar7, _ = form(port, "off", GOOD, ip="198.51.100.5")
            check("inactive user refused generically", status == 401 and not jar7.get("fitk"), status)
            status, page, jar7, _ = form(port, "mfa", GOOD, ip="198.51.100.6")
            check("second factor needed: form refuses, no session", status == 401 and not jar7.get("fitk"), status)
            status, page, jar7, _ = form(port, "spoof", GOOD, ip="198.51.100.7")
            st, info = me(port, jar7)
            check("owner e-mail without everid-admins: no admin", status == 303 and info.get("capo") is False and info.get("id", 1) > 1, (status, info))
            status, page, jar7, _ = form(port, "owner", GOOD, ip="198.51.100.8")
            st, info = me(port, jar7)
            check("owner with everid-admins: admin account", status == 303 and info.get("id") == 1 and info.get("capo") is True, (status, info))
            owner_jar = jar7

            status, page, jar8, _ = form(port, "anna", GOOD, ip="198.51.100.9", query="?apk=23")
            check("android shell query kept through the form", status == 303, status)
            status, page, r = login_page(port, "?apk=23", {"fitm": "1"})
            check("form action keeps ?apk", b'action="/accedi?apk=23"' in page)

            # --- logout
            status, page, jar9, _ = form(port, "anna", GOOD, ip="10.159.124.30")
            status, body, r = request(port, "POST", "/api/esci", body="{}",
                                      headers={"Cookie": ck(jar9), "Content-Type": "application/json"})
            check("logout ends the session", status == 200 and me(port, jar9)[0] == 401, status)
            status, root, r = request(port, "GET", "/", headers={"Accept": "text/html", "Cookie": "fitz=1"})
            check("after logout the form, no redirect", status == 401 and r.getheader("Location") is None and b'name="utente"' in root, status)

            # --- what must keep working
            status, body, _ = request(port, "GET", "/api/io", headers={"X-Fit-Accesso": "ok"})
            check("PC app and scale path header still admin", status == 200 and json.loads(body).get("capo") is True, status)
            status, _, _ = request(port, "GET", "/api/io")
            check("anonymous API 401", status == 401, status)
            status, _, _ = request(port, "GET", "/.well-known/assetlinks.json")
            check("assetlinks public", status in (200, 404), status)
            status, _, _ = request(port, "GET", "/manifest.webmanifest")
            check("manifest public", status == 200, status)
            status, _, r = request(port, "GET", "/accedi", headers={"Cookie": ck(owner_jar)})
            check("signed in person on /accedi goes to the app", status == 303, status)
        finally:
            p.terminate()
            p.wait(timeout=10)

        # legacy code login switched on: unchanged local login
        p, port = start(binary, data, provider, FIT_LOGIN_CODICE="1")
        try:
            status, page, jar, _ = form(port, "admin", CODE)
            check("legacy on: code login works", status == 303 and me(port, jar)[1].get("id") == 1, status)
        finally:
            p.terminate()
            p.wait(timeout=10)

        # service not configured: the app behaves as before
        p, port = start(binary, data, provider, FIT_OIDC_CLIENT_SECRET="")
        try:
            status, page, r = login_page(port)
            check("service unconfigured: no extra link", status == 200 and b"altre opzioni" not in page and b"/oidc/" not in page, status)
            status, _, r = request(port, "GET", "/", headers={"Accept": "text/html"})
            check("service unconfigured: no silent redirect", status == 401, status)
            status, _, _ = request(port, "GET", "/oidc/login")
            check("service unconfigured: /oidc/login not served", status != 302, status)
        finally:
            p.terminate()
            p.wait(timeout=10)

    if failures:
        sys.exit("In-app login: FAIL %s" % failures)
    print("EverID: PASS")


if __name__ == "__main__":
    main(sys.argv[1])
