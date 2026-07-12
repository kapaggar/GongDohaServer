"""Server-rendered admin UI pages (design §8)."""
from __future__ import annotations

import io
import sqlite3
import subprocess
import tarfile
import tempfile
from pathlib import Path

from flask import (Blueprint, flash, g, redirect, render_template, request,
                   send_file, session, url_for)

from .. import clock as clockmod
from .. import jobs, model
from ..scheduler import upcoming_occurrences
from ..timeset import set_system_time
from . import auth
from .routes_api import build_status

ui = Blueprint("ui", __name__)


# ------------------------------------------------------------------ auth

@ui.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        ip = request.remote_addr or "?"
        wait = auth.locked_out(ip)
        if wait:
            flash(f"Too many attempts — wait {wait}s")
        elif auth.verify_pin(g.settings.get("admin_pin_hash"),
                             request.form.get("pin", "")):
            auth.login_session()
            return redirect(url_for("ui.dashboard"))
        else:
            auth.record_failure(ip)
            flash("Wrong PIN")
    return render_template("login.html.j2")


@ui.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("ui.login"))


# ------------------------------------------------------------------ pages

@ui.get("/")
def dashboard():
    return render_template("dashboard.html.j2",
                           status=build_status(g.conn, g.ctx))


@ui.post("/toggles")
def toggles():
    for key in ("enabled", "gong_enabled", "doha_enabled", "relay_enabled"):
        g.settings.set(key, "1" if request.form.get(key) else "0")
    g.ctx.poke.set()
    return redirect(url_for("ui.dashboard"))


@ui.post("/action")
def action():
    what = request.form.get("do", "")
    if what == "gong":
        g.ctx.player.submit(jobs.gong_job(g.conn, g.ctx.config))
        flash("Test gong queued")
    elif what == "doha":
        job = jobs.doha_job(g.conn, g.ctx.config, g.ctx.clock.today())
        if job:
            g.ctx.player.submit(job)
            flash("Test doha queued")
    elif what == "stop":
        g.ctx.player.stop_now()
        flash("Stopped")
    return redirect(request.referrer or url_for("ui.dashboard"))


@ui.route("/courses", methods=["GET", "POST"])
def courses():
    if request.method == "POST":
        if request.form.get("delete"):
            model.delete_course(g.conn, int(request.form["delete"]))
        else:
            try:
                model.add_course(g.conn, int(request.form["course_type_id"]),
                                 request.form["start_date"],
                                 request.form.get("note", ""))
            except (ValueError, KeyError):
                flash("Invalid course entry")
        g.ctx.poke.set()
        return redirect(url_for("ui.courses"))
    active = model.active_course(g.conn, g.ctx.clock.today())
    return render_template("courses.html.j2",
                           courses=model.list_courses(g.conn),
                           course_types=model.list_course_types(g.conn),
                           active=active)


def _parse_scope(args) -> tuple[int | None, int | None]:
    ct = args.get("type", "nc")
    day = args.get("day", "default")
    ct_id = None if ct == "nc" else int(ct)
    day_no = None if day == "default" else int(day)
    if ct_id is None:
        day_no = None  # no-course set has no day dimension
    return ct_id, day_no


@ui.route("/schedule", methods=["GET", "POST"])
def schedule():
    if request.method == "POST":
        ct_id, day_no = _parse_scope(request.form)
        try:
            if request.form.get("delete"):
                model.delete_event(g.conn, int(request.form["delete"]))
            elif request.form.get("copy_to"):
                to = request.form["copy_to"]
                n = model.copy_day(g.conn, ct_id, day_no,
                                   None if to == "default" else int(to))
                flash(f"Copied {n} events")
            else:
                model.add_event(
                    g.conn, ct_id, day_no,
                    request.form["time_local"], int(request.form["repeats"]),
                    int(request.form["gap_seconds"])
                    if request.form.get("gap_seconds") else None,
                    request.form.get("track") or None,
                )
        except sqlite3.IntegrityError:
            flash("That time already exists for this day")
        except (ValueError, KeyError):
            flash("Invalid entry")
        g.ctx.poke.set()
        return redirect(url_for("ui.schedule", type=request.form.get("type", "nc"),
                                day=request.form.get("day", "default")))
    ct_id, day_no = _parse_scope(request.args)
    from ..runtime import gong_tracks
    return render_template(
        "schedule.html.j2",
        course_types=model.list_course_types(g.conn),
        sel_type="nc" if ct_id is None else str(ct_id),
        sel_day="default" if day_no is None else str(day_no),
        days=model.days_with_events(g.conn, ct_id),
        events=model.list_events(g.conn, ct_id, day_no),
        tracks=gong_tracks(g.ctx.config),
    )


@ui.route("/sounds", methods=["GET", "POST"])
def sounds():
    fields = ("gong_track", "gong_volume", "gong_gap_seconds",
              "doha_time", "doha_volume", "no_course_doha")
    if request.method == "POST":
        try:
            for f in fields:
                if f in request.form:
                    if f == "doha_time":
                        from datetime import datetime
                        datetime.strptime(request.form[f], "%H:%M")
                    g.settings.set(f, request.form[f])
            flash("Saved")
        except ValueError:
            flash("Invalid value")
        g.ctx.poke.set()
        return redirect(url_for("ui.sounds"))
    from ..runtime import gong_tracks
    return render_template("sounds.html.j2", tracks=gong_tracks(g.ctx.config),
                           s=g.settings.as_dict())


@ui.route("/time", methods=["GET", "POST"])
def time_page():
    if request.method == "POST":
        if request.form.get("confirm"):
            clockmod.confirm_clock(g.conn, g.ctx.clock.now())
            flash("Clock confirmed")
        else:
            value = (request.form.get("date", "") + " "
                     + request.form.get("time", ""))
            ok, msg = set_system_time(value)
            if ok:
                clockmod.confirm_clock(g.conn, g.ctx.clock.now())
            flash(msg)
        g.ctx.poke.set()
        return redirect(url_for("ui.time_page"))
    rtc = Path("/dev/rtc0").exists() or Path("/dev/rtc").exists()
    return render_template("time.html.j2", rtc=rtc)


@ui.get("/logs")
def logs():
    journal = ""
    try:
        journal = subprocess.run(
            ["journalctl", "-u", "gongd", "-n", "100", "-o", "cat",
             "--no-pager"],
            capture_output=True, text=True, timeout=5,
        ).stdout
    except Exception:
        pass
    return render_template("logs.html.j2",
                           plays=model.recent_plays(g.conn, 50),
                           journal=journal)


# ------------------------------------------------------------------ backup

@ui.get("/backup")
def backup_page():
    return render_template("backup.html.j2")


@ui.get("/backup.tar.gz")
def backup_download():
    buf = io.BytesIO()
    with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
        snap = sqlite3.connect(tmp.name)
        g.conn.backup(snap)
        snap.close()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            tar.add(tmp.name, arcname="gong.db")
            manifest = g.ctx.config.manifest_path
            if manifest.is_file():
                tar.add(manifest, arcname="doha-manifest.json")
    buf.seek(0)
    stamp = g.ctx.clock.now().strftime("%Y%m%d")
    return send_file(buf, as_attachment=True,
                     download_name=f"gong-backup-{stamp}.tar.gz",
                     mimetype="application/gzip")


@ui.post("/restore")
def restore():
    upload = request.files.get("backup")
    if upload is None:
        flash("No file uploaded")
        return redirect(url_for("ui.backup_page"))
    try:
        with tarfile.open(fileobj=upload.stream, mode="r:gz") as tar:
            member = tar.getmember("gong.db")  # only this exact name
            with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
                fp = tar.extractfile(member)
                assert fp is not None
                tmp.write(fp.read())
                tmp.flush()
                src = sqlite3.connect(tmp.name)
                if src.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise ValueError("uploaded DB failed integrity check")
                src.backup(g.conn)
                src.close()
        flash("Restore complete")
    except (tarfile.TarError, KeyError, ValueError, sqlite3.Error) as exc:
        flash(f"Restore failed: {exc}")
    g.ctx.poke.set()
    return redirect(url_for("ui.backup_page"))
