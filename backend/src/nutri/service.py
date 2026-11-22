"""Application logic: turns the store and the engine into what the app shows."""

import json
from datetime import date, timedelta
from importlib import resources
from statistics import mean

from .engine import expenditure as ex
from .engine.checkin import adjusted_phase, fmt_rate, run_checkin
from .engine.formulas import bmr, expenditure_formulas, prior_expenditure
from .engine.habits import Entry, detect_templates, usual_portions
from .engine.plan import Food, Item, Meal, equivalent_grams, fit_day, totals
from .engine.series import days, projection, trend_series, weight_rate
from .engine.settings import Phase, PhaseTemplate, Settings
from .engine.targets import DayTargets, Macros, day_targets, split_macros
from .store import Store, now

SLOT_ORDER = ["colazione", "pranzo", "spuntino", "cena"]
SLOT_LABEL = {"colazione": "Colazione", "pranzo": "Pranzo", "spuntino": "Spuntino", "cena": "Cena"}
RESOLVED = {"confirmed", "modified", "skipped", "logged"}


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
        for r in self.store.q("select day, data from plans where day>=?", today.isoformat()):
            data = json.loads(r["data"])
            if not any(m["status"] in RESOLVED - {"logged"} for m in data["meals"]):
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
            out.append(Meal(m["slot"], items, m.get("locked", False), m.get("status", "planned")))
        return out

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

    def build_plan(self, day: date, today: date, meals: list[Meal] | None = None) -> dict:
        t = self.targets(day, today)
        if t is None:
            raise CoachError("Imposta una fase per avere un piano.")
        source = "modificato"
        if meals is None:
            meals, source = self._source_meals(day, today)
        p = self.phase()
        s = self.settings()
        fitted, rep = fit_day(meals, self.loggable(t), s.engine.plan_kcal_tolerance, p.adjust_macro)
        for m in fitted:
            for i in m.items:
                i.planned_grams = i.grams
                i.planned_food_id = i.food.id
        plan = {
            "day": day.isoformat(),
            "source": source,
            "target": macros_dict(self.loggable(t)),
            "kind": t.kind,
            "meals": self._meals_json(fitted),
            "report": rep.to_dict(),
            "created": now(),
        }
        self.store.put_plan(day, plan)
        return plan

    def plan(self, day: date, today: date) -> dict | None:
        plan = self.store.plan(day)
        if plan is None:
            if self.phase() is None:
                return None
            if day < today:
                return None
            plan = self.build_plan(day, today)
        return self._mark_logged(day, plan)

    def _mark_logged(self, day: date, plan: dict) -> dict:
        """A planned meal whose slot already has diary entries was logged elsewhere (in Cronometer)."""
        slots_with_entries = {r["slot"] for r in self.store.entries(day) if not r["pending"]}
        changed = False
        for m in plan["meals"]:
            if m["status"] == "planned" and m["slot"] in slots_with_entries:
                m["status"] = "logged"
                changed = True
        if changed:
            self.store.put_plan(day, plan)
        return plan

    def _refit_rest(self, day: date, today: date, plan: dict) -> dict:
        """Fit the meals still to come around what has been eaten. fit_day already leaves confirmed
        and skipped meals alone; meals logged directly in Cronometer count through the diary."""
        if not self._deviates(day, plan):
            return plan
        t = self.targets(day, today)
        meals = self._meals(plan["meals"])
        elsewhere = self._logged_elsewhere(day, plan)
        base = self.loggable(t)
        target = Macros(
            base.kcal - elsewhere.kcal,
            base.protein - elsewhere.protein,
            base.carbs - elsewhere.carbs,
            base.fat - elsewhere.fat,
        )
        for m in meals:
            if m.status == "logged":
                m.status = "skipped"  # its food is already in `elsewhere`
        if any(m.status == "planned" for m in meals):
            fitted, rep = fit_day(
                meals, target, self.settings().engine.plan_kcal_tolerance, self.phase().adjust_macro
            )
            for orig, new in zip(plan["meals"], self._meals_json(fitted), strict=True):
                if orig["status"] == "planned":
                    orig["items"] = new["items"]
            plan["report"] = rep.to_dict()
        return plan

    def _deviates(self, day: date, plan: dict) -> bool:
        """Whether what has been eaten so far differs from what the plan expected. A meal eaten as
        planned changes nothing, and the rest of the day is left exactly as it was."""
        foods = self.foods()
        planned = actual = Macros(0, 0, 0, 0)

        def plus(a: Macros, b: Macros) -> Macros:
            return Macros(a.kcal + b.kcal, a.protein + b.protein, a.carbs + b.carbs, a.fat + b.fat)

        for m in plan["meals"]:
            if m["status"] == "planned":
                continue
            for i in m["items"]:
                pf = foods.get(i.get("planned_food_id") or i["food_id"])
                if pf and i.get("planned_grams") is not None:
                    planned = plus(planned, pf.macros(i["planned_grams"]))
                if m["status"] in ("confirmed", "modified") and i["food_id"] in foods:
                    actual = plus(actual, foods[i["food_id"]].macros(i["grams"]))
        actual = plus(actual, self._logged_elsewhere(day, plan))
        tol = self.settings().engine.plan_kcal_tolerance
        return abs(actual.kcal - planned.kcal) > tol / 2 or abs(actual.protein - planned.protein) > 5

    def _logged_elsewhere(self, day: date, plan: dict) -> Macros:
        logged_slots = {m["slot"] for m in plan["meals"] if m["status"] == "logged"}
        known = {m["slot"] for m in plan["meals"]}
        foods = self.foods()
        ms = [
            foods[r["food_id"]].macros(r["grams"])
            for r in self.store.entries(day)
            if r["food_id"] in foods
            and not r["pending"]
            and (r["slot"] in logged_slots or r["slot"] not in known)
        ]
        k = sum(m.kcal for m in ms)
        return Macros(k, sum(m.protein for m in ms), sum(m.carbs for m in ms), sum(m.fat for m in ms))

    def _get_meal(self, plan: dict, slot: str) -> dict:
        m = next((m for m in plan["meals"] if m["slot"] == slot), None)
        if m is None:
            raise CoachError(f"Nessun pasto {slot!r} nel piano")
        return m

    def confirm_meal(self, day: date, slot: str, today: date, items: list[dict] | None = None) -> dict:
        plan = self.plan(day, today)
        if plan is None:
            raise CoachError("Nessun piano per questo giorno")
        m = self._get_meal(plan, slot)
        if m["status"] in ("confirmed", "modified"):
            raise CoachError("Pasto già confermato")
        if items is not None:
            foods = self.foods()
            for i in items:
                if i["food_id"] not in foods:
                    raise CoachError(f"Alimento {i['food_id']} sconosciuto")
            changed = [(i["food_id"], round(i["grams"])) for i in items] != [
                (i["food_id"], round(i["grams"])) for i in m["items"]
            ]
            planned = {i["food_id"]: i.get("planned_grams") for i in m["items"]}
            m["items"] = [
                {
                    "food_id": i["food_id"],
                    "grams": i["grams"],
                    "planned_grams": planned.get(i["food_id"]),
                    "planned_food_id": i["food_id"],
                    "locked": False,
                }
                for i in items
            ]
            m["status"] = "modified" if changed else "confirmed"
        else:
            m["status"] = "confirmed"
        for i in m["items"]:
            if i["grams"] > 0:
                eid = self.store.add_pending_entry(day, slot, i["food_id"], i["grams"])
                self.store.enqueue(
                    "add_serving",
                    {
                        "day": day.isoformat(),
                        "slot": slot,
                        "food_id": i["food_id"],
                        "grams": i["grams"],
                        "entry_id": eid,
                    },
                )
        plan = self._refit_rest(day, today, plan)
        self._maybe_complete(day, plan)
        self.store.put_plan(day, plan)
        return plan

    def skip_meal(self, day: date, slot: str, today: date) -> dict:
        plan = self.plan(day, today)
        m = self._get_meal(plan, slot)
        if m["status"] != "planned":
            raise CoachError("Si salta solo un pasto ancora da confermare")
        m["status"] = "skipped"
        plan = self._refit_rest(day, today, plan)
        self._maybe_complete(day, plan)
        self.store.put_plan(day, plan)
        return plan

    def undo_meal(self, day: date, slot: str, today: date) -> dict:
        plan = self.plan(day, today)
        m = self._get_meal(plan, slot)
        if m["status"] in ("confirmed", "modified"):
            pend = self.store.q(
                "select id from diary_entries where day=? and slot=? and pending=1", day.isoformat(), slot
            )
            for r in pend:
                for o in self.store.pending():
                    if json.loads(o["payload"]).get("entry_id") == r["id"]:
                        self.store.x("delete from outbox where id=?", o["id"])
                self.store.x("delete from diary_entries where id=?", r["id"])
            food_ids = {i["food_id"] for i in m["items"]}
            sids = [
                r["serving_id"]
                for r in self.store.entries(day)
                if r["slot"] == slot and r["food_id"] in food_ids and r["serving_id"] and not r["pending"]
            ]
            if sids:
                self.store.enqueue("delete_servings", {"day": day.isoformat(), "serving_ids": sids})
                self.store.x(
                    f"delete from diary_entries where day=? and serving_id in ({','.join('?' * len(sids))})",
                    day.isoformat(),
                    *sids,
                )
            self.store.set_marked(day, None)
        if m["status"] == "logged":
            raise CoachError("Questo pasto è stato registrato direttamente su Cronometer: si modifica lì.")
        m["status"] = "planned"
        plan = self._refit_rest(day, today, plan)
        self.store.put_plan(day, plan)
        return plan

    def log_extra(self, day: date, slot: str, food_id: str, grams: float) -> None:
        if self.store.food(food_id) is None:
            raise CoachError(f"Alimento {food_id} sconosciuto")
        eid = self.store.add_pending_entry(day, slot, food_id, grams)
        self.store.enqueue(
            "add_serving",
            {"day": day.isoformat(), "slot": slot, "food_id": food_id, "grams": grams, "entry_id": eid},
        )

    def _maybe_complete(self, day: date, plan: dict) -> None:
        if plan["meals"] and all(m["status"] in RESOLVED for m in plan["meals"]):
            self.store.enqueue("mark_complete", {"day": day.isoformat(), "complete": True})
            self.store.set_marked(day, True)

    def fit_preview(self, day: date, today: date, meals: list[dict]) -> dict:
        t = self.targets(day, today)
        ms = self._meals(meals)
        fitted, rep = fit_day(
            ms, self.loggable(t), self.settings().engine.plan_kcal_tolerance, self.phase().adjust_macro
        )
        return {"meals": self.meal_views(self._meals_json(fitted)), "report": rep.to_dict()}

    def save_plan(self, day: date, meals: list[dict]) -> dict:
        plan = self.store.plan(day) or {"day": day.isoformat(), "source": "modificato"}
        t = self.targets(day)
        plan["meals"] = meals
        plan["target"] = macros_dict(self.loggable(t))
        tot = totals(self._meals(meals))
        plan["report"] = {
            "totals": macros_dict(tot),
            "target": plan["target"],
            "within_tolerance": abs(tot.kcal - plan["target"]["kcal"])
            <= self.settings().engine.plan_kcal_tolerance,
            "changes": [],
            "notes": [],
        }
        self.store.put_plan(day, plan)
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
                        "name": f.name,
                        "role": f.role,
                        "step": f.step,
                        "unit_g": f.unit_g,
                        "unit_name": f.unit_name,
                        "macros": macros_dict(mm),
                        "per100": {"kcal": f.kcal, "protein": f.protein, "carbs": f.carbs, "fat": f.fat},
                        "planned_food_name": planned_food.name if planned_food else None,
                    }
                )
            out.append(
                {
                    **m,
                    "label": SLOT_LABEL.get(m["slot"], m["slot"].title()),
                    "items": items,
                    "macros": macros_dict(tot),
                }
            )
        return out

    # views

    def today(self, day: date, today: date) -> dict:
        s = self.settings()
        t = self.targets(day, today)
        plan = self.plan(day, today)
        consumed_rows = self.store.entries(day)
        foods = self.foods()
        consumed = Macros(0, 0, 0, 0)
        for r in consumed_rows:
            f = foods.get(r["food_id"])
            if f:
                m = f.macros(r["grams"])
                consumed = Macros(
                    consumed.kcal + m.kcal,
                    consumed.protein + m.protein,
                    consumed.carbs + m.carbs,
                    consumed.fat + m.fat,
                )
        planned = Macros(0, 0, 0, 0)
        if plan:
            pm = [m for m in self._meals(plan["meals"]) if m.status == "planned"]
            planned = totals(pm) if pm else planned
        exp = self.expenditure(today)
        w = self.weight_now(today)
        rate = weight_rate(self.store.weights(), today, s.engine.rate_window_days)
        target = self.loggable(t) if t else None
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
            "plan": {**plan, "meals": self.meal_views(plan["meals"])} if plan else None,
            "extra": [
                {"slot": r["slot"], "name": r["name"], "grams": r["grams"], "pending": bool(r["pending"])}
                for r in consumed_rows
                if not plan or r["slot"] not in {m["slot"] for m in plan["meals"]}
            ],
            "expenditure": {"kcal": exp.kcal, "sd": exp.sd, "status": exp.status},
            "weight": {
                "trend": w,
                "rate_kg_week": None if rate is None else round(rate.kg_per_week, 2),
                "spark": self._spark(today),
            },
            "suggestions": self.suggestions(day, today, target, consumed, plan) if target else [],
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
        self, day: date, today: date, target: Macros, consumed: Macros, plan: dict | None
    ) -> list:
        """Ideas to close the protein gap within the calories left, from the owner's own foods.

        Only once the plan has nothing left to offer: while a planned meal remains, the plan is the answer.
        """
        if plan and any(m["status"] == "planned" for m in plan["meals"]):
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
        es = [e for e in self.entries(source, source)]
        meals = []
        for slot in SLOT_ORDER:
            items = [Item(e.food, e.grams) for e in es if e.slot == slot]
            if items:
                meals.append(Meal(slot, items))
        if not meals:
            raise CoachError("Il giorno di partenza è vuoto")
        return self.build_plan(target_day, today, meals)

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
            existing = self.store.plan(day)
            if existing and any(m["status"] in RESOLVED - {"logged"} for m in existing["meals"]):
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
            self.store.put_plan(day, plan)
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
