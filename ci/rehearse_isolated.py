"""Isolated Docker rehearsal with a synthetic OIDC provider and a private Compose project.

No host service, sslh configuration, production directory, real secret, or existing Compose project is touched.
It exercises Caddy, the packaged Rust app, OIDC, a persistent volume, upgrade and rollback. It does not execute
the production deploy.sh or test sslh routing: the GitHub runner rehearsal covers those separately.
"""

import http.client
import json
import os
import socket
import ssl
import subprocess
import tempfile
import uuid
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

import prova_everid as fixture

ROOT = Path(__file__).resolve().parent.parent
IMAGE = os.environ.get("EVERFIT_REHEARSE_IMAGE", "local-oidc-review")
ROLLBACK_IMAGE = os.environ.get("EVERFIT_REHEARSE_ROLLBACK_IMAGE", IMAGE)
PROJECT = "fit-review-" + uuid.uuid4().hex[:12]
OLD = PROJECT + "-old"
HOST = "fit.test"


class LocalHTTPS(http.client.HTTPSConnection):
    def connect(self):
        raw = socket.create_connection(("127.0.0.1", self.port), timeout=self.timeout)
        self.sock = self._context.wrap_socket(raw, server_hostname=self.host)


def req(port, method, path, headers=None, body=None):
    c = LocalHTTPS(HOST, port, context=ssl._create_unverified_context(), timeout=20)
    try:
        c.request(method, path, body=body, headers=headers or {})
        response = c.getresponse()
        data = response.read()
        return response.status, data, response
    finally:
        c.close()


def docker(*args, env=None, capture=False, check=True):
    return subprocess.run(["docker", *args], cwd=ROOT, env=env, check=check,
                          capture_output=capture, text=True, timeout=180)


def run():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    provider = fixture.Provider(listen="0.0.0.0", advertised="host.docker.internal")
    env = {k: v for k, v in os.environ.items() if not k.startswith(("FIT_", "OIDC_", "RELEASE", "COMPOSE_"))}
    env.update(RELEASE=IMAGE, FIT_CODICE="isolatedtestcode1234", FIT_PERCORSO="isolated-path-abcdefghijklmnopqrstuvwxyz123456",
               FIT_TLS="internal", FIT_DOMINIO=HOST, HTTPS_PORT=str(port), FIT_LOGIN_CODICE="0",
               FIT_OIDC_ISSUER=provider.issuer, FIT_OIDC_CLIENT_ID=fixture.CLIENT_ID,
               FIT_OIDC_CLIENT_SECRET=fixture.CLIENT_SECRET, FIT_OWNER_EMAIL=fixture.OWNER)
    with tempfile.TemporaryDirectory(prefix="everfit-rehearsal-") as temp:
        override = Path(temp) / "compose.yml"
        override.write_text("services:\n  app:\n    volumes:\n      - isolated-data:/data\nvolumes:\n  isolated-data:\n", encoding="utf-8")
        def compose(*args, check=True):
            return docker("compose", "-p", PROJECT, "-f", str(ROOT / "docker-compose.yml"),
                          "-f", str(override), *args, env=env, check=check)

        for repository in ("everfit", "everfit-web"):
            docker("image", "inspect", f"{repository}:{IMAGE}", env=env, capture=True)
            docker("image", "inspect", f"{repository}:{ROLLBACK_IMAGE}", env=env, capture=True)
            docker("tag", f"{repository}:{ROLLBACK_IMAGE}", f"{repository}:{OLD}", env=env)
        started = False
        try:
            compose("config", "--quiet")
            started = True
            compose("up", "-d", "--wait", "--wait-timeout", "120")
            status, health, _ = req(port, "GET", "/api/health")
            assert status == 200 and json.loads(health) == {"ok": True}
            status, _, first = req(port, "GET", "/?apk=23", {"Accept": "text/html"})
            assert status == 302
            query, back = provider.authorize(first.getheader("Location"), None)
            assert query.get("prompt") == "none" and back.get("error") == "login_required"
            trip = fixture.cookies(first)
            status, _, second = req(port, "GET", "/oidc/callback?" + urlencode(back), {"Cookie": fixture.ck(trip)})
            assert status == 302
            query, back = provider.authorize(second.getheader("Location"), "uid-anna")
            assert "prompt" not in query
            trip = fixture.cookies(second)
            status, _, callback = req(port, "GET", "/oidc/callback?" + urlencode(back), {"Cookie": fixture.ck(trip)})
            assert status == 303 and callback.getheader("Location") == "/?apk=23"
            session = fixture.cookies(callback)
            status, body, _ = req(port, "GET", "/api/io", {"Cookie": fixture.ck(session)})
            account = json.loads(body)
            assert status == 200 and account["id"] > 1 and not account["capo"]
            print("PASS Caddy to packaged app, silent and interactive synthetic OIDC")

            status, _, result = req(port, "POST", "/accedi", {"Content-Type": "application/x-www-form-urlencoded"},
                                     urlencode({"utente": "fixture", "password": "fixture"}))
            assert status == 403 and not fixture.cookies(result).get("fitk")
            status, body, _ = req(port, "GET", "/" + env["FIT_PERCORSO"] + "/api/io")
            assert status == 200 and json.loads(body)["capo"] is True
            assert req(port, "GET", "/api/io", {"X-Fit-Accesso": "ok"})[0] == 401
            assert req(port, "GET", "/.well-known/assetlinks.json")[0] == 200
            print("PASS credential refusal, machine path, header isolation, assetlinks")

            state = json.dumps({"di": account["id"], "updatedAt": 1, "rehearsal": "isolated"})
            status, _, _ = req(port, "PUT", "/api/state", {"Cookie": fixture.ck(session), "Content-Type": "application/json"}, state)
            assert status == 200
            for label, release in (("rollback", OLD), ("upgrade", IMAGE)):
                env["RELEASE"] = release
                compose("up", "-d", "--wait", "--wait-timeout", "120")
                status, body, _ = req(port, "GET", "/api/state", {"Cookie": fixture.ck(session)})
                assert status == 200 and json.loads(body).get("rehearsal") == "isolated"
                status, _, _ = req(port, "POST", "/accedi", {"Content-Type": "application/x-www-form-urlencoded"},
                                   urlencode({"utente": "fixture", "password": "fixture"}))
                assert status == 403
                print("PASS", label, "retains synthetic session and data")
            print("Isolated Compose rehearsal: PASS")
        finally:
            if started:
                compose("down", "--volumes", "--remove-orphans", check=False)
            for repository in ("everfit", "everfit-web"):
                docker("image", "rm", f"{repository}:{OLD}", env=env, capture=True, check=False)
            provider.server.shutdown()
            provider.server.server_close()


if __name__ == "__main__":
    run()
