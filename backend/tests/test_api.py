"""End to end on the demo source: the whole loop a day of use goes through."""

from datetime import date, timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from nutri.api import create_app
from nutri.config import Config
from nutri.sources.demo import DemoSource

TODAY = date(2026, 11, 23)  # a Monday


class FixedConfig(Config):
    def today(self) -> date:
        return TODAY


def make(tmp_path, **auth) -> TestClient:
    cfg = FixedConfig(
        data_dir=tmp_path,
        source="demo",
        tz=ZoneInfo("Europe/Rome"),
        secret="s" * 64,
        sync_minutes=10_000,
        web_dir=None,
        agent_base_url=None,
        agent_api_key=None,
        agent_model="x",
        corpus_dir=tmp_path / "corpus",
        story_path=tmp_path / "story.md",
        **({"auth": "off"} | auth),
    )
    return TestClient(create_app(cfg, DemoSource(TODAY)))


@pytest.fixture
def client(tmp_path):
    with make(tmp_path) as c:
        yield c


def test_bootstrap_and_today(client):
    b = client.get("/api/bootstrap").json()
    assert b["demo"] and b["phase"]["template_id"] == "definizione"
    t = client.get("/api/today").json()
    assert t["targets"]["macros"]["kcal"] > 1500
    meals = t["plan"]["meals"]
    assert [m["slot"] for m in meals][:2] == ["colazione", "pranzo"]
    assert all(m["status"] == "planned" for m in meals)
    assert t["plan"]["report"]["within_tolerance"]
    assert t["consumed"]["kcal"] == 0


def test_meal_eaten_as_planned_leaves_the_rest_alone(client):
    t = client.get("/api/today").json()
    before = {m["slot"]: [i["grams"] for i in m["items"]] for m in t["plan"]["meals"]}
    r = client.post(f"/api/plan/{t['day']}/meals/colazione/confirm", json={}).json()
    after = {m["slot"]: [i["grams"] for i in m["items"]] for m in r["plan"]["meals"]}
    assert after == before


def test_confirm_modify_skip_and_undo(client):
    t = client.get("/api/today").json()
    day = t["day"]
    r = client.post(f"/api/plan/{day}/meals/colazione/confirm", json={}).json()
    assert r["plan"]["meals"][0]["status"] == "confirmed"
    assert r["consumed"]["kcal"] > 200

    lunch = next(m for m in r["plan"]["meals"] if m["slot"] == "pranzo")
    items = [{"food_id": i["food_id"], "grams": i["grams"]} for i in lunch["items"]]
    carb = next(i for i in lunch["items"] if i["role"] == "carb")
    for i in items:
        if i["food_id"] == carb["food_id"]:
            i["grams"] += 40
    dinner_before = next(m for m in r["plan"]["meals"] if m["slot"] == "cena")["macros"]["kcal"]
    r = client.post(f"/api/plan/{day}/meals/pranzo/confirm", json={"items": items}).json()
    lunch = next(m for m in r["plan"]["meals"] if m["slot"] == "pranzo")
    assert lunch["status"] == "modified"
    dinner_after = next(m for m in r["plan"]["meals"] if m["slot"] == "cena")["macros"]["kcal"]
    assert dinner_after < dinner_before  # the bigger lunch came off dinner

    r = client.post(f"/api/plan/{day}/meals/spuntino/skip").json()
    assert next(m for m in r["plan"]["meals"] if m["slot"] == "spuntino")["status"] == "skipped"

    r = client.post(f"/api/plan/{day}/meals/pranzo/undo").json()
    assert next(m for m in r["plan"]["meals"] if m["slot"] == "pranzo")["status"] == "planned"

    r = client.post(f"/api/plan/{day}/meals/cena/confirm", json={}).json()
    r = client.post(f"/api/plan/{day}/meals/pranzo/confirm", json={}).json()
    sync = client.post("/api/sync").json()
    assert sync["pending"] == 0 and sync["failed"] == 0
    days = client.get("/api/history").json()["days"]
    today_row = next(d for d in days if d["day"] == day)
    assert today_row["marked"] is True and today_row["kcal"] > 1000


def test_plan_editor_fit_swap_and_save(client):
    day = client.get("/api/today").json()["day"]
    plan = client.get(f"/api/plan/{day}").json()
    meals = [
        {
            "slot": m["slot"],
            "status": "planned",
            "locked": m["slot"] == "colazione",
            "items": [{"food_id": i["food_id"], "grams": i["grams"], "locked": False} for i in m["items"]],
        }
        for m in plan["meals"]
    ]
    meals[1]["items"][0]["grams"] += 60
    fitted = client.post(f"/api/plan/{day}/fit", json={"meals": meals}).json()
    assert fitted["report"]["within_tolerance"]
    assert [i["grams"] for i in fitted["meals"][0]["items"]] == [i["grams"] for i in meals[0]["items"]]
    first = {"food_id": meals[1]["items"][0]["food_id"], "grams": meals[1]["items"][0]["grams"]}
    alts = client.post("/api/foods/alternatives", json=first).json()
    assert alts and all(a["grams"] > 0 for a in alts)
    saved = client.put(f"/api/plan/{day}", json={"meals": meals}).json()
    assert saved["meals"][1]["items"][0]["grams"] == meals[1]["items"][0]["grams"]


def test_progress_history_templates(client):
    p = client.get("/api/progress").json()
    assert p["trend"] and p["rate"] and p["expenditure"]["status"] == "data"
    assert 2100 < p["expenditure"]["kcal"] < 2800
    assert len(p["weeks"]) == 6
    h = client.get("/api/history", params={"week_start": (TODAY - timedelta(days=7)).isoformat()}).json()
    assert len(h["days"]) == 7 and h["days"][0]["meals"]
    assert any(t["slot"] == "colazione" for t in h["templates"])
    key = h["templates"][0]["key"]
    assert client.post("/api/templates/pin", json={"key": key, "mode": "fixed"}).json()["ok"]
    t = client.get("/api/today").json()
    slot = h["templates"][0]["slot"]
    assert next(m for m in t["plan"]["meals"] if m["slot"] == slot)["locked"]


def test_week_preview_and_apply(client):
    w = client.post("/api/week/preview", json={"variety": "same"}).json()
    assert len(w["days"]) == 7
    assert all(d["report"]["within_tolerance"] for d in w["days"])
    alt = client.post("/api/week/preview", json={"variety": "alternative"}).json()
    assert alt["days"]
    assert client.post("/api/week/apply", json={"variety": "same"}).json()["saved"] == 7


def test_checkin_flow(client):
    c = client.get("/api/checkin").json()
    assert c["verdict"] in {
        "ok",
        "too_fast_loss",
        "too_slow_loss",
        "hold_before_cut",
        "low_adherence",
        "insufficient_data",
    }
    week_end = c["week_end"]
    kcal = c["phase"]["kcal_target"] + 75
    pv = client.post(f"/api/checkin/{week_end}/preview", json={"kcal": kcal, "adjust_macro": "fat"}).json()
    assert pv["kcal_to"] == kcal and pv["macros_to"]["fat"] > pv["macros_from"]["fat"]
    d = client.post(
        f"/api/checkin/{week_end}/decide", json={"decision": "modify", "kcal": kcal, "adjust_macro": "fat"}
    ).json()
    assert d["decision"] == "modify"
    assert client.get("/api/phase").json()["phase"]["kcal_target"] == kcal
    assert client.get("/api/today").json()["checkin"] is None


def test_settings_and_phase(client):
    s = client.get("/api/settings").json()
    assert "engine" in s["schema"]["$defs"] or "EngineParams" in s["schema"]["$defs"]
    body = s["settings"]
    body["engine"]["logging_offset_kcal"] = 200
    assert client.put("/api/settings", json=body).json()["engine"]["logging_offset_kcal"] == 200
    t = client.get("/api/today").json()
    assert t["target_loggable"]["kcal"] == t["targets"]["macros"]["kcal"] - 200
    ph = client.patch("/api/phase", json={"protein_g_per_kg": 2.2}).json()
    assert ph["modified"] and ph["protein_g_per_kg"] == 2.2
    started = client.post("/api/phase", json={"template_id": "mantenimento"}).json()
    assert started["kind"] == "maintenance" and started["kcal_target"]


def test_chat_without_agent_explains(client):
    r = client.post("/api/chat", json={"message": "ciao"})
    assert "Coach non configurato" in r.text
