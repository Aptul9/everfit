"""EverID login end to end against a fake OpenID provider, with the server binary: discovery, PKCE, state and nonce,
the app-fit group, accounts keyed by `sub` (owner e-mail reaches the admin account only with everid-admins), logout
through end-session, the username login switch, and the routes that must keep working without EverID.

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
OWNER = "owner@fit.test"
CODE = "codiceprova12"
failures = []


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else " -> %s" % str(detail)[:300]))
    if not ok:
        failures.append(name)


def b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


class Provider:
    """Answers discovery and the token endpoint the way Authentik does, for codes handed out by `authorize`."""

    def __init__(self):
        self.codes = {}
        self.server = ThreadingHTTPServer((HOST, 0), self.handler())
        self.base = "http://%s:%d" % (HOST, self.server.server_port)
        self.issuer = self.base + "/application/o/everfit/"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def handler(self):
        provider = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def reply(self, status, body):
                data = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                if self.path == "/application/o/everfit/.well-known/openid-configuration":
                    return self.reply(200, {
                        "issuer": provider.issuer,
                        "authorization_endpoint": provider.base + "/application/o/authorize/",
                        "token_endpoint": provider.base + "/application/o/token/",
                        "end_session_endpoint": provider.issuer + "end-session/",
                    })
                self.reply(404, {})

            def do_POST(self):
                body = self.rfile.read(int(self.headers["Content-Length"])).decode()
                form = {k: v[0] for k, v in parse_qs(body).items()}
                grant = provider.codes.pop(form.get("code"), None)
                verifier = form.get("code_verifier", "")
                ok = (self.path == "/application/o/token/" and grant is not None
                      and form.get("grant_type") == "authorization_code"
                      and form.get("client_id") == CLIENT_ID and form.get("client_secret") == CLIENT_SECRET
                      and form.get("redirect_uri") == grant["redirect_uri"]
                      and b64(hashlib.sha256(verifier.encode()).digest()) == grant["challenge"])
                if not ok:
                    return self.reply(400, {"error": "invalid_grant"})
                now = int(time.time())
                claims = {"iss": provider.issuer, "aud": CLIENT_ID, "exp": now + 300, "iat": now,
                          "nonce": grant["nonce"], **grant["user"]}
                id_token = "%s.%s.sig" % (b64(b'{"alg":"RS256"}'), b64(json.dumps(claims).encode()))
                self.reply(200, {"access_token": "a", "token_type": "Bearer", "id_token": id_token})

        return Handler

    def authorize(self, location, user):
        """What the browser does at EverID: the person logs in and is sent back with a code."""
        url = urlsplit(location)
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        assert location.startswith(self.base + "/application/o/authorize/"), location
        assert q["client_id"] == CLIENT_ID and q["response_type"] == "code", q
        assert q["code_challenge_method"] == "S256" and len(q["code_challenge"]) == 43, q
        assert set(q["scope"].split()) == {"openid", "email", "profile"}, q
        code = b64(os.urandom(16))
        self.codes[code] = {"challenge": q["code_challenge"], "nonce": q["nonce"],
                            "redirect_uri": q["redirect_uri"], "user": user}
        return q, code


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


def start(binary, data, provider, **extra):
    with socket.socket() as s:
        s.bind((HOST, 0))
        port = s.getsockname()[1]
    env = {k: v for k, v in os.environ.items() if not k.startswith("FIT_")}
    env.update(FIT_CODICE=CODE, FIT_LOG="warn", FIT_SITO=SITE, TZ="UTC", FIT_OIDC_ISSUER=provider.issuer,
               FIT_OIDC_CLIENT_ID=CLIENT_ID, FIT_OIDC_CLIENT_SECRET=CLIENT_SECRET, FIT_OWNER_EMAIL=OWNER)
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


def login(port, provider, user, tamper=None):
    """The whole round trip; returns (callback status, cookies set by the callback)."""
    status, _, r = request(port, "GET", "/oidc/login")
    trip = cookies(r).get("fito", "")
    if status != 302 or not trip:
        return status, {}
    q, code = provider.authorize(r.getheader("Location") or "", user)
    assert q["redirect_uri"] == SITE + "/oidc/callback", q["redirect_uri"]
    state = q["state"]
    if tamper == "state":
        state = ("A" if state[0] != "A" else "B") + state[1:]
    headers = {} if tamper == "cookie" else {"Cookie": "fito=" + trip}
    status, _, r = request(port, "GET", "/oidc/callback?" + urlencode({"code": code, "state": state}), headers=headers)
    return status, cookies(r)


def me(port, jar):
    status, body, _ = request(port, "GET", "/api/io", headers={"Cookie": "fitk=" + jar.get("fitk", "")})
    return status, (json.loads(body) if status == 200 else {})


def person(sub, email, groups=("app-fit",), name="Anna Rossi", username="anna"):
    return {"sub": sub, "email": email, "name": name, "preferred_username": username, "groups": list(groups)}


def main(binary):
    provider = Provider()
    with tempfile.TemporaryDirectory() as data:
        p, port = start(binary, data, provider)
        try:
            status, page, _ = request(port, "GET", "/")
            check("login page offers EverID and the username form", status == 401
                  and b'href="/oidc/login"' in page and b'name="password"' in page and b"form > input" not in page, status)

            # The owner's e-mail without everid-admins (anyone can type it in an EverID profile) is a new account.
            status, jar = login(port, provider, person("sub-spoof", OWNER, username="owner"))
            st, info = me(port, jar)
            check("owner e-mail without everid-admins gets no admin", status == 303 and st == 200
                  and info.get("id", 1) > 1 and info.get("capo") is False, (status, st, info))

            status, jar = login(port, provider, person("sub-owner", OWNER.upper(), ("app-fit", "everid-admins"), "Owner", "owner"))
            st, info = me(port, jar)
            check("owner with everid-admins maps to the admin account", status == 303 and st == 200
                  and info.get("id") == 1 and info.get("capo") is True, (status, st, info))
            owner_jar = jar

            status, jar = login(port, provider, person("sub-admin2", OWNER, ("app-fit", "everid-admins")))
            check("admin account linked once only", me(port, jar)[1].get("id", 1) > 1)

            status, jar = login(port, provider, person("sub-anna", "anna@fit.test"))
            st, info = me(port, jar)
            check("new EverID person gets a new empty account", status == 303 and st == 200 and info.get("id", 0) > 1
                  and info.get("capo") is False and info.get("utente", "").startswith("anna"), (status, st, info))
            anna = info.get("id")
            status, jar = login(port, provider, person("sub-anna", "anna.new@fit.test"))
            check("same sub, same account after an e-mail change", me(port, jar)[1].get("id") == anna)

            status, jar = login(port, provider, person("sub-drive", "drive@fit.test", ("app-drive",)))
            check("without app-fit refused (403), no session", status == 403 and not jar.get("fitk"), status)
            status, jar = login(port, provider, person("sub-x", "x@fit.test"), tamper="state")
            check("forged state refused", status == 400 and not jar.get("fitk"), status)
            status, jar = login(port, provider, person("sub-x", "x@fit.test"), tamper="cookie")
            check("callback without trip cookie refused", status == 400 and not jar.get("fitk"), status)
            status, _, _ = request(port, "GET", "/oidc/callback?error=access_denied")
            check("EverID error shows the login page", status == 401, status)

            status, body, r = request(port, "POST", "/api/esci", body="{}",
                                      headers={"Cookie": "fitk=" + owner_jar["fitk"], "Content-Type": "application/json"})
            dove = (json.loads(body) if status == 200 else {}).get("dove", "")
            q = {k: v[0] for k, v in parse_qs(urlsplit(dove).query).items()}
            check("EverID logout goes to end-session with hint and return address", status == 200
                  and dove.startswith(provider.issuer + "end-session/") and q.get("id_token_hint", "").count(".") == 2
                  and q.get("post_logout_redirect_uri") == SITE + "/", (status, dove))
            check("logged out session refused", me(port, owner_jar)[0] == 401)

            status, _, r = request(port, "POST", "/accedi", body=urlencode({"utente": "admin", "password": CODE}),
                                   headers={"Content-Type": "application/x-www-form-urlencoded"})
            jar = cookies(r)
            check("username login works while the fallback is on", status == 303 and me(port, jar)[1].get("id") == 1, status)
            status, body, _ = request(port, "POST", "/api/esci", body="{}",
                                      headers={"Cookie": "fitk=" + jar.get("fitk", ""), "Content-Type": "application/json"})
            check("username session logout stays local", status == 200 and "dove" not in json.loads(body), body)

            status, body, _ = request(port, "GET", "/api/io", headers={"X-Fit-Accesso": "ok"})
            check("PC app and scale path header still admin", status == 200 and json.loads(body).get("capo") is True, status)
            status, _, _ = request(port, "GET", "/api/io")
            check("anonymous API 401", status == 401, status)
            status, _, _ = request(port, "GET", "/manifest.webmanifest")
            check("manifest public", status == 200, status)
        finally:
            p.terminate()
            p.wait(timeout=10)

        p, port = start(binary, data, provider, FIT_LOGIN_CODICE="0")
        try:
            status, page, _ = request(port, "GET", "/accedi")
            check("fallback off: page shows only EverID", status == 200 and b'href="/oidc/login"' in page
                  and b"form > input" in page, status)
            status, _, r = request(port, "POST", "/accedi", body=urlencode({"utente": "admin", "password": CODE}),
                                   headers={"Content-Type": "application/x-www-form-urlencoded"})
            check("fallback off: username login refused", status == 403 and not cookies(r).get("fitk"), status)
            status, jar = login(port, provider, person("sub-anna", "anna@fit.test"))
            check("fallback off: EverID login still works", status == 303 and me(port, jar)[1].get("id") == anna, status)
            status, body, _ = request(port, "GET", "/api/io", headers={"X-Fit-Accesso": "ok"})
            check("fallback off: PC app and scale path still admin", status == 200 and json.loads(body).get("capo") is True, status)
        finally:
            p.terminate()
            p.wait(timeout=10)

        p, port = start(binary, data, provider, FIT_OIDC_CLIENT_SECRET="")
        try:
            status, page, _ = request(port, "GET", "/accedi")
            check("EverID unconfigured: no button, username form", status == 200 and b"/oidc/login" not in page, status)
            status, _, _ = request(port, "GET", "/oidc/login")
            check("EverID unconfigured: /oidc/login not served", status != 302, status)
        finally:
            p.terminate()
            p.wait(timeout=10)

    if failures:
        sys.exit("EverID: FAIL %s" % failures)
    print("EverID: PASS")


if __name__ == "__main__":
    main(sys.argv[1])
