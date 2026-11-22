"""Web Push: the Sunday check-in and the evening reminder for meals left unconfirmed."""

import base64
import json
import logging

from cryptography.hazmat.primitives import serialization
from fastapi import APIRouter, Request
from py_vapid import Vapid01
from pydantic import BaseModel
from pywebpush import WebPushException, webpush

log = logging.getLogger(__name__)
router = APIRouter()
DEFAULTS = {"enabled": True, "checkin_hour": 9, "meals_hour": 21}


class Push:
    def __init__(self, app):
        self.app = app
        self.store = app.store
        path = app.cfg.data_dir / "vapid.pem"
        if not path.exists():
            v = Vapid01()
            v.generate_keys()
            v.save_key(str(path))
        self.vapid = Vapid01.from_file(str(path))
        self.key_path = str(path)

    def public_key(self) -> str:
        raw = self.vapid.public_key.public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
        )
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    def prefs(self) -> dict:
        return {**DEFAULTS, **self.store.get("notifications", {})}

    def send(self, title: str, body: str, url: str = "/") -> int:
        sent = 0
        for r in self.store.q("select * from push_subs"):
            try:
                webpush(
                    json.loads(r["sub"]),
                    json.dumps({"title": title, "body": body, "url": url}),
                    vapid_private_key=self.key_path,
                    vapid_claims={"sub": "mailto:nutri@localhost"},
                )
                sent += 1
            except WebPushException as exc:
                status = getattr(exc.response, "status_code", None)
                if status in (404, 410):
                    self.store.x("delete from push_subs where endpoint=?", r["endpoint"])
                log.warning("push failed: %s", exc)
        return sent

    def tick(self) -> None:
        p = self.prefs()
        if not p["enabled"]:
            return
        now = self.app.cfg.now()
        today = now.date()
        coach = self.app.coach
        sent = self.store.get("push_sent", {})
        key_c = f"checkin:{coach.checkin_week_end(today).isoformat()}"
        if now.hour >= p["checkin_hour"] and key_c not in sent:
            banner = coach.checkin_banner(today)
            if banner and coach.checkin_day(today) == today:
                self.send("Check-in settimanale pronto", banner["headline"], "/checkin")
                sent[key_c] = True
        key_m = f"meals:{today.isoformat()}"
        if now.hour >= p["meals_hour"] and key_m not in sent:
            plan = self.store.plan(today)
            left = [m for m in (plan or {}).get("meals", []) if m["status"] == "planned"]
            if left:
                names = ", ".join(m["slot"] for m in left)
                self.send("Pasti da confermare", f"Mancano: {names}. Conferma o regola i grammi.", "/")
            sent[key_m] = True
        if len(sent) > 200:
            sent = dict(list(sent.items())[-100:])
        self.store.put("push_sent", sent)


class SubBody(BaseModel):
    subscription: dict


@router.get("/api/push/key")
def key(request: Request):
    return {"key": request.app.state.app.push.public_key(), "prefs": request.app.state.app.push.prefs()}


@router.post("/api/push/subscribe")
def subscribe(body: SubBody, request: Request):
    store = request.app.state.app.store
    endpoint = body.subscription.get("endpoint")
    store.x(
        "insert into push_subs(endpoint,sub) values(?,?) on conflict(endpoint) do update set sub=excluded.sub",
        endpoint,
        json.dumps(body.subscription),
    )
    return {"ok": True}


@router.put("/api/push/prefs")
def prefs(body: dict, request: Request):
    store = request.app.state.app.store
    p = {**DEFAULTS, **store.get("notifications", {})}
    p.update({k: v for k, v in body.items() if k in DEFAULTS})
    store.put("notifications", p)
    return p


@router.post("/api/push/test")
def test(request: Request):
    n = request.app.state.app.push.send("EverFit", "Le notifiche funzionano.")
    return {"sent": n}
