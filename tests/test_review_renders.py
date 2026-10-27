"""The review page's render queue (S7 spec 5.3) with a fake runner: no ffmpeg, no subprocess."""
import signal
import subprocess
import threading
import time
from pathlib import Path

import pytest

from shorts.review import renders
from shorts.review.renders import RenderQueue, last_line


def status_of(states):
    """states: {id: (state, approved)} -> a status() callable shaped like stages.render_status."""
    return lambda: {cid: {"state": s, "version": "4" if s != "not_rendered" else None,
                          "approved": a, "file": s != "not_rendered"}
                    for cid, (s, a) in states.items()}


def drained(q, timeout=3.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        snap = q.snapshot()
        if not snap["queue"] and not any(c["state"] in ("queued", "rendering")
                                         for c in snap["clips"].values()):
            return snap
        time.sleep(0.01)
    raise AssertionError("the queue did not drain")


def test_last_line_takes_the_last_non_empty_line():
    assert last_line("a\n\nc1: FAILED render: boom (details in x)\n\n") == \
        "c1: FAILED render: boom (details in x)"
    assert last_line("") == ""


def test_renders_one_clip_at_a_time_in_order():
    states = {"a": ("not_rendered", True), "b": ("out_of_date", True)}
    running, order, peak = [], [], [0]

    def runner(cid):
        running.append(cid)
        peak[0] = max(peak[0], len(running))
        order.append(cid)
        time.sleep(0.05)
        running.remove(cid)
        states[cid] = ("rendered", True)
        return 0, f"{cid}: render done -> /x/{cid}.mp4"

    q = RenderQueue(status_of(states), lambda cid: Path("/x"), runner=runner)
    q.enqueue("a")
    q.enqueue("b")
    snap = drained(q)
    assert order == ["a", "b"] and peak[0] == 1
    assert snap["clips"]["a"]["state"] == "rendered" and snap["clips"]["b"]["state"] == "rendered"


def test_queued_and_rendering_show_and_duplicates_are_ignored():
    states = {"a": ("not_rendered", True), "b": ("not_rendered", True)}
    release, started, runs = threading.Event(), threading.Event(), []

    def runner(cid):
        runs.append(cid)
        started.set()
        release.wait(3)
        return 0, ""

    q = RenderQueue(status_of(states), lambda cid: Path("/x"), runner=runner)
    q.enqueue("a")
    assert started.wait(3)
    q.enqueue("a")                     # rendering: no-op
    q.enqueue("b")
    q.enqueue("b")                     # queued: no-op
    snap = q.snapshot()
    assert snap["queue"] == ["b"]
    assert snap["clips"]["a"]["state"] == "rendering" and snap["clips"]["b"]["state"] == "queued"
    release.set()
    drained(q)
    assert runs == ["a", "b"]


def test_a_failed_render_keeps_its_last_line_and_can_be_queued_again():
    states = {"a": ("out_of_date", True)}
    codes = [(1, "noise\nc1: FAILED render: ffmpeg failed (details in log)\n"), (0, "")]
    q = RenderQueue(status_of(states), lambda cid: Path("/x"), runner=lambda cid: codes.pop(0))
    q.enqueue("a")
    snap = drained(q)
    assert snap["clips"]["a"]["state"] == "failed"
    assert snap["clips"]["a"]["error"] == "c1: FAILED render: ffmpeg failed (details in log)"
    q.enqueue("a")
    snap = drained(q)
    assert snap["clips"]["a"]["state"] == "out_of_date" and "error" not in snap["clips"]["a"]


def test_a_runner_that_raises_is_a_failed_render():
    def runner(cid):
        raise OSError("no such file: shorts")

    q = RenderQueue(status_of({"a": ("not_rendered", True)}), lambda cid: Path("/x"), runner=runner)
    q.enqueue("a")
    snap = drained(q)
    assert snap["clips"]["a"] == {**snap["clips"]["a"], "state": "failed",
                                  "error": "OSError: no such file: shorts"}


def test_enqueue_refuses_unknown_and_unapproved_clips():
    q = RenderQueue(status_of({"a": ("not_rendered", False)}), lambda cid: Path("/x"),
                    runner=lambda cid: (0, ""))
    with pytest.raises(ValueError, match="unknown clip zz"):
        q.enqueue("zz")
    with pytest.raises(ValueError, match="a is not approved"):
        q.enqueue("a")
    assert q.snapshot()["queue"] == []


def test_enqueue_all_queues_only_clips_that_need_a_render():
    states = {"a": ("not_rendered", True), "b": ("rendered", True),
              "c": ("out_of_date", False), "d": ("out_of_date", True)}
    seen = []
    q = RenderQueue(status_of(states), lambda cid: Path("/x"),
                    runner=lambda cid: (seen.append(cid), (0, ""))[1])
    q.enqueue_all()
    drained(q)
    assert seen == ["a", "d"]


def test_a_clip_rejected_while_queued_is_dropped_before_it_renders():
    states = {"a": ("not_rendered", True), "b": ("not_rendered", True)}
    release, started, runs = threading.Event(), threading.Event(), []

    def runner(cid):
        runs.append(cid)
        started.set()
        release.wait(3)
        return 0, ""

    q = RenderQueue(status_of(states), lambda cid: Path("/x"), runner=runner)
    q.enqueue("a")
    assert started.wait(3)
    q.enqueue("b")
    states["b"] = ("not_rendered", False)           # rejected on the page while queued
    release.set()
    snap = drained(q)
    assert runs == ["a"] and snap["clips"]["b"]["state"] == "not_rendered"


def test_file_uses_the_cheap_id_list_when_given(tmp_path):
    f = tmp_path / "a.mp4"
    f.write_bytes(b"mp4")

    def status():
        raise AssertionError("file() must not compute the full status")

    q = RenderQueue(status, lambda cid: tmp_path / f"{cid}.mp4", runner=lambda cid: (0, ""),
                    ids=lambda: {"a"})
    assert q.file("a") == f and q.file("zz") is None


def test_file_is_served_only_for_candidates_with_a_render(tmp_path):
    f = tmp_path / "a.mp4"
    f.write_bytes(b"mp4")
    q = RenderQueue(status_of({"a": ("rendered", True), "b": ("not_rendered", True)}),
                    lambda cid: tmp_path / f"{cid}.mp4", runner=lambda cid: (0, ""))
    assert q.file("a") == f
    assert q.file("b") is None                       # a candidate without a file
    assert q.file("zz") is None                      # not a candidate


class FakeProc:
    def __init__(self, exits_on=None):
        self.exits_on, self.signals, self.killed, self.rc = exits_on, [], False, None

    def poll(self):
        return self.rc

    def wait(self, timeout=None):
        if self.rc is None:
            raise subprocess.TimeoutExpired("shorts", timeout)
        return self.rc

    def send_signal(self, sig):
        self.signals.append(sig)
        if self.exits_on == "sigint":
            self.rc = -2

    def kill(self):
        self.killed, self.rc = True, -9


def test_stop_signals_a_render_that_outlives_the_grace(monkeypatch):
    monkeypatch.setattr(renders, "STOP_GRACE", 0.0)
    q = RenderQueue(status_of({}), lambda cid: Path("/x"), runner=lambda cid: (0, ""))
    q._proc = FakeProc(exits_on="sigint")
    q.stop()
    assert q._proc.signals == [signal.SIGINT] and not q._proc.killed


def test_stop_kills_a_render_that_ignores_sigint(monkeypatch):
    monkeypatch.setattr(renders, "STOP_GRACE", 0.0)
    q = RenderQueue(status_of({}), lambda cid: Path("/x"), runner=lambda cid: (0, ""))
    q._proc = FakeProc(exits_on=None)
    q.stop()
    assert q._proc.signals == [signal.SIGINT] and q._proc.killed


def test_stop_clears_the_queue():
    release = threading.Event()
    seen = []
    q = RenderQueue(status_of({"a": ("not_rendered", True), "b": ("not_rendered", True)}),
                    lambda cid: Path("/x"),
                    runner=lambda cid: (seen.append(cid), release.wait(3), (0, ""))[2])
    q.enqueue("a")
    q.enqueue("b")
    worker = q._worker
    q.stop()
    release.set()
    worker.join(3)
    assert not worker.is_alive()
    assert q.snapshot()["queue"] == [] and seen in ([], ["a"])
    assert "b" not in seen


def test_stop_while_the_worker_reads_the_status_never_spawns_a_render():
    # Ctrl+C can land while the worker reads review.json (about 0.8 s on a class-sized job), after
    # it popped the clip and before it spawned the subprocess: nothing may start after stop().
    reading, stopped, runs = threading.Event(), threading.Event(), []
    base = status_of({"a": ("not_rendered", True)})

    def status():
        if threading.current_thread().name == "render-queue":   # only the worker's read blocks
            reading.set()
            stopped.wait(3)
        return base()

    q = RenderQueue(status, lambda cid: Path("/x"), runner=lambda cid: (runs.append(cid), (0, ""))[1])
    q.enqueue("a")
    assert reading.wait(3)
    worker = q._worker
    q.stop()
    stopped.set()
    worker.join(3)
    assert not worker.is_alive()
    assert runs == [] and q.snapshot()["clips"]["a"]["state"] == "not_rendered"


def test_the_default_runner_runs_the_command_and_returns_its_output(tmp_path):
    import sys
    q = RenderQueue(status_of({"a": ("not_rendered", True)}), lambda cid: Path("/x"),
                    command=lambda cid: [sys.executable, "-c",
                                         f"print('{cid}: FAILED render: boom'); raise SystemExit(1)"])
    q.enqueue("a")
    snap = drained(q)
    assert snap["clips"]["a"]["state"] == "failed"
    assert snap["clips"]["a"]["error"] == "a: FAILED render: boom"


class PipeProc:
    """A fake Popen for _run_subprocess: communicate() can raise; kill/wait are recorded."""
    def __init__(self, boom=None):
        self.boom, self.killed, self.waited, self.returncode = boom, False, False, 0

    def communicate(self):
        if self.boom:
            raise self.boom
        return "ok\n", None

    def kill(self):
        self.killed, self.returncode = True, -9

    def wait(self, timeout=None):
        self.waited = True
        return self.returncode

    def poll(self):
        return self.returncode


def test_a_communicate_error_kills_and_waits_the_child_before_the_next_clip(monkeypatch):
    procs, events = [], []

    def popen(cmd, **kw):
        assert kw["encoding"] == "utf-8" and kw["errors"] == "replace"
        p = PipeProc(boom=UnicodeDecodeError("utf-8", b"\xff", 0, 1, "bad") if not procs else None)
        procs.append(p)
        events.append(("start", len(procs)))
        return p

    monkeypatch.setattr(renders.subprocess, "Popen", popen)
    q = RenderQueue(status_of({"a": ("not_rendered", True), "b": ("not_rendered", True)}),
                    lambda cid: Path("/x"), command=lambda cid: ["x", cid])
    q.enqueue("a")
    q.enqueue("b")
    snap = drained(q)
    first = procs[0]
    assert first.killed and first.waited
    assert snap["clips"]["a"]["state"] == "failed" and "UnicodeDecodeError" in snap["clips"]["a"]["error"]
    assert len(procs) == 2 and procs[1].killed is False
    assert q._proc is None


def test_a_subprocess_started_after_stop_is_killed_by_its_own_registration(monkeypatch):
    proc = PipeProc()
    monkeypatch.setattr(renders.subprocess, "Popen", lambda cmd, **kw: proc)
    q = RenderQueue(status_of({}), lambda cid: Path("/x"), command=lambda cid: ["x"])
    q.stop()
    code, out = q._run_subprocess("a")
    assert proc.killed and code == -9 and q._proc is None


def test_busy_is_cheap_and_follows_the_queue():
    gate = threading.Event()
    q = RenderQueue(status=lambda: {"c01": {"state": "not_rendered", "approved": True}},
                    render_file=lambda cid: None, runner=lambda cid: (gate.wait(5), (0, ""))[1])
    assert not q.busy()
    q.enqueue("c01")
    assert q.busy()
    gate.set()
    end = time.time() + 5
    while q.busy() and time.time() < end:
        time.sleep(0.02)
    assert not q.busy()
