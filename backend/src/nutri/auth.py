"""Sign-in through EverID (Authentik), invisible to the person.

The app shows its own form; the username (or e-mail) and password are checked on EverID through its flow
executor, the same login flow its own page runs, and are never stored or logged. The account must be in the
`app-fit` group, and the optional owner e-mail narrows it to one person. "Altre opzioni di accesso" leads to the
normal OpenID Connect authorization page (passkeys, second factor). The session is a signed cookie.

The ID token is read without checking its signature: it comes straight from the token
endpoint over TLS, which OpenID Connect Core 3.1.3.7 accepts in place of the signature.
"""

import base64
import hashlib
import hmac
import json
import logging
import secrets
import threading
import time
from collections import defaultdict, deque
from urllib.parse import urlencode, urlsplit

import httpx
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

log = logging.getLogger(__name__)
router = APIRouter()
SESSION = "nutri_session"
FLOW = "nutri_oidc"
SESSION_DAYS = 90
FLOW_SECONDS = 600
GROUP = "app-fit"
LOGIN_FLOW = "default-authentication-flow"
LOGOUT_FLOW = "default-invalidation-flow"
ATTEMPTS = 5  # failed form logins per client address within WINDOW seconds
WINDOW = 600

WRONG = "Nome utente o password sbagliati."
NO_ACCESS = "Questo account non ha accesso a EverFit."
DOWN = "Il servizio di accesso non risponde: riprova tra poco."
TOO_MANY = "Troppi tentativi sbagliati: riprova tra qualche minuto."


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


def _session_cookie(cfg, resp: Response, user: dict) -> None:
    session = {**user, "iat": int(time.time())}
    resp.set_cookie(
        SESSION,
        seal(cfg.secret, session),
        max_age=SESSION_DAYS * 86400,
        httponly=True,
        samesite="lax",
        secure=cfg.public_url.startswith("https://"),
    )


# ---------- the app's own form ----------

_failed: dict[str, deque] = defaultdict(deque)
_failed_lock = threading.Lock()


def _blocked(ip: str, now: float) -> bool:
    with _failed_lock:
        q = _failed[ip]
        while q and now - q[0] > WINDOW:
            q.popleft()
        return len(q) >= ATTEMPTS


def _fail(ip: str, now: float) -> None:
    with _failed_lock:
        _failed[ip].append(now)


class FlowDown(RuntimeError):
    pass


def check_password(
    issuer: str, username: str, password: str, transport: httpx.BaseTransport | None = None
) -> dict | None:
    """Run EverID's real login flow with these credentials: identification, then password. Returns the account
    (`uid`, `email`, `name`, `username`, `groups`) or None when they are wrong. Any other step (second factor,
    denial) or a step asked twice is "not valid" here: the person can still use the authorization page."""
    parts = urlsplit(issuer)
    base = f"{parts.scheme}://{parts.netloc}"
    flow = f"{base}/api/v3/flows/executor/{LOGIN_FLOW}/?query="
    # the executor answers each POST with a 302 to the GET of the next step
    with httpx.Client(
        timeout=15, transport=transport, follow_redirects=True, headers={"accept": "application/json"}
    ) as http:

        def call(url: str, body: dict | None = None) -> tuple[int, dict]:
            headers = {"x-authentik-csrf": http.cookies.get("authentik_csrf") or ""}
            try:
                r = (
                    http.post(url, json=body, headers=headers)
                    if body is not None
                    else http.get(url, headers=headers)
                )
            except httpx.HTTPError as exc:
                log.error("EverID flow executor unreachable: %s", exc)
                raise FlowDown from exc
            try:
                return r.status_code, r.json()
            except ValueError:
                return r.status_code, {}

        _, step = call(flow)
        sent: list[str] = []
        while True:
            comp = step.get("component", "")
            if comp == "xak-flow-redirect":
                break
            if comp == "ak-stage-identification":
                body = {"component": comp, "uid_field": username, "password": password}
            elif comp == "ak-stage-password":
                body = {"component": comp, "password": password}
            elif not comp:
                raise FlowDown
            else:
                log.info("EverID form: step %s not handled", comp)
                return None
            if comp in sent:
                return None
            sent.append(comp)
            _, step = call(flow, body)
        status, me = call(f"{base}/api/v3/core/users/me/")
        if status != 200:
            raise FlowDown
        try:
            call(
                f"{base}/api/v3/flows/executor/{LOGOUT_FLOW}/?query="
            )  # the check needs no session on EverID
        except FlowDown:
            pass
    u = me.get("user") or {}
    email = (u.get("email") or "").strip().lower()
    if u.get("is_active") is not True or not u.get("uid") or "@" not in email:
        return None
    return {
        "uid": u["uid"],
        "email": email,
        "name": (u.get("name") or "").strip() or email,
        "username": u.get("username") or "",
        "groups": [g.get("name") for g in u.get("groups") or []],
    }


class LoginBody(BaseModel):
    username: str
    password: str


@router.post("/api/auth/login")
def form_login(body: LoginBody, request: Request, response: Response):
    cfg = _cfg(request)
    if cfg.auth != "oidc":
        raise HTTPException(404, "accesso EverID non configurato")
    ip = (request.headers.get("x-real-ip") or (request.client.host if request.client else "")).strip()
    now = time.time()
    if _blocked(ip, now):
        raise HTTPException(429, TOO_MANY)
    username = body.username.strip()
    if not username or not body.password or len(username) > 150:
        raise HTTPException(401, WRONG)
    try:
        account = check_password(
            cfg.oidc_issuer, username, body.password, getattr(request.app.state, "everid_transport", None)
        )
    except FlowDown as exc:
        raise HTTPException(502, DOWN) from exc
    if account is None:
        _fail(ip, now)
        raise HTTPException(401, WRONG)
    if GROUP not in account["groups"] or (cfg.owner_email and account["email"] != cfg.owner_email):
        log.info("form sign-in refused for %s", account["email"])
        raise HTTPException(403, NO_ACCESS)
    user = {"sub": account["uid"], "email": account["email"], "name": account["name"]}
    _session_cookie(cfg, response, user)
    return {"ok": True, "user": {"email": user["email"], "name": user["name"]}}


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


@router.post("/api/auth/logout")
def logout(response: Response):
    response.delete_cookie(SESSION)
    return {"ok": True}
