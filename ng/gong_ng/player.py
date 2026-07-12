"""Playback worker: single queue, non-overlapping plays, relay orchestration.

Preemption rules (design §2.3):
  - a new gong job aborts a still-running gong job (never stacks);
  - doha never preempts a gong, it waits in the queue;
  - stop_now() aborts everything.
Stopping a play is SIGTERM to the mpv child, SIGKILL after 2 s.
"""
from __future__ import annotations

import logging
import queue
import shlex
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import db, model
from .config import Config

log = logging.getLogger(__name__)

GONG_KINDS = {"gong", "test_gong"}


@dataclass
class PlayJob:
    kind: str                 # gong | doha | test_gong | test_doha
    file: Path
    repeats: int = 1
    gap_seconds: float = 0.0
    volume: int = 90
    use_relay: bool = False
    settle_seconds: float = 5.0
    label: str = ""
    done: threading.Event = field(default_factory=threading.Event)
    result: str = ""


class Player(threading.Thread):
    def __init__(self, config: Config, relay, db_path: Path | None = None):
        super().__init__(name="player", daemon=True)
        self.config = config
        self.relay = relay
        self.db_path = db_path or config.db_path
        self.queue: queue.Queue[PlayJob | None] = queue.Queue(maxsize=8)
        self._stop_current = threading.Event()
        self._shutdown = threading.Event()
        self._current: PlayJob | None = None
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------ API

    def submit(self, job: PlayJob) -> bool:
        with self._lock:
            if job.kind in GONG_KINDS:
                self._drain(kinds=GONG_KINDS)
                if self._current is not None and self._current.kind in GONG_KINDS:
                    self._stop_current.set()
        try:
            self.queue.put_nowait(job)
            return True
        except queue.Full:
            log.error("player queue full, dropping %s", job.label or job.kind)
            return False

    def stop_now(self) -> None:
        with self._lock:
            self._drain()
            self._stop_current.set()

    def shutdown(self) -> None:
        self._shutdown.set()
        self.stop_now()
        self.queue.put(None)

    @property
    def busy(self) -> bool:
        return self._current is not None or not self.queue.empty()

    def _drain(self, kinds: set[str] | None = None) -> None:
        kept = []
        while True:
            try:
                j = self.queue.get_nowait()
            except queue.Empty:
                break
            if j is not None and kinds is not None and j.kind not in kinds:
                kept.append(j)
            elif j is not None:
                j.result = "stopped"
                j.done.set()
        for j in kept:
            self.queue.put_nowait(j)

    # ------------------------------------------------------------ loop

    def run(self) -> None:
        conn = db.connect(self.db_path)
        self._mixer_setup()
        while not self._shutdown.is_set():
            job = self.queue.get()
            if job is None:
                break
            self._current = job
            self._stop_current.clear()
            try:
                self._execute(conn, job)
            except Exception as exc:
                log.exception("play job failed: %s", job.label or job.kind)
                job.result = "error"
                model.log_play(conn, job.kind, str(job.file), job.repeats,
                               "error", str(exc))
            finally:
                self._current = None
                job.done.set()
        conn.close()

    def _mixer_setup(self) -> None:
        if self.config.audio.player != "mpv":
            return
        for cmd in self.config.audio.mixer_setup:
            try:
                subprocess.run(shlex.split(cmd), capture_output=True, timeout=10)
            except Exception:
                log.warning("mixer setup failed (ignored): %s", cmd)

    def _execute(self, conn, job: PlayJob) -> None:
        if not job.file.is_file():
            log.error("audio file missing: %s", job.file)
            model.log_play(conn, job.kind, str(job.file), job.repeats,
                           "error", "file missing")
            job.result = "error"
            return
        log.info("playing %s: %s x%d vol=%d", job.kind, job.file.name,
                 job.repeats, job.volume)
        stopped = False
        if job.use_relay:
            self.relay.on()
            stopped = not self._interruptible_sleep(job.settle_seconds)
        if not stopped:
            for i in range(job.repeats):
                if self._stop_current.is_set() or self._shutdown.is_set():
                    stopped = True
                    break
                self._play_file(job.file, job.volume)
                if i < job.repeats - 1 and job.gap_seconds > 0:
                    if not self._interruptible_sleep(job.gap_seconds):
                        stopped = True
                        break
        if job.use_relay:
            self.relay.off()
        job.result = "stopped" if stopped else "ok"
        model.log_play(conn, job.kind, str(job.file), job.repeats,
                       job.result, job.label)

    def _interruptible_sleep(self, seconds: float) -> bool:
        """True if the full wait elapsed, False if stopped."""
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if self._stop_current.is_set() or self._shutdown.is_set():
                return False
            time.sleep(min(0.1, max(0.0, deadline - time.monotonic())))
        return True

    def _play_file(self, file: Path, volume: int) -> None:
        volume = max(0, min(100, int(volume)))
        if self.config.audio.player == "dummy":
            self._interruptible_sleep(self.config.audio.dummy_seconds)
            return
        cmd = ["mpv", "--really-quiet", "--no-video", f"--volume={volume}"]
        if self.config.audio.alsa_device:
            cmd.append(f"--audio-device={self.config.audio.alsa_device}")
        cmd.append(str(file))
        try:
            self._proc = subprocess.Popen(
                cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        except FileNotFoundError:
            raise RuntimeError(
                "mpv not installed — set [audio] player=\"dummy\" for dev"
            ) from None
        try:
            while self._proc.poll() is None:
                if self._stop_current.is_set() or self._shutdown.is_set():
                    self._proc.terminate()
                    try:
                        self._proc.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        self._proc.kill()
                        self._proc.wait()
                    break
                time.sleep(0.1)
        finally:
            self._proc = None
