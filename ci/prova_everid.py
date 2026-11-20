"""Synthetic OIDC provider and HTTP helpers for the OIDC-only server tests."""

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


def b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def user(uid, username, email, groups=("app-fit",), name="Anna Rossi"):
    return {"uid": uid, "username": username, "email": email, "groups": list(groups), "name": name}


USERS = [
    user("uid-anna", "anna", "anna@fixture.test"),
    user("uid-drive", "drive", "drive@fixture.test", ("app-drive",), "Solo Drive"),
    user("uid-owner", "owner", OWNER, ("app-fit", "everid-admins"), "Owner"),
]


class Provider:
    def __init__(self, listen=HOST, advertised=None):
        self.codes = {}
        self.sso = None
        self.server = ThreadingHTTPServer((listen, 0), self.handler())
        self.base = "http://%s:%d" % (advertised or listen, self.server.server_port)
        self.issuer = self.base + "/application/o/everfit/"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def by_uid(self, uid):
        return next((u for u in USERS if u["uid"] == uid), None)

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
                if urlsplit(self.path).path == "/application/o/everfit/.well-known/openid-configuration":
                    return self.reply(200, {
                        "issuer": provider.issuer,
                        "authorization_endpoint": provider.base + "/application/o/authorize/",
                        "token_endpoint": provider.base + "/application/o/token/",
                        "end_session_endpoint": provider.issuer + "end-session/",
                    })
                self.reply(404, {})

            def do_POST(self):
                raw = self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode()
                form = {k: v[0] for k, v in parse_qs(raw).items()}
                grant = provider.codes.pop(form.get("code"), None)
                verifier = form.get("code_verifier", "")
                ok = (urlsplit(self.path).path == "/application/o/token/" and grant is not None
                      and form.get("grant_type") == "authorization_code"
                      and form.get("client_id") == CLIENT_ID and form.get("client_secret") == CLIENT_SECRET
                      and form.get("redirect_uri") == grant["redirect_uri"]
                      and b64(hashlib.sha256(verifier.encode()).digest()) == grant["challenge"])
                if not ok:
                    return self.reply(400, {"error": "invalid_grant"})
                u = grant["user"]
                now = int(time.time())
                claims = {"iss": provider.issuer, "aud": CLIENT_ID, "exp": now + 300, "iat": now,
                          "nonce": grant["nonce"], "sub": u["uid"], "email": u["email"], "name": u["name"],
                          "preferred_username": u["username"], "groups": u["groups"]}
                id_token = "%s.%s.sig" % (b64(b'{"alg":"RS256"}'), b64(json.dumps(claims).encode()))
                self.reply(200, {"access_token": "a", "token_type": "Bearer", "id_token": id_token})

        return Handler

    def authorize(self, location, user_uid):
        q = {k: v[0] for k, v in parse_qs(urlsplit(location).query).items()}
        assert location.startswith(self.base + "/application/o/authorize/"), location
        assert q["client_id"] == CLIENT_ID and q["response_type"] == "code", q
        assert q["code_challenge_method"] == "S256" and len(q["code_challenge"]) == 43, q
        assert set(q["scope"].split()) == {"openid", "email", "profile"}, q
        who = user_uid if user_uid else self.sso
        if q.get("prompt") == "none" and not who:
            return q, {"error": "login_required", "state": q["state"]}
        person = self.by_uid(who)
        assert person is not None, "synthetic user missing"
        code = b64(os.urandom(16))
        self.codes[code] = {"challenge": q["code_challenge"], "nonce": q["nonce"],
                            "redirect_uri": q["redirect_uri"], "user": person}
        return q, {"code": code, "state": q["state"]}


def request(port, method, path, body=None, headers=None):
    connection = http.client.HTTPConnection(HOST, port, timeout=20)
    try:
        connection.request(method, path, body, headers or {})
        response = connection.getresponse()
        return response.status, response.read(), response
    finally:
        connection.close()


def cookies(response):
    jar = {}
    for key, value in response.getheaders():
        if key.lower() == "set-cookie":
            name, _, value = value.split(";")[0].partition("=")
            jar[name] = value
    return jar


def ck(jar):
    return "; ".join("%s=%s" % (k, v) for k, v in jar.items() if v)


def start(binary, data, provider, **extra):
    with socket.socket() as sock:
        sock.bind((HOST, 0))
        port = sock.getsockname()[1]
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("FIT_") and not k.endswith(("_API_KEY", "_SECRET", "_TOKEN", "_PASSWORD"))}
    env.update(FIT_CODICE=CODE, FIT_LOG="warn", FIT_SITO=SITE, TZ="UTC", FIT_OIDC_ISSUER=provider.issuer,
               FIT_OIDC_CLIENT_ID=CLIENT_ID, FIT_OIDC_CLIENT_SECRET=CLIENT_SECRET, FIT_OWNER_EMAIL=OWNER,
               FIT_LOGIN_CODICE="0")
    env.update(extra)
    log = tempfile.TemporaryFile()
    process = subprocess.Popen([binary, "--root", str(ROOT / "app/public"), "--piani", str(ROOT / "app/server/piani"),
                                "--data", str(data), "--host", HOST, "--port", str(port)], env=env, stdout=log, stderr=log)
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and process.poll() is None:
        try:
            if request(port, "GET", "/api/health")[0] == 200:
                return process, port
        except OSError:
            time.sleep(0.05)
    process.kill()
    process.wait()
    log.seek(0)
    raise SystemExit("server did not start:\n" + log.read().decode(errors="replace"))


def me(port, jar):
    status, body, _ = request(port, "GET", "/api/io", headers={"Cookie": ck(jar)})
    return status, json.loads(body) if status == 200 else {}


def form(port, who, pw, ip="198.51.100.1", query=""):
    status, page, response = request(port, "POST", "/accedi" + query, urlencode({"utente": who, "password": pw}),
                                     {"Content-Type": "application/x-www-form-urlencoded", "X-Real-IP": ip})
    return status, page, cookies(response), response


def silent(port, provider, query="", extra=None):
    jar = dict(extra or {})
    status, page, response = request(port, "GET", "/" + query, headers={"Cookie": ck(jar), "Accept": "text/html"})
    jar.update(cookies(response))
    if status != 302:
        return status, jar, response.getheader("Location"), page
    _, back = provider.authorize(response.getheader("Location"), None)
    status, page, response = request(port, "GET", "/oidc/callback?" + urlencode(back), headers={"Cookie": ck(jar)})
    jar.update(cookies(response))
    return status, jar, response.getheader("Location"), page


def named(text):
    return any(s in text.lower() for s in (b"everid", b"authentik"))


if __name__ == "__main__":
    from prova_oidc_only import run
    run(sys.argv[1])
