"""HTTP API and static hosting of the web app."""

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from datetime import date, timedelta

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import auth as auth_mod
from . import config as config_mod
from . import vault
from .engine.settings import Phase, PhaseTemplate, Settings
from .service import Coach, CoachError
from .sources import Source
from .store import Store
from .sync import Syncer

log = logging.getLogger(__name__)


class App:
    def __init__(self, cfg: config_mod.Config, source: Source | None = None):
        self.cfg = cfg
        self.store = Store(cfg.data_dir / "nutri.db")
        self.source = source or make_source(cfg, self.store)
        self.syncer = Syncer(self.store, self.source)
        self.coach = Coach(self.store)
        self.agent = None
        self.push = None

    def credentials(self) -> dict | None:
        token = self.store.get("cronometer_credentials")
        return vault.open_(self.cfg.secret, token) if token else None

    def connect(self, credentials: dict) -> None:
        """Check the credentials with a real login, then keep them encrypted and switch the source over."""
        from .sources.cronometer import CronometerSource, check_login

        check_login(credentials, self.cfg.data_dir)
        self.store.put("cronometer_credentials", vault.seal(self.cfg.secret, credentials))
        (self.cfg.data_dir / "cronometer-session.json").unlink(missing_ok=True)
        self._switch(CronometerSource(self.cfg.data_dir, credentials))

    def disconnect(self) -> None:
        from .sources.cronometer import CronometerSource

        self.store.x("delete from kv where key='cronometer_credentials'")
        (self.cfg.data_dir / "cronometer-session.json").unlink(missing_ok=True)
        self._switch(CronometerSource(self.cfg.data_dir, None))

    def _switch(self, source: Source) -> None:
        self.source = source
        self.syncer.source = source
        status = self.store.get("sync_status", {})
        status.pop("last_pull", None)  # a new account starts with the full history
        self.store.put("sync_status", status)


def make_source(cfg: config_mod.Config, store: Store) -> Source:
    if cfg.source == "cronometer":
        from .sources.cronometer import CronometerSource

        token = store.get("cronometer_credentials")
        return CronometerSource(cfg.data_dir, vault.open_(cfg.secret, token) if token else None)
    from .sources.demo import DemoSource

    return DemoSource(cfg.today())


def seed_demo(app: App) -> None:
    """A demo account starts with a profile and an active phase, so every screen has something to show."""
    if app.store.get("settings") is not None:
        return
    from .engine.settings import Profile

    s = Settings(
        profile=Profile(
            sex="M", birth_date=date(1996, 5, 10), height_cm=175, activity="moderato", goal_weight_kg=66
        )
    )
    app.coach.save_settings(s)
    today = app.cfg.today()
    app.syncer.run(today, days_back=63)
    app.coach.start_phase("definizione", today - timedelta(days=20))
    app.store.put("demo", True)


class ItemsBody(BaseModel):
    items: list[dict] | None = None


class MealsBody(BaseModel):
    meals: list[dict]


class SwapBody(BaseModel):
    food_id: str
    grams: float
    slot: str | None = None


class ExtraBody(BaseModel):
    slot: str
    food_id: str
    grams: float


class PhaseStart(BaseModel):
    template_id: str
    overrides: dict | None = None


class DecideBody(BaseModel):
    decision: str
    kcal: float | None = None
    adjust_macro: str | None = None


class PreviewBody(BaseModel):
    kcal: float
    adjust_macro: str


class PinBody(BaseModel):
    key: str
    mode: str | None


class WeekBody(BaseModel):
    start: date | None = None
    variety: str = "same"


class RepeatBody(BaseModel):
    source: date
    target: date


class CronometerLogin(BaseModel):
    username: str
    password: str
    totp: str | None = None


class FoodImport(BaseModel):
    cr_food_id: int


class FoodPrefs(BaseModel):
    unit_g: float | None = None
    unit_name: str | None = None
    step_g: float | None = None
    role_override: str | None = None


def create_app(cfg: config_mod.Config | None = None, source: Source | None = None) -> FastAPI:
    cfg = cfg or config_mod.load()
    state = App(cfg, source)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if cfg.source == "demo":
            await asyncio.to_thread(seed_demo, state)
        from .push import Push

        state.push = Push(state)
        from .agent import Agent

        state.agent = Agent(state)
        task = asyncio.create_task(background(state))
        yield
        task.cancel()

    api = FastAPI(title="EverFit", lifespan=lifespan)
    api.state.app = state

    @api.exception_handler(CoachError)
    async def coach_error(_: Request, exc: CoachError):
        return JSONResponse({"detail": str(exc)}, status_code=400)

    def auth(request: Request):
        if auth_mod.session_user(cfg, request) is None:
            raise HTTPException(
                401,
                "accesso richiesto" if cfg.auth == "oidc" else "accesso EverID non configurato sul server",
            )

    def today() -> date:
        return cfg.today()

    def day_arg(d: str | None) -> date:
        return date.fromisoformat(d) if d else today()

    guard = [Depends(auth)]
    c = state.coach

    @api.get("/api/health")
    def health():
        return {"ok": True, "source": state.source.name}

    @api.get("/api/auth")
    def auth_state(request: Request):
        user = auth_mod.session_user(cfg, request)
        return {
            "mode": cfg.auth,
            "ok": user is not None,
            "user": user and {k: user.get(k) for k in ("email", "name")},
        }

    @api.get("/api/bootstrap", dependencies=guard)
    def bootstrap():
        s = c.settings()
        return {
            "settings": s.model_dump(mode="json"),
            "phase": c.phase() and c.phase().model_dump(mode="json"),
            "today": today().isoformat(),
            "source": state.source.name,
            "demo": bool(state.store.get("demo")),
            "sync": state.syncer.status(),
            "agent": state.agent.available() if state.agent else False,
            "needs_profile": s.profile.height_cm is None or s.profile.birth_date is None,
            "cronometer": cronometer_state(),
            "has_weights": bool(state.store.weights()),
        }

    @api.get("/api/today", dependencies=guard)
    def get_today(day: str | None = None):
        return c.today(day_arg(day), today())

    @api.post("/api/plan/{day}/meals/{slot}/confirm", dependencies=guard)
    async def confirm(day: str, slot: str, body: ItemsBody):
        c.confirm_meal(date.fromisoformat(day), slot, today(), body.items)
        kick(state)
        return c.today(date.fromisoformat(day), today())

    @api.post("/api/plan/{day}/meals/{slot}/skip", dependencies=guard)
    def skip(day: str, slot: str):
        c.skip_meal(date.fromisoformat(day), slot, today())
        kick(state)
        return c.today(date.fromisoformat(day), today())

    @api.post("/api/plan/{day}/meals/{slot}/undo", dependencies=guard)
    def undo(day: str, slot: str):
        c.undo_meal(date.fromisoformat(day), slot, today())
        kick(state)
        return c.today(date.fromisoformat(day), today())

    @api.post("/api/plan/{day}/extra", dependencies=guard)
    def extra(day: str, body: ExtraBody):
        c.log_extra(date.fromisoformat(day), body.slot, body.food_id, body.grams)
        kick(state)
        return c.today(date.fromisoformat(day), today())

    @api.get("/api/plan/{day}", dependencies=guard)
    def get_plan(day: str):
        d = date.fromisoformat(day)
        plan = c.plan(d, today())
        if plan is None:
            raise HTTPException(404, "nessun piano")
        return {**plan, "meals": c.meal_views(plan["meals"])}

    @api.post("/api/plan/{day}/fit", dependencies=guard)
    def fit(day: str, body: MealsBody):
        return c.fit_preview(date.fromisoformat(day), today(), body.meals)

    @api.put("/api/plan/{day}", dependencies=guard)
    def put_plan(day: str, body: MealsBody):
        plan = c.save_plan(date.fromisoformat(day), body.meals)
        return {**plan, "meals": c.meal_views(plan["meals"])}

    @api.post("/api/plan/{day}/rebuild", dependencies=guard)
    def rebuild(day: str):
        plan = c.build_plan(date.fromisoformat(day), today())
        return {**plan, "meals": c.meal_views(plan["meals"])}

    @api.post("/api/plan/repeat", dependencies=guard)
    def repeat(body: RepeatBody):
        plan = c.repeat_day(body.source, body.target, today())
        return {**plan, "meals": c.meal_views(plan["meals"])}

    @api.post("/api/foods/alternatives", dependencies=guard)
    def alternatives(body: SwapBody):
        return c.alternatives(body.food_id, body.grams, today(), body.slot)

    @api.post("/api/week/preview", dependencies=guard)
    def week_preview(body: WeekBody):
        start = body.start or (today() + timedelta(days=(7 - today().weekday()) % 7 or 7))
        return c.week_preview(start, today(), body.variety)

    @api.post("/api/week/apply", dependencies=guard)
    def week_apply(body: WeekBody):
        start = body.start or (today() + timedelta(days=(7 - today().weekday()) % 7 or 7))
        return {"saved": c.apply_week(c.week_preview(start, today(), body.variety), today())}

    @api.get("/api/history", dependencies=guard)
    def history(week_start: str | None = None):
        ws = date.fromisoformat(week_start) if week_start else today() - timedelta(days=today().weekday())
        return c.history(ws, today())

    @api.post("/api/templates/pin", dependencies=guard)
    def pin(body: PinBody):
        if body.mode not in (None, "fixed", "use", "hidden"):
            raise HTTPException(400, "modo non valido")
        c.pin_template(body.key, body.mode)
        c._drop_future_plans(today())
        return {"ok": True}

    @api.get("/api/progress", dependencies=guard)
    def progress(days: int = 42):
        return c.progress(today(), max(14, min(days, 365)))

    @api.get("/api/checkin", dependencies=guard)
    def checkin(week_end: str | None = None):
        return c.checkin(today(), date.fromisoformat(week_end) if week_end else None)

    @api.post("/api/checkin/{week_end}/preview", dependencies=guard)
    def checkin_preview(week_end: str, body: PreviewBody):
        return c.checkin_preview(date.fromisoformat(week_end), body.kcal, body.adjust_macro, today())

    @api.post("/api/checkin/{week_end}/decide", dependencies=guard)
    def decide(week_end: str, body: DecideBody):
        return c.decide_checkin(
            date.fromisoformat(week_end), body.decision, today(), body.kcal, body.adjust_macro
        )

    @api.get("/api/settings", dependencies=guard)
    def get_settings():
        return {"settings": c.settings().model_dump(mode="json"), "schema": Settings.model_json_schema()}

    @api.put("/api/settings", dependencies=guard)
    def put_settings(s: Settings):
        c.save_settings(s)
        c._drop_future_plans(today())
        return c.settings().model_dump(mode="json")

    @api.get("/api/phase", dependencies=guard)
    def get_phase():
        p = c.phase()
        return {
            "phase": p and p.model_dump(mode="json"),
            "templates": [t.model_dump(mode="json") for t in c.phase_templates()],
            "schema": Phase.model_json_schema(),
        }

    @api.post("/api/phase", dependencies=guard)
    def start_phase(body: PhaseStart):
        return c.start_phase(body.template_id, today(), body.overrides).model_dump(mode="json")

    @api.patch("/api/phase", dependencies=guard)
    def patch_phase(changes: dict):
        return c.update_phase(changes, today()).model_dump(mode="json")

    @api.post("/api/phase/templates", dependencies=guard)
    def save_template(t: PhaseTemplate):
        return c.save_phase_template(t).model_dump(mode="json")

    @api.get("/api/foods/search", dependencies=guard)
    def search(q: str):
        q = q.strip()
        if len(q) < 2:
            return []
        local = [
            {
                "id": r["id"],
                "name": r["name"],
                "kcal": r["kcal"],
                "protein": r["protein"],
                "carbs": r["carbs"],
                "fat": r["fat"],
                "unit_g": r["unit_g"],
                "unit_name": r["unit_name"],
                "local": True,
            }
            for r in state.store.q("select * from foods where name like ? limit 8", f"%{q}%")
        ]
        try:
            remote = state.source.search(q)
        except Exception as exc:
            log.warning("food search failed: %s", exc)
            remote = []
        known = {r["id"] for r in local}
        return local + [r for r in remote if f"cr:{r.get('cr_food_id')}" not in known and r.get("cr_food_id")]

    @api.post("/api/foods/import", dependencies=guard)
    def import_food(body: FoodImport):
        info = state.source.food(body.cr_food_id)
        state.store.put_food(info.row())
        return info.row()

    @api.patch("/api/foods/{food_id}", dependencies=guard)
    def food_prefs(food_id: str, body: FoodPrefs):
        state.store.update_food_prefs(food_id, **body.model_dump(exclude_unset=True))
        return dict(state.store.food(food_id))

    def cronometer_state() -> dict:
        return {
            "connected": getattr(state.source, "connected", True),
            "username": getattr(state.source, "username", None),
            "demo": state.source.name == "demo",
        }

    @api.get("/api/cronometer", dependencies=guard)
    def cronometer_get():
        return cronometer_state()

    @api.put("/api/cronometer", dependencies=guard)
    async def cronometer_put(body: CronometerLogin):
        if state.source.name == "demo":
            raise HTTPException(400, "In modalità demo non si collega un account")
        creds = {
            "username": body.username.strip(),
            "password": body.password,
            "totp": (body.totp or "").strip() or None,
        }
        if not creds["username"] or not creds["password"]:
            raise HTTPException(400, "Servono email e password")
        try:
            await asyncio.to_thread(state.connect, creds)
        except Exception as exc:
            log.warning("cronometer login failed: %s", type(exc).__name__)
            raise HTTPException(400, f"Cronometer ha rifiutato l'accesso: {str(exc)[:200]}") from exc
        asyncio.get_running_loop().create_task(asyncio.to_thread(state.syncer.run, today()))
        return cronometer_state()

    @api.delete("/api/cronometer", dependencies=guard)
    def cronometer_delete():
        state.disconnect()
        return cronometer_state()

    @api.get("/api/sync", dependencies=guard)
    def sync_status():
        return state.syncer.status()

    @api.post("/api/sync", dependencies=guard)
    async def sync_now():
        return await asyncio.to_thread(state.syncer.run, today())

    from .agent import router as agent_router
    from .push import router as push_router

    api.include_router(agent_router, dependencies=guard)
    api.include_router(push_router, dependencies=guard)
    api.include_router(auth_mod.router)

    if cfg.web_dir:
        assets = cfg.web_dir / "assets"
        if assets.exists():
            api.mount("/assets", StaticFiles(directory=assets), name="assets")

        @api.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            f = (cfg.web_dir / path).resolve()
            if path and f.is_file() and cfg.web_dir.resolve() in f.parents:
                return FileResponse(f)
            return FileResponse(cfg.web_dir / "index.html")

    return api


def kick(state: App) -> None:
    """Push the outbox soon, off the request path."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        state.syncer.push()
        return
    loop.create_task(asyncio.to_thread(state.syncer.push))


async def background(state: App) -> None:
    last_sync = 0.0
    while True:
        try:
            if time.time() - last_sync > state.cfg.sync_minutes * 60:
                await asyncio.to_thread(state.syncer.run, state.cfg.today())
                last_sync = time.time()
            if state.push:
                await asyncio.to_thread(state.push.tick)
        except Exception:
            log.exception("background loop")
        await asyncio.sleep(60)
