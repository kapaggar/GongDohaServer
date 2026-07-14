"""Shared application context and data-dir bootstrap."""
from __future__ import annotations

import logging
import secrets
import shutil
import threading
from dataclasses import dataclass
from pathlib import Path

from . import db
from .clock import Clock
from .config import Config
from .player import Player

log = logging.getLogger(__name__)

# Where firstrun.sh installs the seed + media on the appliance; falls back to
# the repo layout for development.
SEED_LOCATIONS = (
    Path("/opt/gong-ng/seed"),
    Path(__file__).resolve().parents[1] / "seed",
)
MEDIA_LOCATIONS = (
    Path("/opt/gong-ng/media-src"),
    Path(__file__).resolve().parents[2] / "app" / "dhamma",
)


@dataclass
class AppContext:
    config: Config
    clock: Clock
    player: Player
    poke: threading.Event

    @property
    def db_path(self) -> Path:
        return self.config.db_path


def find_seed() -> Path | None:
    for base in SEED_LOCATIONS:
        if (base / "seed.sql").is_file():
            return base
    return None


def ensure_data_dir(config: Config) -> None:
    """Create the data dir, DB (with seed), media, and secret key if absent.

    Idempotent — safe to run on every startup.
    """
    config.gongs_dir.mkdir(parents=True, exist_ok=True)
    config.doha_dir.mkdir(parents=True, exist_ok=True)

    seed_dir = find_seed()
    seed_sql = (seed_dir / "seed.sql").read_text() if seed_dir else None
    conn = db.connect(config.db_path)
    db.init_db(conn, seed_sql)
    if seed_dir:
        # Centre course calendar (e.g. courses-sudha-*.sql): applied only on
        # a virgin courses table; the UI owns the calendar afterwards.
        n = conn.execute("SELECT COUNT(*) FROM courses").fetchone()[0]
        if n == 0:
            for f in sorted(seed_dir.glob("courses*.sql")):
                conn.executescript(f.read_text())
                log.info("seeded course calendar from %s", f.name)
        deshna_seed = seed_dir / "deshna-seed.sql"
        n = conn.execute("SELECT COUNT(*) FROM deshna_schedule").fetchone()[0]
        if n == 0 and deshna_seed.is_file():
            conn.executescript(deshna_seed.read_text())
            log.info("seeded deshna schedule from %s", deshna_seed.name)
    conn.close()
    config.deshna_dir.mkdir(parents=True, exist_ok=True)

    if seed_dir and not config.manifest_path.is_file():
        manifest = seed_dir / "doha-manifest.json"
        if manifest.is_file():
            shutil.copy(manifest, config.manifest_path)

    # Dev convenience: populate media from the legacy repo if empty.
    if not any(config.gongs_dir.glob("*.mp3")):
        for base in MEDIA_LOCATIONS:
            for src in base.glob("gong-*.mp3"):
                shutil.copy(src, config.gongs_dir / src.name.removeprefix("gong-"))
            doha_src = base / "doha"
            if doha_src.is_dir():
                for src in doha_src.glob("*.mp3"):
                    shutil.copy(src, config.doha_dir / src.name)
            if any(config.gongs_dir.glob("*.mp3")):
                break

    if not config.secret_key_path.is_file():
        config.secret_key_path.write_text(secrets.token_hex(32))
        config.secret_key_path.chmod(0o600)


def gong_tracks(config: Config) -> list[str]:
    return sorted(p.stem for p in config.gongs_dir.glob("*.mp3"))
