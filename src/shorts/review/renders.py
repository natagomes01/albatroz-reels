"""Render queue of the review page (S7 spec 5.3).

One clip at a time, each in its own `shorts render <job> --clip <id>` subprocess, so ffmpeg and
Vision memory goes back to the system after every clip and a crash never takes the page down.
The queue lives in memory; the render state itself is read from disk by `status()`.
"""
from __future__ import annotations

import signal
import subprocess
import threading
from collections.abc import Callable
from pathlib import Path

NEEDS_RENDER = ("not_rendered", "out_of_date", "failed")
STOP_GRACE = 5.0   # seconds a render gets to exit after Ctrl+C, and again after our SIGINT


def last_line(text: str) -> str:
    lines = [l.strip() for l in (text or "").splitlines() if l.strip()]
    return lines[-1][:300] if lines else ""


class RenderQueue:
    def __init__(self, status: Callable[[], dict], render_file: Callable[[str], Path],
                 command: Callable[[str], list[str]] | None = None,
                 runner: Callable[[str], tuple[int, str]] | None = None,
                 ids: Callable[[], set[str]] | None = None):
        self._status = status
        # Candidate ids only: `file()` runs on every byte-range request while a render is watched,
        # and a full status() costs about 0.8 s on a class-sized job.
        self._ids = ids or (lambda: set(self._status()))
        self._render_file = render_file
        self._command = command
        self._runner = runner or self._run_subprocess
        self._lock = threading.Lock()
        self._queue: list[str] = []
        self._overlay: dict[str, dict] = {}     # id -> {"state": queued|rendering|failed, "error"?}
        self._proc: subprocess.Popen | None = None
        self._worker: threading.Thread | None = None
        self._stopping = False

    # ---- read ----
    def snapshot(self) -> dict:
        clips = self._status()
        with self._lock:
            for cid, extra in self._overlay.items():
                if cid in clips:
                    clips[cid] = {**clips[cid], **extra}
            return {"clips": clips, "queue": list(self._queue)}

    def file(self, clip_id: str) -> Path | None:
        if clip_id not in self._ids():
            return None
        path = Path(self._render_file(clip_id))
        return path if path.is_file() else None

    def busy(self) -> bool:
        """A clip is queued or rendering. Cheap (no status read): the audio panel asks it before
        starting the excerpt (S8 audio spec 5.4)."""
        with self._lock:
            return any(o["state"] in ("queued", "rendering") for o in self._overlay.values())

    # ---- write ----
    def enqueue(self, clip_id: str) -> dict:
        st = self._status().get(clip_id)
        if st is None:
            raise ValueError(f"unknown clip {clip_id}")
        if not st["approved"]:
            raise ValueError(f"{clip_id} is not approved")
        self._add([clip_id])
        return self.snapshot()

    def enqueue_all(self) -> dict:
        snap = self.snapshot()
        self._add([cid for cid, s in snap["clips"].items()
                   if s["approved"] and s["state"] in NEEDS_RENDER])
        return self.snapshot()

    def _add(self, ids: list[str]) -> None:
        with self._lock:
            if self._stopping:
                return
            for cid in ids:
                if self._overlay.get(cid, {}).get("state") in ("queued", "rendering"):
                    continue
                self._queue.append(cid)
                self._overlay[cid] = {"state": "queued"}
            if self._queue and self._worker is None:
                self._worker = threading.Thread(target=self._work, name="render-queue", daemon=True)
                self._worker.start()

    # ---- worker ----
    def _work(self) -> None:
        while True:
            with self._lock:
                if self._stopping or not self._queue:
                    self._worker = None      # under the lock: _add starts a new worker if needed
                    return
                cid = self._queue.pop(0)
            try:
                st = self._status().get(cid)
            except Exception as e:  # e.g. a corrupt review.json: say so on that clip
                with self._lock:
                    self._overlay[cid] = {"state": "failed", "error": f"{type(e).__name__}: {e}"[:300]}
                continue
            if not st or not st["approved"]:
                with self._lock:            # rejected or set back to pending while queued
                    self._overlay.pop(cid, None)
                continue
            with self._lock:
                if self._stopping:              # stop() ran while we read the status: never spawn
                    self._overlay.pop(cid, None)
                    continue
                self._overlay[cid] = {"state": "rendering"}
            try:
                code, output = self._runner(cid)
            except Exception as e:  # the subprocess could not even start
                code, output = 1, f"{type(e).__name__}: {e}"
            with self._lock:
                if code == 0:
                    self._overlay.pop(cid, None)
                else:
                    self._overlay[cid] = {"state": "failed",
                                          "error": last_line(output) or f"exit code {code}"}

    def _run_subprocess(self, clip_id: str) -> tuple[int, str]:
        proc = subprocess.Popen(self._command(clip_id), stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, encoding="utf-8", errors="replace")
        with self._lock:
            self._proc = proc
            if self._stopping:                  # stop() already returned: this render must not outlive it
                proc.kill()
        try:
            out, _ = proc.communicate()
        except BaseException:                   # never leave a live child behind the worker
            proc.kill()
            proc.wait()
            raise
        finally:
            with self._lock:
                self._proc = None
        return proc.returncode, out or ""

    # ---- shutdown ----
    def stop(self) -> None:
        """Ctrl+C in Terminal already sent SIGINT to the render (same process group), so it gets
        STOP_GRACE to delete its .tmp.mp4 and exit; then one SIGINT of ours, then a kill.
        If the render ignores SIGINT for 2*STOP_GRACE it is SIGKILLed alone, so its ffmpeg child and
        `<out>.tmp.mp4` can remain; the old .mp4 stays intact."""
        with self._lock:
            self._stopping = True
            self._queue.clear()
            for cid in [c for c, o in self._overlay.items() if o["state"] == "queued"]:
                del self._overlay[cid]
            proc = self._proc
        if proc is None or proc.poll() is not None:
            return
        try:
            proc.wait(timeout=STOP_GRACE)
            return
        except subprocess.TimeoutExpired:
            pass
        proc.send_signal(signal.SIGINT)
        try:
            proc.wait(timeout=STOP_GRACE)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
