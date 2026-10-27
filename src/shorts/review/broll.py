"""B-roll worker of the review page (S8B spec 7.1): one thread, one task at a time.

A suggestion runs `shorts broll <job> --clip <id> --force` as a subprocess, so it is a logged run
that `shorts cost` reports, then its moments are merged into review.json here (one undo step). A
search or a pick runs in this process: network and small files only, so it may run while a
render runs.
"""
from __future__ import annotations

import signal
import subprocess
import threading
from collections import deque
from collections.abc import Callable
from pathlib import Path

from shorts import jobs
from shorts.broll import paths, timing
from shorts.broll.files import fetch_pick, media_info, media_kind, own_files, own_pick, save_upload, video_thumb
from shorts.broll.inserts import credits
from shorts.ffmpeg import FFmpegError
from shorts.broll.model import MAX_TERM, MAX_TERMS, check_name, clip_range, fill_ok, in_clip, rule_problems
from shorts.broll.search import ORDER, source_keys
from shorts.broll.sources import Candidate, SourceError, http_download, http_fetch, pixabay_fresh
from shorts.broll.suggest import read_result, search_for, write_result
from shorts.review.renders import STOP_GRACE, last_line
from shorts.review.state import merge_suggestion, set_pick
from shorts.words import load_words

LOW_RES = "low resolution for this layout"


class BrollQueue:
    def __init__(self, job, app, channel, command: Callable[[str], list[str]] | None = None,
                 runner: Callable[[str], tuple[int, str]] | None = None, fetch=http_fetch,
                 download=http_download, info=media_info, keys: dict | None = None, clip_map_fn=None):
        self._job, self._app, self._channel = job, app, channel
        self._command = command
        self._runner = runner or self._run_subprocess
        self._fetch, self._download, self._info = fetch, download, info
        self._keys = keys
        self._clip_map = clip_map_fn or timing.clip_map
        self.upload_cap = app.broll.upload_max_mb << 20
        self._lock = threading.Lock()
        self._tasks: deque[tuple] = deque()
        self._state: dict[str, dict] = {}
        self._current: dict[str, tuple] = {}     # clip id -> the task the worker is running
        self._worker: threading.Thread | None = None
        self._proc: subprocess.Popen | None = None
        self._stopping = False

    # ---- read ----
    def snapshot(self) -> dict:
        with self._lock:
            return {"clips": {cid: dict(s) for cid, s in self._state.items()}}

    def idle(self) -> bool:
        with self._lock:
            return not self._tasks and self._worker is None

    def files(self) -> dict:
        return {"files": own_files(paths.broll_dir(self._app, self._job), info=self._info)}

    def media(self, name: str) -> Path | None:
        if media_kind(name) is None:        # never a .sha256 sidecar or a .part download
            return None
        return self._plain(paths.broll_dir(self._app, self._job), name)

    def thumb(self, name: str) -> Path | None:
        """A candidate's thumbnail; an own video's is made on first ask from the file itself."""
        folder = paths.thumbs_dir(self._app, self._job)
        found = self._plain(folder, name)
        own = name[len("own-"):-len(".jpg")] if name.startswith("own-") and name.endswith(".jpg") else ""
        if found is None and media_kind(own) == "video":
            src = self._plain(paths.broll_dir(self._app, self._job), own)
            if src is not None:
                try:
                    video_thumb(src, folder / name)
                except FFmpegError:
                    return None
                found = self._plain(folder, name)
        return found

    def details(self, clip_id: str) -> dict:
        """Clip times, rule problems and the candidates file of one clip, for its drawer."""
        plan = self._plan(clip_id)
        raw = load_words(self._job.words_json)
        tm = self._time_map(plan)
        cfg = self._app.broll
        moments = [m for m in plan.decision.get("broll") or [] if in_clip(raw, m, plan.spans)]
        ranges = {m["id"]: clip_range(raw, m, tm) for m in moments}
        problems = rule_problems(ranges, tm.duration, cfg)
        for m in moments:
            p = m.get("pick")
            if p and p["kind"] == "image" and not fill_ok(p["w"], p["h"], m["layout"], m["fit"], cfg.min_fill_px):
                problems[m["id"]].append(LOW_RES)
            a, b = ranges[m["id"]]
            if p and p["kind"] == "video" and (p["duration"] or 0) + 1e-6 < b - a:
                problems[m["id"]].append("video shorter than the moment")
        picks = [m["pick"] for m in sorted(moments, key=lambda m: ranges[m["id"]][0]) if m.get("pick")]
        return {"result": read_result(self._job, clip_id), "clip_len": round(tm.duration, 2),
                "ranges": {k: [round(a, 2), round(b, 2)] for k, (a, b) in ranges.items()},
                "problems": problems, "credits": credits(picks, self._channel.language)}

    # ---- write ----
    def suggest(self, clip_id: str) -> dict:
        self._known(clip_id)
        self._add(clip_id, ("suggest", clip_id))
        return self.snapshot()

    def on_approved(self, clip_id: str) -> None:
        """Spec 5.1: approving a clip asks for a suggestion once, if its channel wants it."""
        if not getattr(self._channel, "broll", True) or read_result(self._job, clip_id) is not None:
            return
        with self._lock:
            if self._state.get(clip_id, {}).get("state") in ("queued", "working"):
                return
        self.suggest(clip_id)

    def search(self, clip_id: str, moment_id: str, terms, kind: str | None = None) -> dict:
        self._known(clip_id)
        if (not isinstance(terms, list) or not 1 <= len(terms) <= MAX_TERMS
                or not all(isinstance(t, str) and t.strip() and len(t) <= MAX_TERM for t in terms)):
            raise ValueError(f"terms must be 1 to {MAX_TERMS} search texts of at most {MAX_TERM} characters")
        if kind is not None and kind not in ORDER:
            raise ValueError(f"kind must be one of {sorted(ORDER)}")
        self._add(clip_id, ("search", clip_id, str(moment_id), tuple(" ".join(t.split()) for t in terms), kind))
        return self.snapshot()

    def pick(self, clip_id: str, moment_id: str, key: str) -> dict:
        self._known(clip_id)
        check_name(key)
        self._add(clip_id, ("pick", clip_id, str(moment_id), key))
        return self.snapshot()

    def use_file(self, clip_id: str, moment_id: str, name: str) -> dict:
        pick = own_pick(name, paths.broll_dir(self._app, self._job), info=self._info)
        return set_pick(self._job, clip_id, moment_id, pick, self._app.broll)

    def upload(self, stream, length: int, name: str, ctype: str) -> dict:
        return save_upload(stream, length, name, ctype, paths.broll_dir(self._app, self._job),
                           self.upload_cap, info=self._info)

    # ---- worker ----
    def _add(self, clip_id: str, task: tuple) -> None:
        with self._lock:
            if self._stopping:
                return
            if task in self._tasks or self._current.get(clip_id) == task:
                return
            self._tasks.append(task)
            if clip_id not in self._current:    # the state shown is the running task's until it ends
                self._state[clip_id] = {"state": "queued", "error": None, "task": task[0]}
            if self._worker is None:
                self._worker = threading.Thread(target=self._work, name="broll", daemon=True)
                self._worker.start()

    def _work(self) -> None:
        try:
            while True:
                with self._lock:
                    if self._stopping or not self._tasks:
                        self._worker = None     # same lock hold as the check: _add starts a new worker
                        return
                    task = self._tasks.popleft()
                    clip_id = task[1]
                    self._current[clip_id] = task
                    carried = self._state.get(clip_id, {}).get("error")   # an earlier task's failure stays visible
                    self._state[clip_id] = {"state": "working", "error": carried, "task": task[0]}
                try:
                    self._do(task)
                    outcome = {"state": "idle", "error": None, "task": task[0]}
                except Exception as e:      # one failed task must not stop the worker
                    outcome = {"state": "failed", "error": str(e)[:300] or type(e).__name__, "task": task[0]}
                with self._lock:
                    self._current.pop(clip_id, None)
                    later = next((t for t in self._tasks if t[1] == clip_id), None)
                    if later is None:
                        self._state[clip_id] = outcome
                    else:       # a later task of the clip waits; this task's failure stays shown meanwhile
                        self._state[clip_id] = {"state": "queued", "error": outcome["error"], "task": later[0]}
        finally:
            with self._lock:        # only a BaseException exit still owns the slot; a normal exit cleared it
                if self._worker is threading.current_thread():
                    self._worker = None
                    self._current.clear()
                    for cid, s in self._state.items():
                        if s["state"] == "working":
                            self._state[cid] = {"state": "failed", "error": "stopped", "task": s["task"]}

    def _do(self, task: tuple) -> None:
        kind, clip_id = task[0], task[1]
        if kind == "suggest":
            code, output = self._runner(clip_id)
            if code != 0:
                raise RuntimeError(last_line(output) or f"exit code {code}")
            result = read_result(self._job, clip_id)
            if result is None:
                raise RuntimeError("the suggestion wrote no result")
            merge_suggestion(self._job, clip_id, result.get("moments") or [])
        elif kind == "search":
            _, _, moment_id, terms, wanted = task
            plan = self._plan(clip_id)
            m = self._moment(plan, moment_id)
            raw = load_words(self._job.words_json)
            a, b = clip_range(raw, m, self._time_map(plan))
            result = read_result(self._job, clip_id) or {"version": 1, "moments": [], "kinds": {},
                                                          "candidates": {}, "errors": []}
            kind_of = wanted or result.get("kinds", {}).get(moment_id) or "photo"
            if kind_of == "own":
                kind_of = "photo"
            found, errors = search_for(self._job, self._app, {**m, "terms": list(terms)}, kind_of, b - a,
                                       self._source_keys(), self._fetch)
            result.setdefault("candidates", {})[moment_id] = found
            result["errors"] = ([e for e in result.get("errors", []) if not e.startswith(f"{moment_id}: ")]
                                + [f"{moment_id}: {e}" for e in errors])
            write_result(self._job, clip_id, result)
        elif kind == "pick":
            _, _, moment_id, key = task
            result = read_result(self._job, clip_id) or {}
            cand = next((c for c in (result.get("candidates") or {}).get(moment_id, []) if c.get("key") == key), None)
            if cand is None:
                raise ValueError(f"no candidate {key} for moment {moment_id}")
            pick = self._fetch_pick(Candidate.from_dict(cand))
            set_pick(self._job, clip_id, moment_id, pick, self._app.broll)

    # ---- helpers ----
    def _fetch_pick(self, cand: Candidate) -> dict:
        """Download a pick; a Pixabay link from an older search has expired, so on a failed
        download ask Pixabay for the same hit again and retry once with its new link."""
        get = lambda c: fetch_pick(c, paths.broll_dir(self._app, self._job), self._app.broll.user_agent,  # noqa: E731
                                   download=self._download, info=self._info)
        try:
            return get(cand)
        except SourceError:
            key = self._source_keys().get("pixabay")
            if cand.source != "pixabay" or not key:
                raise
            fresh = pixabay_fresh(cand, self._fetch, key, self._app.broll.user_agent)
            if fresh is None:
                raise SourceError(f"pixabay.com: {cand.key} is no longer on Pixabay; pick another") from None
            return get(fresh)

    def _source_keys(self) -> dict:
        if self._keys is None:
            self._keys = source_keys()
        return self._keys

    def _known(self, clip_id: str) -> None:
        ids = {c["id"] for c in jobs.read_json(self._job.candidates_json, {"candidates": []})["candidates"]}
        if clip_id not in ids:
            raise ValueError(f"unknown clip {clip_id!r}")

    def _plan(self, clip_id: str):
        from shorts.stages import approved_clips     # stages imports clip; keep the page start light
        plan = next((p for p in approved_clips(self._job) if p.id == clip_id), None)
        if plan is None:
            raise ValueError(f"clip {clip_id} is not approved")
        return plan

    def _moment(self, plan, moment_id: str) -> dict:
        m = next((m for m in plan.decision.get("broll") or [] if m.get("id") == moment_id), None)
        if m is None:
            raise ValueError(f"unknown moment {moment_id!r}")
        return m

    def _time_map(self, plan):
        from shorts.stages import effective_clip_words
        master = Path(jobs.read_json(self._job.job_json)["master"])
        return self._clip_map(self._job, plan.id, self._channel, plan.spans,
                              effective_clip_words(self._job, plan), master)

    @staticmethod
    def _plain(folder: Path, name: str) -> Path | None:
        try:
            check_name(name)
        except ValueError:
            return None
        path = folder / name
        return path if path.is_file() and not path.is_symlink() else None

    def _run_subprocess(self, clip_id: str) -> tuple[int, str]:
        proc = subprocess.Popen(self._command(clip_id), stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, encoding="utf-8", errors="replace")
        with self._lock:
            self._proc = proc
            if self._stopping:                  # stop() already returned: this run must not outlive it
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
        """Like RenderQueue.stop: drop the queued tasks, give a running suggestion STOP_GRACE to
        end (Ctrl+C already reached it), then SIGINT, then a kill."""
        with self._lock:
            self._stopping = True
            self._tasks.clear()
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

