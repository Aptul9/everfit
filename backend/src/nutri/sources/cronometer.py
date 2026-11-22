"""Cronometer through the mobile API client of `cronometer-api-mcp`.

The API is undocumented and can change without notice. A failure here is an
upstream change: it surfaces as an error in the sync status, and writes stay
in the outbox until they go through.
"""

import logging
import time
from datetime import date
from pathlib import Path

from cronometer_api_mcp.client import CronometerClient

from . import GROUP_BY_SLOT, SLOT_BY_GROUP, DayDiary, FoodInfo

log = logging.getLogger(__name__)

ENERGY, PROTEIN, FAT, CARBS = 208, 203, 204, 205
WEIGHT_METRIC, KG_UNIT = 1, 1


def _nutrients(food: dict) -> dict[int, float]:
    return {
        n["id"]: n["amount"]
        for n in food.get("nutrients", [])
        if isinstance(n, dict) and isinstance(n.get("amount"), (int, float))
    }


def _gram_measure(food: dict) -> dict | None:
    for m in food.get("measures", []):
        if isinstance(m, dict) and m.get("name") == "g" and m.get("value") == 1:
            return m
    return None


def _is_recipe_serving(food: dict) -> bool:
    measures = {m.get("id"): m for m in food.get("measures", []) if isinstance(m, dict)}
    m = measures.get(food.get("defaultMeasureId"))
    return bool(m and m.get("type") == "Recipe")


def food_info(food: dict) -> FoodInfo:
    n = _nutrients(food)
    gram = _gram_measure(food)
    unit_g = unit_name = None
    if _is_recipe_serving(food):
        # serving-based recipe: nutrients per serving, diary "grams" is a count.
        # Modelled as 100 units per serving so the rest of the app stays in grams.
        unit_g, unit_name = 100.0, "porzione"
    else:
        for m in food.get("measures", []):
            if (
                isinstance(m, dict)
                and m.get("type") == "Atomic"
                and m.get("value")
                and m.get("name") not in ("g", "oz")
            ):
                unit_g = float(m["value"]) / (m.get("amount") or 1)
                unit_name = m.get("name")
                break
    fid = food["id"]
    return FoodInfo(
        id=f"cr:{fid}",
        name=food.get("name") or f"Alimento {fid}",
        kcal=n.get(ENERGY, 0.0),
        protein=n.get(PROTEIN, 0.0),
        carbs=n.get(CARBS, 0.0),
        fat=n.get(FAT, 0.0),
        unit_g=unit_g,
        unit_name=unit_name,
        cr_food_id=fid,
        measure_id=(gram or {}).get("id") or food.get("defaultMeasureId"),
        translation_id=_translation(food),
    )


def _translation(food: dict) -> int:
    for t in food.get("translations", []) or []:
        if isinstance(t, dict) and t.get("id"):
            return t["id"]
    return 0


def _marked_complete(data: dict) -> bool | None:
    """`info.complete` is True when the day was marked complete. False is also what every day never marked
    returns, so it says nothing: the completeness threshold decides those days."""
    info = data.get("info")
    if isinstance(info, dict) and info.get("complete") is True:
        return True
    return None


class CronometerSource:
    name = "cronometer"

    def __init__(self, data_dir: Path):
        self.client = CronometerClient(session_path=data_dir / "cronometer-session.json")
        self._foods: dict[int, dict] = {}

    def weights(self, start: date, end: date) -> dict[date, float]:
        data = self.client.get_biometrics(WEIGHT_METRIC, KG_UNIT, start, end)
        out = {}
        for p in data.get("data", []) if isinstance(data, dict) else []:
            try:
                out[date.fromisoformat(str(p["day"]))] = round(float(p["value"]), 2)
            except KeyError, ValueError, TypeError:
                continue
        return out

    def _foods_for(self, ids: list[int]) -> dict[int, dict]:
        missing = [i for i in ids if i not in self._foods]
        if missing:
            for f in self.client.get_foods(missing):
                if isinstance(f, dict) and f.get("id"):
                    self._foods[f["id"]] = f
        return {i: self._foods[i] for i in ids if i in self._foods}

    def diary(self, day: date) -> DayDiary:
        data = self.client.get_diary(day)
        rows = [e for e in data.get("diary", []) if isinstance(e, dict) and e.get("type") == "Serving"]
        foods = self._foods_for(sorted({e["foodId"] for e in rows if isinstance(e.get("foodId"), int)}))
        infos = {fid: food_info(f) for fid, f in foods.items()}
        entries = []
        for e in rows:
            info = infos.get(e.get("foodId"))
            if info is None:
                continue
            group = (e.get("order") or 0) >> 16
            grams = float(e.get("grams") or 0)
            if info.unit_name == "porzione":
                grams *= 100
            entries.append(
                {
                    "slot": SLOT_BY_GROUP.get(group, "spuntino"),
                    "food_id": info.id,
                    "grams": round(grams, 1),
                    "serving_id": str(e.get("servingId") or ""),
                }
            )
        return DayDiary(day, entries, list(infos.values()), _marked_complete(data))

    def search(self, query: str) -> list[dict]:
        out = []
        for f in self.client.search_food(query)[:25]:
            out.append(
                {
                    "cr_food_id": f.get("id"),
                    "name": f.get("name"),
                    "source": f.get("source"),
                    "measure": f.get("measureDisplayName"),
                }
            )
        return out

    def food(self, cr_food_id: int) -> FoodInfo:
        f = self.client.get_food(cr_food_id)
        self._foods[cr_food_id] = f
        return food_info(f)

    def add_serving(self, food: dict, grams: float, day: date, slot: str) -> str | None:
        amount = grams / 100 if food.get("unit_name") == "porzione" else grams
        res = self.client.add_serving(
            food["cr_food_id"],
            food.get("measure_id"),
            amount,
            translation_id=food.get("translation_id") or 0,
            day=day,
            diary_group=GROUP_BY_SLOT.get(slot, 4),
        )
        time.sleep(0.2)
        sid = res.get("id") if isinstance(res, dict) else None
        return None if sid is None else str(sid)

    def delete_servings(self, serving_ids: list[str], day: date) -> None:
        self.client.delete_entries(serving_ids, day)

    def mark_complete(self, day: date, complete: bool) -> None:
        self.client.mark_day_complete(day, complete)
