"""The agent loop against a scripted Messages API: meal and food tools act at once and can be undone,
phase changes surface as proposals that wait for the owner."""

import json
from datetime import date, timedelta

import httpx
import pytest

from nutri.llm import Messages
from nutri.service import CoachError

from .test_api import TODAY, make


def sse(*events: dict) -> bytes:
    return "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events).encode()


def text_reply(text: str) -> bytes:
    return sse(
        {"type": "message_start", "message": {}},
        {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": text}},
        {"type": "content_block_stop", "index": 0},
        {"type": "message_delta", "delta": {"stop_reason": "end_turn"}},
        {"type": "message_stop"},
    )


def tool_reply(tid: str, name: str, args: dict) -> bytes:
    raw = json.dumps(args)
    return sse(
        {"type": "message_start", "message": {}},
        {
            "type": "content_block_start",
            "index": 0,
            "content_block": {"type": "tool_use", "id": tid, "name": name, "input": {}},
        },
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "input_json_delta", "partial_json": raw[:5]},
        },
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "input_json_delta", "partial_json": raw[5:]},
        },
        {"type": "content_block_stop", "index": 0},
        {"type": "message_delta", "delta": {"stop_reason": "tool_use"}},
        {"type": "message_stop"},
    )


def scripted(replies: list[bytes], seen: list[dict]):
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, content=replies.pop(0), headers={"content-type": "text/event-stream"})

    return httpx.MockTransport(handler)


def events(resp: httpx.Response) -> list[dict]:
    return [json.loads(line[5:]) for line in resp.text.splitlines() if line.startswith("data:")]


def meal(view, slot):
    return next(m for m in view["meals"] if m["slot"] == slot)


def planned(view, slot):
    return sorted((i["food_id"], i["grams"]) for i in meal(view, slot)["items"] if i["state"] == "planned")


def diary(state, day, slot):
    return sorted((r["food_id"], r["grams"]) for r in state.store.entries(day) if r["slot"] == slot)


def outbox(state):
    return [(r["kind"], json.loads(r["payload"])) for r in state.store.q("select * from outbox order by id")]


def test_oggi_come_ieri_copies_yesterday_with_the_same_grams(tmp_path):
    with make(tmp_path) as client:
        state = client.app.state.app
        yesterday = (TODAY - timedelta(days=1)).isoformat()
        before = client.get("/api/today").json()
        seen: list[dict] = []
        replies = [
            tool_reply("t1", "copia_pasti", {"source": yesterday, "target": TODAY.isoformat()}),
            text_reply("Fatto: oggi ha gli stessi pasti di ieri, da confermare."),
        ]
        state.agent.client = Messages("http://meridian.test", None, transport=scripted(replies, seen))

        evs = events(client.post("/api/chat", json={"message": "fai che oggi sia come ieri"}))
        kinds = [e["type"] for e in evs]
        assert kinds == ["tool", "action", "text", "done"]
        assert seen[0]["system"][0]["text"].startswith("Sei il coach")
        assert "lunedì 2026-11-23" in seen[0]["system"][0]["text"]
        assert "copia_pasti" in {t["name"] for t in seen[0]["tools"]}
        assert "proponi_registrazione" not in {t["name"] for t in seen[0]["tools"]}
        assert json.loads(seen[1]["messages"][-1]["content"][0]["content"])["action_id"]
        assert "x-meridian-agent" in state.agent.client.headers

        today = client.get("/api/today").json()
        for slot in ("colazione", "pranzo", "spuntino", "cena"):
            assert planned(today, slot) == diary(state, date.fromisoformat(yesterday), slot)
        assert not [k for k, _ in outbox(state)]  # copies are planned: nothing went to Cronometer

        action = next(e for e in evs if e["type"] == "action")["action"]
        assert action["title"].startswith("Copiato tutti i pasti da ieri in oggi")
        added = [c for c in action["changes"] if c["kind"] == "add"]
        assert added and all(c["state"] == "planned" for c in added)

        hist = client.get("/api/chat").json()
        assert [h["role"] for h in hist] == ["user", "assistant", "action", "assistant"]
        assert hist[2]["action"]["status"] == "done"

        r = client.post(f"/api/actions/{action['action_id']}/undo").json()
        assert r["ok"] and r["view"]["meals"] == before["meals"]
        assert client.get("/api/chat").json()[2]["action"]["status"] == "undone"
        assert client.post(f"/api/actions/{action['action_id']}/undo").status_code == 400


def test_each_action_tool_runs_the_service(tmp_path):
    with make(tmp_path) as client:
        state = client.app.state.app
        agent = state.agent
        run = agent.run_tool

        out, ev = run(
            "aggiungi_alimento", {"slot": "pranzo", "food_id": "demo:mela", "grams": 180, "eaten": True}
        )
        assert ev["type"] == "action" and out["action_id"]
        assert ("demo:mela", 180) in diary(state, TODAY, "pranzo")
        ref = next(
            i["ref"]
            for i in meal(state.coach.today(TODAY, TODAY), "pranzo")["items"]
            if i["food_id"] == "demo:mela"
        )

        out, ev = run("modifica_grammi", {"ref": ref, "grams": 120})
        assert ("demo:mela", 120) in diary(state, TODAY, "pranzo")
        assert [c["kind"] for c in ev["action"]["changes"]] == ["grams"]
        ref = next(
            i["ref"]
            for i in meal(state.coach.today(TODAY, TODAY), "pranzo")["items"]
            if i["food_id"] == "demo:mela"
        )

        run("elimina_alimento", {"ref": ref})
        assert "demo:mela" not in [f for f, _ in diary(state, TODAY, "pranzo")]

        out, ev = run("segna_mangiato", {"slot": "colazione"})
        assert meal(state.coach.today(TODAY, TODAY), "colazione")["status"] == "eaten"
        assert {c["kind"] for c in ev["action"]["changes"]} == {"eaten"}

        run("salta_pasto", {"slot": "spuntino"})
        assert meal(state.coach.today(TODAY, TODAY), "spuntino")["status"] == "skipped"
        run("ripristina_pasto", {"slot": "spuntino"})
        assert meal(state.coach.today(TODAY, TODAY), "spuntino")["status"] == "planned"

        tomorrow = TODAY + timedelta(days=1)
        source = TODAY - timedelta(days=3)
        out, ev = run(
            "copia_pasti", {"source": source.isoformat(), "target": tomorrow.isoformat(), "slots": ["cena"]}
        )
        assert planned(state.coach.today(tomorrow, TODAY), "cena") == diary(state, source, "cena")
        assert ev["action"]["day"] == tomorrow.isoformat()

        with pytest.raises(CoachError):
            run("aggiungi_alimento", {"slot": "merenda", "food_id": "demo:mela", "grams": 1, "eaten": False})


def test_undo_puts_back_planned_and_eaten_foods_and_tells_cronometer(tmp_path):
    with make(tmp_path) as client:
        state = client.app.state.app
        run, undo, c = state.agent.run_tool, state.agent.undo, state.coach
        start = c.today(TODAY, TODAY)

        # eaten: confirming breakfast logs it; undoing deletes those servings on Cronometer
        _, ev = run("segna_mangiato", {"slot": "colazione"})
        state.syncer.push()
        sids = [r["serving_id"] for r in state.store.entries(TODAY) if r["slot"] == "colazione"]
        assert sids and all(sids)
        mark = len(outbox(state))
        undo(ev["action"]["action_id"])
        deleted = [p["serving_ids"][0] for k, p in outbox(state)[mark:] if k == "delete_servings"]
        assert sorted(deleted) == sorted(sids)
        assert meal(c.today(TODAY, TODAY), "colazione")["items"] == meal(start, "colazione")["items"]
        assert not [e for e in state.source.diary(TODAY).entries if e["slot"] == "colazione"]

        # eaten, removed: undoing a delete logs the same food and grams again
        run("segna_mangiato", {"slot": "spuntino"})
        state.syncer.push()
        item = next(i for i in meal(c.today(TODAY, TODAY), "spuntino")["items"] if i["state"] == "eaten")
        _, ev = run("elimina_alimento", {"ref": item["ref"]})
        mark = len(outbox(state))
        undo(ev["action"]["action_id"])
        assert [(k, p["food_id"], p["grams"]) for k, p in outbox(state)[mark:]] == [
            ("add_serving", item["food_id"], item["grams"])
        ]
        assert (item["food_id"], item["grams"]) in diary(state, TODAY, "spuntino")

        # planned: grams come back, nothing is written to Cronometer
        dinner = meal(c.today(TODAY, TODAY), "cena")["items"][0]
        _, ev = run("modifica_grammi", {"ref": dinner["ref"], "grams": dinner["grams"] + 60})
        mark = len(outbox(state))
        undo(ev["action"]["action_id"])
        assert len(outbox(state)) == mark
        assert meal(c.today(TODAY, TODAY), "cena")["items"][0]["grams"] == dinner["grams"]

        # a later change to the day blocks the undo instead of being lost
        _, ev = run("salta_pasto", {"slot": "pranzo"})
        c.add_item(TODAY, "pranzo", "demo:mela", 180, TODAY, eaten=True)
        with pytest.raises(CoachError):
            undo(ev["action"]["action_id"])


def test_phase_changes_still_wait_for_the_owner(tmp_path):
    with make(tmp_path) as client:
        state = client.app.state.app
        kcal = state.coach.phase().kcal_target
        replies = [
            tool_reply(
                "t1", "proponi_fase", {"changes": {"kcal_target": kcal + 100}, "summary": "+100 kcal"}
            ),
            text_reply("Ti ho preparato la scheda."),
        ]
        state.agent.client = Messages("http://meridian.test", None, transport=scripted(replies, []))
        evs = events(client.post("/api/chat", json={"message": "alza le calorie di 100"}))
        prop = next(e for e in evs if e["type"] == "proposal")["proposal"]
        assert state.coach.phase().kcal_target == kcal  # nothing written yet
        assert client.post(f"/api/proposals/{prop['proposal_id']}/apply").json()["ok"]
        assert state.coach.phase().kcal_target == kcal + 100
        hist = client.get("/api/chat").json()
        assert any(h["role"] == "proposal" and h["proposal"]["status"] == "applied" for h in hist)


def test_history_survives_a_turn_cut_short(tmp_path):
    with make(tmp_path) as client:
        agent = client.app.state.app.agent
        agent.save("user", "prima domanda")
        agent.save("assistant", [{"type": "tool_use", "id": "x1", "name": "oggi", "input": {}}])
        agent.save("user", "seconda domanda")
        agent.save("assistant", [{"type": "text", "text": "risposta"}])
        agent.save("user", "terza")
        h = agent.history()
        assert [m["role"] for m in h] == ["user", "assistant", "user"]
        assert not any(
            b.get("type") == "tool_use"
            for m in h
            for b in (m["content"] if isinstance(m["content"], list) else [])
        )
        texts = [b["text"] for b in h[0]["content"]]
        assert texts == ["prima domanda", "seconda domanda"]


def test_agent_reports_api_errors(tmp_path):
    with make(tmp_path) as client:
        state = client.app.state.app
        state.agent.client = Messages(
            "http://x.test",
            None,
            transport=httpx.MockTransport(lambda r: httpx.Response(529, content=b'{"error":"overloaded"}')),
        )
        evs = events(client.post("/api/chat", json={"message": "ciao"}))
        assert evs[-1]["type"] == "error" and "529" in evs[-1]["message"]
