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
    conn = db.connect(config.db_path)
    conn.executescript((NG / "seed" / "deshna-seed.sql").read_text())
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


def test_fetch_rejects_bad_hash(client):
    r = client.get("/fetch.php?a=1|hin-eng|deadbeef|")
    assert r.status_code == 403


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


def test_path_traversal_blocked(client, config):
    conn = db.connect(config.db_path)
    conn.execute(
        "INSERT INTO deshna_schedule (id, filename) VALUES (90009, '../../secret_key')")
    conn.commit()
    conn.close()
    r = client.get(f"/fetch.php?a=90009|x|{CLIENT_HASH}|")
    assert r.status_code == 404
