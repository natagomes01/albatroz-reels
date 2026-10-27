# tests/test_analyze_run.py
import json
from pathlib import Path

import pytest

from shorts import jobs
from shorts.analyze.run import ReviewInProgress, run_analyze
from shorts.config import AppConfig, ChannelConfig
from shorts.llm.base import LLMError

REPO = Path(__file__).resolve().parents[1]
FIX = Path(__file__).parent / "fixtures" / "llm"
CH = ChannelConfig(id="catholic-br", language="pt", brand_dir=Path("profiles/catholic-br"),
                   glossary="")


def make_job(tmp_path):
    words, t = [], 0.0
    for s in range(60):
        for k in range(10):
            words.append({"t": round(t, 3), "w": f"p{s}q{k}" + ("." if k == 9 else ""), "p": 1.0})
            t += 0.5
        t += 0.5
    job = jobs.create_job(tmp_path / "jobs", "260927-a", {"channel": "catholic-br",
                                                           "format": "solo-standing",
                                                           "duration": t})
    jobs.write_json_atomic(job.words_json, {"version": 1, "words": words})
    return job


class Scripted:
    model = "stub"
    name = "stub-backend"

    def __init__(self, scan_scores, fail_detail_after=None):
        self.scan_scores, self.n_detail, self.fail_after = scan_scores, 0, fail_detail_after
        self.calls = 0

    def complete(self, system, user, schema):
        self.calls += 1
        if "first-pass editor" in system:
            ids = [l.split("]")[0][1:] for l in user.splitlines() if l.startswith("[w")]
            return {"windows": [{"id": i, "score": self.scan_scores.get(i, 10), "reason": "r"}
                                for i in ids]}
        if "senior editor" in system:
            self.n_detail += 1
            if self.fail_after is not None and self.n_detail > self.fail_after:
                raise LLMError("You've hit your limit", "limit")
            return json.loads((FIX / "detail_w1.json").read_text(encoding="utf-8"))
        ids = [l.split("]")[0][2:] for l in user.splitlines() if l.startswith("[#")]
        if "stands_alone" in str(schema):
            return {"results": [{"id": i, "stands_alone": True, "why": "",
                                 "suggest_earlier_start": False} for i in ids]}
        return {"results": [{"id": i, "faithful": True, "why": ""} for i in ids]}


def app(tmp_path):
    return AppConfig(media_root=tmp_path / "media", jobs_dir=tmp_path / "jobs", backends={})


def backends(b):
    return {"scan": b, "detail": b, "review": b}


def test_analyze_writes_candidates_with_stable_ids_and_provenance(tmp_path):
    job = make_job(tmp_path)
    b = Scripted({"w1": 90})
    res = run_analyze(job, app(tmp_path), CH, REPO, backends=backends(b))
    data = json.loads(job.candidates_json.read_text(encoding="utf-8"))
    assert res["candidates"] == 1 == len(data["candidates"])
    c = data["candidates"][0]
    assert c["id"].startswith("c") and len(c["id"]) == 7
    assert c["verdict"] == "publish" and c["hook_id"] in data["groups"]
    assert set(data["prompts"]) == {"scan", "detail", "review_blind", "review_faithful"}
    assert data["llm"]["detail"] == {"backend": "stub-backend", "model": "stub"}
    # A rerun (fresh backend, same class) yields the same id: decisions stay on the same clip.
    run_analyze(job, app(tmp_path), CH, REPO, backends=backends(Scripted({"w1": 90})))
    assert json.loads(job.candidates_json.read_text(encoding="utf-8"))["candidates"][0]["id"] == c["id"]


def test_weak_class_gives_zero_candidates(tmp_path):
    job = make_job(tmp_path)
    b = Scripted({})
    res = run_analyze(job, app(tmp_path), CH, REPO, backends=backends(b))
    assert res["candidates"] == 0 and res["selected"] == 0
    assert json.loads(job.candidates_json.read_text(encoding="utf-8"))["candidates"] == []


def test_limit_midway_then_resume_uses_cache(tmp_path):
    job = make_job(tmp_path)
    scores = {"w1": 90, "w2": 85}
    b1 = Scripted(scores, fail_detail_after=1)
    with pytest.raises(LLMError) as e:
        run_analyze(job, app(tmp_path), CH, REPO, backends=backends(b1))
    assert e.value.kind == "limit"
    b2 = Scripted(scores)
    run_analyze(job, app(tmp_path), CH, REPO, backends=backends(b2))
    assert b2.n_detail == 1                  # only the unfinished window is called again
    assert job.candidates_json.exists()


def test_refuses_to_overwrite_a_review_in_progress(tmp_path):
    job = make_job(tmp_path)
    run_analyze(job, app(tmp_path), CH, REPO, backends=backends(Scripted({"w1": 90})))
    cid = json.loads(job.candidates_json.read_text(encoding="utf-8"))["candidates"][0]["id"]
    jobs.write_json_atomic(job.review_json, {"decisions": {cid: {"status": "approved"}}})
    with pytest.raises(ReviewInProgress, match="--force"):
        run_analyze(job, app(tmp_path), CH, REPO, backends=backends(Scripted({"w1": 90})))
    run_analyze(job, app(tmp_path), CH, REPO, backends=backends(Scripted({"w1": 90})), force=True)
    assert not job.review_json.exists()
    archived = list(job.root.glob("review.*.json"))
    assert len(archived) == 1 and cid in archived[0].read_text(encoding="utf-8")


class Recording(Scripted):
    """Scripted backend that records the kind of every call and can hit the limit in one pass."""

    def __init__(self, scan_scores, limit_in=None):
        super().__init__(scan_scores)
        self.kinds, self.limit_in = [], limit_in

    def complete(self, system, user, schema):
        if "first-pass editor" in system:
            kind = "scan"
        elif "senior editor" in system:
            kind = "detail"
        else:
            kind = "blind" if "stands_alone" in str(schema) else "faithful"
        self.kinds.append(kind)
        if kind == self.limit_in:
            raise LLMError("You've hit your limit", "limit")
        return super().complete(system, user, schema)


def test_limit_in_the_faithful_review_then_rerun_makes_only_that_call(tmp_path):
    job = make_job(tmp_path)
    b1 = Recording({"w1": 90}, limit_in="faithful")
    with pytest.raises(LLMError) as e:
        run_analyze(job, app(tmp_path), CH, REPO, backends=backends(b1))
    assert e.value.kind == "limit"
    assert b1.kinds.count("faithful") == 1 and not job.candidates_json.exists()
    b2 = Recording({"w1": 90})
    run_analyze(job, app(tmp_path), CH, REPO, backends=backends(b2))
    assert b2.kinds == ["faithful"]                  # scan, detail and blind come from the cache
    assert job.candidates_json.exists()


def test_weak_class_only_calls_scan(tmp_path):
    job = make_job(tmp_path)
    b = Recording({})
    run_analyze(job, app(tmp_path), CH, REPO, backends=backends(b))
    assert b.kinds and set(b.kinds) == {"scan"}


def test_analyze_review_edit_then_clip_stage_field_names_line_up(tmp_path):
    from dataclasses import replace
    from shorts.clip import ClipResult
    from shorts.review.state import apply_decision, apply_edit, set_class_strength
    from shorts.stages import run_clip_stage
    job = make_job(tmp_path)
    ap = app(tmp_path)
    run_analyze(job, ap, CH, REPO, backends=backends(Scripted({"w1": 90})))
    cid = json.loads(job.candidates_json.read_text(encoding="utf-8"))["candidates"][0]["id"]
    apply_decision(job, cid, "approved")
    set_class_strength(job, 0, (0, 10, 20, 30))
    apply_edit(job, cid, {"title": "Titulo editado"})
    jobs.write_json_atomic(job.job_json, {**jobs.read_json(job.job_json),
                                          "master": str(tmp_path / "m.mp4")})
    requests = []

    def fake_produce(req):
        requests.append(req)
        req.out_path.parent.mkdir(parents=True, exist_ok=True)
        req.out_path.write_bytes(b"mp4")
        return ClipResult(out_path=req.out_path, duration=36.0, edl=[], weak_tracking=False)
    out = run_clip_stage(job, ap, replace(CH, color=False), "render", produce=fake_produce)
    expected = tmp_path / "media" / "renders" / "catholic-br" / job.id / f"{cid}.mp4"
    assert out == [{"clip": cid, "render": str(expected), "preview": None, "skipped": False}]
    meta = json.loads(expected.with_suffix(".json").read_text(encoding="utf-8"))
    assert meta["clip_id"] == cid and meta["title"] == "Titulo editado"
    assert requests[0].out_path == expected


class WithCaptions(Scripted):
    """Scripted backend that also answers the class sheet and the caption-fix pass."""

    def __init__(self, scan_scores, fail_sheet=False):
        super().__init__(scan_scores)
        self.fail_sheet, self.seq, self.fix_users = fail_sheet, [], []

    def complete(self, system, user, schema):
        if "You write the class sheet" in system:
            self.seq.append("sheet")
            if self.fail_sheet:
                raise LLMError("You've hit your limit", "limit")
            return {"topic": "Autoria do Pentateuco", "references": [], "terms": [],
                    "variable_spellings": []}
        if "You correct automatic captions" in system:
            self.seq.append("fix")
            self.fix_users.append(user)
            if "\n30|p3q0|1.00\n" in user:
                return {"edits": [{"first": 30, "last": 31, "tokens": ["Eloí,", "Eloí"],
                                   "kind": "foreign_term", "reason": "citação aramaica",
                                   "confidence": 0.9}]}
            return {"edits": []}
        self.seq.append("other")
        return super().complete(system, user, schema)


def all_backends(b):
    return {**backends(b), "class_sheet": b, "caption_fix": b}


def test_analyze_runs_the_caption_pass_last_on_raw_words(tmp_path):
    job = make_job(tmp_path)
    b = WithCaptions({"w1": 90})
    res = run_analyze(job, app(tmp_path), CH, REPO, backends=all_backends(b))
    assert res["candidates"] == 1
    assert res["fixes"] == 1 and res["fix_dropped"] == 0 and res["fix_error"] is None
    assert b.seq[-2:] == ["sheet", "fix"] and "other" not in b.seq[b.seq.index("sheet"):]
    assert json.loads(job.corrections_json.read_text(encoding="utf-8"))["edits"][0]["tokens"] == ["Eloí,", "Eloí"]
    assert json.loads(job.words_json.read_text(encoding="utf-8"))["words"][30]["w"] == "p3q0"


def test_caption_pass_failure_never_blocks_analyze(tmp_path):
    job = make_job(tmp_path)
    res = run_analyze(job, app(tmp_path), CH, REPO, backends=all_backends(WithCaptions({"w1": 90},
                                                                                    fail_sheet=True)))
    assert res["candidates"] == 1 and job.candidates_json.exists()
    assert res["fixes"] == 0 and "hit your limit" in res["fix_error"] and res["fix_error_kind"] == "limit"
    assert not job.corrections_json.exists()
    # no [backends.caption_fix] configured at all: same, a warning instead of a failure
    res = run_analyze(job, app(tmp_path), CH, REPO, backends=backends(Scripted({"w1": 90})))
    assert res["candidates"] == 1 and "backends.class_sheet" in res["fix_error"]


# ---- more windows than scan_ceiling: the owner decides (S4 follow-up) ----
def _ceiling_app(tmp_path):
    from dataclasses import replace
    return replace(app(tmp_path), scan_ceiling=1)


def _detail_windows(b):
    return b.n_detail


def test_over_the_ceiling_the_answer_no_keeps_the_best_ones(tmp_path):
    job = make_job(tmp_path)
    b, asked = Scripted({"w1": 90, "w2": 80}), []
    run_analyze(job, _ceiling_app(tmp_path), CH, REPO, backends=backends(b),
                over_ceiling=lambda q, c: asked.append((q, c)) or False)
    assert asked == [(2, 1)] and _detail_windows(b) == 1
    ev = [json.loads(l) for l in job.log_path.read_text(encoding="utf-8").splitlines()
          if json.loads(l)["kind"] == "scan_ceiling"]
    assert ev[0]["qualified"] == 2 and ev[0]["sent_to_detail"] == 1 and ev[0]["asked"] is True


def test_over_the_ceiling_the_answer_yes_sends_every_window(tmp_path):
    job = make_job(tmp_path)
    b = Scripted({"w1": 90, "w2": 80})
    run_analyze(job, _ceiling_app(tmp_path), CH, REPO, backends=backends(b),
                over_ceiling=lambda q, c: True)
    assert _detail_windows(b) == 2


def test_without_a_callback_the_ceiling_still_caps(tmp_path):
    job = make_job(tmp_path)
    b = Scripted({"w1": 90, "w2": 80})
    run_analyze(job, _ceiling_app(tmp_path), CH, REPO, backends=backends(b))
    assert _detail_windows(b) == 1


def test_at_or_below_the_ceiling_nothing_is_asked(tmp_path):
    job = make_job(tmp_path)
    b, asked = Scripted({"w1": 90}), []
    run_analyze(job, _ceiling_app(tmp_path), CH, REPO, backends=backends(b),
                over_ceiling=lambda q, c: asked.append(1) or True)
    assert asked == [] and _detail_windows(b) == 1
