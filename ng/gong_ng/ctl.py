"""gongctl — appliance CLI: status, tests, PIN reset, course simulation.

Runs standalone against the same DB/config as gongd. Playback commands drive
their own player; if gongd is mid-play, sounds may overlap — use the UI test
buttons on a live appliance.
"""
from __future__ import annotations

import argparse
import secrets
import sys
import threading
from datetime import date, timedelta

from . import __version__, clock as clockmod, config as configmod
from . import db, doha, jobs, model
from .clock import Clock
from .model import CourseCtx, Settings
from .player import Player
from .relay import make_relay
from .runtime import ensure_data_dir, gong_tracks
from .scheduler import upcoming_occurrences
from .web.auth import hash_pin


def _play(config, job) -> None:
    relay = make_relay(config)
    player = Player(config, relay)
    player.start()
    player.submit(job)
    job.done.wait()
    player.shutdown()
    player.join(timeout=5)
    relay.close()
    print(f"{job.label}: {job.result}")


def cmd_init(config, args) -> int:
    ensure_data_dir(config)
    print(f"data dir ready: {config.data_dir}")
    return 0


def cmd_status(config, args) -> int:
    conn = db.connect(config.db_path)
    clk = Clock(config.time.timezone)
    now = clk.now()
    problems: list[str] = []
    print(f"time        : {now:%Y-%m-%d %H:%M:%S} ({config.time.timezone})")
    print(f"clock trust : {'INVALID — playback suppressed' if clockmod.clock_invalid(conn) else 'ok'}")
    ctx = model.active_course(conn, now.date())
    print(f"course      : {ctx.type_name} day {ctx.day}/{ctx.total_days}"
          if ctx else "course      : none")
    settings = Settings(conn)
    print("toggles     : " + " ".join(
        f"{k}={'on' if settings.get_bool(k) else 'off'}"
        for k in ("enabled", "gong_enabled", "doha_enabled", "relay_enabled")))
    ups = [o for o in upcoming_occurrences(conn, clk, now.date())
           if o.fire_at > now][:5]
    for o in ups:
        extra = f"x{o.repeats}" if o.kind == "gong" else ""
        print(f"next        : {o.fire_at:%a %H:%M} {o.kind} {extra}")
    tracks = gong_tracks(config)
    if not tracks:
        problems.append(f"no gong tracks in {config.gongs_dir}")
    if not config.manifest_path.is_file():
        problems.append("doha manifest missing")
    else:
        manifest = doha.load_manifest(config.manifest_path)
        missing = [s for s, f in manifest.items()
                   if not (config.doha_dir / f).is_file()]
        if missing:
            problems.append(f"doha files missing for slots {missing}")
    if args.check:
        for p in problems:
            print(f"CHECK FAIL  : {p}", file=sys.stderr)
        print("check       : " + ("FAIL" if problems else "ok"))
        return 1 if problems else 0
    return 0


def cmd_test_gong(config, args) -> int:
    conn = db.connect(config.db_path)
    _play(config, jobs.gong_job(conn, config, track=args.track,
                                repeats=args.repeats))
    return 0


def cmd_test_doha(config, args) -> int:
    conn = db.connect(config.db_path)
    clk = Clock(config.time.timezone)
    job = jobs.doha_job(conn, config, clk.today(), slot=args.slot)
    if job is None:
        print("doha manifest incomplete", file=sys.stderr)
        return 1
    _play(config, job)
    return 0


def cmd_reset_pin(config, args) -> int:
    conn = db.connect(config.db_path)
    pin = args.pin or f"{secrets.randbelow(10**6):06d}"
    Settings(conn).set("admin_pin_hash", hash_pin(pin))
    print(f"admin PIN set to: {pin}")
    print("(write it down — it is not shown again)")
    return 0


def cmd_simulate(config, args) -> int:
    """Materialize a full course day by day (golden-run dry check)."""
    conn = db.connect(config.db_path)
    ct = conn.execute("SELECT * FROM course_types WHERE name = ?",
                      (args.course,)).fetchone()
    if ct is None:
        names = [r["name"] for r in model.list_course_types(conn)]
        print(f"unknown course type {args.course!r}; have: {names}",
              file=sys.stderr)
        return 1
    start = date.fromisoformat(args.start)
    settings = Settings(conn)
    for day in range(0, ct["total_days"] + 1):
        ctx = CourseCtx(course_id=0, type_id=ct["id"], type_name=ct["name"],
                        start_date=start, total_days=ct["total_days"],
                        anapana_days=ct["anapana_days"], day=day)
        rows = model.events_for(conn, ctx)
        d = start + timedelta(days=day)
        slot = doha.pick_slot(settings, ctx)
        gongs = " ".join(f"{r['time_local']}x{r['repeats']}" for r in rows)
        doha_s = (f"doha@{settings.get('doha_time')}=slot{slot}"
                  if slot and 0 < day else "no-doha")
        print(f"day {day:>2} {d} | {doha_s:<22} | {gongs}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="gongctl", description=__doc__)
    ap.add_argument("--version", action="version", version=__version__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init", help="create data dir, DB, seed, media")
    p = sub.add_parser("status", help="show appliance status")
    p.add_argument("--check", action="store_true",
                   help="exit non-zero if anything is wrong")
    p = sub.add_parser("test-gong", help="play the gong now")
    p.add_argument("--track")
    p.add_argument("--repeats", type=int, default=3)
    p = sub.add_parser("test-doha", help="play a doha now")
    p.add_argument("--slot", type=int)
    p = sub.add_parser("reset-pin", help="set a new admin PIN (break-glass)")
    p.add_argument("--pin", help="explicit PIN instead of a random one")
    p = sub.add_parser("simulate", help="dry-run a full course schedule")
    p.add_argument("--course", required=True, help="course type name")
    p.add_argument("--start", required=True, help="zero day YYYY-MM-DD")
    args = ap.parse_args(argv)

    config = configmod.load()
    handler = {
        "init": cmd_init, "status": cmd_status, "test-gong": cmd_test_gong,
        "test-doha": cmd_test_doha, "reset-pin": cmd_reset_pin,
        "simulate": cmd_simulate,
    }[args.cmd]
    return handler(config, args)


if __name__ == "__main__":
    sys.exit(main())
