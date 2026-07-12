"""Player ordering, relay orchestration, and preemption (dummy audio)."""
from __future__ import annotations

import time

from gong_ng.player import PlayJob, Player
from gong_ng.relay import DummyRelay


def make_player(config):
    relay = DummyRelay()
    player = Player(config, relay, db_path=config.db_path)
    player.start()
    return player, relay


def gong(config, repeats=3, gap=0.02, relay=True, kind="gong"):
    return PlayJob(kind=kind, file=config.gongs_dir / "ting.mp3",
                   repeats=repeats, gap_seconds=gap, volume=90,
                   use_relay=relay, settle_seconds=0.01, label="t")


def test_burst_with_relay(config, conn):
    player, relay = make_player(config)
    job = gong(config)
    player.submit(job)
    assert job.done.wait(5)
    assert job.result == "ok"
    assert relay.transitions == ["on", "off"]
    row = conn.execute("SELECT * FROM play_log ORDER BY id DESC").fetchone()
    assert row["result"] == "ok" and row["repeats"] == 3
    player.shutdown()


def test_gong_preempts_gong(config, conn):
    player, relay = make_player(config)
    long_job = gong(config, repeats=30, gap=0.2)
    player.submit(long_job)
    time.sleep(0.15)  # let it start
    new_job = gong(config, repeats=2, gap=0.0)
    player.submit(new_job)
    assert new_job.done.wait(5)
    assert long_job.result == "stopped"
    assert new_job.result == "ok"
    assert relay.state is False  # never left on
    player.shutdown()


def test_doha_waits_for_gong(config, conn):
    player, _ = make_player(config)
    g = gong(config, repeats=3, gap=0.05, relay=False)
    d = PlayJob(kind="doha", file=config.doha_dir.glob("*.mp3").__next__(),
                volume=75, label="doha")
    player.submit(g)
    player.submit(d)
    assert d.done.wait(5)
    assert g.result == "ok", "doha must not preempt a running gong"
    assert d.result == "ok"
    player.shutdown()


def test_stop_now(config, conn):
    player, relay = make_player(config)
    job = gong(config, repeats=50, gap=0.2)
    player.submit(job)
    time.sleep(0.15)
    player.stop_now()
    assert job.done.wait(5)
    assert job.result == "stopped"
    assert relay.state is False
    player.shutdown()


def test_missing_file_logged_as_error(config, conn):
    player, _ = make_player(config)
    job = PlayJob(kind="gong", file=config.gongs_dir / "nope.mp3", repeats=1)
    player.submit(job)
    assert job.done.wait(5)
    assert job.result == "error"
    row = conn.execute("SELECT * FROM play_log ORDER BY id DESC").fetchone()
    assert row["result"] == "error"
    player.shutdown()
