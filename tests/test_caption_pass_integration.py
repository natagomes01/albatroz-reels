"""analyze (stub LLM) -> corrections.json -> review state -> clip stage -> captions (caption spec 11)."""
import json
from dataclasses import replace

from shorts import jobs
from shorts.analyze.run import run_analyze
from shorts.captions import CaptionStyle, build_screens, render_ass
from shorts.clip import ClipResult
from shorts.review.state import apply_decision, apply_edit, load_state
from shorts.stages import run_clip_stage
from shorts.timeline import TimeMap
from test_analyze_run import CH, REPO, WithCaptions, app, backends, make_job


def all_backends(b):
    return {**backends(b), "class_sheet": b, "caption_fix": b}


def captions_of(job, ap) -> list[str]:
    seen = []

    def fake_produce(req):
        clip_words = [w for s in req.segments for w in req.words if s.start <= w.t < s.end]
        tm = TimeMap(list(req.segments))
        seen.append(render_ass(clip_words, build_screens(clip_words, "pt"), tm, CaptionStyle(),
                               tm.duration))
        return ClipResult(out_path=None, duration=tm.duration, edl=list(req.segments),
                          weak_tracking=False)
    out = run_clip_stage(job, ap, replace(CH, color=False), "captions", produce=fake_produce)
    assert out and all("error" not in r for r in out), out
    return seen


def analyzed(tmp_path, b):
    job = make_job(tmp_path)
    ap = app(tmp_path)
    run_analyze(job, ap, CH, REPO, backends=all_backends(b))
    jobs.write_json_atomic(job.job_json, {**jobs.read_json(job.job_json),
                                          "master": str(tmp_path / "m.mp4")})
    cid = json.loads(job.candidates_json.read_text(encoding="utf-8"))["candidates"][0]["id"]
    return job, ap, cid


def test_analyze_to_review_to_captions_uses_the_automatic_fix(tmp_path):
    job, ap, cid = analyzed(tmp_path, WithCaptions({"w1": 90}))
    assert json.loads(job.words_json.read_text(encoding="utf-8"))["words"][30]["w"] == "p3q0"   # raw stays raw
    s = load_state(job)
    assert s["auto_slots"]["30"] == {"text": "Eloí,", "edit": 0}
    assert s["auto_slots"]["31"] == {"text": "Eloí", "edit": 0}
    assert s["auto_edits"][0]["original"] == "p3q0 p3q1"
    apply_decision(job, cid, "approved")
    ass = captions_of(job, ap)[0]
    assert "ELOÍ," in ass and "P3Q0" not in ass and "P3Q1" not in ass


def test_owner_fix_on_a_corrected_range_wins(tmp_path):
    job, ap, cid = analyzed(tmp_path, WithCaptions({"w1": 90}))
    apply_decision(job, cid, "approved")
    apply_edit(job, cid, {"word_fixes": {"30": "Eli, Eli,", "31": ""}})    # the page's range replace
    ass = captions_of(job, ap)[0]
    assert "ELI, ELI," in ass and "ELOÍ" not in ass and "P3Q1" not in ass


def test_a_failing_caption_pass_leaves_candidates_and_raw_words(tmp_path):
    job = make_job(tmp_path)
    res = run_analyze(job, app(tmp_path), CH, REPO,
                      backends=all_backends(WithCaptions({"w1": 90}, fail_sheet=True)))
    assert res["candidates"] == 1 and job.candidates_json.exists()
    assert res["fixes"] == 0 and res["fix_error_kind"] == "limit"
    assert not job.corrections_json.exists()
    s = load_state(job)
    assert s["auto_slots"] == {} and s["words"][30][1] == "p3q0"
    events = [json.loads(line) for line in job.log_path.read_text(encoding="utf-8").splitlines()]
    assert any(e["kind"] == "error" and e.get("stage") == "fixwords" for e in events)
