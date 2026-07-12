"""SQLite schema, connections, and migrations."""
from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS course_types (
  id            INTEGER PRIMARY KEY,
  name          TEXT NOT NULL UNIQUE,
  total_days    INTEGER NOT NULL,
  anapana_days  INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS courses (
  id             INTEGER PRIMARY KEY,
  course_type_id INTEGER NOT NULL REFERENCES course_types(id),
  start_date     TEXT NOT NULL,
  note           TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS schedule_events (
  id             INTEGER PRIMARY KEY,
  course_type_id INTEGER REFERENCES course_types(id),
  day_no         INTEGER,
  time_local     TEXT NOT NULL,
  repeats        INTEGER NOT NULL CHECK (repeats BETWEEN 1 AND 32),
  gap_seconds    INTEGER,
  track          TEXT
);

CREATE TABLE IF NOT EXISTS settings (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS state (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS play_log (
  id        INTEGER PRIMARY KEY,
  ts_utc    TEXT NOT NULL,
  kind      TEXT NOT NULL,
  file      TEXT NOT NULL,
  repeats   INTEGER NOT NULL,
  result    TEXT NOT NULL,
  detail    TEXT NOT NULL DEFAULT ''
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_sched_unique
  ON schedule_events (COALESCE(course_type_id, -1), COALESCE(day_no, -1), time_local);
CREATE INDEX IF NOT EXISTS idx_playlog_ts ON play_log (ts_utc);
"""


def connect(db_path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def init_db(conn: sqlite3.Connection, seed_sql: str | None = None) -> None:
    """Create schema if needed; apply seed once if schedule is empty."""
    conn.executescript(SCHEMA)
    cur = conn.execute("SELECT value FROM state WHERE key='schema_version'")
    row = cur.fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO state (key, value) VALUES ('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )
    elif int(row["value"]) != SCHEMA_VERSION:
        raise RuntimeError(
            f"DB schema version {row['value']} != code {SCHEMA_VERSION}; "
            "run gongctl migrate-db"
        )
    if seed_sql:
        n = conn.execute("SELECT COUNT(*) AS n FROM course_types").fetchone()["n"]
        if n == 0:
            conn.executescript(seed_sql)
    conn.commit()
