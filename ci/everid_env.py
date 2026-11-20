"""Append the EverID login settings to the protected Compose env file, only when all three OIDC values are set."""

import os
import re
import sys

ISSUER = re.compile(r"https://[a-z0-9.-]+/application/o/[a-z0-9-]+/")
EMAIL = re.compile(r"[^@\s'\"]+@[^@\s'\"]+")
SAFE = re.compile(r"[A-Za-z0-9._~-]+")


def main(path):
    issuer = os.environ.get("OIDC_ISSUER", "").strip()
    client_id = os.environ.get("OIDC_CLIENT_ID", "").strip()
    secret = os.environ.get("OIDC_CLIENT_SECRET", "").strip()
    if not (issuer and client_id and secret):
        print("OIDC: not configured, interactive login unavailable")
        return
    if not ISSUER.fullmatch(issuer):
        raise SystemExit("Invalid OIDC_ISSUER")
    if not SAFE.fullmatch(client_id) or not SAFE.fullmatch(secret):
        raise SystemExit("OIDC client id or secret has unexpected characters")
    lines = [f"FIT_OIDC_ISSUER={issuer}", f"FIT_OIDC_CLIENT_ID={client_id}", f"FIT_OIDC_CLIENT_SECRET={secret}"]
    email = os.environ.get("FIT_OWNER_EMAIL", "").strip().lower()
    if email:
        if not EMAIL.fullmatch(email):
            raise SystemExit("Invalid FIT_OWNER_EMAIL")
        lines.append(f"FIT_OWNER_EMAIL={email}")
    login = os.environ.get("FIT_LOGIN_CODICE", "").strip()
    if login:
        if login not in ("0", "1"):
            raise SystemExit("FIT_LOGIN_CODICE must be 0 or 1")
        lines.append(f"FIT_LOGIN_CODICE={login}")
    with open(path, "a", encoding="utf-8", newline="\n") as env:
        for line in lines:
            print(line, file=env)
    print("OIDC: configured, local credential login disabled")


if __name__ == "__main__":
    main(sys.argv[1])
