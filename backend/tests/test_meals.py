"""The day's meals food by food: edit, delete, copy, and what Cronometer gets told."""

import json
from datetime import timedelta

import pytest

from nutri.service import CoachError

from .test_api import TODAY, make

YESTERDAY = TODAY - timedelta(days=1)
TOMORROW = TODAY + timedelta(days=1)


@pytest.fixture
def app(tmp_path):
    with make(tmp_path) as c:
        yield c.app.state.app


def meal(view, slot):
    return next(m for m in view["meals"] if m["slot"] == slot)


def outbox(app):
    return [(r["kind"], json.loads(r["payload"])) for r in app.store.pending()]


def diary(app, day, slot):
    return sorted((r["food_id"], r["grams"]) for r in app.store.entries(day) if r["slot"] == slot)


def test_copy_keeps_the_exact_grams(app):
    c = app.coach
    for target in (TODAY, TOMORROW):
        v = c.copy_meals(YESTERDAY, target, None, TODAY)
        for slot in ("colazione", "pranzo", "spuntino", "cena"):
            src = diary(app, YESTERDAY, slot)
            if not src:
                continue
            m = meal(v, slot)
            assert m["status"] == "planned"
            assert sorted((i["food_id"], i["grams"]) for i in m["items"]) == src
    assert not outbox(app)  # copies are planned, nothing is written until confirmed


def test_repeat_is_a_copy_and_today_onto_itself_is_refused(app):
    c = app.coach
    v = c.repeat_day(YESTERDAY, TODAY, TODAY)
    assert sorted((i["food_id"], i["grams"]) for i in meal(v, "pranzo")["items"]) == diary(
        app, YESTERDAY, "pranzo"
    )
    with pytest.raises(CoachError):
        c.repeat_day(TODAY, TODAY, TODAY)


def test_copy_replaces_planned_foods_and_keeps_eaten_ones(app):
    c = app.coach
    v = c.today(TODAY, TODAY)
    first = meal(v, "pranzo")["items"][0]
    v = c.confirm_items(TODAY, "pranzo", TODAY, [first["ref"]])
    lunch = meal(v, "pranzo")
    assert lunch["status"] == "partial" and lunch["count_eaten"] == 1
    planned_before = {i["ref"] for i in lunch["items"] if i["state"] == "planned"}

    v = c.copy_meals(YESTERDAY, TODAY, ["pranzo"], TODAY)
    lunch = meal(v, "pranzo")
    eaten = [(i["food_id"], i["grams"]) for i in lunch["items"] if i["state"] == "eaten"]
    planned = [i for i in lunch["items"] if i["state"] == "planned"]
    assert eaten == [(first["food_id"], first["grams"])]
    assert sorted((i["food_id"], i["grams"]) for i in planned) == diary(app, YESTERDAY, "pranzo")
    assert not planned_before & {i["ref"] for i in planned}
    assert meal(v, "colazione")["status"] == "planned"  # meals not chosen are left alone


def test_edit_and_delete_a_planned_food(app):
    c = app.coach
    v = c.today(TOMORROW, TODAY)
    item = meal(v, "cena")["items"][0]
    v = c.update_item(TOMORROW, item["ref"], 137, TODAY)
    edited = next(i for i in meal(v, "cena")["items"] if i["ref"] == item["ref"])
    assert edited["grams"] == 137 and edited["state"] == "planned"
    assert c.plan(TOMORROW, TODAY)["meals"][3]["items"][0]["locked"]

    n = len(meal(v, "cena")["items"])
    v = c.delete_item(TOMORROW, item["ref"], TODAY)
    assert len(meal(v, "cena")["items"]) == n - 1
    assert not outbox(app)


def test_edit_and_delete_a_food_already_on_cronometer(app):
    c = app.coach
    v = c.confirm_items(TODAY, "colazione", TODAY)
    app.syncer.push()
    eaten = [i for i in meal(c.today(TODAY, TODAY), "colazione")["items"] if i["state"] == "eaten"]
    assert all(i["ref"].startswith("s:") for i in eaten)

    a, b = eaten[0], eaten[1]
    v = c.update_item(TODAY, a["ref"], a["grams"] + 30, TODAY)
    assert outbox(app) == [
        ("delete_servings", {"day": TODAY.isoformat(), "serving_ids": [a["ref"][2:]]}),
        (
            "add_serving",
            {
                "day": TODAY.isoformat(),
                "slot": "colazione",
                "food_id": a["food_id"],
                "grams": a["grams"] + 30,
                "entry_id": outbox(app)[1][1]["entry_id"],
            },
        ),
    ]
    assert (a["food_id"], a["grams"] + 30) in [
        (i["food_id"], i["grams"]) for i in meal(v, "colazione")["items"]
    ]

    v = c.delete_item(TODAY, b["ref"], TODAY)
    assert outbox(app)[-1] == ("delete_servings", {"day": TODAY.isoformat(), "serving_ids": [b["ref"][2:]]})
    assert b["ref"] not in {i["ref"] for i in meal(v, "colazione")["items"]}

    app.syncer.push()
    on_cronometer = [
        (e["food_id"], e["grams"]) for e in app.source.diary(TODAY).entries if e["slot"] == "colazione"
    ]
    assert (a["food_id"], a["grams"] + 30) in on_cronometer
    assert (a["food_id"], a["grams"]) not in on_cronometer
    assert (b["food_id"], b["grams"]) not in on_cronometer
    assert meal(c.today(TODAY, TODAY), "colazione")["status"] == "eaten"


def test_edit_and_delete_a_food_still_in_the_outbox(app):
    c = app.coach
    c.confirm_items(TODAY, "spuntino", TODAY)
    eaten = [i for i in meal(c.today(TODAY, TODAY), "spuntino")["items"] if i["state"] == "eaten"]
    assert all(i["ref"].startswith("e:") and i["pending"] for i in eaten)
    v = c.update_item(TODAY, eaten[0]["ref"], 200, TODAY)
    v = c.delete_item(TODAY, eaten[1]["ref"], TODAY)
    kinds = [k for k, _ in outbox(app)]
    assert "delete_servings" not in kinds  # nothing reached Cronometer, nothing to delete there
    assert [p["grams"] for k, p in outbox(app) if k == "add_serving"] == [200]
    assert [(i["food_id"], i["grams"]) for i in meal(v, "spuntino")["items"]] == [(eaten[0]["food_id"], 200)]


def test_a_ref_loaded_before_the_push_still_finds_its_food(app):
    c = app.coach
    v = c.add_item(TODAY, "cena", "demo:mela", 180, TODAY, eaten=True)
    ref = next(i["ref"] for i in meal(v, "cena")["items"] if i["food_id"] == "demo:mela")
    assert ref.startswith("e:")
    app.syncer.push()
    v = c.update_item(TODAY, ref, 120, TODAY)
    assert ("demo:mela", 120) in [(i["food_id"], i["grams"]) for i in meal(v, "cena")["items"]]
    assert outbox(app)[0][0] == "delete_servings"


def test_food_added_inside_a_meal_stays_in_that_meal(app):
    c = app.coach
    v = c.add_item(TODAY, "pranzo", "demo:mela", 180, TODAY, eaten=True)
    lunch = meal(v, "pranzo")
    assert lunch["status"] == "partial"
    assert ("demo:mela", 180) in [(i["food_id"], i["grams"]) for i in lunch["items"] if i["state"] == "eaten"]
    app.syncer.push()
    v = c.today(TODAY, TODAY)
    assert meal(v, "pranzo")["status"] == "partial"  # synced back, still the app's own entry
    assert "extra" not in v


def test_meal_logged_on_cronometer_takes_the_place_of_the_plan(app):
    c = app.coach
    c.today(TODAY, TODAY)
    app.source.add_serving({"id": "demo:pizza"}, 330, TODAY, "cena")
    app.syncer.pull_day(TODAY)
    v = c.today(TODAY, TODAY)
    dinner = meal(v, "cena")
    assert dinner["status"] == "eaten"
    assert [i["food_id"] for i in dinner["items"] if i["state"] == "eaten"] == ["demo:pizza"]
    v = c.undo_meal(TODAY, "cena", TODAY)
    assert meal(v, "cena")["status"] == "partial"  # brought back on request, not skipped again


def test_regression_ripeti_oggi_on_today_wiped_the_other_meals(app):
    """Repeating today onto itself rebuilt the plan from the only meal eaten so far: Pranzo, Spuntino
    and Cena vanished, "Da piano" went to 0 and foods added later fell into "Altro mangiato"."""
    c = app.coach
    c.confirm_items(TODAY, "colazione", TODAY)
    app.syncer.push()
    with pytest.raises(CoachError):
        c.repeat_day(TODAY, TODAY, TODAY)
    c.copy_meals(YESTERDAY, TODAY, ["colazione"], TODAY)
    v = c.add_item(TODAY, "pranzo", "demo:mela", 180, TODAY, eaten=True)
    assert [m["slot"] for m in v["meals"]] == ["colazione", "pranzo", "spuntino", "cena"]
    assert meal(v, "spuntino")["status"] == "planned" and meal(v, "cena")["status"] == "planned"
    assert v["planned_remaining"]["kcal"] > 0


def test_regression_settings_save_after_undo_kept_the_plan(app):
    """An undo left no confirmed meal, and the next settings save deleted the day's plan."""
    c = app.coach
    v = c.today(TODAY, TODAY)
    c.skip_meal(TODAY, "spuntino", TODAY)
    c.undo_meal(TODAY, "spuntino", TODAY)
    item = meal(v, "cena")["items"][0]
    c.update_item(TODAY, item["ref"], item["grams"] + 50, TODAY)
    c.add_item(TODAY, "pranzo", "demo:mela", 180, TODAY, eaten=True)
    c.save_settings(c.settings())
    c._drop_future_plans(TODAY)
    v = c.today(TODAY, TODAY)
    assert item["ref"] in {i["ref"] for i in meal(v, "cena")["items"]}
    assert ("demo:mela", 180) in [(i["food_id"], i["grams"]) for i in meal(v, "pranzo")["items"]]


def test_plans_saved_before_per_food_state_still_load(app):
    c = app.coach
    c.confirm_items(TODAY, "colazione", TODAY)
    app.syncer.push()
    old = {
        "day": TOMORROW.isoformat(),
        "source": "x",
        "meals": [
            {"slot": "colazione", "status": "confirmed", "items": [{"food_id": "demo:yog", "grams": 170}]},
            {"slot": "pranzo", "status": "skipped", "items": [{"food_id": "demo:riso", "grams": 80}]},
            {"slot": "cena", "status": "planned", "items": [{"food_id": "demo:sal", "grams": 150}]},
        ],
    }
    app.store.put_plan(TOMORROW, old)
    v = c.today(TOMORROW, TODAY)
    assert [m["status"] for m in v["meals"]] == ["empty", "skipped", "empty", "planned"]
