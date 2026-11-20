"""Exercise OIDC-only login with a synthetic provider and a temporary SQLite database."""

import hashlib
import json
import sqlite3
import sys
import tempfile
from urllib.parse import urlsplit

import prova_everid as fixture


class Provider(fixture.Provider):
    def __init__(self):
        self.form_requests = 0
        super().__init__()

    def handler(self):
        provider = self
        parent = super().handler()

        class Handler(parent):
            def do_POST(self):
                if self.path.startswith("/api/v3/flows/executor/"):
                    provider.form_requests += 1
                return super().do_POST()

        return Handler


def run(binary):
    provider = Provider()
    with tempfile.TemporaryDirectory() as data:
        process, port = fixture.start(binary, data, provider)
        try:
            status, jar, location, _ = fixture.silent(port, provider)
            assert status == 302 and location.startswith(provider.base + "/application/o/authorize/")
            query, _ = provider.authorize(location, "uid-anna")
            assert "prompt" not in query
            print("PASS no central session goes directly to interactive OIDC")

            status, page, _ = fixture.request(port, "GET", "/accedi")
            assert status == 200 and b'name="utente"' not in page and b'type="password"' not in page
            assert not fixture.named(page)
            print("PASS local error page contains no credential form or provider name")

            for fields in ({"utente": "synthetic", "password": "synthetic"},
                           {"utente": "synthetic", "codice": "synthetic"}):
                from urllib.parse import urlencode
                status, _, response = fixture.request(port, "POST", "/accedi", urlencode(fields),
                                                       {"Content-Type": "application/x-www-form-urlencoded"})
                assert status == 403 and not fixture.cookies(response).get("fitk")
            assert provider.form_requests == 0
            print("PASS credential forms refused, no session or flow-executor request")

            provider.sso = "uid-anna"
            status, oidc, location, _ = fixture.silent(port, provider, "?apk=23")
            assert status == 303 and location == "/?apk=23"
            assert fixture.me(port, oidc)[0] == 200
            print("PASS silent OIDC with Android query")

            status, _, first = fixture.request(port, "GET", "/index.html?apk=23", headers={"Accept": "text/html"})
            query, back = provider.authorize(first.getheader("Location"), "uid-anna")
            status, _, callback = fixture.request(port, "GET", "/oidc/callback?" + fixture.urlencode(back),
                                                    headers={"Cookie": fixture.ck(fixture.cookies(first))})
            assert status == 303 and callback.getheader("Location") == "/index.html?apk=23"
            print("PASS private destination and query preserved")

            provider.sso = "uid-drive"
            status, denied, _, _ = fixture.silent(port, provider)
            assert status == 403 and not denied.get("fitk")
            print("PASS OIDC group denied")

            status, _, response = fixture.request(port, "POST", "/api/esci", "{}",
                                                    {"Cookie": fixture.ck(oidc), "Content-Type": "application/json"})
            out = fixture.cookies(response)
            assert status == 200 and out.get("fitz") == "1" and fixture.me(port, oidc)[0] == 401
            status, _, response = fixture.request(port, "GET", "/", headers={"Accept": "text/html", "Cookie": "fitz=1"})
            from urllib.parse import parse_qs
            assert status == 302 and parse_qs(urlsplit(response.getheader("Location")).query).get("prompt") == ["login"]
            print("PASS logout requires interactive central login")

            provider.sso = "uid-anna"
            status, oidc, _, _ = fixture.silent(port, provider)
            assert status == 303

            status, data_json, _ = fixture.request(port, "GET", "/manifest.webmanifest",
                                                    headers={"Cookie": fixture.ck(oidc)})
            assert status == 200
            home = urlsplit(json.loads(data_json)["start_url"]).fragment.removeprefix("k=")
            assert home
            token_hash = hashlib.sha256(oidc["fitk"].encode()).hexdigest()
            home_hash = hashlib.sha256(home.encode()).hexdigest()
            account_id = fixture.me(port, oidc)[1]["id"]
            with sqlite3.connect(data + "/fit.db") as db:
                db.execute("UPDATE sessioni SET vista = 1 WHERE impronta IN (?, ?)", (token_hash, home_hash))
                db.execute("INSERT INTO stato (utente, aggiornato, json) VALUES (?, 1, '{}')", (account_id,))
                db.execute("INSERT INTO everid_sessioni (impronta, id_token) VALUES ('orphan-test', 'synthetic')")
            assert fixture.me(port, oidc)[0] == 401
            status, _, response = fixture.request(port, "POST", "/accedi", "k=" + home,
                                                   {"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"})
            assert status == 401 and not fixture.cookies(response).get("fitk")
            with sqlite3.connect(data + "/fit.db") as db:
                assert db.execute("SELECT COUNT(*) FROM stato").fetchone()[0] == 1
                assert db.execute("SELECT COUNT(*) FROM everid_sessioni WHERE impronta = 'orphan-test'").fetchone()[0] == 1
            print("PASS expired cookie and Home key rejected")

            status, body, _ = fixture.request(port, "GET", "/api/io", headers={"X-Fit-Accesso": "ok"})
            assert status == 200 and json.loads(body)["capo"] is True
            assert fixture.request(port, "GET", "/.well-known/assetlinks.json")[0] == 200
            print("PASS machine header and anonymous Android assetlinks")
        finally:
            process.terminate()
            process.wait(timeout=10)

        process, port = fixture.start(binary, data, provider)
        try:
            assert fixture.me(port, oidc)[0] == 401
            with sqlite3.connect(data + "/fit.db") as db:
                assert db.execute("SELECT COUNT(*) FROM sessioni WHERE impronta IN (?, ?)",
                                  (token_hash, home_hash)).fetchone()[0] == 2
                assert db.execute("SELECT COUNT(*) FROM stato").fetchone()[0] == 1
                assert db.execute("SELECT COUNT(*) FROM everid_sessioni WHERE impronta = 'orphan-test'").fetchone()[0] == 1
            print("PASS restart preserves expired session and Home records without accepting them")
        finally:
            process.terminate()
            process.wait(timeout=10)

    with tempfile.TemporaryDirectory() as data:
        process, port = fixture.start(binary, data, provider, FIT_CODICE="", FIT_OIDC_CLIENT_SECRET="")
        try:
            assert fixture.request(port, "GET", "/api/io")[0] == 401
            status, _, jar, _ = fixture.form(port, "admin", fixture.CODE)
            assert status == 403 and not jar.get("fitk")
            print("PASS missing OIDC and code configuration fails closed")
        finally:
            process.terminate()
            process.wait(timeout=10)

        process, port = fixture.start(binary, data, provider, FIT_LOGIN_CODICE="1", FIT_COOKIE="fixture-old-cookie")
        try:
            status, _, jar, _ = fixture.form(port, "admin", fixture.CODE)
            assert status == 403 and not jar.get("fitk")
            assert fixture.me(port, {"fitk": "fixture-old-cookie"})[0] == 401
            print("PASS legacy code login remains disabled even when configured on")
        finally:
            process.terminate()
            process.wait(timeout=10)
    provider.server.shutdown()
    provider.server.server_close()
    print("OIDC-only: PASS")


if __name__ == "__main__":
    run(sys.argv[1])
