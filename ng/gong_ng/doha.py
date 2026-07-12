"""Doha track selection (design §5.5)."""
from __future__ import annotations

import json
import random
from pathlib import Path

from .model import CourseCtx, Settings

SLOTS = range(1, 12)  # 1..11


def legacy_modular(day: int, total: int, anapana: int) -> int:
    """Byte-for-byte the legacy algorithm (app/dhamma/doha.php:66-83)."""
    if day <= anapana:
        slot = ((day - 1) % 3) + 1                      # anapana: 1,2,3 cycle
    elif day == anapana + 1:
        slot = 4                                        # first vipassana day
    else:
        slot = 3 + ((day - (anapana + 1)) % 6) + 1      # 4..9 cycle
    metta_days = 2 if total >= 30 else 1
    if day == total:
        slot = 11                                       # homage, last day
    elif day >= total - metta_days:
        slot = 10                                       # metta day(s)
    return slot


def load_manifest(path: Path) -> dict[int, str]:
    data = json.loads(path.read_text())
    return {int(k): v for k, v in data.items()}


def pick_slot(settings: Settings, ctx: CourseCtx | None) -> int | None:
    """Slot to play today, or None for no doha."""
    if ctx is not None and 0 < ctx.day <= ctx.total_days:
        return legacy_modular(ctx.day, ctx.total_days, ctx.anapana_days)
    mode = settings.get("no_course_doha")
    if mode == "off":
        return None
    if mode.startswith("slot:"):
        slot = int(mode.split(":", 1)[1])
        return slot if slot in SLOTS else None
    return random.choice(SLOTS)  # 'random' — legacy behaviour
