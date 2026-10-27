import json
from pathlib import Path

import pytest

from shorts import jobs
from shorts.broll.graph import BrollInsert
from shorts.broll.inserts import (BrollPlan, broll_digest, credits, make_inserts, meta_entries,
                                  picked_plans, split_top)
from shorts.broll.model import BrollConfig
from shorts.clip import ClipResult
from shorts.config import AppConfig, ChannelConfig
from shorts.shots import Crop
from shorts.stages import (RENDER_CHANNEL_FIELDS, _keys, approved_clips, render_path, render_status,
                           run_clip_stage)
from shorts.timeline import Span, TimeMap
from shorts.vision import Box
from shorts.words import Word, load_words

CH = ChannelConfig(id="catholic-br", language="pt", brand_dir=None, glossary="", color=False)
RAW = [Word(i * 0.5, f"w{i}", 1.0) for i in range(200)]
PICK = {"source": "commons", "id": "1", "kind": "image", "file": "commons-1.jpg", "download_url": "https://x/1.jpg",
        "w": 4000, "h": 2000, "duration": None, "title": "A Última Ceia", "author": "Leonardo",
        "license": "CC BY 4.0", "license_url": "", "page_url": "https://c/File:Ceia.jpg"}


def moment(mid, first, last, pick=PICK, **kw):
    return {"id": mid, "origin": "llm", "first": first, "last": last, "layout": "full", "fit": "cover",
            "pan": "ltr", "focus": [0.5, 0.5], "terms": [], "note": "", "pick": pick, **kw}


def test_picked_plans_keep_picked_moments_inside_the_clip(tmp_path):
    d = {"broll": [moment("s2", 40, 45), moment("s1", 20, 25), moment("s3", 30, 35, pick=None),
                   moment("o1", 150, 155)]}
    plans = picked_plans(d, RAW, [Span(0.0, 60.0)], tmp_path)
    assert [p.id for p in plans] == ["s1", "s2"]
    assert plans[0].start == 10.0 and plans[0].end == 13.0 and plans[0].file == tmp_path / "commons-1.jpg"
    assert picked_plans({}, RAW, [Span(0.0, 60.0)], tmp_path) == []


def test_broll_digest_follows_choices_and_file_content(tmp_path):
    (tmp_path / "commons-1.jpg").write_bytes(b"one")
    plans = picked_plans({"broll": [moment("s1", 20, 25)]}, RAW, [Span(0.0, 60.0)], tmp_path)
    cfg = BrollConfig()
    d1 = broll_digest(plans, cfg)
    assert broll_digest([], cfg) == "" and d1
    assert broll_digest([], BrollConfig(pan_px_per_s=99.0, split_face_y=1300)) == ""
    assert broll_digest(plans, BrollConfig(pan_px_per_s=cfg.pan_px_per_s + 5)) != d1
    assert broll_digest(plans, BrollConfig(split_face_y=cfg.split_face_y + 10)) != d1
    split = picked_plans({"broll": [moment("s1", 20, 25, layout="split")]}, RAW, [Span(0.0, 60.0)], tmp_path)
    assert broll_digest(split, cfg) != d1
    import os
    (tmp_path / "commons-1.jpg").write_bytes(b"two")
    os.utime(tmp_path / "commons-1.jpg", ns=(1, 1))
    assert broll_digest(plans, cfg) != d1


def test_split_top_places_the_face_under_the_captions():
    wide = Crop(438, 0, 404, 720)                    # scale 1920 / 720
    face = Box(600, 120, 80, 90)                      # centre y 165 -> output row 440
    assert split_top(face, None, wide, 1250) == 150   # 440 - (1250 - 960)
    body = Box(560, 60, 160, 600)                     # top 60 -> row 160, minus 5% of 960
    assert split_top(None, body, wide, 1250) == 112
    assert split_top(None, None, wide, 1250) == 300
    assert split_top(Box(600, 700, 80, 20), None, wide, 1250) == 960      # clamped
    assert split_top(Box(600, 0, 80, 10), None, wide, 1250) == 0


def test_make_inserts_map_class_time_to_clip_time(tmp_path):
    plans = [BrollPlan("s1", 10.0, 13.0, "image", tmp_path / "a.jpg", "full", "cover", "ltr", (0.5, 0.5),
                       4000, 2000, PICK),
             BrollPlan("s2", 30.0, 33.0, "image", tmp_path / "a.jpg", "split", "cover", "still", (0.5, 0.5),
                       4000, 2000, PICK),
             BrollPlan("s3", 5.9, 6.0, "image", tmp_path / "a.jpg", "full", "cover", "still", (0.5, 0.5),
                       4000, 2000, PICK)]
    tm = TimeMap([Span(6.0, 20.0), Span(25.0, 40.0)])
    crops = [Crop(438, 0, 404, 720)] * int(tm.duration * 30)
    out = make_inserts(plans, tm, crops, lambda t: Box(600, 120, 80, 90), lambda t: None, BrollConfig())
    assert [type(i) for i in out] == [BrollInsert, BrollInsert]          # s3 falls in a cut: no length
    assert (out[0].start, out[0].end) == pytest.approx((4.0, 7.0))
    assert (out[1].start, out[1].end) == pytest.approx((19.0, 22.0)) and out[1].split_top == 150
    assert out[0].split_top == 300 and out[0].pan == "ltr"


def test_credits_only_for_cc_by_in_the_channel_language():
    picks = [PICK, {**PICK, "license": "Public domain"}, {**PICK, "source": "pexels", "license": "Pexels License"}]
    assert credits(picks, "pt") == "Imagem: A Última Ceia, de Leonardo, CC BY 4.0 (https://c/File:Ceia.jpg)"
    assert credits(picks, "en") == "Image: A Última Ceia by Leonardo, CC BY 4.0 (https://c/File:Ceia.jpg)"
    assert credits(picks, "es").startswith("Image:") and credits([], "pt") == ""


def test_meta_entries_use_clip_time(tmp_path):
    plans = picked_plans({"broll": [moment("s1", 20, 25)]}, RAW, [Span(0.0, 60.0)], tmp_path)
    entries = meta_entries(plans, TimeMap([Span(5.0, 60.0)]))
    assert entries == [{"start": 5.0, "end": 8.0, "layout": "full", "source": "commons", "kind": "image",
                        "title": "A Última Ceia", "author": "Leonardo", "license": "CC BY 4.0",
                        "page_url": "https://c/File:Ceia.jpg"}]


# ---- stages ----

def make_job(tmp_path, decision):
    job = jobs.create_job(tmp_path / "jobs", "260927-a", {
        "channel": "catholic-br", "format": "solo-standing", "master": str(tmp_path / "m.mp4")})
    words = [{"t": i * 0.5, "w": f"w{i}" + ("." if i % 10 == 9 else ""), "p": 1} for i in range(400)]
    jobs.write_json_atomic(job.words_json, {"version": 1, "words": words})
    cand = {"id": "c01", "window_id": "w1", "title": "T", "hook": "H", "total": 80.0,
            "segments": [{"window_id": "w1", "first_words": "", "last_words": "",
                          "proposed": [10.0, 50.0], "snapped": [9.65, 50.45]}],
            "scores": {}, "controversy": 1, "controversy_why": "", "who_reacts": "P", "emphasis": [],
            "hook_id": "h01", "out_of_order": False, "too_long": False, "blind": None, "faithful": None,
            "verdict": "publish", "warnings": []}
    jobs.write_json_atomic(job.candidates_json, {"candidates": [cand], "groups": {"h01": ["c01"]}})
    jobs.write_json_atomic(job.review_json, {"decisions": {"c01": {"status": "approved", **decision}},
                                             "dereverb": 0})
    return job


def app(tmp_path):
    return AppConfig(media_root=tmp_path / "media", jobs_dir=tmp_path / "jobs", backends={})


def fake_produce(calls):
    def produce(req):
        calls.append(req)
        req.out_path.parent.mkdir(parents=True, exist_ok=True)
        req.out_path.write_bytes(b"mp4")
        return ClipResult(out_path=req.out_path, duration=40.8, edl=[Span(9.65, 50.45)], weak_tracking=False)
    return produce


def fake_download(calls):
    def download(url, dest, headers, max_bytes):
        calls.append(url)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"jpg")
    return download


def test_a_clip_without_broll_keeps_its_pre_s8b_key(tmp_path, monkeypatch):
    monkeypatch.setenv("SHORTS_ENCODER", "h264_videotoolbox")   # the Mac's keys, on any machine
    monkeypatch.setenv("SHORTS_DETECTOR", "vision")
    job = make_job(tmp_path, {})
    plan = approved_clips(job)[0]
    words = load_words(job.words_json)
    rc = {k: getattr(CH, k) for k in RENDER_CHANNEL_FIELDS}
    meta_job = jobs.read_json(job.job_json)
    track, key = _keys(meta_job, plan, words, "solo-standing", rc, False, "", 0)
    assert track == jobs.stage_key(jobs.RENDER_VERSION, stage="track", master=meta_job.get("master_hash"),
                                   segments=[[s.start, s.end] for s in plan.spans], fmt="solo-standing")
    near = [[w.t, w.w] for w in words if any(s.start - 2.0 <= w.t < s.end + 2.0 for s in plan.spans)]
    old = jobs.stage_key(jobs.RENDER_VERSION, stage="render", track=track, words=near, auto_edits="",
                         channel=rc, emphasis=[[e.start, e.end] for e in plan.emphasis],
                         safe_zone=False, dereverb=0)
    assert key == old
    assert _keys(meta_job, plan, words, "solo-standing", rc, False, "", 0, broll="abc")[1] != key
    assert jobs.RENDER_VERSION == "4"


def test_render_gets_the_picks_meta_gets_credits_and_edits_rerender(tmp_path):
    job = make_job(tmp_path, {"broll": [moment("s1", 26, 31)]})
    calls, downloads = [], []
    a = app(tmp_path)
    out = run_clip_stage(job, a, CH, "render", produce=fake_produce(calls), download=fake_download(downloads))
    assert "error" not in out[0] and downloads == ["https://x/1.jpg"]       # fetched again: not on disk
    req = calls[0]
    assert [p.id for p in req.broll] == ["s1"] and req.broll_cfg == a.broll
    meta = json.loads(render_path(a, "catholic-br", job, "c01").with_suffix(".json").read_text(encoding="utf-8"))
    assert meta["credits"].startswith("Imagem: A Última Ceia") and meta["broll"][0]["start"] == pytest.approx(3.35)
    assert render_status(job, a, CH)["c01"]["state"] == "rendered"
    review = jobs.read_json(job.review_json)
    review["decisions"]["c01"]["broll"][0]["layout"] = "split"
    jobs.write_json_atomic(job.review_json, review)
    assert render_status(job, a, CH)["c01"]["state"] == "out_of_date"
    run_clip_stage(job, a, CH, "render", produce=fake_produce(calls), download=fake_download(downloads))
    assert len(calls) == 2 and len(downloads) == 1


def test_a_clip_without_picks_has_empty_broll_meta(tmp_path):
    job = make_job(tmp_path, {"broll": [moment("s1", 26, 31, pick=None)]})
    a = app(tmp_path)
    run_clip_stage(job, a, CH, "render", produce=fake_produce([]), download=fake_download([]))
    meta = json.loads(render_path(a, "catholic-br", job, "c01").with_suffix(".json").read_text(encoding="utf-8"))
    assert meta["broll"] == [] and meta["credits"] == ""


def test_missing_files_are_fetched_again_or_named(tmp_path):
    own = {**PICK, "source": "own", "id": "own-a.png", "file": "own-a.png", "download_url": "", "license": ""}
    job = make_job(tmp_path, {"broll": [moment("o1", 26, 31, pick=own, origin="owner")]})
    calls = []
    out = run_clip_stage(job, app(tmp_path), CH, "render", produce=fake_produce(calls),
                         download=fake_download([]))
    assert out[0]["error"] == "B-roll file missing: own-a.png; add it again on the review page"
    assert calls == []


def test_only_moments_inside_the_clip_are_fetched_or_checked(tmp_path):
    own = {**PICK, "source": "own", "id": "own-a.png", "file": "own-a.png", "download_url": "", "license": ""}
    other = {**PICK, "id": "2", "file": "commons-2.jpg", "download_url": "https://x/2.jpg"}
    job = make_job(tmp_path, {"broll": [moment("s1", 26, 31), moment("s2", 150, 155, pick=other),
                                        moment("o1", 160, 165, pick=own, origin="owner")]})
    calls, downloads = [], []
    out = run_clip_stage(job, app(tmp_path), CH, "render", produce=fake_produce(calls),
                         download=fake_download(downloads))
    assert "error" not in out[0] and downloads == ["https://x/1.jpg"]
    assert [p.id for p in calls[0].broll] == ["s1"]


def test_meta_and_credits_skip_a_moment_inside_a_silence_cut(tmp_path):
    job = make_job(tmp_path, {"broll": [moment("s1", 26, 31)]})

    def produce(req):
        req.out_path.parent.mkdir(parents=True, exist_ok=True)
        req.out_path.write_bytes(b"mp4")
        return ClipResult(out_path=req.out_path, duration=30.0, weak_tracking=False,
                          edl=[Span(9.65, 12.0), Span(20.0, 50.45)])
    a = app(tmp_path)
    run_clip_stage(job, a, CH, "render", produce=produce, download=fake_download([]))
    meta = json.loads(render_path(a, "catholic-br", job, "c01").with_suffix(".json").read_text(encoding="utf-8"))
    assert meta["broll"] == [] and meta["credits"] == ""


def test_broll_revision_counts_up_and_names_the_change(tmp_path):
    import json
    from shorts.stages import _broll_revision
    out = tmp_path / "c1.mp4"
    a = {"start": 4.0, "end": 9.0, "layout": "full", "title": "one.jpg"}
    b = {"start": 12.0, "end": 15.0, "layout": "split", "title": "two.jpg"}
    assert _broll_revision(out, [a]) == (1, ["added 4-9 s full one.jpg"])      # no earlier meta
    out.with_suffix(".json").write_text(json.dumps({"render_version": "4.01", "broll_revision": 1, "broll": [a]}), encoding="utf-8")
    assert _broll_revision(out, [a, b]) == (2, ["added 12-15 s split two.jpg"])
    out.with_suffix(".json").write_text(json.dumps({"render_version": "4", "broll": [a]}), encoding="utf-8")   # pre-revision meta
    assert _broll_revision(out, [b]) == (1, ["added 12-15 s split two.jpg", "removed 4-9 s full one.jpg"])
