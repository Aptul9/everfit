"""The agent loop against a scripted Messages API: tools run, proposals surface, nothing is written
until the owner applies the proposal."""

import json

import httpx

from nutri.llm import Messages

from .test_api import make


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


def test_agent_reads_with_tools_and_proposes_a_log(tmp_path):
    with make(tmp_path) as client:
        state = client.app.state.app
        day = client.get("/api/today").json()["day"]
        food = state.store.q("select id from foods where name like 'Skyr%'")[0]["id"]
        seen: list[dict] = []
        replies = [
            tool_reply("t1", "oggi", {}),
            tool_reply(
                "t2",
                "proponi_registrazione",
                {"slot": "spuntino", "items": [{"food_id": food, "grams": 150}], "summary": "Skyr"},
            ),
            text_reply("Fatto, conferma la scheda."),
        ]
        state.agent.client = Messages("http://meridian.test", None, transport=scripted(replies, seen))

        r = client.post("/api/chat", json={"message": "ho mangiato uno skyr"})
        evs = events(r)
        kinds = [e["type"] for e in evs]
        assert kinds.count("tool") == 2 and "proposal" in kinds and kinds[-1] == "done"
        assert "".join(e["text"] for e in evs if e["type"] == "text") == "Fatto, conferma la scheda."
        assert seen[0]["system"][0]["text"].startswith("Sei il coach")
        assert seen[1]["messages"][-1]["content"][0]["type"] == "tool_result"
        assert "x-meridian-agent" in state.agent.client.headers

        before = client.get("/api/today").json()["consumed"]["kcal"]
        prop = next(e for e in evs if e["type"] == "proposal")["proposal"]
        assert client.get("/api/today").json()["consumed"]["kcal"] == before  # nothing written yet
        assert client.post(f"/api/proposals/{prop['proposal_id']}/apply").json()["ok"]
        assert client.get("/api/today").json()["consumed"]["kcal"] > before
        assert client.post(f"/api/proposals/{prop['proposal_id']}/apply").status_code == 400

        hist = client.get("/api/chat").json()
        assert [h["role"] for h in hist][0] == "user"
        assert any(h["role"] == "proposal" and h["proposal"]["status"] == "applied" for h in hist)
        assert hist[-1]["text"] == "Fatto, conferma la scheda."
        del day


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
