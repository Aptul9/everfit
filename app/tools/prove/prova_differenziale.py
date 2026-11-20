"""Compare HTTP responses and SQLite state against a Python-created fixture."""

import argparse
from contextlib import contextmanager
import http.client
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time


APP = Path(__file__).resolve().parents[2]
HOST = "127.0.0.1"
ADMIN = {"X-Fit-Accesso": "ok"}
LEGACY = {"Cookie": "fitk=fixture-session"}


def request(port, method, path, body=None, headers=None):
    with_connection = http.client.HTTPConnection(HOST, port, timeout=5)
    try:
        with_connection.request(method, path, body, headers or {})
        response = with_connection.getresponse()
        # The Python version suffix is specific to the reference runtime.
        # Hyper omits the redundant empty-body length on 204/304.
        headers = [(k.lower(), v) for k, v in response.getheaders() if k.lower() != "date"]
        headers = [(k, v.split(" Python/", 1)[0] if k == "server" else v) for k, v in headers]
        if response.status in (204, 304):
            headers = [(k, v) for k, v in headers if (k, v) != ("content-length", "0")]
        return (
            response.status,
            sorted(headers),
            response.read(),
        )
    finally:
        with_connection.close()


@contextmanager
def server(command, public, data, *, with_process=False):
    with socket.socket() as listener:
        listener.bind((HOST, 0))
        port = listener.getsockname()[1]
    env = {k: v for k, v in os.environ.items() if not k.startswith("FIT_") and not k.endswith("_API_KEY")}
    env.update(FIT_CODICE="12345678", FIT_LOG="warn", TZ="UTC")
    with tempfile.TemporaryFile() as log:
        process = subprocess.Popen(
            [*command, "--root", str(public), "--data", str(data), "--host", HOST, "--port", str(port)],
            env=env, stdout=log, stderr=log,
        )
        try:
            deadline = time.monotonic() + 10
            while process.poll() is None and time.monotonic() < deadline:
                try:
                    if request(port, "GET", "/api/health")[0] == 200:
                        break
                except OSError:
                    time.sleep(0.05)
            else:
                log.seek(0)
                raise RuntimeError(log.read().decode(errors="replace"))
            yield (port, process.pid) if with_process else port
        finally:
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
                raise


def snapshot(data):
    with sqlite3.connect(data / "fit.db") as db:
        return [
            db.execute("PRAGMA integrity_check").fetchall(),
            db.execute("PRAGMA journal_mode").fetchone(),
            db.execute("SELECT name, sql FROM sqlite_master ORDER BY name").fetchall(),
            db.execute("SELECT utente, aggiornato, json FROM stato ORDER BY utente").fetchall(),
            db.execute("SELECT utente, giorno, json FROM stato_storia ORDER BY utente, giorno").fetchall(),
        ]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("rust", type=Path)
    parser.add_argument("--python-app", type=Path, default=APP)
    args = parser.parse_args()
    python = [sys.executable, str(APP.parent / "ci/python_reference_no_login.py"), str(args.python_app.resolve())]
    rust = [str(args.rust.resolve()), "--piani", str(args.python_app.resolve() / "server/piani")]
    with tempfile.TemporaryDirectory() as scratch:
        scratch = Path(scratch)
        public = scratch / "public"
        shutil.copytree(APP / "public", public)
        (public / "manifest.webmanifest").write_text('{"start_url":"./?apk=42"}', encoding="utf-8")
        asset = public / ".well-known/assetlinks.json"
        asset.parent.mkdir(exist_ok=True)
        asset.write_text("[]", encoding="utf-8")
        source = scratch / "seed"
        with server(python, public, source) as port:
            assert request(port, "PUT", "/api/state", b'{"di":1,"updatedAt":1}', ADMIN)[0] == 200
        left, right = (shutil.copytree(source, scratch / name) for name in ("python", "rust"))
        for data in (left, right):
            with sqlite3.connect(data / "fit.db") as db:
                now = time.time()
                digest = hashlib.sha256(b"fixture-session").hexdigest()
                db.execute("INSERT INTO sessioni (impronta, utente, tipo, creata, vista) VALUES (?, 1, 'cookie', ?, ?)", (digest, now, now))
        checks = [
            ("GET", "/api/health"), ("HEAD", "/api/health"), ("GET", "/"),
            ("GET", "/accedi"), ("GET", "/api/state"),
            ("GET", "/icons/icon-192.png"), ("GET", "/manifest.webmanifest"),
            ("GET", "/.well-known/assetlinks.json"),
            ("GET", "/manifest.webmanifest", None, LEGACY),
            ("GET", "/", None, ADMIN), ("HEAD", "/js/main.js", None, ADMIN),
            ("GET", "/sw.js?apk=42", None, ADMIN), ("GET", "/missing", None, ADMIN),
            ("GET", "/api/io", None, LEGACY), ("GET", "/api/piano", None, ADMIN),
            ("GET", "/api/misure", None, ADMIN), ("GET", "/api/ai", None, ADMIN),
            ("GET", "/api/state", None, ADMIN), ("POST", "/api/state", None, ADMIN),
            ("PUT", "/api/state", b"[]", ADMIN), ("PUT", "/api/state", b"{", ADMIN),
            ("PUT", "/api/state", b'{ "di": 1, "updatedAt": 2, "giorni": {} }', ADMIN),
            ("PUT", "/api/state", b'{"di":1,"updatedAt":1}', ADMIN),
            ("PUT", "/api/state", b'{"di":2,"updatedAt":3}', ADMIN),
            ("GET", "/api/state/versione", None, ADMIN),
            ("GET", "/api/state", None, ADMIN),
            ("GET", "/api/bilancia/lavoro?attesa=0", None, ADMIN),
        ]

        def exercise(command, data):
            with server(command, public, data) as port:
                result = [request(port, *case) for case in checks]
                etag = dict(result[11][1])["etag"]
                result.append(request(port, "GET", "/sw.js", headers={**ADMIN, "If-None-Match": etag}))
                return result

        expected = exercise(python, left)
        actual = exercise(rust, right)
        assert actual[7][0] == 200 and dict(actual[7][1])["content-type"].split(";")[0] == "application/json"
        assert json.loads(actual[8][2])["start_url"].startswith("./?apk=42#k=")
        differences = {i for i, (a, b) in enumerate(zip(expected, actual, strict=True)) if a != b}
        for i in sorted(differences):
            print(f"{i}: {checks[i][:2] if i < len(checks) else 'conditional sw.js'}")
            for name, results in (("Python", expected), ("Rust", actual)):
                status, headers, body = results[i]
                print(f"  {name}: {status} {headers} {body[:300]!r}")
        # The Rust login page no longer accepts local credentials. Other HTTP and database behavior stays identical.
        assert differences == {2, 3}, differences
        for i in differences:
            assert b'name="utente"' in expected[i][2]
            assert b'name="utente"' not in actual[i][2]
        assert snapshot(left) == snapshot(right), "SQLite schema or state differs"
        with server(python, public, right) as port:
            assert request(port, "GET", "/api/state", headers=ADMIN)[2] == actual[25][2]
        print(f"{len(actual)} HTTP comparisons, two expected login-page differences; SQLite round trip OK")


if __name__ == "__main__":
    main()
