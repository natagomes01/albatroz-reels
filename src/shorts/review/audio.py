"""Audio panel of the review page (S8 audio spec 5, 6): the class strength and its excerpt.

The excerpt runs in its own `shorts excerpt <job>` subprocess, like a render, so UVR memory goes
back to the system when it ends; it never starts while a render is queued or running.
"""
from __future__ import annotations

import subprocess
import threading
from collections.abc import Callable
from pathlib import Path

from shorts import jobs
from shorts.dereverb import class_strength
from shorts.review.renders import last_line
from shorts.review.state import set_class_strength


class Busy(ValueError):
    """The excerpt cannot start while a render runs (one heavy job at a time); answered 409."""


class AudioPanel:
    def __init__(self, job, levels, excerpt_file: Callable[[int], Path],
                 command: list[str] | None = None, busy: Callable[[], bool] = lambda: False,
                 runner: Callable[[], tuple[int, str]] | None = None, enabled: bool = True):
        self._job = job
        self.levels = tuple(levels)
        self._excerpt_file = excerpt_file
        self._command = command
        self._busy = busy
        self._runner = runner or self._run_subprocess
        self.enabled = enabled
        self._lock = threading.Lock()
        self._preparing = False
        self._error: str | None = None

    # ---- read ----
    def chosen(self) -> int | None:
        return class_strength(jobs.read_json(self._job.review_json, {"decisions": {}}))

    def ready(self) -> bool:
        return all(Path(self._excerpt_file(lv)).is_file() for lv in self.levels)

    def preparing(self) -> bool:
        with self._lock:
            return self._preparing

    def state(self) -> dict:
        with self._lock:
            preparing, error = self._preparing, self._error
        if preparing:
            excerpt = "preparing"
        elif self.ready():
            excerpt = "ready"
        elif error:
            excerpt = "failed"
        else:
            excerpt = "missing"
        return {"enabled": self.enabled, "levels": list(self.levels), "chosen": self.chosen(),
                "excerpt": excerpt, "error": error if excerpt == "failed" else None}

    def gate_ok(self) -> bool:
        return not self.enabled or self.chosen() is not None

    def file(self, level: int) -> Path | None:
        if level not in self.levels:
            return None
        path = Path(self._excerpt_file(level))
        return path if path.is_file() else None

    # ---- write ----
    def choose(self, value) -> dict:
        set_class_strength(self._job, value, self.levels)
        return self.state()

    def prepare(self) -> dict:
        # ready() and busy() are read outside the lock, and the server's render routes check
        # preparing() before enqueueing: two clicks in the same instant could still start both.
        # One owner on one page; accepted (Fable plan review).
        if not self.enabled:
            raise ValueError("this channel's sound is not treated")
        if self.ready():
            return self.state()
        if self._busy():
            raise Busy("renders are running: prepare the audio excerpt when they finish")
        with self._lock:
            if not self._preparing:
                self._preparing = True
                self._error = None
                threading.Thread(target=self._work, name="audio-excerpt", daemon=True).start()
        return self.state()

    def _work(self) -> None:
        try:
            code, output = self._runner()
        except Exception as e:  # the subprocess could not even start
            code, output = 1, f"{type(e).__name__}: {e}"
        with self._lock:
            self._preparing = False
            self._error = None if code == 0 else (last_line(output) or f"exit code {code}")

    def _run_subprocess(self) -> tuple[int, str]:
        proc = subprocess.run(self._command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              encoding="utf-8", errors="replace")
        return proc.returncode, proc.stdout or ""
