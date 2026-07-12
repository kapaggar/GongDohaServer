"""The checked-in seed must stay in lockstep with the legacy dump and the
converter (design §7)."""
import importlib.util
import sqlite3
from pathlib import Path

import pytest

NG = Path(__file__).resolve().parents[1]
REPO = NG.parent
DUMP = REPO / "db" / "gong.sql"

spec = importlib.util.spec_from_file_location(
    "convert_legacy_seed", NG / "tools" / "convert_legacy_seed.py")
conv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(conv)


@pytest.fixture(scope="module")
def converted():
    return conv.convert([DUMP])


def test_counts(converted):
    course_types, events = converted
    assert len(course_types) == 12
    assert len(events) == 335


def test_hhmm_conversion():
    assert conv.hhmm_to_time(632) == "06:32"
    assert conv.hhmm_to_time(2100) == "21:00"
    assert conv.hhmm_to_time(400) == "04:00"
    with pytest.raises(ValueError):
        conv.hhmm_to_time(9999)


def test_day2_moved_to_default_pattern(converted):
    _, events = converted
    # no literal day-2 rows survive; every type with day-2 rows has defaults
    assert not any(day == 2 for _, day, _, _ in events)
    ten_day_default = [(t, r) for ct, day, t, r in events
                       if ct == 1 and day is None]
    assert ("04:00", 16) in ten_day_default
    assert ("14:10", 1) in ten_day_default  # legacy row (360,1,2,1410,1)


def test_no_course_set_mapped_to_null_type(converted):
    _, events = converted
    nc = [(t, r) for ct, day, t, r in events if ct is None]
    assert ("04:00", 16) in nc and ("21:00", 3) in nc
    assert all(day is None for ct, day, _, _ in events if ct is None)


def test_checked_in_seed_matches_converter(converted):
    course_types, events = converted
    assert (NG / "seed" / "seed.sql").read_text() == conv.render_seed(
        course_types, events), (
        "seed/seed.sql drifted — re-run ng/tools/convert_legacy_seed.py")


def test_seed_applies_cleanly_and_respects_unique_index(converted):
    from gong_ng import db
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(db.SCHEMA)
    conn.executescript((NG / "seed" / "seed.sql").read_text())
    n = conn.execute("SELECT COUNT(*) FROM schedule_events").fetchone()[0]
    assert n == 335
