from datetime import date, timedelta

import pytest

from nutri.engine.habits import Entry, detect_templates, usual_portions
from nutri.engine.plan import Food, Item, Meal, equivalent_grams, fit_day, swap, totals
from nutri.engine.targets import Macros

YOG = Food("yog", "Yogurt greco", 97, 9, 4, 5)
OATS = Food("ave", "Avena", 370, 13, 60, 7)
RICE = Food("riso", "Riso basmati", 350, 7, 78, 0.6)
PASTA = Food("pasta", "Pasta", 360, 13, 72, 1.5)
POTATO = Food("pat", "Patate", 80, 2, 17, 0.1)
CHICKEN = Food("pol", "Pollo", 110, 23, 0, 1.5)
SALMON = Food("sal", "Salmone", 200, 20, 0, 13)
ZUC = Food("zuc", "Zucchine", 17, 1.2, 3, 0.3)
OIL = Food("olio", "Olio EVO", 900, 0, 0, 100)
EGG = Food("uovo", "Uovo", 143, 12.6, 0.7, 9.5, unit_g=60, unit_name="uovo")
BANANA = Food("ban", "Banana", 89, 1.1, 23, 0.3, unit_g=120, unit_name="banana")


def day() -> list[Meal]:
    return [
        Meal("colazione", [Item(YOG, 250), Item(OATS, 50), Item(BANANA, 120)]),
        Meal("pranzo", [Item(RICE, 100), Item(CHICKEN, 160), Item(ZUC, 200), Item(OIL, 10)]),
        Meal("cena", [Item(SALMON, 160), Item(POTATO, 250), Item(OIL, 10)]),
    ]


def test_roles():
    assert RICE.role == "carb"
    assert CHICKEN.role == "protein"
    assert OIL.role == "fat"
    assert ZUC.role == "veg"
    assert BANANA.role == "fruit"
    assert OIL.step == 5 and RICE.step == 10 and EGG.step == 60


def test_smaller_target_cuts_carbs_and_keeps_protein_and_vegetables():
    meals = day()
    t0 = totals(meals)
    target = Macros(t0.kcal - 150, t0.protein, t0.carbs - 37, t0.fat)
    out, rep = fit_day(meals, target, 50)
    rice = out[1].items[0]
    assert rice.grams < 100 and rice.grams % 10 == 0
    assert out[1].items[1].grams == 160  # chicken
    assert out[1].items[2].grams == 200  # zucchini
    assert abs(rep.totals.kcal - target.kcal) <= 50
    assert rep.within_tolerance
    assert any(c["food"] == "Riso basmati" for c in rep.changes)


def test_locked_meal_and_items_are_never_touched():
    meals = day()
    meals[0].locked = True
    meals[1].items[0].locked = True
    t0 = totals(meals)
    out, _ = fit_day(meals, Macros(t0.kcal - 200, t0.protein, t0.carbs - 50, t0.fat), 50)
    assert [i.grams for i in out[0].items] == [250, 50, 120]
    assert out[1].items[0].grams == 100
    assert out[2].items[1].grams < 250  # potatoes took the cut


def test_confirmed_meals_rebalance_the_rest_of_the_day():
    meals = day()
    t0 = totals(meals)
    meals[1].items[0].grams = 130  # lunch was bigger than planned
    meals[1].status = "modified"
    meals[1].locked = True
    out, rep = fit_day(meals, t0, 50)
    assert out[2].items[1].grams < 250
    assert out[2].items[0].grams == pytest.approx(160, abs=20)
    assert rep.within_tolerance


def test_portions_round_to_real_units():
    meals = [Meal("colazione", [Item(EGG, 180), Item(BANANA, 120), Item(OATS, 40)])]
    t0 = totals(meals)
    out, _ = fit_day(meals, Macros(t0.kcal + 160, t0.protein, t0.carbs + 40, t0.fat), 40)
    assert out[0].items[1].grams % 60 == 0
    assert out[0].items[0].grams % 60 == 0


def test_too_much_fat_comes_off_added_fats_first():
    meals = day()
    t0 = totals(meals)
    out, _ = fit_day(meals, Macros(t0.kcal - 90, t0.protein, t0.carbs, t0.fat - 10), 50)
    oil = [i.grams for m in out for i in m.items if i.food.id == "olio"]
    assert sum(oil) < 20


def test_equivalent_swap_matches_the_macro_that_matters():
    rice = Item(RICE, 80)
    assert equivalent_grams(rice, PASTA) == pytest.approx(80 * 78 / 72, abs=10)
    assert equivalent_grams(rice, POTATO) == pytest.approx(80 * 78 / 17, abs=25)
    meals = swap(day(), "pranzo", 0, PASTA)
    assert meals[1].items[0].food.id == "pasta"
    assert meals[1].items[0].planned_food_id == "riso"


def test_habits_find_the_usual_lunch():
    entries = []
    d0 = date(2026, 11, 1)
    for i in range(10):
        d = d0 + timedelta(days=i)
        entries += [Entry(d, "colazione", YOG, 250), Entry(d, "colazione", OATS, 50)]
        if i % 3:
            entries += [
                Entry(d, "pranzo", RICE, 90 + i),
                Entry(d, "pranzo", CHICKEN, 160),
                Entry(d, "pranzo", ZUC, 200),
            ]
        else:
            entries += [Entry(d, "pranzo", PASTA, 90), Entry(d, "pranzo", SALMON, 120)]
    tpls = detect_templates(entries)
    lunch = [t for t in tpls if t.slot == "pranzo"]
    assert lunch[0].count == 6
    assert {f.id for f, _ in lunch[0].foods} == {"riso", "pol", "zuc"}
    assert tpls[0].slot == "colazione" and tpls[0].count == 10
    assert usual_portions(entries)["pol"] == 160
