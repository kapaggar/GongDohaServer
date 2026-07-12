"""Scheduler firing semantics against the real seeded schedule.

Seed facts used here (from db/gong.sql): 10 Day = type 1, total_days 11;
explicit rows exist for days 0, 1, 4, 10; other days resolve to the default
pattern; day 1 has 04:00 x16 and 04:20 x12; default pattern has 14:10 x1
which day 1 does not.
"""
from __future__ import annotations

from gong_ng import model
from gong_ng.model import Settings
from gong_ng.scheduler import Scheduler, upcoming_occurrences


def make_sched(config, fake_clock, rec_player, poke):
    return Scheduler(config, fake_clock, rec_player, poke,
                     db_path=config.db_path)


def add_ten_day(conn, start="2026-07-01"):
    return model.add_course(conn, 1, start)


def test_fires_due_event_once(config, conn, fake_clock, rec_player, poke):
    add_ten_day(conn)  # day 1 == 2026-07-02
    sched = make_sched(config, fake_clock, rec_player, poke)
    now = fake_clock.set("2026-07-02 04:00:05")
    sched.tick(conn, now)
    gongs = [j for j in rec_player.jobs if j.kind == "gong"]
    assert len(gongs) == 1
    assert gongs[0].repeats == 16
    assert gongs[0].file.name == "ting.mp3"
    # same instant again (e.g. poke) -> no double fire
    sched.tick(conn, now)
    assert len([j for j in rec_player.jobs if j.kind == "gong"]) == 1
    # restart (fresh scheduler object) -> guard persisted in DB
    sched2 = make_sched(config, fake_clock, rec_player, poke)
    sched2.tick(conn, now)
    assert len([j for j in rec_player.jobs if j.kind == "gong"]) == 1


def test_late_within_grace_fires(config, conn, fake_clock, rec_player, poke):
    add_ten_day(conn)
    sched = make_sched(config, fake_clock, rec_player, poke)
    sched.tick(conn, fake_clock.set("2026-07-02 04:01:30"))  # 90s late
    assert any(j.repeats == 16 for j in rec_player.jobs)


def test_beyond_grace_is_missed_not_fired(config, conn, fake_clock,
                                          rec_player, poke):
    add_ten_day(conn)
    sched = make_sched(config, fake_clock, rec_player, poke)
    sched.tick(conn, fake_clock.set("2026-07-02 04:10:00"))  # 10 min late
    assert not any(j.repeats == 16 for j in rec_player.jobs)
    missed = [r for r in model.recent_plays(conn) if r["result"] == "missed"]
    assert missed, "expected a 'missed' play_log row"


def test_never_fires_early_and_reports_next_deadline(
        config, conn, fake_clock, rec_player, poke):
    add_ten_day(conn)
    sched = make_sched(config, fake_clock, rec_player, poke)
    next_fire = sched.tick(conn, fake_clock.set("2026-07-02 03:59:00"))
    assert rec_player.jobs == []
    assert next_fire is not None
    assert f"{next_fire:%H:%M}" == "04:00"


def test_default_day_fallback(config, conn, fake_clock, rec_player, poke):
    """Day 5 has no explicit rows -> default pattern (incl. 14:10 x1)."""
    add_ten_day(conn)  # day 5 == 2026-07-06
    occs = upcoming_occurrences(conn, fake_clock, fake_clock.set(
        "2026-07-06 00:00:00").date())
    times = {f"{o.fire_at:%H:%M}" for o in occs
             if o.kind == "gong" and o.local_date.day == 6}
    assert "14:10" in times  # only in the default pattern
    assert "04:00" in times


def test_explicit_day_overrides_default(config, conn, fake_clock,
                                        rec_player, poke):
    """Day 1 has explicit rows; the default-only 14:10 must NOT appear."""
    add_ten_day(conn)
    occs = upcoming_occurrences(conn, fake_clock, fake_clock.set(
        "2026-07-02 00:00:00").date())
    times = {f"{o.fire_at:%H:%M}" for o in occs
             if o.kind == "gong" and o.local_date.day == 2}
    assert "14:10" not in times
    assert "13:40" in times  # day-1-specific


def test_no_course_uses_no_course_set(config, conn, fake_clock,
                                      rec_player, poke):
    occs = upcoming_occurrences(conn, fake_clock, fake_clock.set(
        "2026-07-02 00:00:00").date())
    gong_times = {f"{o.fire_at:%H:%M}" for o in occs if o.kind == "gong"}
    assert "04:00" in gong_times and "21:00" in gong_times
    assert all(o.ctx is None for o in occs)


def test_course_found_after_power_cut_mid_course(config, conn, fake_clock,
                                                 rec_player, poke):
    """Legacy bug #1: course started while powered off must still be active."""
    add_ten_day(conn, "2026-07-01")
    # First boot ever happens on day 6 — window match, not start-day match.
    ctx = model.active_course(conn, fake_clock.set(
        "2026-07-07 10:00:00").date())
    assert ctx is not None and ctx.day == 6


def test_doha_fires_with_correct_slot_file(config, conn, fake_clock,
                                           rec_player, poke):
    add_ten_day(conn)  # 2026-07-05 is day 4 -> slot 4 (first vipassana day)
    sched = make_sched(config, fake_clock, rec_player, poke)
    sched.tick(conn, fake_clock.set("2026-07-05 06:37:10"))
    dohas = [j for j in rec_player.jobs if j.kind == "doha"]
    assert len(dohas) == 1
    assert dohas[0].file.name.startswith("D04_")


def test_doha_skipped_on_day_zero(config, conn, fake_clock, rec_player, poke):
    add_ten_day(conn)
    settings = Settings(conn)
    settings.set("no_course_doha", "off")  # isolate the in-course rule
    sched = make_sched(config, fake_clock, rec_player, poke)
    sched.tick(conn, fake_clock.set("2026-07-01 06:37:10"))
    assert not [j for j in rec_player.jobs if j.kind == "doha"]


def test_disabled_master_suppresses_everything(config, conn, fake_clock,
                                               rec_player, poke):
    add_ten_day(conn)
    Settings(conn).set("enabled", "0")
    sched = make_sched(config, fake_clock, rec_player, poke)
    sched.tick(conn, fake_clock.set("2026-07-02 04:00:05"))
    assert rec_player.jobs == []


def test_clock_invalid_suppresses_fires(config, conn, fake_clock,
                                        rec_player, poke):
    add_ten_day(conn)
    model.state_set(conn, "clock_invalid", "1")
    sched = make_sched(config, fake_clock, rec_player, poke)
    assert sched.tick(conn, fake_clock.set("2026-07-02 04:00:05")) is None
    assert rec_player.jobs == []


def test_event_track_override(config, conn, fake_clock, rec_player, poke):
    add_ten_day(conn)
    model.add_event(conn, 1, 1, "05:55", 2, track="drum")
    sched = make_sched(config, fake_clock, rec_player, poke)
    sched.tick(conn, fake_clock.set("2026-07-02 05:55:01"))
    assert any(j.file.name == "drum.mp3" for j in rec_player.jobs)
