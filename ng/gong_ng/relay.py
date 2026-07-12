"""Amplifier relay control via gpiozero/libgpiod, with a dummy for dev/CI."""
from __future__ import annotations

import logging

from .config import Config

log = logging.getLogger(__name__)


class DummyRelay:
    """No-op relay that records transitions (used in dev, CI, and when no
    relay hardware is configured)."""

    def __init__(self):
        self.state = False
        self.transitions: list[str] = []

    def on(self):
        self.state = True
        self.transitions.append("on")
        log.info("relay ON (dummy)")

    def off(self):
        self.state = False
        self.transitions.append("off")
        log.info("relay OFF (dummy)")

    def close(self):
        pass


class GpioRelay:
    def __init__(self, gpio: int, active_low: bool):
        from gpiozero import DigitalOutputDevice  # import only on the Pi

        # active_high inverted for active-low boards; initial_value=False
        # guarantees the amp is OFF the moment the line is claimed.
        self._dev = DigitalOutputDevice(
            gpio, active_high=not active_low, initial_value=False
        )
        log.info("relay on GPIO%d (active_%s)", gpio,
                 "low" if active_low else "high")

    @property
    def state(self) -> bool:
        return bool(self._dev.value)

    def on(self):
        self._dev.on()

    def off(self):
        self._dev.off()

    def close(self):
        self._dev.off()
        self._dev.close()


def make_relay(config: Config):
    if not config.relay.enabled_hw:
        return DummyRelay()
    try:
        return GpioRelay(config.relay.gpio, config.relay.active_low)
    except Exception:
        log.exception("could not claim relay GPIO — falling back to dummy")
        return DummyRelay()
