"""Build PlayJobs from current settings — shared by the UI test buttons,
gongctl, and nothing else (the scheduler builds its own with per-event
overrides)."""
from __future__ import annotations

from datetime import date

from . import doha, model
from .config import Config
from .model import Settings
from .player import PlayJob


def gong_job(conn, config: Config, kind: str = "test_gong",
             track: str | None = None, repeats: int = 3) -> PlayJob:
    settings = Settings(conn)
    track = track or settings.get("gong_track")
    return PlayJob(
        kind=kind,
        file=config.gongs_dir / f"{track}.mp3",
        repeats=repeats,
        gap_seconds=settings.get_int("gong_gap_seconds"),
        volume=settings.get_int("gong_volume"),
        use_relay=settings.get_bool("relay_enabled") and config.relay.enabled_hw,
        settle_seconds=config.relay.settle_seconds,
        label=f"test gong ({track} x{repeats})",
    )


def doha_job(conn, config: Config, today: date, kind: str = "test_doha",
             slot: int | None = None) -> PlayJob | None:
    settings = Settings(conn)
    if slot is None:
        ctx = model.active_course(conn, today)
        slot = doha.pick_slot(settings, ctx)
        if slot is None:
            slot = 1
    manifest = doha.load_manifest(config.manifest_path)
    if slot not in manifest:
        return None
    return PlayJob(
        kind=kind,
        file=config.doha_dir / manifest[slot],
        volume=settings.get_int("doha_volume"),
        use_relay=settings.get_bool("relay_enabled") and config.relay.enabled_hw,
        settle_seconds=config.relay.settle_seconds,
        label=f"test doha (slot {slot})",
    )
