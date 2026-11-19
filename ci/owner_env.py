"""Append the personal login to the protected Compose env file."""

import hashlib
import os
import re
import secrets
import sys


def main(path):
    name = os.environ["FIT_UTENTE"]
    credential = os.environ["FIT_PASSWORD"]
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{2,23}", name):
        raise SystemExit("Invalid FIT_UTENTE")
    if not 12 <= len(credential) <= 256:
        raise SystemExit("Invalid FIT_PASSWORD length")
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", credential.encode(), salt, 240_000)
    with open(path, "a", encoding="utf-8", newline="\n") as env:
        print(f"FIT_UTENTE={name}", file=env)
        print(f"FIT_OWNER_HASH='pbkdf2$240000${salt.hex()}${digest.hex()}'", file=env)
        print("FIT_DATA_DIR=/opt/everfit/personal-data", file=env)


if __name__ == "__main__":
    main(sys.argv[1])
