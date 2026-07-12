"""gongd — wire up threads and serve. `python -m gong_ng`."""
from __future__ import annotations

import logging
import os
import signal
import threading

from waitress import serve

from . import config as configmod
from .clock import Clock
from .player import Player
from .relay import make_relay
from .runtime import AppContext, ensure_data_dir
from .scheduler import Scheduler
from .web import create_app

log = logging.getLogger("gongd")


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("GONG_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    config = configmod.load()
    ensure_data_dir(config)
    clk = Clock(config.time.timezone)
    relay = make_relay(config)
    player = Player(config, relay)
    player.start()
    poke = threading.Event()
    sched = Scheduler(config, clk, player, poke)
    sched.start()

    def shutdown(signum, frame):
        log.info("signal %s — shutting down", signum)
        sched.shutdown()
        player.shutdown()
        player.join(timeout=5)
        relay.close()
        os._exit(0)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    ctx = AppContext(config=config, clock=clk, player=player, poke=poke)
    app = create_app(ctx)
    host, _, port = config.web.listen.rpartition(":")
    log.info("gongd up — data=%s web=%s player=%s",
             config.data_dir, config.web.listen, config.audio.player)
    serve(app, host=host or "0.0.0.0", port=int(port), threads=4)


if __name__ == "__main__":
    main()
