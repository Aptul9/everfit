"""Parsing of the Cronometer mobile API payloads, shaped as the live account returns them (2026-11-22)."""

from datetime import date

from nutri.sources.cronometer import CronometerSource, _marked_complete, food_info

FOOD = {
    "id": 4242,
    "name": "Riso basmati",
    "defaultMeasureId": 7,
    "measures": [
        {"id": 7, "name": "cup", "value": 185.0, "amount": 1, "type": "Weight"},
        {"id": 9, "name": "g", "value": 1, "amount": 1, "type": "Weight"},
    ],
    "nutrients": [
        {"id": 208, "amount": 356},
        {"id": 203, "amount": 8},
        {"id": 205, "amount": 78},
        {"id": 204, "amount": 0.9},
    ],
    "translations": [{"id": 3}],
}


def test_unmarked_days_are_unknown_not_incomplete():
    assert _marked_complete({"info": {"complete": True, "day": "2026-11-21"}}) is True
    assert _marked_complete({"info": {"complete": False, "day": "2026-11-21"}}) is None
    assert _marked_complete({}) is None


def test_food_per_100g_and_gram_measure():
    f = food_info(FOOD)
    assert (f.id, f.kcal, f.protein, f.carbs, f.fat) == ("cr:4242", 356, 8, 78, 0.9)
    assert f.measure_id == 9 and f.translation_id == 3


class FakeClient:
    def get_diary(self, day):
        return {
            "diary": [
                {
                    "type": "Serving",
                    "foodId": 4242,
                    "grams": 80,
                    "measureId": 9,
                    "order": (2 << 16) | 1,
                    "servingId": "s1",
                },
                {
                    "type": "Serving",
                    "foodId": 999,
                    "grams": 10,
                    "measureId": 0,
                    "order": (1 << 16) | 1,
                    "servingId": "s2",
                },
            ],
            "info": {"complete": False, "day": str(day)},
        }

    def get_foods(self, ids):
        return [FOOD] if 4242 in ids else []


def test_diary_entries_map_to_meal_slots_and_skip_unknown_foods():
    src = CronometerSource.__new__(CronometerSource)
    src.client = FakeClient()
    src._foods = {}
    d = src.diary(date(2026, 11, 21))
    assert d.entries == [{"slot": "pranzo", "food_id": "cr:4242", "grams": 80.0, "serving_id": "s1"}]
    assert d.marked_complete is None
