"""Second-accurate event scheduler (design §5).

The run() loop is a thin shell around tick(), which is pure enough to unit
test with a fake "now": it materializes today's + tomorrow's events, fires
what is due (within the grace window), and returns the next deadline.

Guarantees:
  - never fires early;
  - never fires twice for one (event, local date) — guard persisted in state;
  - fires late only within fire_grace_seconds, else logs 'missed';
  - suppresses automatic playback entirely while the clock is untrusted.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from . import clock as clockmod
from . import db, doha, model
from .config import Config
from .model import CourseCtx, Settings
from .player import Player, PlayJob

log = logging.getLogger(__name__)

MAX_WAIT = 30.0  # seconds; also how fast wall-clock jumps are noticed


@dataclass(frozen=True)
class Occurrence:
    key: str            # 'g<schedule_event_id>' or 'doha'
    kind: str           # 'gong' | 'doha'
    fire_at: datetime
    local_date: date
    repeats: int = 1
    gap_seconds: int | None = None
    track: str | None = None
    ctx: CourseCtx | None = None


def upcoming_occurrences(conn, clk: clockmod.Clock, today: date,
                         days: int = 2) -> list[Occurrence]:
    """Materialize not-yet-fired occurrences for `today` and the next
    `days - 1` dates, sorted by fire time (design §3.1 + §5.3)."""
    out: list[Occurrence] = []
    for offset in range(days):
        day = today + timedelta(days=offset)
        ctx = model.active_course(conn, day)
        for row in model.events_for(conn, ctx):
            occ = Occurrence(
                key=f"g{row['id']}", kind="gong",
                fire_at=clk.materialize(day, row["time_local"]),
                local_date=day, repeats=row["repeats"],
                gap_seconds=row["gap_seconds"], track=row["track"], ctx=ctx,
            )
            if not model.was_fired(conn, occ.key, day):
                out.append(occ)
        settings = Settings(conn)
        occ = Occurrence(
            key="doha", kind="doha",
            fire_at=clk.materialize(day, settings.get("doha_time")),
            local_date=day, ctx=ctx,
        )
        if not model.was_fired(conn, occ.key, day):
            out.append(occ)
    out.sort(key=lambda o: o.fire_at)
    return out


class Scheduler(threading.Thread):
    def __init__(self, config: Config, clk: clockmod.Clock, player: Player,
                 poke: threading.Event, db_path: Path | None = None):
        super().__init__(name="scheduler", daemon=True)
        self.config = config
        self.clock = clk
        self.player = player
        self.poke = poke
        self.db_path = db_path or config.db_path
        self._shutdown = threading.Event()
        self._last_touch: datetime | None = None
        self._last_prune: date | None = None
        self._last_enabled: dict[str, bool] = {}

    def shutdown(self) -> None:
        self._shutdown.set()
        self.poke.set()

    # ------------------------------------------------------------ loop

    def run(self) -> None:
        conn = db.connect(self.db_path)
        clockmod.check_clock_on_start(conn, self.clock.now())
        log.info("scheduler started (tz=%s, grace=%ds)",
                 self.config.time.timezone, self.config.time.fire_grace_seconds)
        while not self._shutdown.is_set():
            now = self.clock.now()
            try:
                next_fire = self.tick(conn, now)
            except Exception:
                log.exception("scheduler tick failed")
                next_fire = None
            if next_fire is None:
                timeout = MAX_WAIT
            else:
                timeout = min(MAX_WAIT,
                              max(0.05, (next_fire - now).total_seconds()))
            self.poke.wait(timeout)
            self.poke.clear()
        conn.close()

    # ------------------------------------------------------------ tick

    def tick(self, conn, now: datetime) -> datetime | None:
        """Fire everything due at `now`; return the next deadline (or None)."""
        if clockmod.clock_invalid(conn):
            return None  # suppressed until staff confirm the time (§6)
        if self._last_touch is None or now - self._last_touch >= clockmod.TOUCH_INTERVAL:
            clockmod.touch_last_good(conn, now)
            self._last_touch = now
        today = now.date()
        if self._last_prune != today:
            model.prune_fired(conn, today)
            self._last_prune = today

        grace = timedelta(seconds=self.config.time.fire_grace_seconds)
        pending: list[Occurrence] = []
        for occ in self.upcoming(conn, today):
            if occ.fire_at > now:
                pending.append(occ)
                continue
            model.mark_fired(conn, occ.key, occ.local_date)
            if now - occ.fire_at > grace:
                log.warning("missed %s scheduled for %s (now %s)",
                            occ.key, occ.fire_at, now)
                model.log_play(conn, occ.kind, "-", occ.repeats, "missed",
                               f"scheduled {occ.fire_at.isoformat()}")
            else:
                self.dispatch(conn, occ)
        return min((o.fire_at for o in pending), default=None)

    def upcoming(self, conn, today: date) -> list[Occurrence]:
        return upcoming_occurrences(conn, self.clock, today)

    # ------------------------------------------------------------ dispatch

    def _enabled(self, settings: Settings, which: str) -> bool:
        on = settings.get_bool("enabled") and settings.get_bool(which)
        if self._last_enabled.get(which) != on:
            log.info("%s is now %s", which, "enabled" if on else "disabled")
            self._last_enabled[which] = on
        return on

    def dispatch(self, conn, occ: Occurrence) -> None:
        settings = Settings(conn)
        use_relay = (settings.get_bool("relay_enabled")
                     and self.config.relay.enabled_hw)
        course = (f"{occ.ctx.type_name} course, Day {occ.ctx.day}"
                  if occ.ctx else "No course")
        if occ.kind == "gong":
            if not self._enabled(settings, "gong_enabled"):
                return
            track = occ.track or settings.get("gong_track")
            gap = occ.gap_seconds
            if gap is None:
                gap = settings.get_int("gong_gap_seconds")
            job = PlayJob(
                kind="gong",
                file=self.config.gongs_dir / f"{track}.mp3",
                repeats=occ.repeats,
                gap_seconds=max(0, gap),
                volume=settings.get_int("gong_volume"),
                use_relay=use_relay,
                settle_seconds=self.config.relay.settle_seconds,
                label=f"{course}, {occ.fire_at:%H:%M} x{occ.repeats}",
            )
        else:  # doha
            if not self._enabled(settings, "doha_enabled"):
                return
            slot = doha.pick_slot(settings, occ.ctx)
            if slot is None:
                return
            try:
                manifest = doha.load_manifest(self.config.manifest_path)
                filename = manifest[slot]
            except (OSError, KeyError, ValueError):
                log.error("doha slot %s missing from manifest — skipping", slot)
                model.log_play(conn, "doha", f"slot {slot}", 1, "error",
                               "missing from manifest")
                return
            job = PlayJob(
                kind="doha",
                file=self.config.doha_dir / filename,
                volume=settings.get_int("doha_volume"),
                use_relay=use_relay,
                settle_seconds=self.config.relay.settle_seconds,
                label=f"{course}, doha slot {slot}",
            )
        log.info("firing %s", job.label)
        self.player.submit(job)
