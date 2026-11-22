"""Encryption at rest for the Cronometer credentials the owner types in the app.

The key derives from the server secret (`NUTRI_SECRET`, or `secret.key` in the data volume), so a copy of the
SQLite file alone, such as the pre-deploy snapshots, does not reveal the password.
"""

import base64
import hashlib
import json
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def _key(secret: str) -> bytes:
    return hashlib.sha256(f"everfit-cronometer:{secret}".encode()).digest()


def seal(secret: str, data: dict) -> str:
    nonce = os.urandom(12)
    ct = AESGCM(_key(secret)).encrypt(nonce, json.dumps(data).encode(), b"cronometer")
    return base64.b64encode(nonce + ct).decode()


def open_(secret: str, token: str) -> dict:
    raw = base64.b64decode(token)
    return json.loads(AESGCM(_key(secret)).decrypt(raw[:12], raw[12:], b"cronometer"))
