"""Sign-in through EverID (Authentik, OpenID Connect, authorization code with PKCE).

The application keeps no password. EverID decides who may enter (the app-fit group); the
optional owner e-mail narrows it to one person. The session is a signed cookie.

The ID token is read without checking its signature: it comes straight from the token
endpoint over TLS, which OpenID Connect Core 3.1.3.7 accepts in place of the signature.
"""

import base64
import hashlib
import hmac
import json
import logging
import secrets
import time
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

log = logging.getLogger(__name__)
router = APIRouter()
SESSION = "nutri_session"
FLOW = "nutri_oidc"
SESSION_DAYS = 90
FLOW_SECONDS = 600


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def seal(secret: str, payload: dict) -> str:
    body = _b64(json.dumps(payload, separators=(",", ":")).encode())
    mac = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{mac}"


def unseal(secret: str, token: str | None, max_age: int) -> dict | None:
    if not token or "." not in token:
        return None
    body, _, mac = token.rpartition(".")
    if not hmac.compare_digest(mac, hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()):
        return None
    try:
        payload = json.loads(_unb64(body))
    except ValueError:
        return None
    if time.time() - payload.get("iat", 0) > max_age:
        return None
    return payload


def session_user(cfg, request: Request) -> dict | None:
    if cfg.auth == "off":
        return {"email": "demo", "name": "Demo"}
    return unseal(cfg.secret, request.cookies.get(SESSION), SESSION_DAYS * 86400)


class Discovery:
    def __init__(self, issuer: str):
        self.issuer = issuer.rstrip("/") + "/"
        self._doc: dict | None = None
        self._at = 0.0

    def get(self) -> dict:
        if self._doc is None or time.time() - self._at > 3600:
            r = httpx.get(self.issuer + ".well-known/openid-configuration", timeout=10)
            r.raise_for_status()
            self._doc = r.json()
            self._at = time.time()
        return self._doc


def _cfg(request: Request):
    return request.app.state.app.cfg


def _discovery(request: Request) -> Discovery:
    state = request.app.state.app
    if getattr(state, "discovery", None) is None:
        state.discovery = Discovery(state.cfg.oidc_issuer)
    return state.discovery


def _safe_next(value: str | None) -> str:
    return value if value and value.startswith("/") and not value.startswith("//") else "/"


@router.get("/oidc/login")
def login(request: Request, next: str | None = None):
    cfg = _cfg(request)
    if cfg.auth != "oidc":
        raise HTTPException(404, "accesso EverID non configurato")
    doc = _discovery(request).get()
    verifier = _b64(secrets.token_bytes(32))
    flow = {
        "state": secrets.token_urlsafe(16),
        "nonce": secrets.token_urlsafe(16),
        "verifier": verifier,
        "next": _safe_next(next),
        "iat": int(time.time()),
    }
    query = urlencode(
        {
            "response_type": "code",
            "client_id": cfg.oidc_client_id,
            "redirect_uri": cfg.public_url + "/oidc/callback",
            "scope": "openid email profile",
            "state": flow["state"],
            "nonce": flow["nonce"],
            "code_challenge": _b64(hashlib.sha256(verifier.encode()).digest()),
            "code_challenge_method": "S256",
        }
    )
    resp = RedirectResponse(f"{doc['authorization_endpoint']}?{query}", status_code=302)
    resp.set_cookie(
        FLOW,
        seal(cfg.secret, flow),
        max_age=FLOW_SECONDS,
        httponly=True,
        samesite="lax",
        secure=cfg.public_url.startswith("https://"),
        path="/oidc",
    )
    return resp


@router.get("/oidc/callback")
def callback(request: Request, code: str | None = None, state: str | None = None, error: str | None = None):
    cfg = _cfg(request)
    if cfg.auth != "oidc":
        raise HTTPException(404, "accesso EverID non configurato")
    flow = unseal(cfg.secret, request.cookies.get(FLOW), FLOW_SECONDS)
    if error:
        raise HTTPException(403, f"EverID ha rifiutato l'accesso: {error}")
    if not flow or not code or not state or not hmac.compare_digest(state, flow["state"]):
        raise HTTPException(400, "Accesso scaduto o non valido: riprova")
    doc = _discovery(request).get()
    tok = httpx.post(
        doc["token_endpoint"],
        timeout=15,
        auth=(cfg.oidc_client_id, cfg.oidc_client_secret),
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": cfg.public_url + "/oidc/callback",
            "code_verifier": flow["verifier"],
        },
    )
    if tok.status_code != 200:
        log.warning("token exchange failed: %s %s", tok.status_code, tok.text[:200])
        raise HTTPException(403, "EverID non ha confermato l'accesso")
    tokens = tok.json()
    try:
        claims = json.loads(_unb64(tokens["id_token"].split(".")[1]))
    except (KeyError, IndexError, ValueError) as exc:
        raise HTTPException(403, "Risposta di EverID non valida") from exc
    if claims.get("nonce") != flow["nonce"] or claims.get("aud") not in (
        cfg.oidc_client_id,
        [cfg.oidc_client_id],
    ):
        raise HTTPException(403, "Risposta di EverID non valida")
    if claims.get("iss", "").rstrip("/") != cfg.oidc_issuer.rstrip("/"):
        raise HTTPException(403, "Risposta di EverID non valida")
    email = (claims.get("email") or "").lower()
    if not email and tokens.get("access_token") and doc.get("userinfo_endpoint"):
        info = httpx.get(
            doc["userinfo_endpoint"],
            timeout=10,
            headers={"authorization": f"Bearer {tokens['access_token']}"},
        )
        if info.status_code == 200:
            email = (info.json().get("email") or "").lower()
    if cfg.owner_email and email != cfg.owner_email:
        log.warning("sign-in refused for %s", email or "(no e-mail)")
        raise HTTPException(403, "Questo account EverID non ha accesso a EverFit")
    session = {
        "sub": claims.get("sub"),
        "email": email,
        "name": claims.get("name") or email,
        "iat": int(time.time()),
    }
    resp = RedirectResponse(flow["next"], status_code=302)
    resp.set_cookie(
        SESSION,
        seal(cfg.secret, session),
        max_age=SESSION_DAYS * 86400,
        httponly=True,
        samesite="lax",
        secure=cfg.public_url.startswith("https://"),
    )
    resp.delete_cookie(FLOW, path="/oidc")
    return resp


@router.get("/oidc/logout")
def logout(request: Request):
    cfg = _cfg(request)
    target = "/"
    if cfg.auth == "oidc":
        try:
            end = _discovery(request).get().get("end_session_endpoint")
            if end:
                target = end
        except httpx.HTTPError:
            pass
    resp = RedirectResponse(target, status_code=302)
    resp.delete_cookie(SESSION)
    return resp
