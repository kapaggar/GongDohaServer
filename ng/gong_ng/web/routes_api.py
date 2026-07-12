"""JSON API (design §8). Session-authenticated except /healthz."""
from __future__ import annotations

import shutil

from flask import Blueprint, g, jsonify, request

from .. import clock as clockmod
from .. import jobs, model
from ..model import EDITABLE_SETTINGS, Settings
from ..scheduler import upcoming_occurrences
from ..timeset import set_system_time

api = Blueprint("api", __name__, url_prefix="/api")


def build_status(conn, ctx) -> dict:
    now = ctx.clock.now()
    today = now.date()
    course = model.active_course(conn, today)
    ups = [o for o in upcoming_occurrences(conn, ctx.clock, today)
           if o.fire_at > now][:5]
    settings = Settings(conn)
    disk = shutil.disk_usage(ctx.config.data_dir)
    last = model.recent_plays(conn, 1)
    return {
        "time": now.isoformat(timespec="seconds"),
        "tz": ctx.config.time.timezone,
        "clock_ok": not clockmod.clock_invalid(conn),
        "course": (
            {"type": course.type_name, "day": course.day,
             "total_days": course.total_days,
             "start_date": course.start_date.isoformat()}
            if course else None
        ),
        "toggles": {k: settings.get_bool(k) for k in
                    ("enabled", "gong_enabled", "doha_enabled", "relay_enabled")},
        "next": [
            {"kind": o.kind, "at": o.fire_at.isoformat(timespec="minutes"),
             "repeats": o.repeats}
            for o in ups
        ],
        "disk_free_mb": disk.free // (1024 * 1024),
        "playing": ctx.player.busy,
        "last_play": dict(last[0]) if last else None,
    }


@api.get("/status")
def status():
    return jsonify(build_status(g.conn, g.ctx))


@api.get("/healthz")
def healthz():
    return jsonify(ok=True, clock_ok=not clockmod.clock_invalid(g.conn),
                   playing=g.ctx.player.busy)


@api.get("/settings")
def get_settings():
    return jsonify(g.settings.as_dict())


@api.put("/settings")
def put_settings():
    data = request.get_json(force=True, silent=True) or {}
    changed = {}
    for key, value in data.items():
        if key not in EDITABLE_SETTINGS:
            return jsonify(error=f"unknown or read-only setting {key!r}"), 400
        changed[key] = str(value)
    for key, value in changed.items():
        g.settings.set(key, value)
    g.ctx.poke.set()
    return jsonify(ok=True, changed=sorted(changed))


@api.get("/courses")
def get_courses():
    return jsonify([dict(r) for r in model.list_courses(g.conn)])


@api.post("/courses")
def post_course():
    data = request.get_json(force=True, silent=True) or {}
    try:
        cid = model.add_course(g.conn, int(data["course_type_id"]),
                               str(data["start_date"]),
                               str(data.get("note", "")))
    except (KeyError, ValueError) as exc:
        return jsonify(error=f"invalid course: {exc}"), 400
    g.ctx.poke.set()
    return jsonify(ok=True, id=cid)


@api.delete("/courses/<int:course_id>")
def del_course(course_id: int):
    model.delete_course(g.conn, course_id)
    g.ctx.poke.set()
    return jsonify(ok=True)


@api.get("/schedule")
def get_schedule():
    ct = request.args.get("type", "")
    day = request.args.get("day", "")
    ct_id = None if ct in ("", "nc") else int(ct)
    day_no = None if day in ("", "default") else int(day)
    rows = model.list_events(g.conn, ct_id, day_no)
    return jsonify([dict(r) for r in rows])


@api.post("/schedule")
def post_event():
    data = request.get_json(force=True, silent=True) or {}
    try:
        eid = model.add_event(
            g.conn,
            None if data.get("course_type_id") in (None, "", "nc")
            else int(data["course_type_id"]),
            None if data.get("day_no") in (None, "", "default")
            else int(data["day_no"]),
            str(data["time_local"]), int(data["repeats"]),
            data.get("gap_seconds"), data.get("track"),
        )
    except Exception as exc:
        return jsonify(error=f"invalid event: {exc}"), 400
    g.ctx.poke.set()
    return jsonify(ok=True, id=eid)


@api.delete("/schedule/<int:event_id>")
def del_event(event_id: int):
    model.delete_event(g.conn, event_id)
    g.ctx.poke.set()
    return jsonify(ok=True)


@api.post("/test/gong")
def test_gong():
    job = jobs.gong_job(g.conn, g.ctx.config)
    g.ctx.player.submit(job)
    return jsonify(ok=True, file=job.file.name)


@api.post("/test/doha")
def test_doha():
    job = jobs.doha_job(g.conn, g.ctx.config, g.ctx.clock.today())
    if job is None:
        return jsonify(error="doha manifest incomplete"), 500
    g.ctx.player.submit(job)
    return jsonify(ok=True, file=job.file.name)


@api.post("/stop")
def stop():
    g.ctx.player.stop_now()
    return jsonify(ok=True)


@api.post("/time")
def set_time():
    data = request.get_json(force=True, silent=True) or {}
    if data.get("confirm"):
        clockmod.confirm_clock(g.conn, g.ctx.clock.now())
        g.ctx.poke.set()
        return jsonify(ok=True, message="clock confirmed")
    ok, msg = set_system_time(str(data.get("datetime", "")))
    if ok:
        clockmod.confirm_clock(g.conn, g.ctx.clock.now())
        g.ctx.poke.set()
        return jsonify(ok=True, message=msg)
    return jsonify(error=msg), 400


@api.get("/logs")
def logs():
    n = min(int(request.args.get("n", 50)), 500)
    return jsonify([dict(r) for r in model.recent_plays(g.conn, n)])
