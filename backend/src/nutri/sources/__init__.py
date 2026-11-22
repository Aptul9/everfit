"""Where the diary and the weigh-ins come from.

`CronometerSource` talks to the real account through the reverse-engineered
mobile API. `DemoSource` serves a synthetic person, so the app runs and can be
developed with no credentials at all.
"""

from dataclasses import dataclass
from datetime import date
from typing import Protocol

SLOT_BY_GROUP = {1: "colazione", 2: "pranzo", 3: "cena", 4: "spuntino"}
GROUP_BY_SLOT = {v: k for k, v in SLOT_BY_GROUP.items()}


@dataclass
class FoodInfo:
    id: str
    name: str
    kcal: float
    protein: float
    carbs: float
    fat: float
    unit_g: float | None = None
    unit_name: str | None = None
    cr_food_id: int | None = None
    measure_id: int | None = None
    translation_id: int | None = None

    def row(self) -> dict:
        return self.__dict__.copy()


@dataclass
class DayDiary:
    day: date
    entries: list[dict]  # {slot, food_id, grams, serving_id}
    foods: list[FoodInfo]
    marked_complete: bool | None


class Source(Protocol):
    name: str

    def weights(self, start: date, end: date) -> dict[date, float]: ...
    def diary(self, day: date) -> DayDiary: ...
    def search(self, query: str) -> list[dict]: ...
    def food(self, cr_food_id: int) -> FoodInfo: ...
    def add_serving(self, food: dict, grams: float, day: date, slot: str) -> str | None: ...
    def delete_servings(self, serving_ids: list[str], day: date) -> None: ...
    def mark_complete(self, day: date, complete: bool) -> None: ...
