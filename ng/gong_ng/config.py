"""Static machine configuration (/etc/gong-ng/config.toml).

Everything staff can change lives in the DB settings table instead; this file
holds facts about the hardware and never changes from the UI.
"""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_CONFIG_PATH = "/etc/gong-ng/config.toml"
DEFAULT_DATA_DIR = "/var/lib/gong"


@dataclass(frozen=True)
class AudioConfig:
    player: str = "mpv"  # mpv | dummy
    alsa_device: str = "alsa/plughw:CARD=Headphones"  # Pi 3B 3.5mm jack, Bookworm
    mixer_setup: tuple[str, ...] = ("amixer sset Headphone 100%",)
    dummy_seconds: float = 0.05  # simulated play duration in dummy mode


@dataclass(frozen=True)
class RelayConfig:
    enabled_hw: bool = False
    gpio: int = 17  # BCM numbering; physical pin 11
    active_low: bool = True
    settle_seconds: float = 5.0


@dataclass(frozen=True)
class TimeConfig:
    timezone: str = "Asia/Kolkata"
    fire_grace_seconds: int = 120


@dataclass(frozen=True)
class WebConfig:
    listen: str = "0.0.0.0:80"
    session_hours: int = 720


@dataclass(frozen=True)
class Config:
    audio: AudioConfig = field(default_factory=AudioConfig)
    relay: RelayConfig = field(default_factory=RelayConfig)
    time: TimeConfig = field(default_factory=TimeConfig)
    web: WebConfig = field(default_factory=WebConfig)
    data_dir: Path = Path(DEFAULT_DATA_DIR)

    @property
    def db_path(self) -> Path:
        return self.data_dir / "gong.db"

    @property
    def gongs_dir(self) -> Path:
        return self.data_dir / "media" / "gongs"

    @property
    def doha_dir(self) -> Path:
        return self.data_dir / "media" / "doha"

    @property
    def manifest_path(self) -> Path:
        return self.doha_dir / "manifest.json"

    @property
    def secret_key_path(self) -> Path:
        return self.data_dir / "secret_key"


def _section(data: dict, name: str, cls, **coerce):
    raw = dict(data.get(name, {}))
    for key, fn in coerce.items():
        if key in raw:
            raw[key] = fn(raw[key])
    known = {f for f in cls.__dataclass_fields__}
    return cls(**{k: v for k, v in raw.items() if k in known})


def load(path: str | os.PathLike | None = None) -> Config:
    """Load config; missing file means all defaults (dev mode)."""
    path = Path(path or os.environ.get("GONG_CONFIG", DEFAULT_CONFIG_PATH))
    data: dict = {}
    if path.is_file():
        with open(path, "rb") as fp:
            data = tomllib.load(fp)
    data_dir = Path(
        os.environ.get("GONG_DATA_DIR")
        or data.get("paths", {}).get("data_dir", DEFAULT_DATA_DIR)
    )
    return Config(
        audio=_section(data, "audio", AudioConfig, mixer_setup=tuple),
        relay=_section(data, "relay", RelayConfig),
        time=_section(data, "time", TimeConfig),
        web=_section(data, "web", WebConfig),
        data_dir=data_dir,
    )
