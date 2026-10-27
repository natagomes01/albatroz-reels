import http.client
import json
import threading
import time
from http.server import ThreadingHTTPServer

import pytest

from shorts import jobs
from shorts.review.audio import AudioPanel, Busy
from shorts.review.server import make_handler

LEVELS = (0, 10, 20, 30)


def make_job(tmp_path):
    master = tmp_path / "m.mp4"
    master.write_bytes(b"x" * 64)
    job = jobs.create_job(tmp_path / "jobs", "j", {"master": str(master)})
    jobs.write_json_atomic(job.words_json, {"version": 1, "words": []})
    jobs.write_json_atomic(job.candidates_json, {"candidates": [{"id": "c01", "segments": []}], "groups": {}})
    jobs.write_json_atomic(job.review_json, {"decisions": {"c01": {"status": "approved"}}})
    return job, master


def files(tmp_path):
    return lambda lv: tmp_path / "audio" / f"excerpt-{lv}.m4a"


def write_excerpts(tmp_path):
    (tmp_path / "audio").mkdir(exist_ok=True)
    for lv in LEVELS:
        files(tmp_path)(lv).write_bytes(b"m4a" * 10)


def wait_until(fn, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if fn():
            return
        time.sleep(0.02)
    raise AssertionError("timed out")


def test_states_from_missing_to_ready(tmp_path):
    job, _ = make_job(tmp_path)
    go = threading.Event()

    def runner():
        go.wait(5)
        write_excerpts(tmp_path)
        return 0, ""
    p = AudioPanel(job, LEVELS, files(tmp_path), runner=runner)
    assert p.state() == {"enabled": True, "levels": [0, 10, 20, 30], "chosen": None,
                         "excerpt": "missing", "error": None}
    assert p.prepare()["excerpt"] == "preparing" and p.preparing()
    go.set()
    wait_until(lambda: p.state()["excerpt"] == "ready")


def test_failure_keeps_the_last_line_and_retries(tmp_path):
    job, _ = make_job(tmp_path)
    p = AudioPanel(job, LEVELS, files(tmp_path), runner=lambda: (2, "x\nerror: UVR not installed\n"))
    p.prepare()
    wait_until(lambda: p.state()["excerpt"] == "failed")
    assert p.state()["error"] == "error: UVR not installed"


def test_prepare_refuses_while_renders_run(tmp_path):
    job, _ = make_job(tmp_path)
    p = AudioPanel(job, LEVELS, files(tmp_path), busy=lambda: True, runner=lambda: (0, ""))
    with pytest.raises(Busy):
        p.prepare()


def test_choose_and_gate(tmp_path):
    job, _ = make_job(tmp_path)
    p = AudioPanel(job, LEVELS, files(tmp_path))
    assert not p.gate_ok()
    assert p.choose(20)["chosen"] == 20 and p.gate_ok()
    assert AudioPanel(job, LEVELS, files(tmp_path), enabled=False).gate_ok()


class FakeRenders:
    def __init__(self):
        self.queued = []

    def snapshot(self):
        return {"clips": {}, "queue": list(self.queued)}

    def enqueue(self, cid):
        self.queued.append(cid)
        return self.snapshot()

    def enqueue_all(self):
        return self.snapshot()

    def file(self, cid):
        return None

    def busy(self):
        return bool(self.queued)


@pytest.fixture
def server(tmp_path):
    job, master = make_job(tmp_path)
    renders = FakeRenders()
    audio = AudioPanel(job, LEVELS, files(tmp_path), busy=renders.busy, runner=lambda: (0, ""))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(job, master, renders, audio))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield httpd, job, renders, audio
    httpd.shutdown()


def call(httpd, method, path, body=None):
    port = httpd.server_address[1]
    c = http.client.HTTPConnection("127.0.0.1", port)
    headers = {"Host": f"127.0.0.1:{port}"}
    data = None
    if method == "POST":
        headers.update({"Content-Type": "application/json", "Origin": f"http://127.0.0.1:{port}"})
        data = json.dumps(body or {})
    c.request(method, path, body=data, headers=headers)
    r = c.getresponse()
    return r.status, dict(r.getheaders()), r.read()


def test_render_is_refused_until_a_strength_is_chosen(server):
    httpd, job, renders, _ = server
    status, _, body = call(httpd, "POST", "/api/render", {"id": "c01"})
    assert status == 409 and json.loads(body)["error"] == "Choose the audio strength first"
    assert call(httpd, "POST", "/api/render-all")[0] == 409 and renders.queued == []
    status, _, body = call(httpd, "POST", "/api/audio", {"dereverb": 20})
    assert status == 200 and json.loads(body)["chosen"] == 20
    assert jobs.read_json(job.review_json)["dereverb"] == 20
    assert call(httpd, "POST", "/api/render", {"id": "c01"})[0] == 200


def test_bad_strength_is_400(server):
    httpd, *_ = server
    assert call(httpd, "POST", "/api/audio", {"dereverb": 15})[0] == 400


def test_excerpt_files_are_served_fresh_and_only_known_levels(server, tmp_path):
    httpd, *_ = server
    write_excerpts(tmp_path)
    status, headers, body = call(httpd, "GET", "/media/excerpt/20.m4a")
    assert status == 200 and headers["Content-Type"] == "audio/mp4"
    assert headers["Cache-Control"] == "no-store" and body == b"m4a" * 10
    assert call(httpd, "GET", "/media/excerpt/15.m4a")[0] == 404
    assert call(httpd, "GET", "/media/excerpt/..%2F20.m4a")[0] == 404


def test_excerpt_and_renders_never_run_together(server):
    # Review Focus 4
    httpd, _, renders, audio = server
    call(httpd, "POST", "/api/audio", {"dereverb": 20})
    renders.queued.append("c01")
    status, _, body = call(httpd, "POST", "/api/audio/prepare")
    assert status == 409 and "renders are running" in json.loads(body)["error"]
    renders.queued.clear()
    audio._preparing = True          # an excerpt in progress
    status, _, body = call(httpd, "POST", "/api/render", {"id": "c01"})
    assert status == 409 and "being prepared" in json.loads(body)["error"]


def test_clip_edit_uses_the_panel_levels(tmp_path):
    job, master = make_job(tmp_path)
    audio = AudioPanel(job, (0, 20, 40), files(tmp_path))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(job, master, None, audio))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        assert call(httpd, "POST", "/api/edit", {"id": "c01", "edit": {"dereverb": 40}})[0] == 200
        assert call(httpd, "POST", "/api/edit", {"id": "c01", "edit": {"dereverb": 30}})[0] == 400
    finally:
        httpd.shutdown()


def test_off_can_be_chosen_without_any_excerpt(server):
    httpd, job, renders, _ = server          # no excerpt files were written
    status, _, body = call(httpd, "POST", "/api/audio", {"dereverb": 0})
    assert status == 200 and json.loads(body)["chosen"] == 0
    assert call(httpd, "POST", "/api/render", {"id": "c01"})[0] == 200
