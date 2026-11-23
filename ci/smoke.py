"""HTTP smoke test through Caddy.

    python ci/smoke.py --url https://fit.test:4450 --insecure --demo      CI: demo data, sign-in off
    python ci/smoke.py --url https://fit.everbright.it                    production: everything closed but the shell
"""

import argparse
import http.client
import json
import ssl
import sys
from urllib.parse import urlsplit

parser = argparse.ArgumentParser()
parser.add_argument("--url", required=True)
parser.add_argument("--insecure", action="store_true")
parser.add_argument("--demo", action="store_true")
args = parser.parse_args()
base = urlsplit(args.url)
context = ssl._create_unverified_context() if args.insecure else ssl.create_default_context()
failures = []


def request(method, path, body=None):
    connection = http.client.HTTPSConnection(base.hostname, base.port or 443, context=context, timeout=60)
    headers = {"content-type": "application/json"} if body is not None else {}
    connection.request(method, path, body=json.dumps(body) if body is not None else None, headers=headers)
    response = connection.getresponse()
    data = response.read()
    connection.close()
    return response, data


def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name)
    if not ok:
        failures.append(name)


r, data = request("GET", "/api/health")
check("health", r.status == 200 and json.loads(data)["ok"] is True)
r, data = request("GET", "/")
check("web app shell", r.status == 200 and b"<title>EverFit</title>" in data)
check("security headers", "frame-ancestors 'none'" in (r.getheader("content-security-policy") or "")
      and r.getheader("strict-transport-security") is not None)
r, data = request("GET", "/.well-known/assetlinks.json")
check("android app links", r.status == 200 and "json" in (r.getheader("content-type") or "")
      and json.loads(data)[0]["target"]["package_name"] == "it.alias_pv60kg.everfit")
r, data = request("GET", "/manifest.webmanifest")
check("pwa manifest", r.status == 200 and json.loads(data)["name"] == "EverFit")

if args.demo:
    r, data = request("GET", "/api/today")
    today = json.loads(data) if r.status == 200 else {}
    meals = today.get("meals") or []
    check("today", len(meals) == 4)
    slot = next((m["slot"] for m in meals if m["planned"]["kcal"] > 0), "cena")
    r, data = request("POST", f"/api/plan/{today.get('day')}/meals/{slot}/confirm", {})
    eaten = json.loads(data)["consumed"]["kcal"] if r.status == 200 else 0
    check("confirm a meal", eaten > today.get("consumed", {}).get("kcal", 0))
    r, data = request("GET", "/api/progress")
    check("progress", r.status == 200 and json.loads(data)["expenditure"]["status"] == "data")
    r, data = request("GET", "/api/checkin")
    check("check-in", r.status == 200 and "verdict" in json.loads(data))
else:
    r, _ = request("GET", "/api/today")
    check("api closed without a session", r.status == 401)
    r, _ = request("GET", "/oidc/login")
    check("other sign-in options go to EverID", r.status == 302 and "id.everbright.it" in (r.getheader("location") or ""))
    r, data = request("POST", "/api/auth/login", {"username": "smoke-test-nobody", "password": "not-a-password-2026"})
    check("sign-in form reaches EverID and refuses wrong credentials", r.status == 401)

if failures:
    sys.exit(f"{len(failures)} smoke checks failed")
print("smoke: all checks passed")
