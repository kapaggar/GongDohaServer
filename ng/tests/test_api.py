"""Web auth, CSRF, settings, time validation."""
from __future__ import annotations

import threading

import pytest

from gong_ng import db
from gong_ng.clock import Clock
from gong_ng.model import Settings
from gong_ng.runtime import AppContext
from gong_ng.web import create_app
from gong_ng.web.auth import hash_pin

PIN = "4321"


@pytest.fixture
def app(config, rec_player, monkeypatch):
    monkeypatch.setenv("GONG_FAKE_SETTIME", "1")
    from gong_ng.web import auth as auth_module
    auth_module._fails.clear()  # lockout state is process-global
    conn = db.connect(config.db_path)
    Settings(conn).set("admin_pin_hash", hash_pin(PIN))
    conn.close()
    ctx = AppContext(config=config, clock=Clock(config.time.timezone),
                     player=rec_player, poke=threading.Event())
    application = create_app(ctx)
    application.config["TESTING"] = True
    return application


@pytest.fixture
def client(app):
    return app.test_client()


def login(client, pin=PIN):
    return client.post("/login", data={"pin": pin})


def csrf_of(client):
    with client.session_transaction() as sess:
        return sess.get("csrf", "")


def test_unauthenticated_redirects_and_api_401(client):
    assert client.get("/").status_code == 302
    assert client.get("/api/status").status_code == 401
    assert client.get("/api/healthz").status_code == 200  # only open route


def test_wrong_pin_rejected_then_right_pin_works(client):
    r = login(client, "0000")
    assert r.status_code == 200  # login page again
    assert client.get("/").status_code == 302
    r = login(client)
    assert r.status_code == 302
    assert client.get("/").status_code == 200


def test_lockout_after_five_failures(app):
    client = app.test_client()
    for _ in range(5):
        login(client, "9999")
    r = login(client)  # correct PIN but locked
    assert client.get("/").status_code == 302, "must stay locked out"


def test_csrf_required_on_ui_posts(client):
    login(client)
    assert client.post("/toggles", data={"enabled": "1"}).status_code == 403
    r = client.post("/toggles", data={"enabled": "1", "csrf": csrf_of(client)})
    assert r.status_code == 302


def test_settings_roundtrip_via_api(client, config):
    login(client)
    headers = {"X-CSRF-Token": csrf_of(client)}
    r = client.put("/api/settings", json={"gong_volume": "70"},
                   headers=headers)
    assert r.status_code == 200
    assert client.get("/api/settings").get_json()["gong_volume"] == "70"
    # read-only / unknown keys rejected
    r = client.put("/api/settings", json={"admin_pin_hash": "x"},
                   headers=headers)
    assert r.status_code == 400


def test_time_validation_rejects_garbage(client):
    login(client)
    headers = {"X-CSRF-Token": csrf_of(client)}
    for bad in ("2026-01-01 99:99", "2026-02-30 10:00", "yesterday"):
        r = client.post("/api/time", json={"datetime": bad}, headers=headers)
        assert r.status_code == 400, bad
    r = client.post("/api/time", json={"datetime": "2026-07-12 06:30"},
                    headers=headers)
    assert r.status_code == 200


def test_test_buttons_enqueue_jobs(client, rec_player):
    login(client)
    headers = {"X-CSRF-Token": csrf_of(client)}
    assert client.post("/api/test/gong", headers=headers).status_code == 200
    assert client.post("/api/test/doha", headers=headers).status_code == 200
    kinds = [j.kind for j in rec_player.jobs]
    assert kinds == ["test_gong", "test_doha"]
    assert client.post("/api/stop", headers=headers).status_code == 200
    assert rec_player.stopped == 1


def test_courses_api(client):
    login(client)
    headers = {"X-CSRF-Token": csrf_of(client)}
    r = client.post("/api/courses", headers=headers,
                    json={"course_type_id": 1, "start_date": "2026-08-01"})
    assert r.status_code == 200
    cid = r.get_json()["id"]
    dates = [c["start_date"] for c in client.get("/api/courses").get_json()]
    assert "2026-08-01" in dates
    assert client.delete(f"/api/courses/{cid}",
                         headers=headers).status_code == 200
