"""Connecting the Cronometer account from the app: a real login check, encrypted storage, the source switch."""

from zoneinfo import ZoneInfo

import pytest
from cryptography.exceptions import InvalidTag
from fastapi.testclient import TestClient

from nutri import vault
from nutri.api import create_app
from nutri.sources import cronometer

from .test_api import FixedConfig


def make(tmp_path):
    cfg = FixedConfig(
        data_dir=tmp_path,
        source="cronometer",
        tz=ZoneInfo("Europe/Rome"),
        secret="k" * 64,
        sync_minutes=10_000,
        web_dir=None,
        agent_base_url=None,
        agent_api_key=None,
        agent_model="x",
        corpus_dir=tmp_path,
        story_path=tmp_path / "story.md",
        auth="off",
    )
    return TestClient(create_app(cfg))


@pytest.fixture
def logins(monkeypatch):
    seen = []

    def fake_check(credentials, data_dir):
        seen.append(credentials)
        if credentials["password"] != "giusta":
            raise cronometer.CronometerError("Login failed: {'result': 'FAIL'}")

    monkeypatch.setattr(cronometer, "check_login", fake_check)
    monkeypatch.setattr(cronometer.CronometerClient, "get_biometrics", lambda *a, **k: {"data": []})
    monkeypatch.setattr(cronometer.CronometerClient, "get_diary", lambda *a, **k: {"diary": [], "info": {}})
    return seen


def test_starts_unconnected_and_says_so(tmp_path, logins):
    with make(tmp_path) as c:
        assert c.get("/api/cronometer").json() == {"connected": False, "username": None, "demo": False}
        assert c.get("/api/bootstrap").json()["cronometer"]["connected"] is False
        sync = c.post("/api/sync").json()
        assert sync["connected"] is False and not sync.get("last_error")


def test_wrong_password_is_refused_and_nothing_is_stored(tmp_path, logins):
    with make(tmp_path) as c:
        r = c.put("/api/cronometer", json={"username": "me@x.it", "password": "sbagliata"})
        assert r.status_code == 400 and "rifiutato" in r.json()["detail"]
        assert c.app.state.app.store.get("cronometer_credentials") is None


def test_good_login_is_kept_encrypted_and_survives_a_restart(tmp_path, logins):
    with make(tmp_path) as c:
        r = c.put("/api/cronometer", json={"username": " me@x.it ", "password": "giusta", "totp": ""})
        assert r.json() == {"connected": True, "username": "me@x.it", "demo": False}
        token = c.app.state.app.store.get("cronometer_credentials")
        assert "giusta" not in token and vault.open_("k" * 64, token)["password"] == "giusta"
    with make(tmp_path) as c:
        assert c.get("/api/cronometer").json()["connected"] is True
        assert c.delete("/api/cronometer").json()["connected"] is False
        assert c.app.state.app.store.get("cronometer_credentials") is None


def test_vault_rejects_another_key():
    token = vault.seal("a" * 64, {"password": "x"})
    with pytest.raises(InvalidTag):
        vault.open_("b" * 64, token)


def test_today_works_before_connecting(tmp_path, logins):
    with make(tmp_path) as c:
        assert c.get("/api/today").status_code == 200
