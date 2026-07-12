"""Set the system clock via the sudo-whitelisted helper (design §4).

The helper (bin/gong-settime) is the only privileged operation in the
appliance; both sides validate the argument strictly.
"""
from __future__ import annotations

import os
import subprocess
from datetime import datetime

HELPER = "/opt/gong-ng/bin/gong-settime"


def validate(value: str) -> datetime:
    """Strict 'YYYY-MM-DD HH:MM' — a real calendar parse, so 99:99 and
    Feb 30 are rejected (fixes legacy finding #3)."""
    return datetime.strptime(value, "%Y-%m-%d %H:%M")


def set_system_time(value: str) -> tuple[bool, str]:
    try:
        validate(value)
    except ValueError:
        return False, "Invalid date/time — use YYYY-MM-DD HH:MM"
    if os.environ.get("GONG_FAKE_SETTIME") == "1":
        return True, f"(dev) would set clock to {value}"
    try:
        proc = subprocess.run(
            ["sudo", "-n", HELPER, value],
            capture_output=True, text=True, timeout=30,
        )
    except Exception as exc:
        return False, f"could not run {HELPER}: {exc}"
    if proc.returncode != 0:
        return False, (proc.stderr or proc.stdout or "gong-settime failed").strip()
    return True, f"Clock set to {value}"
