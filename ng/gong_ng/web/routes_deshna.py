"""Deshna responder — exact-compat reimplementation of the legacy fetch.php.

The Deshna Android app (dhamma.org.deshna, decompiled dn3.1) requests course
audio from its local server as:

    GET /fetch.php?a=<track_id>|<course_lang_code>|<ip_hash>|<selected_lang>

The legacy ip_hash token (md5("<client-ip>-dowifi")) is accepted but NOT
validated — the endpoint serves anyone on the network (owner's decision,
2026-07-14: the AP's WPA2 passphrase is the boundary). track_id resolves via
deshna_schedule (ids seeded from the original appliance dump) to a file
under <data_dir>/media/deshna/.

Language params: schedule rows are already language-specific (the app picks
the right row from its own DB), so the common path ignores them. For rows
marked `multiple`, selected_lang picks the sibling row with that lang — the
best reconstruction available, as the original fetch.php is lost; flagged in
the README.
"""
from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from flask import Blueprint, abort, g, request, send_file

log = logging.getLogger(__name__)

deshna = Blueprint("deshna", __name__)


def ip_hash(remote_addr: str) -> str:
    return hashlib.md5(f"{remote_addr}-dowifi".encode()).hexdigest()


def resolve_track(conn, track_id: int, selected_lang: str):
    row = conn.execute(
        "SELECT * FROM deshna_schedule WHERE id=?", (track_id,)
    ).fetchone()
    if row is None:
        return None
    if selected_lang and row["multiple"]:
        alt = conn.execute(
            "SELECT * FROM deshna_schedule WHERE course_id=? AND day_no=?"
            " AND track=? AND lang=? LIMIT 1",
            (row["course_id"], row["day_no"], row["track"], selected_lang),
        ).fetchone()
        if alt is not None:
            row = alt
    return row


@deshna.get("/fetch.php")
def fetch():
    a = request.args.get("a", "")
    parts = a.split("|")
    if not parts or not parts[0].isdigit():
        abort(400)
    track_id = int(parts[0])
    selected_lang = parts[3] if len(parts) > 3 else ""

    row = resolve_track(g.conn, track_id, selected_lang)
    if row is None:
        abort(404)
    root = g.ctx.config.deshna_dir.resolve()
    path = (root / row["filename"]).resolve()
    if not path.is_relative_to(root):  # defence-in-depth; filename is ours
        abort(404)
    if not path.is_file():
        log.warning("deshna fetch: media missing: %s", row["filename"])
        abort(404)
    log.info("deshna fetch: %s -> %s", request.remote_addr, row["filename"])
    return send_file(path, mimetype="audio/mpeg", conditional=True)
