"""PIN auth: scrypt hashing, session login, simple lockout."""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time

from flask import session

SCRYPT_N, SCRYPT_R, SCRYPT_P = 16384, 8, 1
MAX_FAILS = 5
LOCKOUT_SECONDS = 60

_fails: dict[str, list[float]] = {}  # ip -> fail timestamps


def hash_pin(pin: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(pin.encode(), salt=salt,
                        n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P)
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${salt.hex()}${dk.hex()}"


def verify_pin(stored: str, pin: str) -> bool:
    if not stored:
        # No PIN set yet (fresh dev DB): allow only the explicit dev override.
        dev = os.environ.get("GONG_DEV_PIN")
        return bool(dev) and hmac.compare_digest(dev, pin)
    try:
        _, n, r, p, salt, want = stored.split("$")
        dk = hashlib.scrypt(pin.encode(), salt=bytes.fromhex(salt),
                            n=int(n), r=int(r), p=int(p))
        return hmac.compare_digest(dk.hex(), want)
    except (ValueError, TypeError):
        return False


def locked_out(ip: str) -> int:
    """Seconds remaining in lockout, 0 if not locked."""
    now = time.monotonic()
    stamps = [t for t in _fails.get(ip, []) if now - t < LOCKOUT_SECONDS]
    _fails[ip] = stamps
    if len(stamps) >= MAX_FAILS:
        return int(LOCKOUT_SECONDS - (now - stamps[0])) + 1
    return 0


def record_failure(ip: str) -> None:
    _fails.setdefault(ip, []).append(time.monotonic())


def login_session() -> None:
    session.clear()
    session["auth"] = True
    session["csrf"] = secrets.token_hex(16)
    session.permanent = True


def csrf_token() -> str:
    return session.get("csrf", "")
