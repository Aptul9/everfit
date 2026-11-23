"""SQLite persistence.

Cronometer stays the record for what was eaten and weighed; the tables mirroring
it are a cache rebuilt by the sync. What lives only here is what Cronometer
cannot hold: settings, the active phase, plans, check-in decisions, the outbox
of pending writes, and the chat.
"""

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import UTC, date, datetime
from pathlib import Path

SCHEMA = """
create table if not exists kv (key text primary key, value text not null);
create table if not exists weights (day text primary key, kg real not null);
create table if not exists diary_days (
    day text primary key, kcal real, protein real, carbs real, fat real,
    marked_complete integer, synced_at text);
create table if not exists diary_entries (
    id integer primary key autoincrement, day text not null, slot text not null,
    food_id text not null, grams real not null, serving_id text, pending integer default 0);
create index if not exists diary_entries_day on diary_entries(day);
create table if not exists foods (
    id text primary key, name text not null, kcal real, protein real, carbs real, fat real,
    unit_g real, unit_name text, step_g real, role_override text,
    cr_food_id integer, measure_id integer, translation_id integer, updated_at text);
create table if not exists plans (day text primary key, data text not null, updated_at text);
create table if not exists checkins (
    week_end text primary key, result text not null, decision text, decided_kcal real,
    decided_at text);
create table if not exists phase_history (
    id integer primary key autoincrement, started text, ended text, phase text not null);
create table if not exists template_pins (key text primary key, mode text not null);
create table if not exists outbox (
    id integer primary key autoincrement, created text, kind text not null, payload text not null,
    status text not null default 'pending', attempts integer default 0, error text);
create table if not exists proposals (
    id integer primary key autoincrement, created text, kind text not null, payload text not null,
    status text not null default 'open');
create table if not exists chat (
    id integer primary key autoincrement, created text, role text not null, content text not null);
create table if not exists push_subs (endpoint text primary key, sub text not null);
"""


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db.execute("pragma journal_mode=wal")
        self._db.executescript(SCHEMA)
        self._lock = threading.RLock()

    @contextmanager
    def tx(self):
        with self._lock:
            self._db.execute("begin")
            try:
                yield self._db
                self._db.execute("commit")
            except BaseException:
                self._db.execute("rollback")
                raise

    def q(self, sql: str, *args) -> list[sqlite3.Row]:
        with self._lock:
            return self._db.execute(sql, args).fetchall()

    def x(self, sql: str, *args) -> int:
        with self._lock:
            return self._db.execute(sql, args).lastrowid

    # key-value

    def get(self, key: str, default=None):
        rows = self.q("select value from kv where key=?", key)
        return json.loads(rows[0]["value"]) if rows else default

    def put(self, key: str, value) -> None:
        self.x(
            "insert into kv(key,value) values(?,?) on conflict(key) do update set value=excluded.value",
            key,
            json.dumps(value, default=str),
        )

    # mirrored data

    def weights(self) -> dict[date, float]:
        return {date.fromisoformat(r["day"]): r["kg"] for r in self.q("select day, kg from weights")}

    def put_weights(self, values: dict[date, float]) -> None:
        with self.tx() as db:
            for d, kg in values.items():
                db.execute(
                    "insert into weights(day,kg) values(?,?) on conflict(day) do update set kg=excluded.kg",
                    (d.isoformat(), kg),
                )

    def days(self, start: date | None = None) -> list[sqlite3.Row]:
        if start:
            return self.q("select * from diary_days where day>=? order by day", start.isoformat())
        return self.q("select * from diary_days order by day")

    def entries(self, start: date, end: date | None = None) -> list[sqlite3.Row]:
        end = end or start
        return self.q(
            "select e.*, f.name, f.kcal as f_kcal, f.protein as f_protein, f.carbs as f_carbs, f.fat as f_fat "
            "from diary_entries e left join foods f on f.id=e.food_id where e.day between ? and ? "
            "order by e.day, e.slot, e.id",
            start.isoformat(),
            end.isoformat(),
        )

    def replace_day(self, day: date, entries: list[dict], marked_complete: bool | None) -> None:
        """Swap in Cronometer's view of a day, keeping app entries still waiting in the outbox."""
        d = day.isoformat()
        with self.tx() as db:
            db.execute("delete from diary_entries where day=? and pending=0", (d,))
            for e in entries:
                db.execute(
                    "insert into diary_entries(day,slot,food_id,grams,serving_id) values(?,?,?,?,?)",
                    (d, e["slot"], e["food_id"], e["grams"], e.get("serving_id")),
                )
            self._recount(db, d, marked_complete, keep_mark=False)

    def add_pending_entry(self, day: date, slot: str, food_id: str, grams: float) -> int:
        with self.tx() as db:
            cur = db.execute(
                "insert into diary_entries(day,slot,food_id,grams,pending) values(?,?,?,?,1)",
                (day.isoformat(), slot, food_id, grams),
            )
            self._recount(db, day.isoformat(), None, keep_mark=True)
            return cur.lastrowid

    def delete_entry(self, entry_id: int) -> None:
        with self.tx() as db:
            row = db.execute("select day from diary_entries where id=?", (entry_id,)).fetchone()
            if row is None:
                return
            db.execute("delete from diary_entries where id=?", (entry_id,))
            self._recount(db, row["day"], None, keep_mark=True)

    def set_marked(self, day: date, value: bool | None) -> None:
        with self.tx() as db:
            self._recount(db, day.isoformat(), value, keep_mark=False)

    def _recount(self, db, d: str, marked: bool | None, keep_mark: bool) -> None:
        row = db.execute(
            "select coalesce(sum(e.grams*f.kcal/100),0) k, coalesce(sum(e.grams*f.protein/100),0) p, "
            "coalesce(sum(e.grams*f.carbs/100),0) c, coalesce(sum(e.grams*f.fat/100),0) f "
            "from diary_entries e join foods f on f.id=e.food_id where e.day=?",
            (d,),
        ).fetchone()
        if keep_mark:
            old = db.execute("select marked_complete from diary_days where day=?", (d,)).fetchone()
            marked = None if old is None or old[0] is None else bool(old[0])
        db.execute(
            "insert into diary_days(day,kcal,protein,carbs,fat,marked_complete,synced_at) values(?,?,?,?,?,?,?) "
            "on conflict(day) do update set kcal=excluded.kcal, protein=excluded.protein, "
            "carbs=excluded.carbs, fat=excluded.fat, marked_complete=excluded.marked_complete, "
            "synced_at=excluded.synced_at",
            (d, row["k"], row["p"], row["c"], row["f"], None if marked is None else int(marked), now()),
        )

    # foods

    def food(self, food_id: str) -> sqlite3.Row | None:
        rows = self.q("select * from foods where id=?", food_id)
        return rows[0] if rows else None

    def put_food(self, f: dict) -> None:
        cols = [
            "id",
            "name",
            "kcal",
            "protein",
            "carbs",
            "fat",
            "unit_g",
            "unit_name",
            "cr_food_id",
            "measure_id",
            "translation_id",
        ]
        vals = [f.get(c) for c in cols]
        sets = ", ".join(f"{c}=excluded.{c}" for c in cols[1:])
        self.x(
            f"insert into foods({','.join(cols)},updated_at) values({','.join('?' * len(cols))},?) "
            f"on conflict(id) do update set {sets}, updated_at=excluded.updated_at",
            *vals,
            now(),
        )

    def update_food_prefs(self, food_id: str, **prefs) -> None:
        allowed = {"unit_g", "unit_name", "step_g", "role_override"}
        for k, v in prefs.items():
            if k in allowed:
                self.x(f"update foods set {k}=? where id=?", v, food_id)

    # json documents

    def plan(self, day: date) -> dict | None:
        rows = self.q("select data from plans where day=?", day.isoformat())
        return json.loads(rows[0]["data"]) if rows else None

    def put_plan(self, day: date, data: dict) -> None:
        self.x(
            "insert into plans(day,data,updated_at) values(?,?,?) on conflict(day) do update set "
            "data=excluded.data, updated_at=excluded.updated_at",
            day.isoformat(),
            json.dumps(data),
            now(),
        )

    def checkins(self) -> list[sqlite3.Row]:
        return self.q("select * from checkins order by week_end")

    def put_checkin(self, week_end: date, result: dict) -> None:
        self.x(
            "insert into checkins(week_end,result) values(?,?) on conflict(week_end) do update set "
            "result=excluded.result where checkins.decision is null",
            week_end.isoformat(),
            json.dumps(result, default=str),
        )

    def decide_checkin(self, week_end: date, decision: str, kcal: float | None) -> None:
        self.x(
            "update checkins set decision=?, decided_kcal=?, decided_at=? where week_end=?",
            decision,
            kcal,
            now(),
            week_end.isoformat(),
        )

    # outbox

    def enqueue(self, kind: str, payload: dict) -> int:
        return self.x(
            "insert into outbox(created,kind,payload) values(?,?,?)", now(), kind, json.dumps(payload)
        )

    def pending(self) -> list[sqlite3.Row]:
        return self.q("select * from outbox where status='pending' order by id")

    def outbox_done(self, oid: int) -> None:
        self.x("update outbox set status='done' where id=?", oid)

    def outbox_failed(self, oid: int, error: str, give_up: bool) -> None:
        self.x(
            "update outbox set attempts=attempts+1, error=?, status=? where id=?",
            error[:500],
            "failed" if give_up else "pending",
            oid,
        )
