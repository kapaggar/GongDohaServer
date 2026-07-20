"""USB Deshna media control, surfaced in the admin UI (Deshna tab).

Thin wrapper over the bin/gong-usb-media helper, mirroring timeset.py:
- status() reads the world-readable JSON the helper writes on the udev event,
  so the page needs no privilege to show what is plugged in.
- copy()/eject() are the two staff actions, run through the sudo whitelist.

Everything degrades quietly off the appliance (dev laptop, Docker, CI): if the
status file and helper are absent, status() reports "nothing attached" and the
actions return a friendly message instead of raising.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

HELPER = "/opt/gong-ng/bin/gong-usb-media"


def _status_path() -> Path:
    return Path(os.environ.get("GONG_USB_STATUS", "/run/gong/usb-media.json"))


def status() -> dict:
    """What (if anything) is attached. Always returns a dict with 'attached'."""
    try:
        data = json.loads(_status_path().read_text())
    except (OSError, ValueError):
        return {"attached": None}
    if not isinstance(data, dict):
        return {"attached": None}
    data.setdefault("attached", None)
    return data


def _run(action: str) -> tuple[bool, str]:
    if os.environ.get("GONG_FAKE_USBMEDIA") == "1":
        return True, f"(dev) would run gong-usb-media {action}"
    try:
        proc = subprocess.run(
            ["sudo", "-n", HELPER, action],
            capture_output=True, text=True, timeout=600,
        )
    except Exception as exc:
        return False, f"could not run {HELPER}: {exc}"
    out = (proc.stdout or proc.stderr or "").strip()
    if proc.returncode != 0:
        return False, out or f"gong-usb-media {action} failed"
    return True, out or f"{action} done"


def copy() -> tuple[bool, str]:
    """Persist the attached stick's deshna/ onto the SD card (overwrites)."""
    return _run("copy")


def eject() -> tuple[bool, str]:
    """Unbind + unmount the attached stick so it is safe to pull out."""
    return _run("eject")
