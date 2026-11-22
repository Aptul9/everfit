"""Recurring meals, detected from the diary.

Detection only proposes. The owner pins a template as fixed or usable, and
from then on the pin is what counts.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from statistics import median

from .plan import Food, Item, Meal

SLOTS = ("colazione", "pranzo", "cena", "spuntino")


@dataclass(frozen=True)
class Entry:
    day: date
    slot: str
    food: Food
    grams: float


@dataclass
class Template:
    id: str
    slot: str
    foods: list[tuple[Food, float]]
    count: int
    last_seen: date
    grams_range: dict[str, tuple[float, float]]

    def meal(self) -> Meal:
        return Meal(self.slot, [Item(f, g) for f, g in self.foods])

    @property
    def name(self) -> str:
        return ", ".join(f.name for f, _ in self.foods[:3])


def jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if a | b else 0.0


def meals_by_day(entries: list[Entry]) -> dict[tuple[date, str], list[Entry]]:
    out: dict[tuple[date, str], list[Entry]] = defaultdict(list)
    for e in entries:
        out[(e.day, e.slot)].append(e)
    return out


def usual_portions(entries: list[Entry]) -> dict[str, float]:
    by_food: dict[str, list[float]] = defaultdict(list)
    for e in entries:
        by_food[e.food.id].append(e.grams)
    return {k: median(v) for k, v in by_food.items()}


def detect_templates(entries: list[Entry], min_count: int = 2, similarity: float = 0.5) -> list[Template]:
    meals = meals_by_day(entries)
    clusters: dict[str, list[list[tuple[date, list[Entry]]]]] = defaultdict(list)
    for (day, slot), es in sorted(meals.items(), key=lambda kv: kv[0][0], reverse=True):
        ids = {e.food.id for e in es}
        placed = False
        for cl in clusters[slot]:
            core = set.intersection(*({e.food.id for e in m} for _, m in cl)) or {e.food.id for e in cl[0][1]}
            if jaccard(ids, core) >= similarity:
                cl.append((day, es))
                placed = True
                break
        if not placed:
            clusters[slot].append([(day, es)])

    out = []
    for slot, cls in clusters.items():
        for n, cl in enumerate(cls):
            if len(cl) < min_count:
                continue
            freq: dict[str, list[Entry]] = defaultdict(list)
            for _, es in cl:
                for e in es:
                    freq[e.food.id].append(e)
            core = [es for es in freq.values() if len(es) * 2 >= len(cl)]
            core.sort(key=lambda es: -median(e.grams for e in es) * es[0].food.kcal)
            foods = [(es[0].food, round(median(e.grams for e in es))) for es in core]
            ranges = {es[0].food.id: (min(e.grams for e in es), max(e.grams for e in es)) for es in core}
            out.append(Template(f"{slot}-{n}", slot, foods, len(cl), max(d for d, _ in cl), ranges))
    out.sort(key=lambda t: (SLOTS.index(t.slot) if t.slot in SLOTS else 9, -t.count))
    return out
