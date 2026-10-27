# tests/test_review_server.py
import http.client
import json
import threading
from http.server import ThreadingHTTPServer

import pytest

from shorts import jobs
from shorts.review.server import RangeNotSatisfiable, make_handler, parse_range


@pytest.mark.parametrize("header,size,expected", [
    (None, 1000, None),
    ("bytes=0-", 1000, (0, 999)),
    ("bytes=0-1", 1000, (0, 1)),
    ("bytes=100-199", 1000, (100, 199)),
    ("bytes=-500", 1000, (500, 999)),
    ("bytes=900-5000", 1000, (900, 999)),
    ("bytes=0-10,20-30", 1000, None),
])
def test_parse_range(header, size, expected):
    assert parse_range(header, size) == expected


@pytest.mark.parametrize("header", ["bytes=1000-", "bytes=abc", "items=0-1", "bytes=5-2"])
def test_parse_range_invalid(header):
    with pytest.raises(RangeNotSatisfiable):
        parse_range(header, 1000)


@pytest.fixture
def server(tmp_path):
    master = tmp_path / "m.mp4"
    master.write_bytes(bytes(range(256)) * 4)
    job = jobs.create_job(tmp_path / "jobs", "j", {"master": str(master)})
    jobs.write_json_atomic(job.words_json, {"version": 1, "words": []})
    jobs.write_json_atomic(job.candidates_json, {"candidates": [], "groups": {}})
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(job, master))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield httpd, master, job
    httpd.shutdown()


def get(httpd, path, headers=None):
    c = http.client.HTTPConnection("127.0.0.1", httpd.server_address[1])
    c.request("GET", path, headers=headers or {})
    r = c.getresponse()
    return r.status, dict(r.getheaders()), r.read()


def test_safari_probe_gets_two_bytes(server):
    httpd, _, _ = server
    status, headers, body = get(httpd, "/media/master", {"Range": "bytes=0-1"})
    assert status == 206 and body == b"\x00\x01"
    assert headers["Content-Range"] == "bytes 0-1/1024"
    assert headers["Accept-Ranges"] == "bytes"


def test_full_file_without_range(server):
    httpd, _, _ = server
    status, headers, body = get(httpd, "/media/master")
    assert status == 200 and len(body) == 1024


def test_unsatisfiable_is_416(server):
    httpd, _, _ = server
    status, headers, _ = get(httpd, "/media/master", {"Range": "bytes=5000-"})
    assert status == 416 and headers["Content-Range"] == "bytes */1024"


def test_missing_master_is_404_json(server):
    httpd, master, _ = server
    master.unlink()
    status, _, body = get(httpd, "/media/master")
    assert status == 404 and "master not found" in json.loads(body)["error"]


def test_api_job_and_static(server):
    httpd, _, _ = server
    status, _, body = get(httpd, "/api/job")
    assert status == 200 and json.loads(body)["job"] == "j"
    status, _, body = get(httpd, "/")
    assert status == 200 and b"<html" in body.lower()
    status, _, _ = get(httpd, "/static/../../etc/passwd")
    assert status == 404


def req(httpd, method, path, body=None, headers=None):
    c = http.client.HTTPConnection("127.0.0.1", httpd.server_address[1])
    c.request(method, path, body=body, headers=headers or {})
    r = c.getresponse()
    return r.status, dict(r.getheaders()), r.read()


def test_foreign_host_is_refused(server):
    httpd, _, _ = server
    status, _, _ = req(httpd, "GET", "/api/job", headers={"Host": "evil.example:8765"})
    assert status == 403
    status, _, _ = req(httpd, "GET", "/media/master", headers={"Host": "attacker.test"})
    assert status == 403


def test_post_requires_json_and_same_origin(server):
    httpd, _, _ = server
    port = httpd.server_address[1]
    body = json.dumps({"id": "c01", "status": "approved"})
    own = f"http://127.0.0.1:{port}"
    status, _, _ = req(httpd, "POST", "/api/decision", body,
                       {"Content-Type": "text/plain", "Origin": own})
    assert status == 415                               # a no-cors form post
    status, _, _ = req(httpd, "POST", "/api/decision", body,
                       {"Content-Type": "application/json", "Origin": "https://evil.example"})
    assert status == 403
    status, _, _ = req(httpd, "POST", "/api/decision", body, {"Content-Type": "application/json"})
    assert status == 403                               # no Origin at all


def test_malformed_post_is_400_not_a_dropped_connection(server):
    httpd, _, _ = server
    own = {"Content-Type": "application/json", "Origin": f"http://127.0.0.1:{httpd.server_address[1]}"}
    for body in ["[1, 2]", '{"id": "c01"}', '{"id": "c01", "edit": "x"}', "not json"]:
        path = "/api/edit" if "edit" in body or body.startswith("[") or body == "not json" else "/api/decision"
        status, _, payload = req(httpd, "POST", path, body, own)
        assert status == 400 and "error" in json.loads(payload)


def test_head_and_mov_content_type(tmp_path):
    master = tmp_path / "260927-a.mov"
    master.write_bytes(b"\x00" * 64)
    job = jobs.create_job(tmp_path / "jobs", "j", {"master": str(master)})
    jobs.write_json_atomic(job.words_json, {"version": 1, "words": []})
    jobs.write_json_atomic(job.candidates_json, {"candidates": [], "groups": {}})
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(job, master))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        status, headers, body = req(httpd, "HEAD", "/media/master")
        assert status == 200 and body == b""
        assert headers["Content-Type"] == "video/quicktime" and headers["Content-Length"] == "64"
        status, headers, body = req(httpd, "GET", "/media/master", headers={"Range": "bytes=0-3"})
        assert status == 206 and headers["Content-Type"] == "video/quicktime" and len(body) == 4
    finally:
        httpd.shutdown()


def test_bad_content_length_is_400(server):
    httpd, _, _ = server
    own = {"Content-Type": "application/json", "Origin": f"http://127.0.0.1:{httpd.server_address[1]}"}
    for value in ["abc", "-5"]:
        status, _, payload = req(httpd, "POST", "/api/edit", None, {**own, "Content-Length": value})
        assert status == 400 and "error" in json.loads(payload)


def test_nan_segment_over_http_is_400_and_review_unchanged(server):
    httpd, _, job = server
    jobs.write_json_atomic(job.words_json, {"version": 1, "words": [
        {"t": i * 0.5, "w": f"w{i}.", "p": 1} for i in range(200)]})
    jobs.write_json_atomic(job.candidates_json, {"candidates": [{"id": "c01", "segments": []}],
                                                 "groups": {}})
    own = {"Content-Type": "application/json", "Origin": f"http://127.0.0.1:{httpd.server_address[1]}"}
    for seg in ["[[NaN, NaN]]", "[[NaN, 5]]", "[[true, 5]]", "[[0, Infinity]]"]:
        body = '{"id": "c01", "edit": {"segments": %s}}' % seg
        status, _, payload = req(httpd, "POST", "/api/edit", body, own)
        assert status == 400 and "error" in json.loads(payload)
    assert not job.review_json.exists()


def test_corrupt_review_json_is_a_json_error_not_a_dropped_connection(server):
    httpd, _, job = server
    job.review_json.write_text("<<<<<<< HEAD\n", encoding="utf-8")
    status, _, payload = get(httpd, "/api/job")
    assert status == 500 and "review.json is not valid JSON" in json.loads(payload)["error"]
    own = {"Content-Type": "application/json", "Origin": f"http://127.0.0.1:{httpd.server_address[1]}"}
    status, _, payload = req(httpd, "POST", "/api/decision",
                             '{"id": "c01", "status": "approved"}', own)
    assert status in (400, 500) and "error" in json.loads(payload)


def test_valid_same_origin_edit_and_decision_return_200(server):
    httpd, _, job = server
    jobs.write_json_atomic(job.candidates_json, {"candidates": [{"id": "c01", "segments": []}],
                                                 "groups": {}})
    own = {"Content-Type": "application/json", "Origin": f"http://127.0.0.1:{httpd.server_address[1]}"}
    status, _, payload = req(httpd, "POST", "/api/edit",
                             json.dumps({"id": "c01", "edit": {"title": "Novo titulo"}}), own)
    assert status == 200 and json.loads(payload)["title"] == "Novo titulo"
    status, _, payload = req(httpd, "POST", "/api/decision",
                             json.dumps({"id": "c01", "status": "approved"}), own)
    assert status == 200 and json.loads(payload)["status"] == "approved"
    saved = json.loads(job.review_json.read_text(encoding="utf-8"))["decisions"]["c01"]
    assert saved == {"title": "Novo titulo", "status": "approved"}
    status, _, payload = req(httpd, "POST", "/api/edit",
                             json.dumps({"id": "c01", "edit": {"title": " "}}), own)
    assert status == 400


def test_undo_and_redo_routes(server):
    httpd, _, job = server
    jobs.write_json_atomic(job.candidates_json, {"candidates": [{"id": "c01", "segments": []}],
                                                 "groups": {}})
    port = httpd.server_address[1]
    own = {"Content-Type": "application/json", "Origin": f"http://127.0.0.1:{port}"}
    one = json.dumps({"id": "c01"})
    status, _, payload = req(httpd, "POST", "/api/undo", one, own)
    assert status == 409 and json.loads(payload) == {"error": "nothing to undo"}
    assert not job.review_json.exists()
    req(httpd, "POST", "/api/edit", json.dumps({"id": "c01", "edit": {"title": "Novo"}}), own)
    status, _, payload = req(httpd, "POST", "/api/undo", one, own)
    assert status == 200 and json.loads(payload) == {"undo": 0, "redo": 1}
    assert json.loads(job.review_json.read_text(encoding="utf-8")) == {"decisions": {}}
    status, _, payload = req(httpd, "POST", "/api/redo", one, own)
    assert status == 200 and json.loads(payload) == {"title": "Novo", "undo": 1, "redo": 0}
    status, _, payload = req(httpd, "POST", "/api/redo", one, own)
    assert status == 409 and json.loads(payload) == {"error": "nothing to redo"}
    status, _, payload = req(httpd, "POST", "/api/undo", json.dumps({"id": "c99"}), own)
    assert status == 400 and "unknown clip" in json.loads(payload)["error"]
    status, _, payload = req(httpd, "POST", "/api/undo", "{}", own)
    assert status == 400
    status, _, _ = req(httpd, "POST", "/api/undo", one,
                       {"Content-Type": "application/json", "Origin": "https://evil.example"})
    assert status == 403
    status, _, _ = req(httpd, "POST", "/api/redo", one, {**own, "Host": "evil.example:8765"})
    assert status == 403
    assert json.loads(job.review_json.read_text(encoding="utf-8")) == {"decisions": {"c01": {"title": "Novo"}}}


def test_fonts_route_serves_only_ttf_from_assets_fonts(server):
    httpd, _, _ = server
    status, headers, body = get(httpd, "/fonts/Anton-Regular.ttf")
    assert status == 200 and headers["Content-Type"] == "font/ttf"
    assert body[:4] == b"\x00\x01\x00\x00"
    status, headers, body = req(httpd, "HEAD", "/fonts/Raleway-Variable.ttf")
    assert status == 200 and headers["Content-Type"] == "font/ttf" and body == b""
    for bad in ["/fonts/OFL.txt", "/fonts/../config.toml", "/fonts/../../pyproject.toml",
                "/fonts/missing.ttf", "/fonts/", "/fonts/%2e%2e/config.toml"]:
        status, _, _ = get(httpd, bad)
        assert status == 404, bad


def test_fonts_route_checks_the_host(server):
    httpd, _, _ = server
    status, _, _ = req(httpd, "GET", "/fonts/Anton-Regular.ttf", headers={"Host": "evil.example:8765"})
    assert status == 403


def test_svg_is_served_as_svg(server):
    httpd, _, _ = server
    status, headers, body = get(httpd, "/static/albatroz-symbol.svg")
    assert status == 200 and headers["Content-Type"] == "image/svg+xml"
    assert body.lstrip().startswith(b"<svg")


class FakeRenders:
    def __init__(self, tmp_path, broken=False):
        self.calls, self.broken = [], broken
        self.mp4 = tmp_path / "c1.mp4"
        self.mp4.write_bytes(bytes(range(256)))

    def snapshot(self):
        if self.broken:
            raise ValueError("review.json is not valid JSON: /x/review.json (fix or restore the file)")
        return {"clips": {"c1": {"state": "rendered", "version": "4", "approved": True, "file": True}},
                "queue": []}

    def enqueue(self, cid):
        if cid != "c1":
            raise ValueError(f"unknown clip {cid}")
        self.calls.append(("one", cid))
        return self.snapshot()

    def enqueue_all(self):
        self.calls.append(("all", None))
        return self.snapshot()

    def file(self, cid):
        return self.mp4 if cid == "c1" else None


@pytest.fixture
def rserver(tmp_path):
    master = tmp_path / "m.mp4"
    master.write_bytes(b"\x00" * 16)
    job = jobs.create_job(tmp_path / "jobs", "j", {"master": str(master)})
    jobs.write_json_atomic(job.words_json, {"version": 1, "words": []})
    jobs.write_json_atomic(job.candidates_json, {"candidates": [], "groups": {}})
    fake = FakeRenders(tmp_path)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(job, master, renders=fake))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield httpd, fake
    httpd.shutdown()


def own(httpd):
    return {"Content-Type": "application/json", "Origin": f"http://127.0.0.1:{httpd.server_address[1]}"}


def test_render_routes_are_404_without_a_queue(server):
    httpd, _, _ = server
    assert get(httpd, "/api/renders")[0] == 404
    assert get(httpd, "/renders/c1.mp4")[0] == 404
    assert req(httpd, "POST", "/api/render", json.dumps({"id": "c1"}), own(httpd))[0] == 404


def test_api_renders_returns_the_snapshot(rserver):
    httpd, _ = rserver
    status, _, body = get(httpd, "/api/renders")
    assert status == 200 and json.loads(body)["clips"]["c1"]["state"] == "rendered"


def test_post_render_and_render_all(rserver):
    httpd, fake = rserver
    status, _, body = req(httpd, "POST", "/api/render", json.dumps({"id": "c1"}), own(httpd))
    assert status == 200 and "clips" in json.loads(body)
    status, _, _ = req(httpd, "POST", "/api/render-all", "{}", own(httpd))
    assert status == 200 and fake.calls == [("one", "c1"), ("all", None)]
    status, _, body = req(httpd, "POST", "/api/render", json.dumps({"id": "zz"}), own(httpd))
    assert status == 400 and json.loads(body)["error"] == "unknown clip zz"


def test_post_render_keeps_the_origin_guard(rserver):
    httpd, fake = rserver
    status, _, _ = req(httpd, "POST", "/api/render", json.dumps({"id": "c1"}),
                       {"Content-Type": "application/json"})
    assert status == 403 and fake.calls == []


def test_render_file_serves_ranges_and_is_never_cached(rserver):
    httpd, _ = rserver
    status, headers, body = get(httpd, "/renders/c1.mp4", {"Range": "bytes=0-1"})
    assert status == 206 and body == b"\x00\x01"
    assert headers["Content-Type"] == "video/mp4" and headers["Cache-Control"] == "no-store"
    status, headers, _ = get(httpd, "/renders/c1.mp4")
    assert status == 200 and headers["Cache-Control"] == "no-store"


@pytest.mark.parametrize("path", ["/renders/zz.mp4", "/renders/..%2Fm.mp4", "/renders/../m.mp4",
                                  "/renders/c1.mov", "/renders/c1.mp4/x"])
def test_render_file_refuses_other_paths(rserver, path):
    httpd, _ = rserver
    assert get(httpd, path)[0] == 404


def test_render_routes_check_the_host(rserver):
    httpd, _ = rserver
    assert get(httpd, "/api/renders", {"Host": "evil.example"})[0] == 403
    assert get(httpd, "/renders/c1.mp4", {"Host": "evil.example"})[0] == 403


def test_a_broken_snapshot_is_a_json_500(tmp_path):
    master = tmp_path / "m.mp4"
    master.write_bytes(b"\x00")
    job = jobs.create_job(tmp_path / "jobs", "j", {"master": str(master)})
    httpd = ThreadingHTTPServer(("127.0.0.1", 0),
                                make_handler(job, master, renders=FakeRenders(tmp_path, broken=True)))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        status, _, body = get(httpd, "/api/renders")
        assert status == 500 and "is not valid JSON" in json.loads(body)["error"]
    finally:
        httpd.shutdown()
