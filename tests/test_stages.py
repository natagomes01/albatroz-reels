import json
from dataclasses import replace
from pathlib import Path

import pytest

from shorts import jobs
from shorts.clip import ClipResult
from shorts.color import Grade
from shorts.config import AppConfig, ChannelConfig
from shorts import wordfix
from shorts.stages import approved_clips, next_stage, render_path, render_status, run_clip_stage
from shorts.timeline import Span
from shorts.words import Word

CH = ChannelConfig(id="catholic-br", language="pt", brand_dir=None, glossary="")


def make_job(tmp_path, decisions=None):
    job = jobs.create_job(tmp_path / "jobs", "260927-a", {
        "channel": "catholic-br", "format": "solo-standing", "master": str(tmp_path / "m.mp4")})
    words = [{"t": i * 0.5, "w": f"w{i}" + ("." if i % 10 == 9 else ""), "p": 1} for i in range(400)]
    jobs.write_json_atomic(job.words_json, {"version": 1, "words": words})
    cand = {"id": "c01", "window_id": "w1", "title": "T", "hook": "H", "total": 80.0,
            "segments": [{"window_id": "w1", "first_words": "", "last_words": "",
                          "proposed": [10.0, 50.0], "snapped": [9.65, 50.45]}],
            "scores": {"hook": {"score": 8, "why": "x"}}, "controversy": 1, "controversy_why": "",
            "who_reacts": "P", "emphasis": ["w30 w31 w32"], "hook_id": "h01",
            "out_of_order": False, "too_long": False, "blind": {"stands_alone": True},
            "faithful": {"faithful": True}, "verdict": "publish", "warnings": []}
    jobs.write_json_atomic(job.candidates_json, {"candidates": [cand], "groups": {"h01": ["c01"]}})
    if decisions is not None:
        jobs.write_json_atomic(job.review_json, {"decisions": decisions, "dereverb": 0})
    return job


def app(tmp_path):
    return AppConfig(media_root=tmp_path / "media", jobs_dir=tmp_path / "jobs", backends={})


def no_color(master, duration):
    return [(0.0, Grade(0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 1.0))]


def test_word_fixes_keep_time():
    ws = [Word(0.0, "a", 1), Word(1.0, "b", 1)]
    fixed = wordfix.effective_words(ws, [], {"1": "Denzinger"})
    assert fixed[1] == Word(1.0, "Denzinger", 1)


def test_approved_clips_use_edits_hook_and_emphasis(tmp_path):
    job = make_job(tmp_path, {"c01": {"status": "approved", "segments": [[12.0, 48.0]],
                                      "title": "Novo"}})
    plans = approved_clips(job)
    assert len(plans) == 1
    p = plans[0]
    assert p.spans == [Span(12.0, 48.0)] and p.title == "Novo"
    assert p.hook is not None and p.hook.start == 12.0          # first sentence of the clip
    assert p.emphasis and p.emphasis[0].start == 15.0            # w30 at 15.0 s


def test_rejected_and_pending_are_skipped(tmp_path):
    job = make_job(tmp_path, {"c01": {"status": "rejected"}})
    assert approved_clips(job) == []
    assert approved_clips(make_job(tmp_path / "b", None)) == []


def test_render_stage_writes_meta_next_to_render_and_skips_when_fresh(tmp_path):
    job = make_job(tmp_path, {"c01": {"status": "approved"}})
    calls = []

    def fake_produce(req):
        calls.append(req)
        if req.stop_after == "render":
            req.out_path.parent.mkdir(parents=True, exist_ok=True)
            req.out_path.write_bytes(b"mp4")
        return ClipResult(out_path=req.out_path if req.stop_after == "render" else None,
                          duration=36.2, edl=[Span(12.0, 48.2)], weak_tracking=True)

    out = run_clip_stage(job, app(tmp_path), CH, "render", produce=fake_produce, measure=no_color)
    render = tmp_path / "media" / "renders" / "catholic-br" / "260927-a" / "c01.mp4"
    assert out[0]["render"] == str(render) and render.exists()
    meta = json.loads(render.with_suffix(".json").read_text(encoding="utf-8"))
    assert meta["score"]["total"] == 80.0 and meta["warnings"] == ["weak_tracking"]
    assert meta["content_language"] == "pt" and meta["format"] == "solo-standing"
    assert json.loads((job.clip_dir("c01") / "meta.json").read_text(encoding="utf-8")) == meta
    assert calls[0].work_dir == job.clip_dir("c01") and calls[0].reuse_track is False
    assert set(meta["analysis"]) == {"profile_digest", "prompts", "llm"}
    run_clip_stage(job, app(tmp_path), CH, "render", produce=fake_produce, measure=no_color)
    assert len(calls) == 1                                        # fresh: skipped
    # A rubric weight change must not re-render (spec 4.3)
    ch2 = replace(CH, weights={"hook": .10, "value": .40, "conversation": .30, "emotion": .20})
    run_clip_stage(job, app(tmp_path), ch2, "render", produce=fake_produce, measure=no_color)
    assert len(calls) == 1
    # A caption toggle does
    run_clip_stage(job, app(tmp_path), replace(CH, captions=False), "render", produce=fake_produce,
                   measure=no_color)
    assert len(calls) == 2


def test_track_then_render_reuses_track(tmp_path):
    job = make_job(tmp_path, {"c01": {"status": "approved"}})
    calls = []

    def fake_produce(req):
        calls.append(req)
        (req.work_dir).mkdir(parents=True, exist_ok=True)
        (req.work_dir / "track.json").write_text("{}", encoding="utf-8")
        if req.stop_after == "render":
            req.out_path.parent.mkdir(parents=True, exist_ok=True)
            req.out_path.write_bytes(b"x")
        return ClipResult(out_path=None, duration=36.0, edl=[], weak_tracking=False)

    run_clip_stage(job, app(tmp_path), CH, "track", produce=fake_produce)
    run_clip_stage(job, app(tmp_path), CH, "render", produce=fake_produce, measure=no_color)
    assert calls[0].stop_after == "track" and calls[1].reuse_track is True


def test_preview_and_safe_zone_reach_the_request(tmp_path):
    job = make_job(tmp_path, {"c01": {"status": "approved"}})
    calls = []

    def fake_produce(req):
        calls.append(req)
        return ClipResult(out_path=None, duration=36.0, edl=[], weak_tracking=False,
                          preview_path=req.work_dir / "track-preview.mp4")

    out = run_clip_stage(job, app(tmp_path), CH, "track", produce=fake_produce, preview=True)
    assert calls[0].preview is True and out[0]["preview"].endswith("track-preview.mp4")
    run_clip_stage(job, app(tmp_path), CH, "captions", produce=fake_produce, safe_zone=True, preview=True)
    assert calls[1].preview is False and calls[1].safe_zone is True   # preview only on the track stage


def test_next_stage(tmp_path):
    job = make_job(tmp_path, None)
    assert next_stage(job) == "review"
    jobs.write_json_atomic(job.review_json, {"decisions": {"c01": {"status": "approved"}}, "dereverb": 0})
    assert next_stage(job, app(tmp_path)) == "render"

    def fake_produce(req):
        req.out_path.parent.mkdir(parents=True, exist_ok=True)
        req.out_path.write_bytes(b"mp4")
        return ClipResult(out_path=req.out_path, duration=36.0, edl=[], weak_tracking=False)
    run_clip_stage(job, app(tmp_path), CH, "render", produce=fake_produce, measure=no_color)
    assert next_stage(job, app(tmp_path)) == "done"
    job.candidates_json.unlink()
    assert next_stage(job) == "analyze"


def test_one_failing_clip_does_not_stop_the_others(tmp_path):
    job = make_job(tmp_path, {"c01": {"status": "approved"}, "c02": {"status": "approved"}})
    data = json.loads(job.candidates_json.read_text(encoding="utf-8"))
    c2 = dict(data["candidates"][0], id="c02",
              segments=[{"window_id": "w1", "first_words": "", "last_words": "",
                         "proposed": [100.0, 140.0], "snapped": [100.0, 140.0]}])
    data["candidates"].append(c2)
    jobs.write_json_atomic(job.candidates_json, data)

    class Boom(Exception):
        cmd = ["ffmpeg", "-i", "m.mp4"]
        stderr_tail = "Invalid data found when processing input"

    def fake_produce(req):
        if req.work_dir.name == "c01":
            raise Boom("ffmpeg failed")
        req.out_path.parent.mkdir(parents=True, exist_ok=True)
        req.out_path.write_bytes(b"mp4")
        return ClipResult(out_path=req.out_path, duration=36.0, edl=[], weak_tracking=False)
    out = run_clip_stage(job, app(tmp_path), CH, "render", produce=fake_produce, measure=no_color)
    by = {r["clip"]: r for r in out}
    assert "error" in by["c01"] and by["c02"]["render"].endswith("c02.mp4")
    events = [json.loads(l) for l in job.log_path.read_text(encoding="utf-8").splitlines()]
    err = next(e for e in events if e["kind"] == "error")
    assert err["clip"] == "c01" and err["cmd"][0] == "ffmpeg" and "Invalid data" in err["stderr_tail"]


def test_invalid_edited_segments_become_an_error_entry(tmp_path):
    job = make_job(tmp_path, {"c01": {"status": "approved", "segments": [[10.0, 40.0], [30.0, 60.0]]}})
    out = run_clip_stage(job, app(tmp_path), CH, "render",
                         produce=lambda req: pytest.fail("must not render"), measure=no_color)
    assert "overlap" in out[0]["error"]


def test_color_is_measured_once_per_job(tmp_path):
    job = make_job(tmp_path, {"c01": {"status": "approved"}})
    measured = []

    def measure(master, duration):
        measured.append(duration)
        return [(0.0, Grade(0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 1.0))]

    def fake_produce(req):
        assert req.color_points and req.color_points[0][1].gamma == 1.0
        req.out_path.parent.mkdir(parents=True, exist_ok=True)
        req.out_path.write_bytes(b"mp4")
        return ClipResult(out_path=req.out_path, duration=36.0, edl=[], weak_tracking=False)
    run_clip_stage(job, app(tmp_path), CH, "render", produce=fake_produce, measure=measure)
    run_clip_stage(job, app(tmp_path), replace(CH, captions=False), "render", produce=fake_produce,
                   measure=measure)
    assert len(measured) == 1 and job.color_json.exists()


def _render_all(job, tmp_path):
    def fake_produce(req):
        req.out_path.parent.mkdir(parents=True, exist_ok=True)
        req.out_path.write_bytes(b"mp4")
        return ClipResult(out_path=req.out_path, duration=36.0, edl=[], weak_tracking=False)
    return run_clip_stage(job, app(tmp_path), CH, "render", produce=fake_produce, measure=no_color)


def test_next_stage_is_not_done_after_edits_or_version_bump(tmp_path, monkeypatch):
    job = make_job(tmp_path, {"c01": {"status": "approved"}})
    _render_all(job, tmp_path)
    assert next_stage(job, app(tmp_path)) == "done"
    assert next_stage(job, app(tmp_path), CH) == "done"
    assert next_stage(job, app(tmp_path), replace(CH, captions=False)) == "render"
    monkeypatch.setattr(jobs, "RENDER_VERSION", jobs.RENDER_VERSION + "-bumped")
    assert next_stage(job, app(tmp_path)) == "render"
    monkeypatch.undo()
    jobs.write_json_atomic(job.review_json, {"decisions": {"c01": {"status": "approved",
                                                                    "segments": [[12.0, 48.0]]}}, "dereverb": 0})
    assert next_stage(job, app(tmp_path)) == "render"
    jobs.write_json_atomic(job.review_json, {"decisions": {"c01": {"status": "approved"}}, "dereverb": 0})
    assert next_stage(job, app(tmp_path)) == "done"
    render = tmp_path / "media" / "renders" / "catholic-br" / "260927-a" / "c01.json"
    render.unlink()
    assert next_stage(job, app(tmp_path)) == "render"


def test_malformed_candidates_become_errors_and_good_clip_renders(tmp_path):
    job = make_job(tmp_path, {"c01": {"status": "approved"}, "c02": {"status": "approved"},
                              "c03": {"status": "approved", "segments": [[10.0, 40.0], [30.0, 60.0]]}})
    data = json.loads(job.candidates_json.read_text(encoding="utf-8"))
    good = data["candidates"][0]
    no_scores = {k: v for k, v in good.items() if k != "scores"} | {"id": "c02"}
    bad_seg = dict(good, id="c03")
    data["candidates"] += [no_scores, bad_seg]
    jobs.write_json_atomic(job.candidates_json, data)
    out = _render_all(job, tmp_path)
    by = {r["clip"]: r for r in out}
    assert by["c01"]["render"].endswith("c01.mp4") and "error" not in by["c01"]
    assert "error" in by["c02"] and "error" in by["c03"]
    # a candidate that cannot even be planned is an error entry too
    data["candidates"].append({"id": "c04", "segments": "oops"})
    jobs.write_json_atomic(job.candidates_json, data)
    jobs.write_json_atomic(job.review_json, {"decisions": {"c01": {"status": "approved"},
                                                            "c04": {"status": "approved"}}, "dereverb": 0})
    by = {r["clip"]: r for r in _render_all(job, tmp_path)}
    assert "error" in by["c04"] and by["c01"]["skipped"] is True
    assert next_stage(job, app(tmp_path)) == "render"



def test_backup_failure_after_render_keeps_results_and_logs_error(tmp_path, monkeypatch):
    import shorts.backup
    job = make_job(tmp_path, {"c01": {"status": "approved"}})

    def fake_produce(req):
        if req.stop_after == "render":
            req.out_path.parent.mkdir(parents=True, exist_ok=True)
            req.out_path.write_bytes(b"mp4")
        return ClipResult(out_path=req.out_path if req.stop_after == "render" else None,
                          duration=36.2, edl=[Span(12.0, 48.2)], weak_tracking=False)

    def boom(*a, **k):
        raise RuntimeError("rclone exploded")
    monkeypatch.setattr(shorts.backup, "run_backup", boom)
    a = replace(app(tmp_path), backup_auto=True)
    out = run_clip_stage(job, a, CH, "render", produce=fake_produce, measure=no_color)
    assert out[0]["render"].endswith("c01.mp4") and "error" not in out[0]
    events = [json.loads(line) for line in job.log_path.read_text(encoding="utf-8").splitlines()]
    assert any(e.get("kind") == "error" and e.get("stage") == "backup"
               and "rclone exploded" in e["error"] for e in events)


def test_safe_zone_render_is_never_done(tmp_path):
    job = make_job(tmp_path, {"c01": {"status": "approved"}})

    def fake_produce(req):
        req.out_path.parent.mkdir(parents=True, exist_ok=True)
        req.out_path.write_bytes(b"mp4")
        return ClipResult(out_path=req.out_path, duration=36.0, edl=[], weak_tracking=False)
    run_clip_stage(job, app(tmp_path), CH, "render", produce=fake_produce, measure=no_color,
                   safe_zone=True)
    assert next_stage(job, app(tmp_path)) == "render"
    assert next_stage(job, app(tmp_path), CH) == "render"


def test_color_measure_failure_is_one_clear_failure(tmp_path):
    job = make_job(tmp_path, {"c01": {"status": "approved"}})

    def bad_measure(master, duration):
        raise FileNotFoundError(f"master not found: {master}")
    out = run_clip_stage(job, app(tmp_path), CH, "render", produce=lambda r: None, measure=bad_measure)
    assert len(out) == 1 and "error" in out[0] and "master not found" in out[0]["error"]
    events = [json.loads(line) for line in job.log_path.read_text(encoding="utf-8").splitlines()]
    assert any(e.get("kind") == "error" for e in events)


def test_nonzero_rclone_exit_is_logged(tmp_path, monkeypatch):
    import shorts.backup
    job = make_job(tmp_path, {"c01": {"status": "approved"}})

    def fake_produce(req):
        if req.stop_after == "render":
            req.out_path.parent.mkdir(parents=True, exist_ok=True)
            req.out_path.write_bytes(b"mp4")
        return ClipResult(out_path=req.out_path if req.stop_after == "render" else None,
                          duration=36.2, edl=[Span(12.0, 48.2)], weak_tracking=False)
    monkeypatch.setattr(shorts.backup, "run_backup", lambda *a, **k: [0, 3])
    a = replace(app(tmp_path), backup_auto=True)
    run_clip_stage(job, a, CH, "render", produce=fake_produce, measure=no_color)
    events = [json.loads(line) for line in job.log_path.read_text(encoding="utf-8").splitlines()]
    assert any(e.get("kind") == "error" and e.get("stage") == "backup" and "3" in e["error"]
               for e in events)


ELOI = wordfix.Edit(30, 32, ("Eloí,", "Eloí,"), "foreign_term", "aramaico", 0.9)


def write_edits(job, edits):
    jobs.write_json_atomic(job.corrections_json, {
        "version": 1, "words_hash": jobs.file_hash(job.words_json),
        "edits": [e.to_dict() for e in edits]})


def _capture(calls):
    def fake_produce(req):
        calls.append(req)
        req.out_path.parent.mkdir(parents=True, exist_ok=True)
        req.out_path.write_bytes(b"mp4")
        return ClipResult(out_path=req.out_path, duration=36.0, edl=[], weak_tracking=False)
    return fake_produce


def test_render_version_was_bumped_for_the_one_line_caption_height():
    assert jobs.RENDER_VERSION == "4"


def test_render_gets_the_effective_words(tmp_path):
    job = make_job(tmp_path, {"c01": {"status": "approved"}})
    write_edits(job, [ELOI])
    calls = []
    run_clip_stage(job, app(tmp_path), CH, "render", produce=_capture(calls), measure=no_color)
    texts = [w.w for w in calls[0].words]
    assert texts[29:33] == ["w29.", "Eloí,", "Eloí,", "w33"] and len(texts) == 399
    assert calls[0].words[30].t == 15.0 and calls[0].words[31].t == 15.5
    assert json.loads(job.words_json.read_text(encoding="utf-8"))["words"][30]["w"] == "w30"


def test_owner_fix_inside_an_automatic_range_wins_in_the_render(tmp_path):
    job = make_job(tmp_path, {"c01": {"status": "approved", "word_fixes": {"31": "Eli"}}})
    write_edits(job, [ELOI])
    calls = []
    run_clip_stage(job, app(tmp_path), CH, "render", produce=_capture(calls), measure=no_color)
    assert [w.w for w in calls[0].words[30:33]] == ["w30", "Eli", "w32"]


def test_stale_corrections_are_ignored(tmp_path):
    job = make_job(tmp_path, {"c01": {"status": "approved"}})
    write_edits(job, [ELOI])
    data = json.loads(job.words_json.read_text(encoding="utf-8"))
    data["words"][0]["w"] = "retranscribed"
    jobs.write_json_atomic(job.words_json, data)
    calls = []
    run_clip_stage(job, app(tmp_path), CH, "render", produce=_capture(calls), measure=no_color)
    assert calls[0].words[30].w == "w30"


def test_automatic_edit_rerenders_only_the_clip_it_touches(tmp_path):
    job = make_job(tmp_path, {"c01": {"status": "approved"}, "c02": {"status": "approved"}})
    data = json.loads(job.candidates_json.read_text(encoding="utf-8"))
    data["candidates"].append(dict(data["candidates"][0], id="c02", segments=[
        {"window_id": "w1", "first_words": "", "last_words": "", "proposed": [100.0, 140.0],
         "snapped": [100.0, 140.0]}]))
    jobs.write_json_atomic(job.candidates_json, data)
    calls = []
    run_clip_stage(job, app(tmp_path), CH, "render", produce=_capture(calls), measure=no_color)
    assert sorted(r.work_dir.name for r in calls) == ["c01", "c02"]
    septuaginta = wordfix.Edit(250, 251, ("Septuaginta",), "proper_name", "", 0.9)   # 125 s: c02
    write_edits(job, [septuaginta])
    calls.clear()
    run_clip_stage(job, app(tmp_path), CH, "render", produce=_capture(calls), measure=no_color)
    assert [r.work_dir.name for r in calls] == ["c02"]
    assert next_stage(job, app(tmp_path)) == "done"
    far = wordfix.Edit(380, 380, ("Tobias",), "proper_name", "", 0.9)                  # 190 s: none
    write_edits(job, [septuaginta, far])
    calls.clear()
    run_clip_stage(job, app(tmp_path), CH, "render", produce=_capture(calls), measure=no_color)
    assert calls == [] and next_stage(job, app(tmp_path)) == "done"
    near = wordfix.Edit(102, 102, ("Eclesiástico",), "proper_name", "", 0.9)           # 51 s: c01 +2 s
    write_edits(job, [septuaginta, far, near])
    assert next_stage(job, app(tmp_path)) == "render"


def test_edits_touching_uses_the_pad():
    raw = [Word(float(i), f"w{i}", 1.0) for i in range(20)]
    e = wordfix.Edit(12, 12, ("x",))                       # covers [12, 13)
    assert wordfix.edits_touching([e], raw, [Span(0.0, 10.0)]) == []
    assert wordfix.edits_touching([e], raw, [Span(0.0, 10.5)]) == [e]        # 10.5 + 2 > 12
    assert wordfix.edits_digest([e], raw, [Span(0.0, 10.5)]) != wordfix.edits_digest([], raw, [Span(0.0, 10.5)])


def test_prefer_auto_reads_only_integers():
    from shorts.stages import _prefer_auto
    assert _prefer_auto({"use_auto": [30, 7]}) == frozenset({30, 7})
    assert _prefer_auto({}) == frozenset()
    assert _prefer_auto({"use_auto": "30"}) == frozenset()
    assert _prefer_auto({"use_auto": [True, "30", 1.5, None, 30]}) == frozenset({30})


def test_choosing_the_suggestion_rerenders_only_that_clip(tmp_path):
    job = make_job(tmp_path, {"c01": {"status": "approved", "word_fixes": {"31": "Eli"}},
                              "c02": {"status": "approved"}})
    data = json.loads(job.candidates_json.read_text(encoding="utf-8"))
    data["candidates"].append(dict(data["candidates"][0], id="c02", segments=[
        {"window_id": "w1", "first_words": "", "last_words": "", "proposed": [100.0, 140.0],
         "snapped": [100.0, 140.0]}]))
    jobs.write_json_atomic(job.candidates_json, data)
    write_edits(job, [ELOI])
    calls = []
    run_clip_stage(job, app(tmp_path), CH, "render", produce=_capture(calls), measure=no_color)
    c01 = next(r for r in calls if r.work_dir.name == "c01")
    assert [w.w for w in c01.words[30:33]] == ["w30", "Eli", "w32"]          # "Mine" by default
    jobs.write_json_atomic(job.review_json, {"decisions": {
        "c01": {"status": "approved", "word_fixes": {"31": "Eli"}, "use_auto": [30]},
        "c02": {"status": "approved"}}, "dereverb": 0})
    assert next_stage(job, app(tmp_path)) == "render"
    calls.clear()
    run_clip_stage(job, app(tmp_path), CH, "render", produce=_capture(calls), measure=no_color)
    assert [r.work_dir.name for r in calls] == ["c01"]
    assert [w.w for w in calls[0].words[29:33]] == ["w29.", "Eloí,", "Eloí,", "w33"]
    assert next_stage(job, app(tmp_path)) == "done"


def test_clip_ids_limit_the_stage_to_the_named_clips(tmp_path):
    job = make_job(tmp_path, {"c01": {"status": "approved"}})
    calls = []

    def fake_produce(req):
        calls.append(req)
        req.out_path.parent.mkdir(parents=True, exist_ok=True)
        req.out_path.write_bytes(b"mp4")
        return ClipResult(out_path=req.out_path, duration=36.0, edl=[], weak_tracking=False)

    out = run_clip_stage(job, app(tmp_path), CH, "render", produce=fake_produce, measure=no_color,
                         clip_ids={"other"})
    assert out == [] and calls == []
    out = run_clip_stage(job, app(tmp_path), CH, "render", produce=fake_produce, measure=no_color,
                         clip_ids={"c01"})
    assert [r["clip"] for r in out] == ["c01"] and len(calls) == 1


def test_render_status_follows_renders_edits_and_versions(tmp_path, monkeypatch):
    job = make_job(tmp_path, {"c01": {"status": "approved"}})
    a = app(tmp_path)
    assert render_status(job, a, CH) == {
        "c01": {"state": "not_rendered", "version": None, "approved": True, "file": False}}
    _render_all(job, tmp_path)
    v = jobs.RENDER_VERSION
    assert render_status(job, a, CH)["c01"] == {
        "state": "rendered", "version": v, "approved": True, "file": True}
    # an edit after the render makes it out of date; undoing the edit makes it current again
    jobs.write_json_atomic(job.review_json, {"decisions": {"c01": {"status": "approved",
                                                                    "segments": [[12.0, 48.0]]}}, "dereverb": 0})
    assert render_status(job, a, CH)["c01"]["state"] == "out_of_date"
    jobs.write_json_atomic(job.review_json, {"decisions": {"c01": {"status": "approved"}}, "dereverb": 0})
    assert render_status(job, a, CH)["c01"]["state"] == "rendered"
    # a new RENDER_VERSION: out of date, and the version shown is the one the file was made with
    monkeypatch.setattr(jobs, "RENDER_VERSION", v + "-next")
    assert render_status(job, a, CH)["c01"] == {
        "state": "out_of_date", "version": v, "approved": True, "file": True}


def test_render_status_version_is_none_when_the_meta_is_missing_or_corrupt(tmp_path):
    job = make_job(tmp_path, {"c01": {"status": "approved"}})
    _render_all(job, tmp_path)
    meta = render_path(app(tmp_path), "catholic-br", job, "c01").with_suffix(".json")
    meta.write_text("{not json", encoding="utf-8")
    assert render_status(job, app(tmp_path), CH)["c01"]["version"] is None
    meta.unlink()
    st = render_status(job, app(tmp_path), CH)["c01"]
    assert st["version"] is None and st["state"] == "rendered"   # the key still matches


def test_render_status_of_a_clip_that_is_not_approved(tmp_path):
    job = make_job(tmp_path, {"c01": {"status": "approved"}})
    _render_all(job, tmp_path)
    jobs.write_json_atomic(job.review_json, {"decisions": {"c01": {"status": "rejected"}}})
    assert render_status(job, app(tmp_path), CH)["c01"] == {
        "state": "out_of_date", "version": jobs.RENDER_VERSION, "approved": False, "file": True}
    jobs.write_json_atomic(job.review_json, {"decisions": {}})
    render_path(app(tmp_path), "catholic-br", job, "c01").unlink()
    assert render_status(job, app(tmp_path), CH)["c01"] == {
        "state": "not_rendered", "version": jobs.RENDER_VERSION, "approved": False, "file": False}


def test_render_status_treats_a_safe_zone_render_as_out_of_date(tmp_path):
    job = make_job(tmp_path, {"c01": {"status": "approved"}})

    def fake_produce(req):
        req.out_path.parent.mkdir(parents=True, exist_ok=True)
        req.out_path.write_bytes(b"mp4")
        return ClipResult(out_path=req.out_path, duration=36.0, edl=[], weak_tracking=False)

    run_clip_stage(job, app(tmp_path), CH, "render", produce=fake_produce, measure=no_color,
                   safe_zone=True)
    assert render_status(job, app(tmp_path), CH)["c01"]["state"] == "out_of_date"


def _fake_produce(seen):
    def produce(req):
        seen.append(req)
        req.out_path.parent.mkdir(parents=True, exist_ok=True)
        req.out_path.write_bytes(b"mp4")
        return ClipResult(req.out_path, 40.0, [], False, [], None, None)
    return produce


def _review(job, **top):
    data = jobs.read_json(job.review_json)
    data.update(top)
    jobs.write_json_atomic(job.review_json, data)


def test_render_refuses_until_the_class_strength_is_chosen(tmp_path):
    from shorts.dereverb import StrengthNotChosen
    job = make_job(tmp_path, {"c01": {"status": "approved"}})
    _review(job, dereverb=None)
    seen = []
    with pytest.raises(StrengthNotChosen):
        run_clip_stage(job, app(tmp_path), CH, "render", produce=_fake_produce(seen), measure=no_color)
    assert seen == []
    run_clip_stage(job, app(tmp_path), replace(CH, sound=False), "render",
                   produce=_fake_produce(seen), measure=no_color)     # untreated sound: no gate
    assert len(seen) == 1


def test_strength_reaches_the_request_and_the_render_key(tmp_path):
    job = make_job(tmp_path, {"c01": {"status": "approved"}})
    _review(job, dereverb=20)
    seen = []
    run_clip_stage(job, app(tmp_path), CH, "render", produce=_fake_produce(seen), measure=no_color)
    req = seen[0]
    assert req.dereverb == 20 and req.audio_cache == tmp_path / "media" / "cache" / job.id / "audio"
    assert render_status(job, app(tmp_path), CH)["c01"]["state"] == "rendered"
    meta = jobs.read_json(render_path(app(tmp_path), "catholic-br", job, "c01").with_suffix(".json"))
    assert meta["dereverb"] == 20
    _review(job, dereverb=30)                                          # class change: out of date
    assert render_status(job, app(tmp_path), CH)["c01"]["state"] == "out_of_date"
    run_clip_stage(job, app(tmp_path), CH, "render", produce=_fake_produce(seen), measure=no_color)
    assert seen[-1].dereverb == 30


def test_clip_override_beats_the_class(tmp_path):
    job = make_job(tmp_path, {"c01": {"status": "approved", "dereverb": 0}})
    _review(job, dereverb=20)
    seen = []
    run_clip_stage(job, app(tmp_path), CH, "render", produce=_fake_produce(seen), measure=no_color)
    assert seen[0].dereverb == 0
    _review(job, dereverb=30)            # the class changes; the clip keeps its own strength
    assert render_status(job, app(tmp_path), CH)["c01"]["state"] == "rendered"


def test_sound_off_channel_keeps_its_key_when_the_strength_changes(tmp_path):
    job = make_job(tmp_path, {"c01": {"status": "approved"}})
    ch = replace(CH, sound=False)
    _review(job, dereverb=20)
    seen = []
    run_clip_stage(job, app(tmp_path), ch, "render", produce=_fake_produce(seen), measure=no_color)
    meta = jobs.read_json(render_path(app(tmp_path), "catholic-br", job, "c01").with_suffix(".json"))
    assert "dereverb" not in meta and seen[0].dereverb == 0
    assert render_status(job, app(tmp_path), ch)["c01"]["state"] == "rendered"
    _review(job, dereverb=30)                                           # class change
    assert render_status(job, app(tmp_path), ch)["c01"]["state"] == "rendered"
    data = jobs.read_json(job.review_json)
    data["decisions"]["c01"]["dereverb"] = 10                           # clip override
    jobs.write_json_atomic(job.review_json, data)
    assert render_status(job, app(tmp_path), ch)["c01"]["state"] == "rendered"
    assert next_stage(job, app(tmp_path), ch) == "done"
    assert next_stage(job, app(tmp_path)) == "done"                     # key from the meta's channel fields


def test_sound_on_channel_still_goes_out_of_date_with_an_override(tmp_path):
    job = make_job(tmp_path, {"c01": {"status": "approved"}})
    _review(job, dereverb=20)
    run_clip_stage(job, app(tmp_path), CH, "render", produce=_fake_produce([]), measure=no_color)
    data = jobs.read_json(job.review_json)
    data["decisions"]["c01"]["dereverb"] = 10
    jobs.write_json_atomic(job.review_json, data)
    assert render_status(job, app(tmp_path), CH)["c01"]["state"] == "out_of_date"
    assert next_stage(job, app(tmp_path), CH) == "render"


def test_no_approved_clips_is_not_a_strength_error(tmp_path):
    job = make_job(tmp_path, {"c01": {"status": "rejected"}})
    _review(job, dereverb=None)
    assert run_clip_stage(job, app(tmp_path), CH, "render", produce=_fake_produce([]),
                          measure=no_color) == []


def _with_settings(job, settings):
    meta = jobs.read_json(job.job_json)
    jobs.write_json_atomic(job.job_json, {**meta, "settings": settings})


def test_job_settings_turn_color_off_move_captions_and_the_split_face(tmp_path):
    job = make_job(tmp_path, {"c01": {"status": "approved"}})
    _with_settings(job, {"color": False, "caption_y": 1300, "split_face_y": 1500, "close_zoom": 1.25,
                         "open_close": False, "burn_captions": False})
    calls = []

    def measure(master, duration):
        raise AssertionError("color must not be measured when the job turns it off")

    def fake_produce(req):
        calls.append(req)
        req.out_path.parent.mkdir(parents=True, exist_ok=True)
        req.out_path.write_bytes(b"mp4")
        return ClipResult(out_path=req.out_path, duration=36.0, edl=[], weak_tracking=False)

    run_clip_stage(job, app(tmp_path), CH, "render", produce=fake_produce, measure=measure)
    req = calls[0]
    assert req.color_points is None and req.channel.color is False
    assert req.channel.caption_y == 1300 and req.broll_cfg.split_face_y == 1500
    assert req.close_zoom == 1.25 and req.burn_captions is False
    assert req.hook.start == req.hook.end      # an empty hook: the clip opens wide
    assert render_status(job, app(tmp_path), CH)["c01"]["state"] == "rendered"
    assert next_stage(job, app(tmp_path), CH) == "done"
    assert next_stage(job, app(tmp_path)) == "done"     # channel taken from the render's meta


def test_changing_a_job_setting_puts_the_render_out_of_date(tmp_path):
    job = make_job(tmp_path, {"c01": {"status": "approved"}})
    _with_settings(job, {"caption_y": 1300})
    _render_all(job, tmp_path)
    assert render_status(job, app(tmp_path), CH)["c01"]["state"] == "rendered"
    _with_settings(job, {"caption_y": 1350})
    assert render_status(job, app(tmp_path), CH)["c01"]["state"] == "out_of_date"
    assert next_stage(job, app(tmp_path)) == "render"


def test_a_job_without_settings_keeps_its_key(tmp_path):
    job = make_job(tmp_path, {"c01": {"status": "approved"}})
    _render_all(job, tmp_path)
    _with_settings(job, {})
    assert render_status(job, app(tmp_path), CH)["c01"]["state"] == "rendered"


def test_bad_job_settings_fail_clearly(tmp_path):
    job = make_job(tmp_path, {"c01": {"status": "approved"}})
    _with_settings(job, {"colour": False})
    with pytest.raises(ValueError, match="unknown job setting"):
        render_status(job, app(tmp_path), CH)
    _with_settings(job, {"caption_y": 2500})
    with pytest.raises(ValueError, match="caption_y"):
        render_status(job, app(tmp_path), CH)
    _with_settings(job, {"burn_captions": "no"})
    with pytest.raises(ValueError, match="burn_captions"):
        render_status(job, app(tmp_path), CH)
    _with_settings(job, {"close_zoom": 3})
    with pytest.raises(ValueError, match="close_zoom"):
        render_status(job, app(tmp_path), CH)
