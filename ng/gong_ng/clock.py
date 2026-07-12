"""Wall-clock/timezone handling and clock-sanity state (design §5.1, §6).

All schedule times are wall-clock local. Day arithmetic is calendar-date
subtraction, never seconds/86400.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from . import model

log = logging.getLogger(__name__)

LAST_GOOD_KEY = "last_good_time"
CLOCK_INVALID_KEY = "clock_invalid"
BACKWARDS_TOLERANCE = timedelta(minutes=10)
TOUCH_INTERVAL = timedelta(minutes=5)


class Clock:
    def __init__(self, tz_name: str):
        self.tz = ZoneInfo(tz_name)

    def now(self) -> datetime:
        return datetime.now(self.tz)

    def today(self) -> date:
        return self.now().date()

    def materialize(self, day: date, hhmm: str) -> datetime:
        """Local datetime for wall time `hhmm` on `day`.

        Spring-forward gap: returns the first valid instant after the gap.
        Fall-back ambiguity: returns the first occurrence (fold=0).
        """
        t = time.fromisoformat(hhmm)
        dt = datetime.combine(day, t, tzinfo=self.tz)
        roundtrip = dt.astimezone(timezone.utc).astimezone(self.tz)
        return roundtrip if roundtrip != dt else dt


def current_day(zero_day: date, today: date) -> int:
    return (today - zero_day).days


# ------------------------------------------------------------ clock sanity

def check_clock_on_start(conn, now: datetime) -> bool:
    """Returns True if the clock is trusted. Sets clock_invalid if the clock
    appears to have gone backwards since the daemon last saw it."""
    last_good = model.state_get(conn, LAST_GOOD_KEY)
    if last_good is not None:
        lg = datetime.fromisoformat(last_good)
        if now < lg - BACKWARDS_TOLERANCE:
            model.state_set(conn, CLOCK_INVALID_KEY, "1")
            log.warning("clock went backwards (now=%s, last_good=%s) — "
                        "automatic playback suppressed", now, lg)
    return not clock_invalid(conn)


def clock_invalid(conn) -> bool:
    return model.state_get(conn, CLOCK_INVALID_KEY) == "1"


def confirm_clock(conn, now: datetime) -> None:
    """Staff confirmed or set the time; trust it from here."""
    model.state_del(conn, CLOCK_INVALID_KEY)
    model.state_set(conn, LAST_GOOD_KEY, now.isoformat())


def touch_last_good(conn, now: datetime) -> None:
    """Advance last_good_time; also auto-clears invalid mode when the clock
    catches up past the last known-good instant (e.g. NTP step)."""
    last_good = model.state_get(conn, LAST_GOOD_KEY)
    if clock_invalid(conn):
        if last_good is None or now >= datetime.fromisoformat(last_good):
            log.info("clock recovered past last_good_time — trusting it again")
            model.state_del(conn, CLOCK_INVALID_KEY)
        else:
            return  # do not advance last_good while untrusted
    model.state_set(conn, LAST_GOOD_KEY, now.isoformat())
