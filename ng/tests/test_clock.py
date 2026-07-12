from datetime import date, datetime, timedelta

from gong_ng import clock as clockmod
from gong_ng.clock import Clock, current_day


def test_current_day_is_calendar_based():
    assert current_day(date(2026, 6, 30), date(2026, 7, 10)) == 10
    assert current_day(date(2026, 12, 30), date(2027, 1, 2)) == 3
    assert current_day(date(2026, 7, 10), date(2026, 7, 10)) == 0


def test_day_count_across_dst_change():
    # Legacy /86400 math was off by one across DST; calendar math is not.
    assert current_day(date(2026, 3, 28), date(2026, 3, 30)) == 2  # 47h elapsed


def test_ist_materialize_plain():
    clk = Clock("Asia/Kolkata")
    dt = clk.materialize(date(2026, 7, 5), "04:00")
    assert (dt.hour, dt.minute) == (4, 0)
    assert dt.utcoffset() == timedelta(hours=5, minutes=30)


def test_spring_forward_gap_fires_after_gap():
    # Europe/London 2026-03-29: 01:00-02:00 does not exist.
    clk = Clock("Europe/London")
    dt = clk.materialize(date(2026, 3, 29), "01:30")
    assert dt.hour == 2 and dt.utcoffset() == timedelta(hours=1)


def test_fall_back_ambiguity_uses_first_occurrence():
    # Europe/London 2026-10-25: 01:30 happens twice; we take the BST one.
    clk = Clock("Europe/London")
    dt = clk.materialize(date(2026, 10, 25), "01:30")
    assert dt.utcoffset() == timedelta(hours=1)


def test_clock_backwards_detection_and_recovery(conn):
    clk = Clock("Asia/Kolkata")
    t0 = datetime(2026, 7, 10, 12, 0, tzinfo=clk.tz)
    clockmod.touch_last_good(conn, t0)
    # reboot with the clock 3 days behind -> untrusted
    assert clockmod.check_clock_on_start(conn, t0 - timedelta(days=3)) is False
    assert clockmod.clock_invalid(conn)
    # while invalid, last_good must not advance
    clockmod.touch_last_good(conn, t0 - timedelta(days=3))
    assert clockmod.clock_invalid(conn)
    # NTP steps the clock forward past last_good -> trusted again
    clockmod.touch_last_good(conn, t0 + timedelta(minutes=1))
    assert not clockmod.clock_invalid(conn)


def test_staff_confirm_clears_invalid(conn):
    clk = Clock("Asia/Kolkata")
    t0 = datetime(2026, 7, 10, 12, 0, tzinfo=clk.tz)
    clockmod.touch_last_good(conn, t0)
    clockmod.check_clock_on_start(conn, t0 - timedelta(days=3))
    assert clockmod.clock_invalid(conn)
    clockmod.confirm_clock(conn, t0 - timedelta(days=3))
    assert not clockmod.clock_invalid(conn)
