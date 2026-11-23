"""Application logic: turns the store and the engine into what the app shows."""

import json
import secrets
from datetime import date, timedelta
from importlib import resources
from statistics import mean

from .engine import expenditure as ex
from .engine.checkin import adjusted_phase, fmt_rate, run_checkin
from .engine.formulas import bmr, expenditure_formulas, prior_expenditure
from .engine.habits import Entry, detect_templates, usual_portions
from .engine.plan import Food, Item, Meal, add, equivalent_grams, fit_day, totals
from .engine.series import days, projection, trend_series, weight_rate
from .engine.settings import Phase, PhaseTemplate, Settings
from .engine.targets import DayTargets, Macros, day_targets, split_macros
from .store import Store, now

SLOT_ORDER = ["colazione", "pranzo", "spuntino", "cena"]
SLOT_LABEL = {"colazione": "Colazione", "pranzo": "Pranzo", "spuntino": "Spuntino", "cena": "Cena"}


class CoachError(ValueError):
    pass


def macros_dict(m: Macros) -> dict:
    m = m.rounded()
    return {"kcal": m.kcal, "protein": m.protein, "carbs": m.carbs, "fat": m.fat}


def builtin_templates() -> list[PhaseTemplate]:
    raw = resources.files("nutri.engine").joinpath("presets/phases.json").read_text(encoding="utf-8")
    return [PhaseTemplate.model_validate(t) for t in json.loads(raw)]


def template_key(slot: str, food_ids) -> str:
    return f"{slot}:{'+'.join(sorted(set(food_ids)))}"


class Coach:
    def __init__(self, store: Store):
        self.store = store
        self._exp_cache: dict = {}

    # configuration

    def settings(self) -> Settings:
        return Settings.model_validate(self.store.get("settings", {}))

    def save_settings(self, s: Settings) -> Settings:
        self.store.put("settings", s.model_dump(mode="json"))
        self._exp_cache.clear()
        return s

    def phase_templates(self) -> list[PhaseTemplate]:
        custom = [PhaseTemplate.model_validate(t) for t in self.store.get("phase_templates", [])]
        return builtin_templates() + custom

    def save_phase_template(self, t: PhaseTemplate) -> PhaseTemplate:
        t = t.model_copy(update={"builtin": False})
        if any(b.id == t.id for b in builtin_templates()):
            raise CoachError("Un modello del libro non si sovrascrive: salvalo con un altro nome.")
        rest = [x for x in self.store.get("phase_templates", []) if x["id"] != t.id]
        self.store.put("phase_templates", rest + [t.model_dump(mode="json")])
        return t

    def phase(self) -> Phase | None:
        raw = self.store.get("phase")
        return Phase.model_validate(raw) if raw else None

    def _set_phase(self, p: Phase, today: date) -> Phase:
        old = self.store.get("phase")
        if old:
            self.store.x(
                "insert into phase_history(started,ended,phase) values(?,?,?)",
                old.get("start"),
                today.isoformat(),
                json.dumps(old),
            )
        self.store.put("phase", p.model_dump(mode="json"))
        self._drop_future_plans(today)
        return p

    def start_phase(self, template_id: str, today: date, overrides: dict | None = None) -> Phase:
        t = next((t for t in self.phase_templates() if t.id == template_id), None)
        if t is None:
            raise CoachError(f"Modello di fase {template_id!r} sconosciuto")
        w = self.weight_now(today)
        if w is None:
            raise CoachError("Serve almeno una pesata su Cronometer per impostare una fase.")
        overrides = dict(overrides or {})
        if "rate_pct_week" in overrides:
            t = t.model_copy(update={"rate_pct_week": overrides.pop("rate_pct_week")})
            overrides["modified"] = True
        p = Phase.from_template(t, today, w)
        if overrides:
            p = Phase.model_validate({**p.model_dump(), **overrides, "modified": True})
        exp = self.expenditure(today)
        params = self.settings().engine
        if p.kcal_target is None:
            base = exp.kcal if p.kind == "reverse" else exp.kcal + p.rate_kg_week * params.kcal_per_kg / 7
            p = p.model_copy(update={"kcal_target": round(base / 25) * 25})
        return self._set_phase(p, today)

    def update_phase(self, changes: dict, today: date) -> Phase:
        p = self.phase()
        if p is None:
            raise CoachError("Nessuna fase attiva")
        changes = dict(changes)
        if "rate_kg_week" in changes and changes["rate_kg_week"] != p.rate_kg_week:
            shift = changes["rate_kg_week"] - p.rate_kg_week
            changes.setdefault(
                "band_kg_week", (round(p.band_kg_week[0] + shift, 2), round(p.band_kg_week[1] + shift, 2))
            )
            if "kcal_target" not in changes and p.kind != "reverse":
                exp = self.expenditure(today).kcal
                base = exp + changes["rate_kg_week"] * self.settings().engine.kcal_per_kg / 7
                changes["kcal_target"] = round(base / 25) * 25
        p = Phase.model_validate({**p.model_dump(), **changes, "modified": True})
        self.store.put("phase", p.model_dump(mode="json"))
        self._drop_future_plans(today)
        return p

    def _drop_future_plans(self, today: date) -> None:
        """Plans the owner has not touched are rebuilt on the new targets. What was eaten is in the
        diary, so a rebuild loses nothing; a plan with edits, copies or skipped meals stays."""
        for r in self.store.q("select day, data from plans where day>=?", today.isoformat()):
            if not self._touched(self._normalize(json.loads(r["data"]))):
                self.store.x("delete from plans where day=?", r["day"])

    # data

    def foods(self) -> dict[str, Food]:
        return {
            r["id"]: Food(
                r["id"],
                r["name"],
                r["kcal"] or 0,
                r["protein"] or 0,
                r["carbs"] or 0,
                r["fat"] or 0,
                r["unit_g"],
                r["unit_name"],
                r["step_g"],
                r["role_override"],
            )
            for r in self.store.q("select * from foods")
        }

    def logs(self) -> dict[date, ex.DayLog]:
        out = {}
        for r in self.store.days():
            mc = r["marked_complete"]
            out[date.fromisoformat(r["day"])] = ex.DayLog(
                r["kcal"] or 0,
                r["protein"] or 0,
                r["carbs"] or 0,
                r["fat"] or 0,
                None if mc is None else bool(mc),
            )
        return out

    def weight_now(self, today: date) -> float | None:
        ws = self.store.weights()
        past = {d: w for d, w in ws.items() if d <= today}
        if not past:
            return None
        e = self.settings().engine
        pts = trend_series(past, max(past), max(past), e.trend_alpha, e.trend_beta)
        return pts[-1].trend

    def prior(self, today: date) -> tuple[float, float]:
        s = self.settings()
        w = self.weight_now(today) or 70.0
        return prior_expenditure(s.profile, w, s.engine.prior_sd_kcal)

    def expenditure_series(self, today: date, start: date | None = None) -> list[ex.Expenditure]:
        key = (today, start, self.store.get("sync_status", {}).get("last_pull"), self.store.get("settings"))
        key = json.dumps(key, default=str)
        if key in self._exp_cache:
            return self._exp_cache[key]
        s = self.settings()
        logs, ws = self.logs(), self.store.weights()
        prior, prior_sd = self.prior(today)
        first = min([*logs, *ws], default=today)
        start = max(start or first, today - timedelta(days=180), first)
        series = ex.estimate_series(start, today, logs, ws, s.engine, prior, prior_sd)
        self._exp_cache = {key: series}
        return series

    def expenditure(self, today: date) -> ex.Expenditure:
        return self.expenditure_series(today)[-1]

    def bmr(self, today: date) -> float | None:
        w = self.weight_now(today)
        return None if w is None else bmr(self.settings().profile, w, today)

    def targets(self, day: date, today: date | None = None) -> DayTargets | None:
        p = self.phase()
        w = self.weight_now(today or day)
        if p is None or w is None:
            return None
        s = self.settings()
        exp = self.expenditure(today or day)
        return day_targets(day, p, exp.kcal, w, s.engine, s.guardrails, self.bmr(today or day))

    def loggable(self, t: DayTargets) -> Macros:
        """The part of the target that goes in the diary: the logging offset is eaten but never logged,
        and the owner's account of it says it is mostly carbohydrates."""
        off = self.settings().engine.logging_offset_kcal
        m = t.macros
        return Macros(m.kcal - off, m.protein, max(0, m.carbs - off / 4), m.fat)

    # habits

    def entries(self, start: date, end: date) -> list[Entry]:
        foods = self.foods()
        return [
            Entry(date.fromisoformat(r["day"]), r["slot"], foods[r["food_id"]], r["grams"])
            for r in self.store.entries(start, end)
            if r["food_id"] in foods
        ]

    def templates(self, today: date, weeks: int = 6) -> list[dict]:
        es = self.entries(today - timedelta(days=7 * weeks), today - timedelta(days=1))
        pins = {r["key"]: r["mode"] for r in self.store.q("select * from template_pins")}
        out = []
        for t in detect_templates(es):
            key = template_key(t.slot, [f.id for f, _ in t.foods])
            out.append(
                {
                    "key": key,
                    "slot": t.slot,
                    "name": t.name,
                    "count": t.count,
                    "last_seen": t.last_seen.isoformat(),
                    "pin": pins.get(key),
                    "items": [
                        {"food_id": f.id, "name": f.name, "grams": g, "range": t.grams_range.get(f.id)}
                        for f, g in t.foods
                    ],
                    "_t": t,
                }
            )
        return out

    def pin_template(self, key: str, mode: str | None) -> None:
        if mode is None:
            self.store.x("delete from template_pins where key=?", key)
        else:
            self.store.x(
                "insert into template_pins(key,mode) values(?,?) on conflict(key) do update set "
                "mode=excluded.mode",
                key,
                mode,
            )

    # plans
    #
    # A plan holds, for each of the four meals, only what is still to eat. What has been eaten is the
    # diary (Cronometer plus the writes still waiting in the outbox), so the two never disagree.

    @staticmethod
    def _new_meal(slot: str) -> dict:
        return {"slot": slot, "skipped": False, "locked": False, "items": [], "seen": []}

    @staticmethod
    def _new_item(food_id: str, grams: float, locked: bool = True) -> dict:
        return {
            "id": secrets.token_hex(4),
            "food_id": food_id,
            "grams": grams,
            "planned_grams": grams,
            "planned_food_id": food_id,
            "locked": locked,
        }

    @staticmethod
    def _key(r) -> list:
        return [r["food_id"], round(r["grams"], 1)]

    def _normalize(self, plan: dict) -> dict:
        """Plans saved before meals held per-food state kept one status per meal. The foods of a meal
        confirmed or logged then are in the diary, so only a meal still to eat keeps its foods."""
        by_slot = {m["slot"]: m for m in plan.get("meals", [])}
        meals = []
        for slot in SLOT_ORDER:
            old = by_slot.get(slot, {})
            status = old.get("status")
            m = self._new_meal(slot)
            m["locked"] = old.get("locked", False)
            m["skipped"] = old.get("skipped", status == "skipped")
            m["seen"] = old.get("seen", [])
            if status not in ("confirmed", "modified", "logged"):
                m["items"] = [
                    {
                        "id": i.get("id") or secrets.token_hex(4),
                        "food_id": i["food_id"],
                        "grams": i["grams"],
                        "planned_grams": i.get("planned_grams"),
                        "planned_food_id": i.get("planned_food_id"),
                        "locked": i.get("locked", False),
                    }
                    for i in old.get("items", [])
                ]
            meals.append(m)
        plan["meals"] = meals
        return plan

    @staticmethod
    def _touched(plan: dict) -> bool:
        return bool(plan.get("edited")) or any(m["skipped"] for m in plan["meals"])

    def _stored(self, day: date) -> dict | None:
        plan = self.store.plan(day)
        return None if plan is None else self._normalize(plan)

    def _save(self, day: date, plan: dict) -> None:
        plan["edited"] = True
        self.store.put_plan(day, plan)

    def _skeleton(self, day: date, today: date) -> dict:
        t = self.targets(day, today)
        return {
            "day": day.isoformat(),
            "source": "nessuno",
            "kind": t.kind if t else "normal",
            "target": macros_dict(self.loggable(t)) if t else None,
            "meals": [self._new_meal(s) for s in SLOT_ORDER],
            "report": None,
            "created": now(),
        }

    def _ensure_plan(self, day: date, today: date) -> dict:
        plan = self._stored(day)
        if plan is None and day >= today and self.phase() is not None:
            try:
                plan = self.build_plan(day, today)
            except CoachError:
                pass  # no weigh-in yet: the day starts empty
        if plan is None:
            plan = self._skeleton(day, today)
        if self._absorb(day, plan) and self.store.plan(day) is not None:
            self.store.put_plan(day, plan)
        return plan

    def _absorb(self, day: date, plan: dict) -> bool:
        """Diary entries the plan has not seen were logged on Cronometer directly. As before, a meal
        logged there takes the place of what the plan still had for it."""
        rows = self.store.entries(day)
        changed = False
        for m in plan["meals"]:
            in_slot = [r for r in rows if r["slot"] == m["slot"]]
            left = [tuple(k) for k in m["seen"]]
            new = False
            for r in in_slot:
                k = tuple(self._key(r))
                if k in left:
                    left.remove(k)
                elif not r["pending"]:
                    new = True
            if new:
                if m["items"] and not m["skipped"]:
                    m["skipped"] = True
                m["seen"] = [self._key(r) for r in in_slot]
                changed = True
        return changed

    def _meal(self, plan: dict, slot: str) -> dict:
        m = next((m for m in plan["meals"] if m["slot"] == slot), None)
        if m is None:
            raise CoachError(f"Pasto {slot!r} sconosciuto: i pasti sono {', '.join(SLOT_ORDER)}")
        return m

    def _eaten(self, day: date) -> Macros:
        foods = self.foods()
        return add(
            foods[r["food_id"]].macros(r["grams"]) for r in self.store.entries(day) if r["food_id"] in foods
        )

    def _left(self, day: date, t: DayTargets) -> Macros:
        base, eaten = self.loggable(t), self._eaten(day)
        return Macros(
            base.kcal - eaten.kcal,
            base.protein - eaten.protein,
            base.carbs - eaten.carbs,
            base.fat - eaten.fat,
        )

    def _meals(self, data: list[dict]) -> list[Meal]:
        foods = self.foods()
        out = []
        for m in data:
            items = [
                Item(
                    foods[i["food_id"]],
                    i["grams"],
                    i.get("locked", False),
                    i.get("planned_grams"),
                    i.get("planned_food_id"),
                )
                for i in m["items"]
                if i["food_id"] in foods
            ]
            skipped = m.get("skipped") or m.get("status") == "skipped"
            out.append(Meal(m["slot"], items, m.get("locked", False), "skipped" if skipped else "planned"))
        return out

    def _meals_json(self, meals: list[Meal]) -> list[dict]:
        return [
            {
                "slot": m.slot,
                "status": m.status,
                "locked": m.locked,
                "items": [
                    {
                        "food_id": i.food.id,
                        "grams": i.grams,
                        "planned_grams": i.planned_grams,
                        "planned_food_id": i.planned_food_id,
                        "locked": i.locked,
                    }
                    for i in m.items
                ],
            }
            for m in meals
        ]

    def _source_meals(self, day: date, today: date) -> tuple[list[Meal], str]:
        tpls = self.templates(today)
        by_slot: dict[str, list[dict]] = {}
        for t in tpls:
            if t["pin"] != "hidden":
                by_slot.setdefault(t["slot"], []).append(t)
        last_week = day - timedelta(days=7)
        prev = [e for e in self.entries(last_week, last_week)]
        logs = self.logs()
        prev_ok = ex.is_complete(
            logs.get(last_week), self.expenditure(today).kcal, self.settings().engine.incomplete_threshold
        )
        meals, sources = [], set()
        for slot in SLOT_ORDER:
            cands = by_slot.get(slot, [])
            fixed = next((t for t in cands if t["pin"] == "fixed"), None)
            if fixed:
                m = fixed["_t"].meal()
                m.locked = True
                meals.append(m)
                sources.add("fisso")
                continue
            prev_items = [e for e in prev if e.slot == slot]
            if prev_ok and prev_items:
                meals.append(Meal(slot, [Item(e.food, e.grams) for e in prev_items]))
                sources.add("settimana scorsa")
            elif cands:
                use = next((t for t in cands if t["pin"] == "use"), cands[0])
                meals.append(use["_t"].meal())
                sources.add("pasti tipo")
        return meals, ", ".join(sorted(sources)) or "nessuno"

    def build_plan(self, day: date, today: date) -> dict:
        """The day's plan from the owner's habits, fitted to what is left of the target. A meal that
        already has foods in the diary is not planned again."""
        t = self.targets(day, today)
        if t is None:
            raise CoachError("Imposta una fase per avere un piano.")
        rows = self.store.entries(day)
        eaten_slots = {r["slot"] for r in rows}
        meals, source = self._source_meals(day, today)
        meals = [m for m in meals if m.slot not in eaten_slots]
        s = self.settings()
        fitted, rep = fit_day(
            meals, self._left(day, t), s.engine.plan_kcal_tolerance, self.phase().adjust_macro
        )
        by_slot = {m.slot: m for m in fitted}
        plan_meals = []
        for slot in SLOT_ORDER:
            m = self._new_meal(slot)
            f = by_slot.get(slot)
            if f:
                m["locked"] = f.locked
                m["items"] = [self._new_item(i.food.id, i.grams, i.locked) for i in f.items]
            m["seen"] = [self._key(r) for r in rows if r["slot"] == slot]
            plan_meals.append(m)
        plan = {
            "day": day.isoformat(),
            "source": source,
            "target": macros_dict(self.loggable(t)),
            "kind": t.kind,
            "meals": plan_meals,
            "report": rep.to_dict(),
            "created": now(),
        }
        self.store.put_plan(day, plan)
        return plan

    def plan(self, day: date, today: date) -> dict:
        return self._ensure_plan(day, today)

    def plan_view(self, day: date, today: date) -> dict:
        """The plan as the editor sees it: what is still to eat, against what is left of the target."""
        plan = self._ensure_plan(day, today)
        t = self.targets(day, today)
        return {
            **plan,
            "target": macros_dict(self._left(day, t)) if t else None,
            "meals": self.meal_views(plan["meals"]),
        }

    def _rebalance(self, day: date, today: date, plan: dict) -> None:
        """Fit what is still to eat around what has been eaten, once the day no longer adds up the way
        the plan expected. Foods set by hand (added, edited, copied) and locked meals keep their grams."""
        t, p = self.targets(day, today), self.phase()
        if t is None or p is None:
            return
        foods = self.foods()
        meals, ids = [], []
        for m in plan["meals"]:
            its = [i for i in m["items"] if i["food_id"] in foods]
            meals.append(
                Meal(
                    m["slot"],
                    [
                        Item(
                            foods[i["food_id"]],
                            i["grams"],
                            i["locked"],
                            i.get("planned_grams"),
                            i.get("planned_food_id"),
                        )
                        for i in its
                    ],
                    m["locked"],
                    "skipped" if m["skipped"] else "planned",
                )
            )
            ids.append([i["id"] for i in its])
        tol = self.settings().engine.plan_kcal_tolerance
        target = self._left(day, t)
        gap = totals(meals).kcal - target.kcal
        rep = plan.get("report") or {}
        expected = (
            rep["totals"]["kcal"] - rep["target"]["kcal"] if rep.get("totals") and rep.get("target") else 0
        )
        if abs(gap) <= tol or abs(gap - expected) <= tol / 2:
            return
        fitted, report = fit_day(meals, target, tol, p.adjust_macro)
        grams = {
            iid: i.grams
            for fm, mids in zip(fitted, ids, strict=True)
            for iid, i in zip(mids, fm.items, strict=True)
        }
        for m in plan["meals"]:
            for i in m["items"]:
                if i["id"] in grams:
                    i["grams"] = grams[i["id"]]
        plan["report"] = report.to_dict()

    def _log_entry(self, day: date, plan: dict, slot: str, food_id: str, grams: float) -> None:
        eid = self.store.add_pending_entry(day, slot, food_id, grams)
        self.store.enqueue(
            "add_serving",
            {"day": day.isoformat(), "slot": slot, "food_id": food_id, "grams": grams, "entry_id": eid},
        )
        self._meal(plan, slot)["seen"].append([food_id, round(grams, 1)])

    def _unlog(self, day: date, plan: dict, row) -> None:
        """Take an entry out of the diary: still in the outbox, it never leaves; already on Cronometer,
        it is deleted there too."""
        if row["pending"]:
            for o in self.store.pending():
                if json.loads(o["payload"]).get("entry_id") == row["id"]:
                    self.store.x("delete from outbox where id=?", o["id"])
        elif row["serving_id"]:
            self.store.enqueue(
                "delete_servings", {"day": day.isoformat(), "serving_ids": [row["serving_id"]]}
            )
        self.store.delete_entry(row["id"])
        seen = self._meal(plan, row["slot"])["seen"]
        if self._key(row) in seen:
            seen.remove(self._key(row))

    @staticmethod
    def entry_ref(row) -> str:
        return f"s:{row['serving_id']}" if row["serving_id"] else f"e:{row['id']}"

    def _find(self, day: date, plan: dict, ref: str):
        """An item by reference: p:<id> for a planned food, s:<serving id> or e:<entry id> for an eaten one."""
        kind, _, key = ref.partition(":")
        if kind == "p":
            for m in plan["meals"]:
                for i in m["items"]:
                    if i["id"] == key:
                        return "plan", m, i
        elif kind in ("s", "e"):
            if kind == "e":  # pushed since the view was loaded: now known by its Cronometer serving
                for o in self.store.q(
                    "select payload from outbox where kind='add_serving' and payload like ?", f"%{key}%"
                ):
                    p = json.loads(o["payload"])
                    if str(p.get("entry_id")) == key and p.get("serving_id"):
                        ref = f"s:{p['serving_id']}"
            for r in self.store.entries(day):
                if self.entry_ref(r) == ref or (kind == "e" and str(r["id"]) == key):
                    return "diary", self._meal(plan, r["slot"]), r
        raise CoachError("Alimento non trovato: la giornata è cambiata, ricaricala.")

    def _check_food(self, food_id: str, grams: float) -> None:
        if self.store.food(food_id) is None:
            raise CoachError(f"Alimento {food_id} sconosciuto")
        if grams <= 0:
            raise CoachError("Servono dei grammi maggiori di zero")

    def add_item(
        self, day: date, slot: str, food_id: str, grams: float, today: date, eaten: bool = False
    ) -> dict:
        """Add a food to a meal: eaten goes to the diary (and Cronometer), otherwise into the plan."""
        self._check_food(food_id, grams)
        plan = self._ensure_plan(day, today)
        m = self._meal(plan, slot)
        if eaten:
            self._log_entry(day, plan, slot, food_id, grams)
            self._rebalance(day, today, plan)
        else:
            if m["skipped"]:
                m["items"], m["skipped"] = [], False
            m["items"].append(self._new_item(food_id, grams))
        self._save(day, plan)
        return self.today(day, today)

    def update_item(self, day: date, ref: str, grams: float, today: date) -> dict:
        """New grams for a food. A planned one just changes; an eaten one is replaced on Cronometer."""
        if grams <= 0:
            raise CoachError("Per togliere un alimento usa Elimina")
        plan = self._ensure_plan(day, today)
        kind, m, it = self._find(day, plan, ref)
        if kind == "plan":
            it["grams"] = grams
            it["locked"] = True
        elif round(it["grams"], 1) != round(grams, 1):
            self._unlog(day, plan, it)
            self._log_entry(day, plan, it["slot"], it["food_id"], grams)
            self._rebalance(day, today, plan)
        self._save(day, plan)
        return self.today(day, today)

    def delete_item(self, day: date, ref: str, today: date) -> dict:
        """Remove a food from its meal: from the plan, or from the diary and Cronometer."""
        plan = self._ensure_plan(day, today)
        kind, m, it = self._find(day, plan, ref)
        if kind == "plan":
            m["items"].remove(it)
            if not m["items"]:
                m["skipped"] = False
        else:
            self._unlog(day, plan, it)
            self._rebalance(day, today, plan)
        self._save(day, plan)
        return self.today(day, today)

    def confirm_items(self, day: date, slot: str, today: date, refs: list[str] | None = None) -> dict:
        """Mark planned foods of a meal as eaten (all that is left, or the given p:<id> refs): they go to
        the diary and Cronometer with their grams."""
        plan = self._ensure_plan(day, today)
        m = self._meal(plan, slot)
        todo = [i for i in m["items"] if refs is None or f"p:{i['id']}" in refs]
        if not todo:
            raise CoachError("In questo pasto non c'è niente da confermare")
        for i in todo:
            if i["grams"] > 0:
                self._log_entry(day, plan, slot, i["food_id"], i["grams"])
        m["items"] = [i for i in m["items"] if i not in todo]
        if not m["items"]:
            m["skipped"] = False
        self._rebalance(day, today, plan)
        self._maybe_complete(day, plan)
        self.store.put_plan(day, plan)
        return self.today(day, today)

    def confirm_meal(self, day: date, slot: str, today: date, items: list[dict] | None = None) -> dict:
        """Eaten as planned, or with `items` ({food_id, grams}) in place of what was left to eat."""
        if items is not None:
            plan = self._ensure_plan(day, today)
            for i in items:
                self._check_food(i["food_id"], i["grams"])
            m = self._meal(plan, slot)
            m["items"] = [self._new_item(i["food_id"], i["grams"]) for i in items]
            m["skipped"] = False
            self.store.put_plan(day, plan)
        return self.confirm_items(day, slot, today)

    def skip_meal(self, day: date, slot: str, today: date) -> dict:
        """What is left of a meal will not be eaten; the rest of the day is refitted."""
        plan = self._ensure_plan(day, today)
        m = self._meal(plan, slot)
        if not m["items"] or m["skipped"]:
            raise CoachError("In questo pasto non c'è niente da saltare")
        m["skipped"] = True
        self._rebalance(day, today, plan)
        self._maybe_complete(day, plan)
        self._save(day, plan)
        return self.today(day, today)

    def undo_meal(self, day: date, slot: str, today: date) -> dict:
        """Bring back what was skipped. A food already eaten is removed from its own row instead."""
        plan = self._ensure_plan(day, today)
        m = self._meal(plan, slot)
        if not m["skipped"]:
            raise CoachError(
                "Si annulla solo un pasto saltato: un alimento mangiato si elimina dalla sua riga"
            )
        m["skipped"] = False
        self._rebalance(day, today, plan)
        self.store.put_plan(day, plan)
        return self.today(day, today)

    def log_extra(self, day: date, slot: str, food_id: str, grams: float, today: date | None = None) -> dict:
        return self.add_item(day, slot, food_id, grams, today or day, eaten=True)

    def copy_meals(self, source: date, target: date, slots: list[str] | None, today: date) -> dict:
        """Copy what was eaten in some meals of `source` into the same meals of `target`, with the same
        grams: nothing is refitted. The copies land as planned, to confirm; in a meal that already has
        foods the planned ones are replaced and the eaten ones stay."""
        if source == target:
            raise CoachError("Scegli un giorno diverso da cui copiare")
        foods = self.foods()
        by_slot: dict[str, list] = {}
        for r in self.store.entries(source):
            if r["food_id"] in foods:
                by_slot.setdefault(r["slot"], []).append(r)
        chosen = [s for s in (slots or SLOT_ORDER) if by_slot.get(s)]
        if not chosen:
            raise CoachError("Nei pasti scelti non c'è niente da copiare")
        plan = self._ensure_plan(target, today)
        for s in chosen:
            m = self._meal(plan, s)
            m["items"] = [self._new_item(r["food_id"], r["grams"]) for r in by_slot[s]]
            m["skipped"] = False
        plan["source"] = f"copiato dal {source.isoformat()}"
        self._save(target, plan)
        return self.today(target, today)

    def _maybe_complete(self, day: date, plan: dict) -> None:
        if any(m["items"] and not m["skipped"] for m in plan["meals"]) or not self.store.entries(day):
            return
        row = self.store.q("select marked_complete from diary_days where day=?", day.isoformat())
        if row and row[0]["marked_complete"]:
            return
        self.store.enqueue("mark_complete", {"day": day.isoformat(), "complete": True})
        self.store.set_marked(day, True)

    def fit_preview(self, day: date, today: date, meals: list[dict]) -> dict:
        t = self.targets(day, today)
        ms = self._meals(meals)
        fitted, rep = fit_day(
            ms, self._left(day, t), self.settings().engine.plan_kcal_tolerance, self.phase().adjust_macro
        )
        return {"meals": self.meal_views(self._meals_json(fitted)), "report": rep.to_dict()}

    def save_plan(self, day: date, meals: list[dict]) -> dict:
        """Replace what is still to eat on a day (the plan editor, a plan the coach proposed)."""
        old = self._stored(day)
        plan = old or {"day": day.isoformat(), "source": "modificato", "created": now()}
        seen = {m["slot"]: m["seen"] for m in old["meals"]} if old else {}
        plan["meals"] = self._normalize({"meals": meals})["meals"]
        for m in plan["meals"]:
            m["seen"] = seen.get(m["slot"]) or [
                self._key(r) for r in self.store.entries(day) if r["slot"] == m["slot"]
            ]
        t = self.targets(day)
        plan["target"] = macros_dict(self.loggable(t)) if t else None
        tot = totals(self._meals(plan["meals"]))
        left = self._left(day, t) if t else None
        plan["report"] = {
            "totals": macros_dict(tot),
            "target": macros_dict(left) if left else None,
            "within_tolerance": left is None
            or abs(tot.kcal - left.kcal) <= self.settings().engine.plan_kcal_tolerance,
            "changes": [],
            "notes": [],
        }
        self._save(day, plan)
        return plan

    def alternatives(self, food_id: str, grams: float, today: date, slot: str | None = None) -> list[dict]:
        """Foods with the same role, the ones eaten in this same meal first: a swap for the breakfast
        yogurt should be another breakfast food, not chicken."""
        foods = self.foods()
        if food_id not in foods:
            raise CoachError("Alimento sconosciuto")
        orig = Item(foods[food_id], grams)
        recent = self.entries(today - timedelta(days=60), today)
        freq: dict[str, int] = {}
        in_slot: dict[str, int] = {}
        for e in recent:
            freq[e.food.id] = freq.get(e.food.id, 0) + 1
            if e.slot == slot:
                in_slot[e.food.id] = in_slot.get(e.food.id, 0) + 1
        role = orig.food.role
        cands = [f for f in foods.values() if f.id != food_id and f.role == role]
        cands.sort(key=lambda f: (-in_slot.get(f.id, 0), -freq.get(f.id, 0)))
        out = []
        for f in cands[:8]:
            g = equivalent_grams(orig, f)
            m = f.macros(g)
            out.append(
                {
                    "food_id": f.id,
                    "name": f.name,
                    "grams": g,
                    "macros": macros_dict(m),
                    "frequent": freq.get(f.id, 0) > 0,
                }
            )
        return out

    @staticmethod
    def _food_view(f: Food, grams: float) -> dict:
        return {
            "name": f.name,
            "role": f.role,
            "step": f.step,
            "unit_g": f.unit_g,
            "unit_name": f.unit_name,
            "macros": macros_dict(f.macros(grams)),
            "per100": {"kcal": f.kcal, "protein": f.protein, "carbs": f.carbs, "fat": f.fat},
        }

    def meal_views(self, meals: list[dict]) -> list[dict]:
        foods = self.foods()
        out = []
        for m in meals:
            items = []
            tot = Macros(0, 0, 0, 0)
            for i in m["items"]:
                f = foods.get(i["food_id"])
                if f is None:
                    continue
                mm = f.macros(i["grams"])
                tot = Macros(
                    tot.kcal + mm.kcal, tot.protein + mm.protein, tot.carbs + mm.carbs, tot.fat + mm.fat
                )
                planned_food = foods.get(i.get("planned_food_id") or "")
                items.append(
                    {
                        **i,
                        **self._food_view(f, i["grams"]),
                        "planned_food_name": planned_food.name if planned_food else None,
                    }
                )
            out.append(
                {
                    **m,
                    "status": m.get("status") or ("skipped" if m.get("skipped") else "planned"),
                    "label": SLOT_LABEL.get(m["slot"], m["slot"].title()),
                    "items": items,
                    "macros": macros_dict(tot),
                }
            )
        return out

    def _card(self, m: dict, rows: list, foods: dict[str, Food]) -> dict:
        """One meal as the day shows it: eaten foods from the diary, then what is still planned."""
        eaten = [
            {
                "ref": self.entry_ref(r),
                "state": "eaten",
                "pending": bool(r["pending"]),
                "food_id": r["food_id"],
                "grams": r["grams"],
                **self._food_view(foods[r["food_id"]], r["grams"]),
            }
            for r in rows
            if r["slot"] == m["slot"]
        ]
        planned = [
            {
                "ref": f"p:{i['id']}",
                "state": "skipped" if m["skipped"] else "planned",
                "pending": False,
                "food_id": i["food_id"],
                "grams": i["grams"],
                "planned_grams": i.get("planned_grams"),
                **self._food_view(foods[i["food_id"]], i["grams"]),
            }
            for i in m["items"]
            if i["food_id"] in foods
        ]
        active = [] if m["skipped"] else planned
        if eaten and active:
            status = "partial"
        elif eaten:
            status = "eaten"
        elif active:
            status = "planned"
        else:
            status = "skipped" if planned else "empty"

        def tot(items):
            return macros_dict(add(foods[i["food_id"]].macros(i["grams"]) for i in items))

        return {
            "slot": m["slot"],
            "label": SLOT_LABEL[m["slot"]],
            "status": status,
            "skipped": m["skipped"],
            "locked": m["locked"],
            "items": eaten + planned,
            "macros": tot(eaten + active),
            "eaten": tot(eaten),
            "planned": tot(active),
            "count_eaten": len(eaten),
            "count": len(eaten) + len(active),
        }

    # views

    def today(self, day: date, today: date) -> dict:
        """A day as the app shows it: the four meals with what was eaten and what is planned, against
        the day's target. Every change to a day answers with this view."""
        s = self.settings()
        t = self.targets(day, today)
        plan = self._ensure_plan(day, today)
        foods = self.foods()
        rows = [r for r in self.store.entries(day) if r["food_id"] in foods]
        cards = [self._card(m, rows, foods) for m in plan["meals"]]
        consumed = self._eaten(day)
        planned = Macros(*(sum(c["planned"][k] for c in cards) for k in ("kcal", "protein", "carbs", "fat")))
        exp = self.expenditure(today)
        w = self.weight_now(today)
        rate = weight_rate(self.store.weights(), today, s.engine.rate_window_days)
        target = self.loggable(t) if t else None
        lg = self.logs().get(day)
        out = {
            "day": day.isoformat(),
            "phase": self.phase().model_dump(mode="json") if self.phase() else None,
            "targets": t.to_dict() if t else None,
            "target_loggable": macros_dict(target) if target else None,
            "consumed": macros_dict(consumed),
            "planned_remaining": macros_dict(planned),
            "remaining": macros_dict(
                Macros(
                    target.kcal - consumed.kcal,
                    target.protein - consumed.protein,
                    target.carbs - consumed.carbs,
                    target.fat - consumed.fat,
                )
            )
            if target
            else None,
            "plan": {k: plan.get(k) for k in ("day", "source", "kind", "target", "report")},
            "meals": cards,
            "complete": ex.is_complete(lg, t.macros.kcal if t else exp.kcal, s.engine.incomplete_threshold),
            "expenditure": {"kcal": exp.kcal, "sd": exp.sd, "status": exp.status},
            "weight": {
                "trend": w,
                "rate_kg_week": None if rate is None else round(rate.kg_per_week, 2),
                "spark": self._spark(today),
            },
            "suggestions": self.suggestions(day, today, target, consumed, planned.kcal > 0)
            if target and day == today
            else [],
            "checkin": self.checkin_banner(today),
        }
        return out

    def _spark(self, today: date) -> list[float]:
        ws = self.store.weights()
        if not ws:
            return []
        e = self.settings().engine
        pts = trend_series(ws, today - timedelta(days=20), today, e.trend_alpha, e.trend_beta)
        return [p.trend for p in pts if p.trend is not None]

    def suggestions(
        self, day: date, today: date, target: Macros, consumed: Macros, planned_left: bool
    ) -> list:
        """Ideas to close the protein gap within the calories left, from the owner's own foods.

        Only once the plan has nothing left to offer: while a planned food remains, the plan is the answer.
        """
        if planned_left:
            return []
        gap_p = target.protein - consumed.protein
        kcal_left = target.kcal - consumed.kcal
        if gap_p < 15 or kcal_left < 150:
            return []
        recent = self.entries(today - timedelta(days=60), today)
        freq: dict[str, int] = {}
        for e in recent:
            freq[e.food.id] = freq.get(e.food.id, 0) + 1
        usual = usual_portions(recent)
        out = []
        for t in self.templates(today):
            meal = t["_t"].meal()
            fitted, rep = fit_day(
                [meal], Macros(kcal_left, gap_p, max(0, (kcal_left - 4 * gap_p) * 0.6 / 4), 0), 60
            )
            mm = fitted[0].macros()
            if mm.kcal <= kcal_left + 60:
                out.append(
                    {
                        "title": " + ".join(f"{i.food.name} {round(i.grams)} g" for i in fitted[0].items[:3]),
                        "items": [{"food_id": i.food.id, "grams": i.grams} for i in fitted[0].items],
                        "macros": macros_dict(mm),
                        "tag": "lo mangi spesso" if t["count"] >= 4 else "simile",
                        "score": abs(mm.protein - gap_p) + max(0, mm.kcal - kcal_left) / 10,
                    }
                )
        foods = self.foods()
        for fid in sorted(freq, key=lambda k: -freq[k]):
            f = foods.get(fid)
            if f is None or f.role != "protein":
                continue
            g = gap_p / (f.protein / 100) if f.protein else 0
            g = min(g, kcal_left / (f.kcal / 100) if f.kcal else g, usual.get(fid, g) * 1.6)
            g = max(f.step, round(g / f.step) * f.step)
            mm = f.macros(g)
            out.append(
                {
                    "title": f"{f.name} {round(g)} g",
                    "items": [{"food_id": fid, "grams": g}],
                    "macros": macros_dict(mm),
                    "tag": "lo mangi spesso",
                    "score": abs(mm.protein - gap_p) + max(0, mm.kcal - kcal_left) / 10 + 5,
                }
            )
        out.sort(key=lambda s: s["score"])
        seen, res = set(), []
        for s_ in out:
            if s_["title"] not in seen:
                seen.add(s_["title"])
                res.append({k: v for k, v in s_.items() if k != "score"})
        return res[:3]

    def progress(self, today: date, window: int = 42) -> dict:
        s = self.settings()
        ws = self.store.weights()
        start = today - timedelta(days=window - 1)
        pts = trend_series(ws, start, today, s.engine.trend_alpha, s.engine.trend_beta)
        rate = weight_rate(ws, today, s.engine.rate_window_days)
        level = next((p.trend for p in reversed(pts) if p.trend is not None), None)
        proj = projection(level, rate, 3, s.profile.goal_weight_kg) if rate and level else None
        series = self.expenditure_series(today)
        by_day = {e.day: e for e in series}
        logs = self.logs()
        exp_points = []
        excluded = []
        for d in days(start, today):
            e = by_day.get(d)
            lg = logs.get(d)
            ref = e.kcal if e else self.prior(today)[0]
            complete = ex.is_complete(lg, ref, s.engine.incomplete_threshold)
            if lg and lg.kcal > 0 and not complete and d < today:
                excluded.append({"day": d.isoformat(), "kcal": round(lg.kcal)})
            exp_points.append(
                {
                    "day": d.isoformat(),
                    "kcal": e.kcal if e else None,
                    "sd": e.sd if e else None,
                    "intake": round(lg.kcal + s.engine.logging_offset_kcal) if lg and lg.kcal else None,
                    "complete": complete,
                }
            )
        weeks = []
        for k in range(window // 7 - 1, -1, -1):
            wend = today - timedelta(days=7 * k)
            wstart = wend - timedelta(days=6)
            ins = [
                logs[d].kcal + s.engine.logging_offset_kcal
                for d in days(wstart, wend)
                if ex.is_complete(
                    logs.get(d), by_day[d].kcal if d in by_day else 2000, s.engine.incomplete_threshold
                )
            ]
            exps = [by_day[d].kcal for d in days(wstart, wend) if d in by_day]
            weeks.append(
                {
                    "start": wstart.isoformat(),
                    "end": wend.isoformat(),
                    "intake": round(mean(ins)) if ins else None,
                    "expenditure": round(mean(exps)) if exps else None,
                }
            )
        exp = series[-1] if series else None
        prior, prior_sd = self.prior(today)
        w = self.weight_now(today)
        return {
            "weights": [{"day": p.day.isoformat(), "weight": p.weight, "trend": p.trend} for p in pts],
            "trend": level,
            "rate": None
            if rate is None
            else {
                "kg_per_week": round(rate.kg_per_week, 2),
                "se": round(rate.se_kg_per_week, 2),
                "weighins": rate.weighins,
            },
            "band": list(self.phase().band_kg_week) if self.phase() else None,
            "projection": proj,
            "goal": s.profile.goal_weight_kg,
            "expenditure": None
            if exp is None
            else {
                "kcal": exp.kcal,
                "sd": exp.sd,
                "status": exp.status,
                "complete_days": exp.complete_days,
                "weighins": exp.weighins,
                "prior": prior,
                "prior_sd": prior_sd,
                "formulas": [
                    {"name": f.name, "low": round(f.low), "high": round(f.high), "source": f.source}
                    for f in expenditure_formulas(s.profile, w or 70)
                ],
            },
            "expenditure_series": exp_points,
            "weeks": weeks,
            "excluded": excluded,
            "weighins": sum(1 for p in pts if p.weight is not None),
        }

    def history(self, week_start: date, today: date) -> dict:
        logs = self.logs()
        foods = self.foods()
        s = self.settings()
        rows = self.store.entries(week_start, week_start + timedelta(days=6))
        out_days = []
        p = self.phase()
        for d in days(week_start, week_start + timedelta(days=6)):
            lg = logs.get(d)
            t = self.targets(d, today) if p and d >= p.start else None
            ref = t.macros.kcal if t else self.expenditure(today).kcal
            meals: dict[str, list] = {}
            for r in rows:
                if r["day"] == d.isoformat() and r["food_id"] in foods:
                    f = foods[r["food_id"]]
                    meals.setdefault(r["slot"], []).append(
                        {
                            "food_id": f.id,
                            "name": f.name,
                            "grams": r["grams"],
                            "macros": macros_dict(f.macros(r["grams"])),
                        }
                    )
            out_days.append(
                {
                    "day": d.isoformat(),
                    "kcal": round(lg.kcal) if lg else 0,
                    "macros": {"protein": round(lg.protein), "carbs": round(lg.carbs), "fat": round(lg.fat)}
                    if lg
                    else None,
                    "target": round(self.loggable(t).kcal) if t else None,
                    "complete": ex.is_complete(lg, ref, s.engine.incomplete_threshold),
                    "marked": lg.marked_complete if lg else None,
                    "future": d > today,
                    "meals": [
                        {
                            "slot": k,
                            "label": SLOT_LABEL.get(k, k),
                            "items": v,
                            "kcal": round(sum(i["macros"]["kcal"] for i in v)),
                        }
                        for k, v in sorted(
                            meals.items(),
                            key=lambda kv: SLOT_ORDER.index(kv[0]) if kv[0] in SLOT_ORDER else 9,
                        )
                    ],
                }
            )
        tpls = [{k: v for k, v in t.items() if k != "_t"} for t in self.templates(today)]
        return {"week_start": week_start.isoformat(), "days": out_days, "templates": tpls}

    def repeat_day(self, source: date, target_day: date, today: date) -> dict:
        """Every meal of `source` into `target_day`, same grams."""
        if not self.store.entries(source):
            raise CoachError("Il giorno di partenza è vuoto")
        return self.copy_meals(source, target_day, None, today)

    def week_preview(self, start: date, today: date, variety: str = "same") -> dict:
        """Next week's plan from last week's habits, portions refitted to each day's target."""
        days_out = []
        changes: dict[tuple[str, str], list[tuple[float, float]]] = {}
        foods = self.foods()
        freq: dict[str, int] = {}
        for e in self.entries(today - timedelta(days=60), today):
            freq[e.food.id] = freq.get(e.food.id, 0) + 1
        swaps_done = 0
        for k, d in enumerate(days(start, start + timedelta(days=6))):
            src_day = d - timedelta(days=7)
            while src_day >= today:
                src_day -= timedelta(days=7)
            meals, source = self._source_meals(src_day + timedelta(days=7), today)
            if variety == "alternative" and swaps_done < 3 and meals:
                m = meals[(k * 2) % len(meals)]
                cands = [i for i in m.items if not m.locked and i.food.role in ("carb", "protein")]
                if cands:
                    it = cands[k % len(cands)]
                    alts = [f for f in foods.values() if f.role == it.food.role and f.id != it.food.id]
                    alts.sort(key=lambda f: -freq.get(f.id, 0))
                    if alts:
                        alt = alts[k % min(3, len(alts))]
                        idx = m.items.index(it)
                        m.items[idx] = Item(alt, equivalent_grams(it, alt))
                        swaps_done += 1
            before = {(m.slot, i.food.id): i.grams for m in meals for i in m.items}
            t = self.targets(d, today)
            fitted, rep = fit_day(
                meals, self.loggable(t), self.settings().engine.plan_kcal_tolerance, self.phase().adjust_macro
            )
            for m in fitted:
                for i in m.items:
                    b = before.get((m.slot, i.food.id))
                    if b is not None:
                        changes.setdefault((m.slot, i.food.id), []).append((b, i.grams))
            days_out.append(
                {
                    "day": d.isoformat(),
                    "kind": t.kind,
                    "source": source,
                    "meals": self.meal_views(self._meals_json(fitted)),
                    "report": rep.to_dict(),
                }
            )
        diff = []
        same = []
        for (slot, fid), pairs in changes.items():
            b = round(mean(p[0] for p in pairs))
            a = round(mean(p[1] for p in pairs))
            name = foods[fid].name if fid in foods else fid
            if abs(a - b) >= max(5, 0.05 * b):
                diff.append({"slot": slot, "food": name, "from": b, "to": a, "role": foods[fid].role})
            else:
                same.append({"slot": slot, "food": name, "role": foods[fid].role})
        diff.sort(key=lambda x: -abs(x["to"] - x["from"]))
        return {"start": start.isoformat(), "variety": variety, "days": days_out, "diff": diff, "same": same}

    def apply_week(self, preview: dict, today: date) -> int:
        n = 0
        for d in preview["days"]:
            day = date.fromisoformat(d["day"])
            existing = self._stored(day)
            if (existing and self._touched(existing)) or self.store.entries(day):
                continue
            meals = [
                {
                    "slot": m["slot"],
                    "status": "planned",
                    "locked": m.get("locked", False),
                    "items": [
                        {
                            "food_id": i["food_id"],
                            "grams": i["grams"],
                            "planned_grams": i["grams"],
                            "planned_food_id": i["food_id"],
                            "locked": False,
                        }
                        for i in m["items"]
                    ],
                }
                for m in d["meals"]
            ]
            plan = {
                "day": d["day"],
                "source": "dalle abitudini",
                "kind": d["kind"],
                "meals": meals,
                "target": d["report"]["target"],
                "report": d["report"],
                "created": now(),
            }
            self.store.put_plan(day, self._normalize(plan))
            n += 1
        return n

    # check-in

    def checkin_day(self, today: date) -> date:
        """The most recent check-in day (Sunday unless configured otherwise)."""
        wd = self.store.get("checkin_weekday", 6)
        return today - timedelta(days=(today.weekday() - wd) % 7)

    def checkin_week_end(self, today: date) -> date:
        """The check-in reviews the seven days that end the day before it: on check-in morning
        the day itself has no diary yet."""
        return self.checkin_day(today) - timedelta(days=1)

    def checkin(self, today: date, week_end: date | None = None) -> dict | None:
        p = self.phase()
        if p is None:
            return None
        week_end = week_end or self.checkin_week_end(today)
        if week_end < p.start + timedelta(days=6):
            first = self.checkin_day(p.start + timedelta(days=13))
            return {"week_end": week_end.isoformat(), "too_early": True, "first": first.isoformat()}
        stored = {r["week_end"]: r for r in self.store.checkins()}
        row = stored.get(week_end.isoformat())
        if row and row["decision"]:
            res = json.loads(row["result"])
        else:
            s = self.settings()
            prev = [
                json.loads(r["result"])["verdict"]
                for k, r in sorted(stored.items())
                if k < week_end.isoformat()
            ]
            exp = self.expenditure(week_end)
            w = self.weight_now(week_end) or self.weight_now(today)
            r = run_checkin(
                week_end,
                self.logs(),
                self.store.weights(),
                p,
                exp,
                w,
                s.engine,
                s.guardrails,
                prev,
                self.bmr(week_end),
            )
            res = r.to_dict()
            self.store.put_checkin(week_end, res)
            row = {r_["week_end"]: r_ for r_ in self.store.checkins()}.get(week_end.isoformat())
        res["decision"] = row["decision"] if row else None
        res["decided_kcal"] = row["decided_kcal"] if row else None
        res["phase"] = p.model_dump(mode="json")
        return res

    def checkin_banner(self, today: date) -> dict | None:
        c = self.checkin(today)
        if not c or c.get("too_early") or c.get("decision"):
            return None
        return {
            "week_end": c["week_end"],
            "verdict": c["verdict"],
            "headline": c["headline"],
            "has_proposal": bool(c.get("proposal")),
        }

    def checkin_preview(self, week_end: date, kcal: float, adjust_macro: str, today: date) -> dict:
        c = self.checkin(today, week_end)
        p = self.phase()
        s = self.settings()
        current = p.kcal_target
        cap = s.engine.max_weekly_change_kcal
        kcal = max(current - cap, min(current + cap, kcal))
        w = self.weight_now(today)
        p2 = p.model_copy(update={"adjust_macro": adjust_macro})
        changes = adjusted_phase(p2, w, current, kcal, s.guardrails)
        p3 = p2.model_copy(update=changes)
        rate = c.get("rate_kg_week")
        proj = None if rate is None else round(rate + (kcal - current) * 7 / s.engine.kcal_per_kg, 2)
        lo, hi = p.band_kg_week
        return {
            "kcal_from": current,
            "kcal_to": kcal,
            "cap": cap,
            "macros_from": macros_dict(split_macros(current, w, p, s.guardrails)),
            "macros_to": macros_dict(split_macros(kcal, w, p3, s.guardrails)),
            "projected_rate": proj,
            "in_band": None if proj is None else lo <= proj <= hi,
            "changes": {**changes, "adjust_macro": adjust_macro},
        }

    def decide_checkin(
        self,
        week_end: date,
        decision: str,
        today: date,
        kcal: float | None = None,
        adjust_macro: str | None = None,
    ) -> dict:
        c = self.checkin(today, week_end)
        if c is None or c.get("too_early"):
            raise CoachError("Nessun check-in da decidere")
        if c.get("decision"):
            raise CoachError("Check-in già deciso")
        p = self.phase()
        if decision == "accept":
            if not c.get("proposal"):
                self.store.decide_checkin(week_end, "accept", p.kcal_target)
                return self.checkin(today, week_end)
            changes = c["proposal"]["phase_changes"]
            self.update_phase(changes, today)
            self.store.decide_checkin(week_end, "accept", changes["kcal_target"])
        elif decision == "modify":
            if kcal is None:
                raise CoachError("Serve il nuovo target")
            pv = self.checkin_preview(week_end, kcal, adjust_macro or p.adjust_macro, today)
            self.update_phase(pv["changes"], today)
            self.store.decide_checkin(week_end, "modify", pv["kcal_to"])
        elif decision == "reject":
            self.store.decide_checkin(week_end, "reject", p.kcal_target)
        else:
            raise CoachError("Decisione non valida")
        return self.checkin(today, week_end)

    def describe_rate(self, r: float | None) -> str:
        return "n/d" if r is None else fmt_rate(r)
