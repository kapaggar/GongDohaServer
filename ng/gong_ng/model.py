"""Typed access to settings, courses, schedule, play log, and daemon state."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

SETTINGS_DEFAULTS: dict[str, str] = {
    "enabled": "1",
    "gong_enabled": "1",
    "doha_enabled": "1",
    "relay_enabled": "0",
    "gong_track": "ting",
    "gong_volume": "90",
    "gong_gap_seconds": "4",
    "doha_time": "06:37",
    "doha_volume": "75",
    "doha_strategy": "legacy_modular",
    "no_course_doha": "random",
    "active_course_id": "",
    "admin_pin_hash": "",
}

EDITABLE_SETTINGS = set(SETTINGS_DEFAULTS) - {"admin_pin_hash", "active_course_id"}


class Settings:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def get(self, key: str) -> str:
        row = self.conn.execute(
            "SELECT value FROM settings WHERE key=?", (key,)
        ).fetchone()
        if row is not None:
            return row["value"]
        return SETTINGS_DEFAULTS[key]

    def get_int(self, key: str) -> int:
        return int(self.get(key))

    def get_bool(self, key: str) -> bool:
        return self.get(key) == "1"

    def set(self, key: str, value: str) -> None:
        if key not in SETTINGS_DEFAULTS:
            raise KeyError(f"unknown setting {key!r}")
        self.conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, str(value)),
        )
        self.conn.commit()

    def as_dict(self) -> dict[str, str]:
        return {k: self.get(k) for k in SETTINGS_DEFAULTS if k != "admin_pin_hash"}


# ---------------------------------------------------------------- state

def state_get(conn, key: str) -> str | None:
    row = conn.execute("SELECT value FROM state WHERE key=?", (key,)).fetchone()
    return row["value"] if row else None


def state_set(conn, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO state (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )
    conn.commit()


def state_del(conn, key: str) -> None:
    conn.execute("DELETE FROM state WHERE key=?", (key,))
    conn.commit()


def mark_fired(conn, event_key: str, local_date: date) -> None:
    state_set(conn, f"fired:{event_key}:{local_date.isoformat()}",
              datetime.now(timezone.utc).isoformat())


def was_fired(conn, event_key: str, local_date: date) -> bool:
    return state_get(conn, f"fired:{event_key}:{local_date.isoformat()}") is not None


def prune_fired(conn, today: date, keep_days: int = 2) -> None:
    cutoff = (today - timedelta(days=keep_days)).isoformat()
    conn.execute(
        "DELETE FROM state WHERE key LIKE 'fired:%' AND substr(key, -10) < ?",
        (cutoff,),
    )
    conn.commit()


# ---------------------------------------------------------------- courses

@dataclass(frozen=True)
class CourseCtx:
    """The active course, resolved for a given local date."""
    course_id: int
    type_id: int
    type_name: str
    start_date: date
    total_days: int
    anapana_days: int
    day: int  # current_day: 0 = arrival day


def active_course(conn, today: date) -> CourseCtx | None:
    """Design §5.2 — match the course *window*, not just the start day."""
    rows = conn.execute(
        "SELECT c.id, c.course_type_id, c.start_date, ct.name, ct.total_days,"
        "       ct.anapana_days"
        "  FROM courses c JOIN course_types ct ON ct.id = c.course_type_id"
    ).fetchall()
    candidates = []
    for r in rows:
        start = date.fromisoformat(r["start_date"])
        if start <= today <= start + timedelta(days=r["total_days"]):
            candidates.append((start, r))
    if not candidates:
        return None
    settings = Settings(conn)
    pinned = settings.get("active_course_id")
    chosen = None
    if pinned:
        for start, r in candidates:
            if str(r["id"]) == pinned:
                chosen = (start, r)
                break
    if chosen is None:
        chosen = max(candidates, key=lambda c: c[0])  # most recent start wins
        settings.set("active_course_id", str(chosen[1]["id"]))
    start, r = chosen
    return CourseCtx(
        course_id=r["id"], type_id=r["course_type_id"], type_name=r["name"],
        start_date=start, total_days=r["total_days"],
        anapana_days=r["anapana_days"], day=(today - start).days,
    )


def list_course_types(conn):
    return conn.execute("SELECT * FROM course_types ORDER BY id").fetchall()


def list_courses(conn):
    return conn.execute(
        "SELECT c.*, ct.name AS type_name, ct.total_days"
        "  FROM courses c JOIN course_types ct ON ct.id = c.course_type_id"
        " ORDER BY c.start_date DESC"
    ).fetchall()


def add_course(conn, course_type_id: int, start_date: str, note: str = "") -> int:
    date.fromisoformat(start_date)  # validates
    cur = conn.execute(
        "INSERT INTO courses (course_type_id, start_date, note) VALUES (?, ?, ?)",
        (course_type_id, start_date, note),
    )
    conn.commit()
    return cur.lastrowid


def delete_course(conn, course_id: int) -> None:
    conn.execute("DELETE FROM courses WHERE id=?", (course_id,))
    settings = Settings(conn)
    if settings.get("active_course_id") == str(course_id):
        settings.set("active_course_id", "")
    conn.commit()


# ---------------------------------------------------------------- schedule

def list_events(conn, course_type_id: int | None, day_no: int | None):
    return conn.execute(
        "SELECT * FROM schedule_events"
        " WHERE course_type_id IS ? AND day_no IS ? ORDER BY time_local",
        (course_type_id, day_no),
    ).fetchall()


def days_with_events(conn, course_type_id: int | None) -> list[int | None]:
    rows = conn.execute(
        "SELECT DISTINCT day_no FROM schedule_events WHERE course_type_id IS ?"
        " ORDER BY day_no",
        (course_type_id,),
    ).fetchall()
    return [r["day_no"] for r in rows]


def events_for(conn, ctx: CourseCtx | None):
    """Effective rows for the current context (design §3.1):
    explicit day -> default pattern (day_no NULL) -> no-course set."""
    if ctx is None:
        return list_events(conn, None, None)
    rows = list_events(conn, ctx.type_id, ctx.day)
    if not rows:
        rows = list_events(conn, ctx.type_id, None)
    return rows


def add_event(conn, course_type_id: int | None, day_no: int | None,
              time_local: str, repeats: int,
              gap_seconds: int | None = None, track: str | None = None) -> int:
    datetime.strptime(time_local, "%H:%M")  # validates
    cur = conn.execute(
        "INSERT INTO schedule_events"
        " (course_type_id, day_no, time_local, repeats, gap_seconds, track)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (course_type_id, day_no, time_local, int(repeats), gap_seconds, track),
    )
    conn.commit()
    return cur.lastrowid


def delete_event(conn, event_id: int) -> None:
    conn.execute("DELETE FROM schedule_events WHERE id=?", (event_id,))
    conn.commit()


def copy_day(conn, course_type_id: int | None, from_day: int | None,
             to_day: int | None) -> int:
    rows = list_events(conn, course_type_id, from_day)
    n = 0
    for r in rows:
        try:
            add_event(conn, course_type_id, to_day, r["time_local"],
                      r["repeats"], r["gap_seconds"], r["track"])
            n += 1
        except sqlite3.IntegrityError:
            pass  # destination already has this time
    return n


# ---------------------------------------------------------------- play log

def log_play(conn, kind: str, file: str, repeats: int, result: str,
             detail: str = "") -> None:
    conn.execute(
        "INSERT INTO play_log (ts_utc, kind, file, repeats, result, detail)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (datetime.now(timezone.utc).isoformat(timespec="seconds"),
         kind, file, repeats, result, detail),
    )
    conn.commit()


def recent_plays(conn, n: int = 50):
    return conn.execute(
        "SELECT * FROM play_log ORDER BY id DESC LIMIT ?", (n,)
    ).fetchall()
