"""Meal plans: fit a day of real foods to the targets, in real portions.

The cut is never proportional across the plate. The order is fixed and shown
to the owner:

1. protein foods move first, to hold the protein target;
2. added fats come down if fat is over target;
3. the remaining calories are taken from (or given to) carbohydrate foods,
   or fats, or both, as the phase says;
4. vegetables, locked items and locked meals are never touched;
5. portions round to sensible steps and whole units, then the largest
   adjustable item absorbs the rounding drift.
"""

from copy import deepcopy
from dataclasses import asdict, dataclass, field

from .targets import Macros


@dataclass
class Food:
    id: str
    name: str
    kcal: float  # per 100 g
    protein: float
    carbs: float
    fat: float
    unit_g: float | None = None
    unit_name: str | None = None
    step_g: float | None = None
    role_override: str | None = None

    @property
    def role(self) -> str:
        if self.role_override:
            return self.role_override
        if self.kcal <= 0:
            return "other"
        p = 4 * self.protein / self.kcal
        c = 4 * self.carbs / self.kcal
        f = 9 * self.fat / self.kcal
        if self.kcal < 45 and p < 0.4:
            return "veg"
        if f >= 0.6:
            return "fat"
        if p >= 0.4:
            return "protein"
        if c >= 0.55:
            return "fruit" if self.kcal < 100 else "carb"
        return "mixed"

    @property
    def step(self) -> float:
        if self.step_g:
            return self.step_g
        if self.unit_g:
            return self.unit_g / 2 if self.unit_g >= 100 else self.unit_g
        if self.kcal >= 500:
            return 5
        if self.role == "veg":
            return 50
        if self.kcal >= 150:
            return 10
        return 25

    def macros(self, grams: float) -> Macros:
        k = grams / 100
        return Macros(self.kcal * k, self.protein * k, self.carbs * k, self.fat * k)


@dataclass
class Item:
    food: Food
    grams: float
    locked: bool = False
    planned_grams: float | None = None
    planned_food_id: str | None = None

    def macros(self) -> Macros:
        return self.food.macros(self.grams)


@dataclass
class Meal:
    slot: str
    items: list[Item] = field(default_factory=list)
    locked: bool = False
    status: str = "planned"  # planned | confirmed | modified | skipped

    def macros(self) -> Macros:
        return add(i.macros() for i in self.items)


def add(ms) -> Macros:
    k = p = c = f = 0.0
    for m in ms:
        k += m.kcal
        p += m.protein
        c += m.carbs
        f += m.fat
    return Macros(k, p, c, f)


def totals(meals: list[Meal]) -> Macros:
    return add(m.macros() for m in meals if m.status != "skipped")


def snap(food: Food, grams: float) -> float:
    s = food.step
    return max(0.0, round(grams / s) * s)


@dataclass
class FitReport:
    totals: Macros
    target: Macros
    within_tolerance: bool
    changes: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _adjustable(meals: list[Meal], roles: set[str]) -> list[Item]:
    return [
        i
        for m in meals
        if not m.locked and m.status == "planned"
        for i in m.items
        if not i.locked and i.food.role in roles
    ]


def _scale(items: list[Item], key: str, gap: float, lo: float, hi: float) -> float:
    """Scale items so their `key` total moves by `gap`; returns the part not absorbed."""
    have = sum(getattr(i.macros(), key) for i in items)
    if have <= 0 or gap == 0:
        return gap
    s = max(lo, min(hi, 1 + gap / have))
    for i in items:
        i.grams *= s
    return gap - have * (s - 1)


def fit_day(
    meals: list[Meal], target: Macros, tolerance_kcal: float = 50, adjust: str = "carbs"
) -> tuple[list[Meal], FitReport]:
    meals = deepcopy(meals)
    before = {id(i): i.grams for m in meals for i in m.items}
    for m in meals:
        for i in m.items:
            if i.planned_grams is None:
                i.planned_grams = i.grams
    notes = []

    protein_items = _adjustable(meals, {"protein"})
    gap_p = target.protein - totals(meals).protein
    if abs(gap_p) > 5 and protein_items:
        _scale(protein_items, "protein", gap_p, 0.6, 1.6)
        notes.append("Proteine portate al target spostando gli alimenti proteici.")

    fat_items = _adjustable(meals, {"fat"})
    gap_f = target.fat - totals(meals).fat
    if gap_f < -5 and fat_items:
        _scale(fat_items, "fat", gap_f, 0.0, 1.0)
        notes.append("Grassi aggiunti ridotti perché sopra il target.")

    order = {
        "carbs": [{"carb", "fruit"}, {"fat"}, {"mixed"}],
        "fat": [{"fat"}, {"carb", "fruit"}, {"mixed"}],
        "mixed": [{"carb", "fruit", "fat"}, {"mixed"}],
    }[adjust]
    gap_k = target.kcal - totals(meals).kcal
    for roles in order:
        if abs(gap_k) <= tolerance_kcal:
            break
        items = _adjustable(meals, roles)
        if items:
            gap_k = _scale(items, "kcal", gap_k, 0.3, 2.0)

    for m in meals:
        for i in m.items:
            if i.grams != before[id(i)]:
                i.grams = max(snap(i.food, i.grams), i.food.step if before[id(i)] > 0 else 0)

    pool = sorted(
        _adjustable(meals, set(r for rs in order for r in rs)), key=lambda i: i.macros().kcal, reverse=True
    )
    for _ in range(12):
        gap_k = target.kcal - totals(meals).kcal
        if abs(gap_k) <= tolerance_kcal or not pool:
            break
        best = None
        for i in pool:
            delta = i.food.step if gap_k > 0 else -i.food.step
            if i.grams + delta < i.food.step:
                continue
            new_gap = abs(gap_k - i.food.macros(delta).kcal)
            if new_gap < abs(gap_k) and (best is None or new_gap < best[0]):
                best = (new_gap, i, delta)
        if best is None:
            break
        best[1].grams += best[2]

    t = totals(meals)
    changes = [
        {"slot": m.slot, "food": i.food.name, "from": round(before[id(i)]), "to": round(i.grams)}
        for m in meals
        for i in m.items
        if round(i.grams) != round(before[id(i)])
    ]
    ok = abs(t.kcal - target.kcal) <= tolerance_kcal
    if not ok:
        notes.append(
            "Con questi alimenti il target non si raggiunge senza stravolgere le "
            "porzioni: il piano resta indicativo."
        )
    return meals, FitReport(t.rounded(), target.rounded(), ok, changes, notes)


def equivalent_grams(original: Item, food: Food) -> float:
    """Grams of `food` that replace `original` on the macro that defines its role."""
    key = {"carb": "carbs", "fruit": "carbs", "protein": "protein", "fat": "fat"}.get(
        original.food.role, "kcal"
    )
    want = getattr(original.macros(), key)
    per_g = getattr(food, key) / 100
    if per_g <= 0:
        key, want, per_g = "kcal", original.macros().kcal, food.kcal / 100
    return max(food.step, snap(food, want / per_g)) if per_g > 0 else original.grams


def swap(meals: list[Meal], slot: str, index: int, food: Food) -> list[Meal]:
    meals = deepcopy(meals)
    meal = next(m for m in meals if m.slot == slot)
    old = meal.items[index]
    meal.items[index] = Item(
        food,
        equivalent_grams(old, food),
        old.locked,
        old.planned_grams or old.grams,
        old.planned_food_id or old.food.id,
    )
    return meals
