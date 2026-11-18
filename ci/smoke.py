"""HTTP smoke test through Caddy: login, admin-only secret path, forged header ignored, Android app links.

    FIT_CODICE=... FIT_PERCORSO=... python ci/smoke.py --url https://fit.everbright.it [--insecure]
"""
import argparse
import http.client
import json
import os
import ssl
import sys
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
parser = argparse.ArgumentParser()
parser.add_argument("--url", required=True)
parser.add_argument("--insecure", action="store_true")
args = parser.parse_args()
base = urlsplit(args.url)
codice, percorso = os.environ["FIT_CODICE"], os.environ["FIT_PERCORSO"]
context = ssl._create_unverified_context() if args.insecure else ssl.create_default_context()
failures = []


def request(method, path, body=None, headers=None):
    connection = http.client.HTTPSConnection(base.hostname, base.port or 443, context=context, timeout=30)
    connection.request(method, path, body=body, headers=headers or {})
    response = connection.getresponse()
    data = response.read()
    connection.close()
    return response.status, data, response


def check(name, condition, detail=""):
    print(("PASS " if condition else "FAIL ") + name + ("" if condition else " -> %s" % str(detail)[:300]))
    if not condition:
        failures.append(name)


def as_json(data):
    try:
        return json.loads(data)
    except ValueError:
        return None


status, data, _ = request("GET", "/api/health")
check("health 200", status == 200 and as_json(data) == {"ok": True}, (status, data))

status, data, response = request("GET", "/")
check("anonymous root shows EverFit login (401)", status == 401 and b"<title>EverFit</title>" in data and b"Ever<em>Fit" in data, status)
check("no FitFuel left on login page", b"FitFuel" not in data)
check("security headers", response.getheader("X-Content-Type-Options") == "nosniff" and response.getheader("Server") is None)

status, data, _ = request("GET", "/manifest.webmanifest")
manifest = as_json(data) or {}
check("manifest name EverFit", status == 200 and manifest.get("name") == "EverFit" and manifest.get("short_name") == "EverFit", (status, data[:200]))

for header in ("X-Fit-Accesso", "x-fit-accesso"):
    status, data, _ = request("GET", "/api/io", headers={header: "ok"})
    check("forged %s ignored (401)" % header, status == 401, (status, data))

status, data, _ = request("GET", "/%s/api/io" % percorso)
check("secret path is admin", status == 200 and (as_json(data) or {}).get("capo") is True, (status, data))

status, data, response = request("POST", "/accedi", body="utente=admin&password=%s" % codice,
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
cookies = [value for key, value in response.getheaders() if key.lower() == "set-cookie"]
fitk = next((c.split(";")[0] for c in cookies if c.startswith("fitk=")), None)
check("login with FIT_CODICE sets session", status == 303 and fitk is not None and "Secure" in (cookies[0] if cookies else ""), (status, cookies))
if fitk:
    status, data, _ = request("GET", "/api/io", headers={"Cookie": fitk})
    check("session is admin", status == 200 and (as_json(data) or {}).get("capo") is True, (status, data))
    status, data, _ = request("GET", "/", headers={"Cookie": fitk})
    check("app shell 200 with EverFit title", status == 200 and b"<title>EverFit</title>" in data, status)
    status, data, _ = request("POST", "/api/esci", body="{}", headers={"Cookie": fitk, "Content-Type": "application/json"})
    check("logout", status == 200, (status, data))
    status, data, _ = request("GET", "/api/io", headers={"Cookie": fitk})
    check("closed session refused", status == 401, status)

links = ROOT / "app/public/.well-known/assetlinks.json"
status, data, response = request("GET", "/.well-known/assetlinks.json")
if links.is_file():
    check("assetlinks served anonymously as JSON", status == 200 and data == links.read_bytes()
          and (response.getheader("Content-Type") or "").startswith("application/json"), (status, response.getheader("Content-Type")))
else:
    check("assetlinks route present, file not in this release (404)", status == 404, status)

if failures:
    sys.exit("HTTP smoke: FAIL %s" % failures)
print("HTTP smoke: PASS")
