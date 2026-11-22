"""Write the protected Compose env file for the VM from the CI secrets and variables.

Everything the server needs at runtime is a GitHub secret or variable; nothing is typed on the VM. The Cronometer
account is not here: the owner connects it in the app, which keeps the credentials encrypted in its volume.
Values are checked here and again by ci/deploy.sh, and never printed.
"""

import os
import re
import sys

ISSUER = re.compile(r"https://[a-z0-9.-]+/application/o/[a-z0-9-]+/")
EMAIL = re.compile(r"[^@\s'\"]+@[^@\s'\"]+")
SAFE = re.compile(r"[A-Za-z0-9._~-]+")
MODEL = re.compile(r"[a-z0-9.-]+")
DATA_DIR = "/opt/everfit/coach"


def need(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"{name} is not set")
    return value


def lines() -> list[str]:
    issuer = need("OIDC_ISSUER")
    client_id = need("OIDC_CLIENT_ID")
    secret = need("OIDC_CLIENT_SECRET")
    email = need("FIT_OWNER_EMAIL").lower()
    if not ISSUER.fullmatch(issuer):
        raise SystemExit("Invalid OIDC_ISSUER")
    if not SAFE.fullmatch(client_id) or not SAFE.fullmatch(secret):
        raise SystemExit("OIDC client id or secret has unexpected characters")
    if not EMAIL.fullmatch(email):
        raise SystemExit("Invalid FIT_OWNER_EMAIL")
    out = [
        f"NUTRI_OIDC_ISSUER={issuer}",
        f"NUTRI_OIDC_CLIENT_ID={client_id}",
        f"NUTRI_OIDC_CLIENT_SECRET={secret}",
        f"NUTRI_OWNER_EMAIL={email}",
    ]
    model = os.environ.get("NUTRI_AGENT_MODEL", "").strip()
    if model:
        if not MODEL.fullmatch(model):
            raise SystemExit("Invalid NUTRI_AGENT_MODEL")
        out.append(f"NUTRI_AGENT_MODEL={model}")
    out.append(f"FIT_DATA_DIR={DATA_DIR}")
    return out


def main(path: str) -> None:
    content = "".join(line + "\n" for line in lines())
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as env:
        env.write(content)
    print(f"environment: {content.count(chr(10))} lines written")


if __name__ == "__main__":
    main(sys.argv[1])
