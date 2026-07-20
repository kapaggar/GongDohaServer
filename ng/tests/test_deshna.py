"""Deshna fetch.php compat endpoint + seed conversion."""
from __future__ import annotations

import hashlib
import importlib.util
import threading
from pathlib import Path

import pytest

from gong_ng import db
from gong_ng.clock import Clock
from gong_ng.runtime import AppContext
from gong_ng.web import create_app
from gong_ng.web.routes_deshna import ip_hash

NG = Path(__file__).resolve().parents[1]
DESHNA_DUMP = Path("/Users/wizops/DIPI/asks/deshna/pi/deshna.sql")
DESHNA_APK_DB = Path("/Users/wizops/DIPI/asks/Apks/dn3.1/assets/deshna.db")

spec = importlib.util.spec_from_file_location(
    "convert_deshna_seed", NG / "tools" / "convert_deshna_seed.py")
conv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(conv)

TRACK1_FILE = "10-day/Hi-En/D00_2000_Anapana_Hi-En_10d.mp3"
CLIENT_HASH = ip_hash("127.0.0.1")  # Flask test client remote addr


@pytest.fixture
def app(config, rec_player):
    from gong_ng.model import Settings
    from gong_ng.web.auth import hash_pin
    conn = db.connect(config.db_path)
    conn.executescript((NG / "seed" / "deshna-seed.sql").read_text())
    Settings(conn).set("admin_pin_hash", hash_pin("4321"))
    conn.close()
    media = config.deshna_dir / Path(TRACK1_FILE).parent
    media.mkdir(parents=True)
    (config.deshna_dir / TRACK1_FILE).write_bytes(b"ID3fake-mp3-bytes")
    ctx = AppContext(config=config, clock=Clock(config.time.timezone),
                     player=rec_player, poke=threading.Event())
    application = create_app(ctx)
    application.config["TESTING"] = True
    return application


@pytest.fixture
def client(app):
    return app.test_client()


# ------------------------------------------------------------ converter

def test_ip_hash_matches_app_algorithm():
    # MyUtils.get_ip_hash: md5("<ip>-dowifi")
    assert ip_hash("10.10.0.55") == hashlib.md5(b"10.10.0.55-dowifi").hexdigest()


sources_present = DESHNA_DUMP.is_file() and DESHNA_APK_DB.is_file()


@pytest.mark.skipif(not sources_present, reason="deshna sources not on this machine")
def test_converter_counts_and_ids_preserved():
    courses, schedule = conv.convert(DESHNA_DUMP, DESHNA_APK_DB)
    assert len(courses) == 30
    assert len(schedule) == 3716
    by_id = {r[0]: r for r in schedule}
    assert by_id[1][4] == TRACK1_FILE   # filename verbatim (both sources)
    assert 4218 in by_id                # app-3.1-only id resolvable
    assert by_id[1][8] == 2100          # conflicting valid_till: APK rev wins


def test_checked_in_seed_matches_converter():
    if not sources_present:
        pytest.skip("deshna sources not on this machine")
    courses, schedule = conv.convert(DESHNA_DUMP, DESHNA_APK_DB)
    assert (NG / "seed" / "deshna-seed.sql").read_text() == conv.render(
        courses, schedule), (
        "seed/deshna-seed.sql drifted — re-run ng/tools/convert_deshna_seed.py")


# ------------------------------------------------------------ endpoint

def test_fetch_serves_mp3_without_session(client):
    r = client.get(f"/fetch.php?a=1|hin-eng|{CLIENT_HASH}|")
    assert r.status_code == 200
    assert r.data == b"ID3fake-mp3-bytes"
    assert r.mimetype == "audio/mpeg"


def test_fetch_open_to_all_hash_ignored(client):
    # Owner's decision: no ip-hash gate; any/no token is served.
    for a in ("1|hin-eng|deadbeef|", "1|hin-eng||", "1"):
        r = client.get(f"/fetch.php?a={a}")
        assert r.status_code == 200, a
        assert r.data == b"ID3fake-mp3-bytes"


def test_ip_hash_helper_still_documents_legacy_algorithm():
    # kept for reference/tests even though the route no longer enforces it
    assert ip_hash("1.2.3.4") == hashlib.md5(b"1.2.3.4-dowifi").hexdigest()


def test_fetch_unknown_track_404(client):
    r = client.get(f"/fetch.php?a=999999|hin-eng|{CLIENT_HASH}|")
    assert r.status_code == 404


def test_fetch_missing_media_404(client):
    # track 2 exists in the seed but its file is not on disk
    r = client.get(f"/fetch.php?a=2|hin-eng|{CLIENT_HASH}|")
    assert r.status_code == 404


def test_fetch_garbage_param_400(client):
    assert client.get("/fetch.php?a=").status_code == 400
    assert client.get("/fetch.php?a=abc|x|y|z").status_code == 400


def test_multiple_track_language_selection(client, config, app):
    conn = db.connect(config.db_path)
    conn.execute(
        "INSERT INTO deshna_schedule (id, track, course_id, day_no, filename,"
        " multiple, lang) VALUES (90001,'Discourse',1,1,'d/base.mp3',1,'hin-eng')")
    conn.execute(
        "INSERT INTO deshna_schedule (id, track, course_id, day_no, filename,"
        " multiple, lang) VALUES (90002,'Discourse',1,1,'d/eng.mp3',1,'eng')")
    conn.commit()
    conn.close()
    (config.deshna_dir / "d").mkdir()
    (config.deshna_dir / "d" / "base.mp3").write_bytes(b"base")
    (config.deshna_dir / "d" / "eng.mp3").write_bytes(b"english")
    r = client.get(f"/fetch.php?a=90001|hin-eng|{CLIENT_HASH}|eng")
    assert r.status_code == 200 and r.data == b"english"
    r = client.get(f"/fetch.php?a=90001|hin-eng|{CLIENT_HASH}|")
    assert r.status_code == 200 and r.data == b"base"


def test_deshna_helper_tab(client):
    assert client.get("/deshna").status_code == 302  # login required
    client.post("/login", data={"pin": "4321"})
    page = client.get("/deshna")
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    assert "fetch.php?a=1" in html        # one-click test for the on-disk file
    assert "of <b>3716</b>" in html       # media status counter
    assert "chown -R gong:gong" in html   # install/troubleshooting present


def test_path_traversal_blocked(client, config):
    conn = db.connect(config.db_path)
    conn.execute(
        "INSERT INTO deshna_schedule (id, filename) VALUES (90009, '../../secret_key')")
    conn.commit()
    conn.close()
    r = client.get(f"/fetch.php?a=90009|x|{CLIENT_HASH}|")
    assert r.status_code == 404


# ------------------------------------------------------------ USB media

def test_usb_status_absent(monkeypatch, tmp_path):
    from gong_ng import usbmedia
    monkeypatch.setenv("GONG_USB_STATUS", str(tmp_path / "nope.json"))
    assert usbmedia.status() == {"attached": None}


def test_usb_status_parsed(monkeypatch, tmp_path):
    from gong_ng import usbmedia
    f = tmp_path / "usb-media.json"
    f.write_text('{"attached": "sda1", "files": 42, "bound": true}')
    monkeypatch.setenv("GONG_USB_STATUS", str(f))
    st = usbmedia.status()
    assert st["attached"] == "sda1" and st["files"] == 42 and st["bound"] is True


def test_usb_copy_fake_mode(monkeypatch):
    from gong_ng import usbmedia
    monkeypatch.setenv("GONG_FAKE_USBMEDIA", "1")
    ok, msg = usbmedia.copy()
    assert ok and "copy" in msg


def test_deshna_tab_shows_attached_usb(client, monkeypatch, tmp_path):
    f = tmp_path / "usb-media.json"
    f.write_text('{"attached": "sda1", "label": "DESHNA", "files": 7,'
                 ' "bound": true, "mode": "mounted", "note": ""}')
    monkeypatch.setenv("GONG_USB_STATUS", str(f))
    client.post("/login", data={"pin": "4321"})
    html = client.get("/deshna").get_data(as_text=True)
    assert "USB sda1" in html
    assert "Copy onto the Pi" in html
    assert "stp/" in html and "STP/" in html   # directory-structure reference


def test_deshna_usb_action_routes_to_helper(client, monkeypatch):
    monkeypatch.setenv("GONG_FAKE_USBMEDIA", "1")
    client.post("/login", data={"pin": "4321"})
    # grab a csrf token from a rendered page
    html = client.get("/deshna").get_data(as_text=True)
    import re
    token = re.search(r'name="csrf" value="([^"]+)"', html).group(1)
    r = client.post("/deshna/usb", data={"do": "copy", "csrf": token})
    assert r.status_code == 302  # redirect back to the tab with a flash
