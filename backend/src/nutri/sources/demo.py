"""A synthetic person with Italian habits, for development and for trying the app
without a Cronometer account. Everything is deterministic for a given start day."""

import random
from collections import defaultdict
from datetime import date, timedelta

from . import DayDiary, FoodInfo

F = FoodInfo
FOODS = {
    f.id: f
    for f in [
        F("demo:yog", "Yogurt greco 2%", 73, 9.9, 3.9, 2.0, 170, "vasetto"),
        F("demo:ave", "Fiocchi d'avena", 372, 13.5, 58.7, 7.0),
        F("demo:mir", "Mirtilli", 57, 0.7, 14.5, 0.3),
        F("demo:noc", "Noci", 654, 15.2, 13.7, 65.2),
        F("demo:riso", "Riso basmati", 356, 8.0, 78.0, 0.9),
        F("demo:pasta", "Pasta di semola", 359, 13.0, 71.0, 1.5),
        F("demo:pol", "Petto di pollo", 110, 23.0, 0.0, 1.5),
        F("demo:zuc", "Zucchine", 17, 1.2, 3.1, 0.3),
        F("demo:olio", "Olio extravergine d'oliva", 884, 0.0, 0.0, 100.0),
        F("demo:sal", "Salmone", 208, 20.0, 0.0, 13.0),
        F("demo:pat", "Patate", 77, 2.0, 17.0, 0.1),
        F("demo:pane", "Pane comune", 270, 9.0, 51.0, 3.2, 40, "fetta"),
        F("demo:sky", "Skyr", 63, 11.0, 4.0, 0.2, 150, "vasetto"),
        F("demo:ban", "Banana", 89, 1.1, 23.0, 0.3, 120, "banana"),
        F("demo:uovo", "Uova", 143, 12.6, 0.7, 9.5, 60, "uovo"),
        F("demo:tonno", "Tonno al naturale", 103, 24.0, 0.0, 0.8),
        F("demo:bres", "Bresaola", 151, 32.0, 0.4, 2.6),
        F("demo:pizza", "Pizza margherita", 250, 10.0, 33.0, 8.0, 330, "pizza"),
        F("demo:ins", "Insalata mista", 15, 1.3, 2.2, 0.2),
        F("demo:mela", "Mela", 52, 0.3, 14.0, 0.2, 180, "mela"),
        F("demo:latte", "Latte parzialmente scremato", 46, 3.3, 4.9, 1.6),
        F("demo:parm", "Parmigiano Reggiano", 392, 33.0, 0.0, 28.0),
        F("demo:farro", "Farro", 335, 15.0, 67.0, 2.5),
        F("demo:merl", "Merluzzo", 82, 18.0, 0.0, 0.7),
    ]
}

MEALS = {
    "colazione": [
        (0.8, [("yog", 250), ("ave", 50), ("mir", 100), ("noc", 15)]),
        (0.2, [("uovo", 120), ("pane", 80), ("latte", 200)]),
    ],
    "pranzo": [
        (0.6, [("riso", 90), ("pol", 160), ("zuc", 200), ("olio", 10)]),
        (0.4, [("pasta", 90), ("tonno", 120), ("ins", 100), ("olio", 10)]),
    ],
    "spuntino": [(0.6, [("sky", 150), ("ban", 120)]), (0.4, [("mela", 180), ("noc", 15)])],
    "cena": [
        (0.55, [("sal", 160), ("pat", 250), ("ins", 100), ("olio", 10)]),
        (0.3, [("merl", 220), ("farro", 70), ("zuc", 200), ("olio", 10)]),
        (0.15, [("uovo", 180), ("pane", 80), ("zuc", 200), ("parm", 15)]),
    ],
}

EXPENDITURE = 2450
START_WEIGHT = 71.4
HISTORY_DAYS = 63


class DemoSource:
    name = "demo"

    def __init__(self, today: date | None = None, seed: int = 11):
        self.today = today or date.today()
        self.rng = random.Random(seed)
        self._diary: dict[date, list[dict]] = defaultdict(list)
        self._complete: dict[date, bool] = {}
        self._weights: dict[date, float] = {}
        self._next_id = 1
        self._generate()

    def _sid(self) -> str:
        self._next_id += 1
        return f"demo-{self._next_id}"

    def _generate(self) -> None:
        weight, water = START_WEIGHT, 0.0
        start = self.today - timedelta(days=HISTORY_DAYS)
        for i in range(HISTORY_DAYS):
            d = start + timedelta(days=i)
            water = 0.6 * water + self.rng.gauss(0, 0.3)
            if self.rng.random() < 0.9:
                self._weights[d] = round(weight + water, 1)
            kcal = 0.0
            skipped = self.rng.random() < 0.12
            for slot, options in MEALS.items():
                if skipped and slot in ("spuntino", "cena"):
                    continue
                if d.weekday() == 5 and slot == "cena" and self.rng.random() < 0.5:
                    items = [("pizza", 330)]
                else:
                    r, acc = self.rng.random(), 0.0
                    items = options[-1][1]
                    for p, its in options:
                        acc += p
                        if r <= acc:
                            items = its
                            break
                for fid, g in items:
                    food = FOODS[f"demo:{fid}"]
                    grams = g if food.unit_g else round(g * self.rng.uniform(0.85, 1.15) / 5) * 5
                    self._diary[d].append(
                        {"slot": slot, "food_id": food.id, "grams": grams, "serving_id": self._sid()}
                    )
                    kcal += food.kcal * grams / 100
            if not skipped:
                self._complete[d] = True
            eaten = kcal + (0 if skipped else self.rng.gauss(0, 60)) + (900 if skipped else 0)
            weight += (eaten - EXPENDITURE) / 7000

    def weights(self, start: date, end: date) -> dict[date, float]:
        return {d: w for d, w in self._weights.items() if start <= d <= end}

    def diary(self, day: date) -> DayDiary:
        entries = list(self._diary.get(day, []))
        foods = [FOODS[e["food_id"]] for e in entries if e["food_id"] in FOODS]
        return DayDiary(day, entries, foods, self._complete.get(day))

    def search(self, query: str) -> list[dict]:
        q = query.lower()
        return [
            {"cr_food_id": None, "id": f.id, "name": f.name, "source": "demo", "measure": "g"}
            for f in FOODS.values()
            if q in f.name.lower()
        ]

    def food(self, cr_food_id: int) -> FoodInfo:
        raise KeyError(cr_food_id)

    def food_by_id(self, food_id: str) -> FoodInfo | None:
        return FOODS.get(food_id)

    def add_serving(self, food: dict, grams: float, day: date, slot: str) -> str | None:
        sid = self._sid()
        self._diary[day].append({"slot": slot, "food_id": food["id"], "grams": grams, "serving_id": sid})
        return sid

    def delete_servings(self, serving_ids: list[str], day: date) -> None:
        ids = set(serving_ids)
        self._diary[day] = [e for e in self._diary.get(day, []) if e["serving_id"] not in ids]

    def mark_complete(self, day: date, complete: bool) -> None:
        self._complete[day] = complete
