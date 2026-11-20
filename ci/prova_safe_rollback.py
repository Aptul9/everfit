"""Exercise the OIDC-only rollback image using only a synthetic provider and temporary SQLite data."""

import hashlib
import json
import sqlite3
import sys
import tempfile
from urllib.parse import urlencode, urlsplit

import prova_everid as fixture


def login(port, provider, uid):
    status, _, first = fixture.request(port, "GET", "/oidc/login")
    assert status == 302
    _, back = provider.authorize(first.getheader("Location"), uid)
    status, page, response = fixture.request(port, "GET", "/oidc/callback?" + urlencode(back),
                                               headers={"Cookie": fixture.ck(fixture.cookies(first))})
    return status, page, fixture.cookies(response)


def run(binary):
    provider = fixture.Provider()
    with tempfile.TemporaryDirectory() as data:
        process, port = fixture.start(binary, data, provider, FIT_LOGIN_CODICE="1", FIT_COOKIE="fixture-old-cookie")
        try:
            status, _, jar, _ = fixture.form(port, "admin", fixture.CODE)
            assert status == 403 and not jar.get("fitk")
            assert fixture.me(port, {"fitk": "fixture-old-cookie"})[0] == 401
            status, page, _ = fixture.request(port, "GET", "/accedi")
            assert status == 200 and b'name="utente"' not in page and not fixture.named(page)
            print("PASS rollback image refuses credential and legacy cookie paths")

            status, _, jar = login(port, provider, "uid-anna")
            assert status == 303 and fixture.me(port, jar)[0] == 200
            status, _, denied = login(port, provider, "uid-drive")
            assert status == 403 and not denied.get("fitk")
            print("PASS rollback image OIDC login and group check")

            status, data_json, _ = fixture.request(port, "GET", "/manifest.webmanifest",
                                                    headers={"Cookie": fixture.ck(jar)})
            assert status == 200
            home = urlsplit(json.loads(data_json)["start_url"]).fragment.removeprefix("k=")
            digest_cookie = hashlib.sha256(jar["fitk"].encode()).hexdigest()
            home_hash = hashlib.sha256(home.encode()).hexdigest()
            with sqlite3.connect(data + "/fit.db") as db:
                db.execute("UPDATE sessioni SET vista = 1 WHERE impronta IN (?, ?)", (digest_cookie, home_hash))
                db.execute("INSERT INTO everid_sessioni (impronta, id_token) VALUES ('orphan-test', 'synthetic')")
            assert fixture.me(port, jar)[0] == 401
            status, _, _ = fixture.request(port, "POST", "/accedi", "k=" + home,
                                             {"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"})
            assert status == 401
            status, body, _ = fixture.request(port, "GET", "/api/io", headers={"X-Fit-Accesso": "ok"})
            assert status == 200 and json.loads(body)["capo"] is True
            assert fixture.request(port, "GET", "/.well-known/assetlinks.json")[0] == 200
            print("PASS rollback image expires sessions and keeps machine and Android endpoints")
        finally:
            process.terminate()
            process.wait(timeout=10)

        process, port = fixture.start(binary, data, provider)
        try:
            with sqlite3.connect(data + "/fit.db") as db:
                assert db.execute("SELECT COUNT(*) FROM sessioni WHERE impronta IN (?, ?)",
                                  (digest_cookie, home_hash)).fetchone()[0] == 2
                assert db.execute("SELECT COUNT(*) FROM everid_sessioni WHERE impronta = 'orphan-test'").fetchone()[0] == 1
            print("PASS rollback restart preserves session and Home records")
        finally:
            process.terminate()
            process.wait(timeout=10)

    with tempfile.TemporaryDirectory() as data:
        process, port = fixture.start(binary, data, provider, FIT_CODICE="", FIT_OIDC_CLIENT_SECRET="")
        try:
            assert fixture.request(port, "GET", "/api/io")[0] == 401
            status, _, jar, _ = fixture.form(port, "admin", fixture.CODE)
            assert status == 403 and not jar.get("fitk")
            print("PASS rollback image fails closed without OIDC configuration")
        finally:
            process.terminate()
            process.wait(timeout=10)
    provider.server.shutdown()
    provider.server.server_close()
    print("Safe rollback image: PASS")


if __name__ == "__main__":
    run(sys.argv[1])
