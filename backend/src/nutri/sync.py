"""Mirror Cronometer into the local store and push the outbox back."""

import json
import logging
import threading
from datetime import date, timedelta

from .sources import Source
from .store import Store, now

log = logging.getLogger(__name__)
MAX_ATTEMPTS = 8


class Syncer:
    def __init__(self, store: Store, source: Source):
        self.store = store
        self.source = source
        self._lock = threading.RLock()

    def status(self) -> dict:
        s = self.store.get("sync_status", {})
        s["source"] = self.source.name
        s["pending"] = len(self.store.pending())
        s["failed"] = len(self.store.q("select id from outbox where status='failed'"))
        return s

    def _set(self, **kw) -> None:
        s = self.store.get("sync_status", {})
        s.update(kw)
        self.store.put("sync_status", s)

    def pull_day(self, day: date) -> None:
        diary = self.source.diary(day)
        for f in diary.foods:
            self.store.put_food(f.row())
        self.store.replace_day(day, diary.entries, diary.marked_complete)

    def run(self, today: date, days_back: int | None = None) -> dict:
        """Push pending writes first, so the pull that follows already sees them."""
        with self._lock:
            if not getattr(self.source, "connected", True):
                self._set(last_error=None, connected=False)
                return {"pushed": 0, **self.status()}
            pushed = self.push()
            if days_back is None:
                days_back = 7 if self.store.get("sync_status", {}).get("last_pull") else 90
            start = today - timedelta(days=days_back)
            try:
                self.store.put_weights(self.source.weights(start, today))
                d = start
                while d <= today:
                    self.pull_day(d)
                    d += timedelta(days=1)
                self._set(
                    last_pull=now(),
                    last_error=None,
                    connected=True,
                    last_range=[start.isoformat(), today.isoformat()],
                )
            except Exception as exc:  # upstream API change or network: report, never crash the app
                log.exception("sync failed")
                self._set(last_error=f"{type(exc).__name__}: {exc}"[:300], last_error_at=now())
            return {"pushed": pushed, **self.status()}

    def push(self) -> int:
        with self._lock:
            return self._push()

    def _push(self) -> int:
        if not getattr(self.source, "connected", True):
            return 0  # writes wait in the outbox until an account is connected
        done = 0
        touched: set[date] = set()
        for row in self.store.pending():
            p = json.loads(row["payload"])
            day = date.fromisoformat(p["day"])
            try:
                if row["kind"] == "add_serving":
                    food = self.store.food(p["food_id"])
                    if food is None:
                        raise RuntimeError(f"alimento {p['food_id']} sconosciuto")
                    sid = self.source.add_serving(dict(food), p["grams"], day, p["slot"])
                    if p.get("entry_id") and sid:
                        # the entry stays in the diary until the pull brings Cronometer's copy, and a view
                        # loaded before the push still finds it by its old reference
                        self.store.x(
                            "update diary_entries set serving_id=?, pending=0 where id=? and pending=1",
                            sid,
                            p["entry_id"],
                        )
                        self.store.x(
                            "update outbox set payload=? where id=?",
                            json.dumps({**p, "serving_id": sid}),
                            row["id"],
                        )
                    elif p.get("entry_id"):
                        self.store.x("delete from diary_entries where id=? and pending=1", p["entry_id"])
                elif row["kind"] == "delete_servings":
                    self.source.delete_servings(p["serving_ids"], day)
                elif row["kind"] == "mark_complete":
                    self.source.mark_complete(day, p["complete"])
                self.store.outbox_done(row["id"])
                touched.add(day)
                done += 1
            except Exception as exc:
                log.warning("outbox %s failed: %s", row["id"], exc)
                self.store.outbox_failed(
                    row["id"], f"{type(exc).__name__}: {exc}", row["attempts"] + 1 >= MAX_ATTEMPTS
                )
                self._set(last_error=f"{type(exc).__name__}: {exc}"[:300], last_error_at=now())
        for day in touched:
            try:
                self.pull_day(day)
            except Exception:
                log.exception("re-pull after push failed")
        return done
