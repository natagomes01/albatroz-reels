import http.client
import json
import threading
import time
from http.server import ThreadingHTTPServer

import pytest

from shorts import jobs
from shorts.broll.model import BrollConfig
from shorts.broll.paths import broll_dir, thumbs_dir
from shorts.broll.suggest import read_result, write_result
from shorts.config import AppConfig, ChannelConfig
from shorts.review.broll import BrollQueue
from shorts.review.server import make_handler
from shorts.timeline import TimeMap

CH = ChannelConfig(id="catholic-br", language="pt", brand_dir=None, glossary="")
CAND = {"source": "commons", "id": "1", "kind": "image", "w": 4000, "h": 2000, "duration": None,
        "thumb_url": "t", "download_url": "https://x/1.jpg", "title": "Ceia", "author": "L",
        "license": "Public domain", "license_url": "", "page_url": "p", "key": "commons-1"}


def moment(mid, first, last, **kw):
    return {"id": mid, "origin": "llm", "first": first, "last": last, "layout": "full", "fit": "cover",
            "pan": "still", "focus": [0.5, 0.5], "terms": ["altar"], "note": "", "pick": None, **kw}


def make_job(tmp_path, status="approved", broll=None):
    job = jobs.create_job(tmp_path / "jobs", "260927-a", {
        "channel": "catholic-br", "format": "solo-standing", "master": str(tmp_path / "m.mp4")})
    (tmp_path / "m.mp4").write_bytes(b"\x00" * 16)
    words = [{"t": i * 0.5, "w": f"w{i}", "p": 1} for i in range(400)]
    jobs.write_json_atomic(job.words_json, {"version": 1, "words": words})
    cand = {"id": "c01", "window_id": "w1", "title": "T", "hook": "H", "total": 80.0,
            "segments": [{"window_id": "w1", "first_words": "", "last_words": "",
                          "proposed": [10.0, 50.0], "snapped": [9.65, 50.45]}],
            "scores": {}, "controversy": 1, "controversy_why": "", "who_reacts": "P", "emphasis": [],
            "hook_id": "h01", "out_of_order": False, "too_long": False, "blind": None, "faithful": None,
            "verdict": "publish", "warnings": []}
    jobs.write_json_atomic(job.candidates_json, {"candidates": [cand], "groups": {"h01": ["c01"]}})
    d = {"status": status, **({"broll": broll} if broll else {})}
    jobs.write_json_atomic(job.review_json, {"decisions": {"c01": d}})
    return job


def app(tmp_path):
    return AppConfig(media_root=tmp_path / "media", jobs_dir=tmp_path / "jobs", backends={},
                     broll=BrollConfig(user_agent="ua", upload_max_mb=1))


def plain_map(job, clip_id, channel, spans, words, master):
    return TimeMap(list(spans))


def info(path):
    return {"w": 4000, "h": 2000, "duration": None, "hdr": False}


def download(url, dest, headers, max_bytes):
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(b"jpg")


def queue(tmp_path, job, runner=None, **kw):
    return BrollQueue(job, app(tmp_path), CH, runner=runner, fetch=lambda u, h: b"{}", download=download,
                      info=info, keys={}, clip_map_fn=plain_map, **kw)


def wait(q):
    for _ in range(200):
        if q.idle():
            return
        time.sleep(0.02)
    raise AssertionError("the B-roll worker did not finish")


def writes_result(job, moments):
    def runner(clip_id):
        write_result(job, clip_id, {"version": 1, "moments": moments, "kinds": {m["id"]: "painting" for m in moments},
                                    "candidates": {m["id"]: [CAND] for m in moments}, "errors": []})
        return 0, "c01: 1 B-roll moments"
    return runner


def test_a_suggestion_runs_the_command_and_merges_one_undo_step(tmp_path):
    job = make_job(tmp_path, broll=[moment("o1", 60, 65, origin="owner")])
    q = queue(tmp_path, job, runner=writes_result(job, [moment("s1", 26, 31)]))
    q.suggest("c01")
    wait(q)
    saved = jobs.read_json(job.review_json)["decisions"]["c01"]["broll"]
    assert [m["id"] for m in saved] == ["o1", "s1"] and q.snapshot()["clips"]["c01"]["state"] == "idle"


def test_a_failed_suggestion_shows_the_last_line(tmp_path):
    job = make_job(tmp_path)
    q = queue(tmp_path, job, runner=lambda cid: (2, "something\nerror: LLM usage limit reached"))
    q.suggest("c01")
    wait(q)
    s = q.snapshot()["clips"]["c01"]
    assert s["state"] == "failed" and s["error"] == "error: LLM usage limit reached"


def test_approval_suggests_once(tmp_path):
    job = make_job(tmp_path)
    gate = threading.Event()
    calls = []

    def runner(cid):
        calls.append(cid)
        gate.wait(5)
        return writes_result(job, [])(cid)
    q = queue(tmp_path, job, runner=runner)
    q.on_approved("c01")
    q.on_approved("c01")
    q.suggest("c01")              # the same task while it is queued or working: not added again
    gate.set()
    wait(q)
    assert calls == ["c01"]
    q.on_approved("c01")          # a result exists: approval does not ask again
    wait(q)
    assert calls == ["c01"]


def test_no_automatic_suggestion_when_the_channel_turns_it_off(tmp_path):
    from dataclasses import replace
    job = make_job(tmp_path)
    q = BrollQueue(job, app(tmp_path), replace(CH, broll=False), runner=lambda cid: pytest.fail("ran"),
                   keys={}, clip_map_fn=plain_map)
    q.on_approved("c01")
    assert q.idle()


def test_search_updates_the_candidates_and_pick_downloads_and_sets_the_pick(tmp_path, monkeypatch):
    job = make_job(tmp_path, broll=[moment("o1", 26, 31, origin="owner")])
    found = []

    def fake_search(job_, app_, m, kind, duration, keys, fetch=None, now=None):
        found.append((m["terms"], kind, round(duration, 2)))
        return [CAND], ["pexels: HTTP Error 401"]
    monkeypatch.setattr("shorts.review.broll.search_for", fake_search)
    q = queue(tmp_path, job)
    q.search("c01", "o1", ["Last Supper"])
    wait(q)
    assert found == [(["Last Supper"], "photo", 3.0)]
    res = read_result(job, "c01")
    assert res["candidates"]["o1"][0]["key"] == "commons-1" and res["errors"] == ["o1: pexels: HTTP Error 401"]
    q.pick("c01", "o1", "commons-1")
    wait(q)
    m = jobs.read_json(job.review_json)["decisions"]["c01"]["broll"][0]
    assert m["pick"]["file"] == "commons-1.jpg" and m["pan"] == "ltr"
    assert (broll_dir(app(tmp_path), job) / "commons-1.jpg").exists()


def test_bad_requests_are_refused_before_queueing(tmp_path):
    job = make_job(tmp_path)
    q = queue(tmp_path, job)
    with pytest.raises(ValueError):
        q.search("c01", "o1", ["a", "b", "c", "d"])
    with pytest.raises(ValueError):
        q.search("c01", "o1", "Last Supper")
    with pytest.raises(ValueError):
        q.suggest("c99")
    with pytest.raises(ValueError):
        q.pick("c01", "o1", "../x")


def test_use_file_and_files(tmp_path):
    job = make_job(tmp_path, broll=[moment("o1", 26, 31, origin="owner")])
    q = queue(tmp_path, job)
    d = broll_dir(app(tmp_path), job)
    d.mkdir(parents=True)
    (d / "own-a.png").write_bytes(b"x")
    assert [f["name"] for f in q.files()["files"]] == ["own-a.png"]
    res = q.use_file("c01", "o1", "own-a.png")
    assert res["broll"][0]["pick"]["source"] == "own" and res["undo"] == 1


def test_details_give_clip_times_and_warnings(tmp_path):
    small = {"source": "pixabay", "id": "9", "kind": "image", "file": "pixabay-9.jpg", "download_url": "u",
             "w": 1280, "h": 853, "duration": None, "title": "", "author": "", "license": "",
             "license_url": "", "page_url": ""}
    job = make_job(tmp_path, broll=[moment("o1", 20, 23, origin="owner", pick=small)])
    d = queue(tmp_path, job).details("c01")
    assert d["ranges"]["o1"] == pytest.approx([0.35, 2.35]) and d["clip_len"] == pytest.approx(40.8)
    assert "starts in the first 3 s" in d["problems"]["o1"]
    assert "low resolution for this layout" in d["problems"]["o1"]
    assert d["result"] is None and d["credits"] == ""          # an empty licence needs no credit


# ---- routes ----

@pytest.fixture
def bserver(tmp_path):
    job = make_job(tmp_path, status="approved", broll=[moment("o1", 26, 31, origin="owner")])
    q = queue(tmp_path, job, runner=writes_result(job, []))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(job, tmp_path / "m.mp4", broll=q))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield httpd, q, job, tmp_path
    httpd.shutdown()


def call(httpd, method, path, body=None, headers=None):
    c = http.client.HTTPConnection("127.0.0.1", httpd.server_address[1])
    c.request(method, path, body=body, headers=headers or {})
    r = c.getresponse()
    return r.status, r.read()


def own(httpd, ctype="application/json"):
    return {"Content-Type": ctype, "Origin": f"http://127.0.0.1:{httpd.server_address[1]}"}


def test_approving_on_the_page_queues_a_suggestion(bserver):
    httpd, q, job, _ = bserver
    status, _ = call(httpd, "POST", "/api/decision", json.dumps({"id": "c01", "status": "approved"}), own(httpd))
    assert status == 200
    wait(q)
    assert read_result(job, "c01") is not None
    status, body = call(httpd, "GET", "/api/broll")
    assert status == 200 and json.loads(body)["clips"]["c01"]["state"] == "idle"


def test_upload_route_checks_origin_type_and_size(bserver):
    httpd, q, job, tmp_path = bserver
    hdr = {**own(httpd, "image/png"), "X-File-Name": "..%2FTela%201.png"}
    status, body = call(httpd, "POST", "/api/broll/upload", b"png", hdr)
    assert status == 200 and json.loads(body)["name"] == "own-Tela-1.png"
    assert (broll_dir(app(tmp_path), job) / "own-Tela-1.png").exists()
    status, _ = call(httpd, "POST", "/api/broll/upload", b"x", {**hdr, "Content-Type": "application/x-msdownload"})
    assert status == 415
    status, _ = call(httpd, "POST", "/api/broll/upload", b"x",
                     {**hdr, "Content-Length": str((1 << 20) + 1)})   # never read past the header
    assert status == 413
    status, _ = call(httpd, "POST", "/api/broll/upload", b"png", {**hdr, "Origin": "https://evil.example"})
    assert status == 403


def test_media_routes_serve_only_plain_names(bserver):
    httpd, q, job, tmp_path = bserver
    t = thumbs_dir(app(tmp_path), job)
    t.mkdir(parents=True)
    (t / "commons-1.jpg").write_bytes(b"jpgdata")
    status, body = call(httpd, "GET", "/media/broll-thumb/commons-1.jpg")
    assert status == 200 and body == b"jpgdata"
    assert call(httpd, "GET", "/media/broll-thumb/..%2F..%2Fjob.json")[0] == 404
    assert call(httpd, "GET", "/media/broll/missing.jpg")[0] == 404


def test_json_routes(bserver):
    httpd, q, job, _ = bserver
    status, body = call(httpd, "GET", "/api/broll/candidates/c01")
    assert status == 200 and "ranges" in json.loads(body)
    status, _ = call(httpd, "POST", "/api/broll/search", json.dumps({"id": "c01", "moment": "o1", "terms": "x"}),
                     own(httpd))
    assert status == 400
    status, _ = call(httpd, "POST", "/api/broll/suggest", json.dumps({"id": "c01"}), own(httpd, "text/plain"))
    assert status == 415


def test_broll_routes_are_404_without_a_queue(tmp_path):
    job = make_job(tmp_path)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(job, tmp_path / "m.mp4"))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        assert call(httpd, "GET", "/api/broll")[0] == 404
        assert call(httpd, "POST", "/api/broll/suggest", json.dumps({"id": "c01"}), own(httpd))[0] == 404
    finally:
        httpd.shutdown()


# ---- fix round 1 ----

class _WideLock:
    """A lock that runs a hook on the release of the worker's empty-check hold (the second hold,
    after a task, with nothing queued or running), so an add lands in the exit window."""
    def __init__(self, q, hook):
        self._l, self.q, self.hook, self.seen = threading.Lock(), q, hook, 0

    def __enter__(self):
        self._l.acquire()

    def __exit__(self, *a):
        quiet = not self.q._tasks and not self.q._current
        self._l.release()
        if quiet and self.q._ran:
            self.seen += 1
            if self.seen == 2 and self.hook:
                hook, self.hook = self.hook, None
                hook()


def test_a_task_added_right_after_the_worker_empty_check_is_not_stranded(tmp_path):
    job = make_job(tmp_path)
    calls = []

    def runner(cid):
        calls.append(cid)
        q._ran = True
        return writes_result(job, [])(cid)
    q = queue(tmp_path, job, runner=runner)
    q._ran = False
    q._lock = _WideLock(q, lambda: q.suggest("c01"))
    q.suggest("c01")
    for _ in range(100):
        if len(calls) == 2 and q.idle():
            break
        time.sleep(0.02)
    assert len(calls) == 2 and q.snapshot()["clips"]["c01"]["state"] == "idle"


def test_a_failure_is_kept_and_the_running_task_is_shown(tmp_path, monkeypatch):
    job = make_job(tmp_path, broll=[moment("o1", 26, 31, origin="owner")])
    gate, gate2 = threading.Event(), threading.Event()

    def runner(cid):
        gate.wait(5)
        return 2, "error: LLM usage limit reached"

    def slow_search(*a, **k):
        gate2.wait(5)
        return [], []
    monkeypatch.setattr("shorts.review.broll.search_for", slow_search)
    q = queue(tmp_path, job, runner=runner)

    def state():
        return q.snapshot()["clips"]["c01"]
    q.suggest("c01")
    for _ in range(100):
        if state()["state"] == "working":
            break
        time.sleep(0.02)
    q.search("c01", "o1", ["x"])
    assert state()["state"] == "working" and state()["task"] == "suggest"
    gate.set()
    for _ in range(100):
        if state()["task"] == "search" and state()["state"] == "working":
            break
        time.sleep(0.02)
    assert state()["task"] == "search" and state()["error"] == "error: LLM usage limit reached"
    gate2.set()
    wait(q)


def test_upload_disk_fault_is_500(bserver, monkeypatch):
    httpd, q, job, _ = bserver

    def boom(*a):
        raise OSError("disk full")
    monkeypatch.setattr(q, "upload", boom)
    hdr = {**own(httpd, "image/png"), "X-File-Name": "a.png"}
    assert call(httpd, "POST", "/api/broll/upload", b"png", hdr)[0] == 500


def test_details_errors_answer_json(bserver, monkeypatch):
    httpd, q, job, _ = bserver

    def boom(cid):
        raise RuntimeError("ffmpeg failed")
    monkeypatch.setattr(q, "details", boom)
    status, body = call(httpd, "GET", "/api/broll/candidates/c01")
    assert status == 500 and json.loads(body)["error"] == "ffmpeg failed"


def test_an_old_worker_exit_does_not_fail_the_new_workers_task(tmp_path):
    job = make_job(tmp_path)
    gate = threading.Event()
    calls = []

    def runner(cid):
        calls.append(cid)
        if len(calls) == 2:
            gate.wait(5)
        return writes_result(job, [])(cid)
    q = queue(tmp_path, job, runner=runner)
    q._ran = False
    orig = runner

    def runner2(cid):
        q._ran = True
        return orig(cid)
    q._runner = runner2
    q._lock = _WideLock(q, lambda: (q.suggest("c01"), time.sleep(0.2)))   # the new worker pops before the old finally
    q.suggest("c01")
    for _ in range(100):
        if len(calls) == 2:
            break
        time.sleep(0.02)
    time.sleep(0.3)
    s = q.snapshot()["clips"]["c01"]
    assert len(calls) == 2 and s["state"] == "working" and s["error"] is None
    assert q._current.get("c01") is not None
    gate.set()
    wait(q)


def test_get_route_programming_error_logs_and_answers_json(bserver, monkeypatch, capsys):
    httpd, q, job, _ = bserver
    monkeypatch.setattr(q, "files", lambda: (_ for _ in ()).throw(KeyError("boom")))
    status, body = call(httpd, "GET", "/api/broll/files")
    assert status == 500 and "boom" in json.loads(body)["error"]
    assert "KeyError" in capsys.readouterr().err


def test_an_expired_pixabay_link_is_asked_again_by_id(tmp_path):
    from shorts.broll.sources import SourceError
    job = make_job(tmp_path, broll=[moment("o1", 26, 31, origin="owner")])
    old = {**CAND, "source": "pixabay", "id": "5", "key": "pixabay-5", "download_url": "https://pixabay.com/get/old.jpg"}
    write_result(job, "c01", {"version": 1, "moments": [], "kinds": {}, "candidates": {"o1": [old]}, "errors": []})
    got = []

    def dl(url, dest, headers, max_bytes):
        got.append(url)
        if "old" in url:
            raise SourceError("pixabay.com: HTTP Error 400: Bad Request")
        download(url, dest, headers, max_bytes)
    fresh = json.dumps({"hits": [{"id": 5, "largeImageURL": "https://pixabay.com/get/new.jpg"}]}).encode()
    q = BrollQueue(job, app(tmp_path), CH, fetch=lambda u, h: fresh, download=dl, info=info,
                   keys={"pixabay": "K"}, clip_map_fn=plain_map)
    q.pick("c01", "o1", "pixabay-5")
    wait(q)
    m = jobs.read_json(job.review_json)["decisions"]["c01"]["broll"][0]
    assert got == ["https://pixabay.com/get/old.jpg", "https://pixabay.com/get/new.jpg"]
    assert m["pick"]["download_url"] == "https://pixabay.com/get/new.jpg"
    assert q.snapshot()["clips"]["c01"]["state"] == "idle"


def test_an_own_video_gets_its_thumbnail_on_first_ask(tmp_path, monkeypatch):
    job = make_job(tmp_path)
    q = queue(tmp_path, job)
    d = broll_dir(app(tmp_path), job)
    d.mkdir(parents=True)
    (d / "own-mira.mp4").write_bytes(b"x")
    made = []

    def fake_thumb(src, dest):
        made.append(src.name)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"jpg")
    monkeypatch.setattr("shorts.review.broll.video_thumb", fake_thumb)
    assert q.thumb("own-own-mira.mp4.jpg") == thumbs_dir(app(tmp_path), job) / "own-own-mira.mp4.jpg"
    assert q.thumb("own-own-mira.mp4.jpg") is not None and made == ["own-mira.mp4"]
    assert q.thumb("own-own-gone.mp4.jpg") is None and q.thumb("own-own-a.png.jpg") is None
