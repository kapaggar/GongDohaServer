from __future__ import annotations

import json
import shutil
import threading
from datetime import datetime
from pathlib import Path

import pytest

from gong_ng import db
from gong_ng.clock import Clock
from gong_ng.config import AudioConfig, Config, RelayConfig, TimeConfig

NG = Path(__file__).resolve().parents[1]
SEED = NG / "seed"


@pytest.fixture
def config(tmp_path) -> Config:
    """A fully seeded throwaway appliance data dir with dummy audio."""
    cfg = Config(
        audio=AudioConfig(player="dummy", dummy_seconds=0.01),
        relay=RelayConfig(enabled_hw=False, settle_seconds=0.01),
        time=TimeConfig(timezone="Asia/Kolkata", fire_grace_seconds=120),
        data_dir=tmp_path / "data",
    )
    cfg.gongs_dir.mkdir(parents=True)
    cfg.doha_dir.mkdir(parents=True)
    for track in ("ting", "drum"):
        (cfg.gongs_dir / f"{track}.mp3").write_bytes(b"\xff\xfb")
    shutil.copy(SEED / "doha-manifest.json", cfg.manifest_path)
    for name in json.loads(cfg.manifest_path.read_text()).values():
        (cfg.doha_dir / name).write_bytes(b"\xff\xfb")
    cfg.secret_key_path.write_text("test-secret")

    conn = db.connect(cfg.db_path)
    db.init_db(conn, (SEED / "seed.sql").read_text())
    conn.close()
    return cfg


@pytest.fixture
def conn(config):
    c = db.connect(config.db_path)
    yield c
    c.close()


class FakeClock(Clock):
    def __init__(self, tz_name="Asia/Kolkata"):
        super().__init__(tz_name)
        self._now: datetime | None = None

    def set(self, value: str) -> datetime:
        self._now = datetime.fromisoformat(value).replace(tzinfo=self.tz)
        return self._now

    def now(self) -> datetime:
        assert self._now is not None, "FakeClock.set() first"
        return self._now


class RecordingPlayer:
    """Player stand-in that records submitted jobs."""

    def __init__(self):
        self.jobs = []
        self.stopped = 0

    def submit(self, job):
        self.jobs.append(job)
        job.done.set()
        return True

    def stop_now(self):
        self.stopped += 1

    @property
    def busy(self):
        return False


@pytest.fixture
def fake_clock():
    return FakeClock()


@pytest.fixture
def rec_player():
    return RecordingPlayer()


@pytest.fixture
def poke():
    return threading.Event()
