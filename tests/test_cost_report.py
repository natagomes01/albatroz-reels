"""`shorts cost` numbers: per pass and model, totals, per minute, per clip (S4 spec 3, "Report").
Every expected value is computed by hand from the log written here."""
import json

import pytest

from shorts import jobs
from shorts.cost import UNKNOWN_PASS, job_report

LIMIT = "You've hit your limit"


def llm(pass_, model, run, cost, *, attempt=1, ok=True, inp=0, cw=0, cr=0, out=0, wall=0,
        kind=None, ts=100.0):
    e = {"ts": ts, "kind": "llm", "pass": pass_, "job": "260927-a", "run": run,
         "backend": "claude-cli", "model": model, "attempt": attempt, "ok": ok,
         "input_tokens": inp, "cache_creation_input_tokens": cw,
         "cache_creation_1h_input_tokens": cw, "cache_read_input_tokens": cr,
         "output_tokens": out, "thinking_tokens": 0, "duration_ms": wall,
         "duration_api_ms": wall, "wall_ms": wall, "cost_usd": cost,
         "cost_table_usd": cost, "cost_basis": "list" if cost is not None else None}
    if kind:
        e.update(error=LIMIT, error_kind=kind)
    return e


H, O, S = "claude-haiku-4-5", "claude-opus-5-5", "claude-sonnet-5"

EVENTS = [
    {"ts": 50.0, "kind": "transcreve", "returncode": 0, "wall_s": 95.0},
    {"ts": 100.0, "kind": "run_start", "run": "r1", "job": "260927-a", "command": "analyze",
     "args": {}},
    llm("scan", H, "r1", 0.04, inp=9, cw=6000, out=5000, wall=30000),
    llm("detail", O, "r1", 0.10, inp=2, cw=8000, cr=1000, out=3000, wall=20000),
    llm("detail", O, "r1", 0.12, attempt=2, inp=2, cr=9000, out=3500, wall=25000),
    llm("review_blind", S, "r1", 0.05, inp=5, cw=7000, out=800, wall=9000),
    llm("review_faithful", S, "r1", 0.07, inp=5, cw=9000, out=1200, wall=12000),
    llm("detail", O, "r1", None, ok=False, kind="limit", wall=1000, ts=190.0),
    {"ts": 200.0, "kind": "run_end", "run": "r1", "job": "260927-a", "command": "analyze",
     "exit_code": 2, "wall_s": 100.0},
    {"ts": 300.0, "kind": "run_start", "run": "r2", "job": "260927-a", "command": "analyze",
     "args": {}},
    {"ts": 301.0, "kind": "llm_cache_hit", "pass": "scan", "job": "260927-a", "run": "r2",
     "saved_usd": 0.04},
    {"ts": 302.0, "kind": "llm_cache_hit", "pass": "detail", "job": "260927-a", "run": "r2",
     "saved_usd": 0.10},
    llm("detail", O, "r2", 0.12, inp=2, cr=8000, out=3000, wall=24000, ts=310.0),
    {"ts": 330.0, "kind": "run_end", "run": "r2", "job": "260927-a", "command": "analyze",
     "exit_code": 0, "wall_s": 30.0},
    {"ts": 400.0, "kind": "run_start", "run": "r3", "job": "260927-a", "command": "render",
     "args": {}},
    {"ts": 445.5, "kind": "run_end", "run": "r3", "job": "260927-a", "command": "render",
     "exit_code": 0, "wall_s": 45.5},
]


def make(tmp_path, events=EVENTS, duration=600.0, job_id="260927-a", candidates=4, approved=2,
         provenance=None):
    job = jobs.create_job(tmp_path / "jobs", job_id, {"channel": "catholic-br",
                                                       "duration": duration})
    job.log_path.write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")
    if candidates is not None:
        jobs.write_json_atomic(job.candidates_json, {
            "candidates": [{"id": f"c{i}"} for i in range(candidates)],
            "llm": provenance or {}})
    jobs.write_json_atomic(job.review_json, {"decisions": {
        f"c{i}": {"status": "approved" if i < approved else "rejected"}
        for i in range(candidates or 0)}})
    return job


def row(rep, pass_, model):
    return next(r for r in rep["rows"] if r["pass"] == pass_ and r["model"] == model)


def test_rows_per_pass_and_model_in_pipeline_order(tmp_path):
    rep = job_report(make(tmp_path))
    assert [(r["pass"], r["model"]) for r in rep["rows"]] == [
        ("scan", H), ("detail", O), ("review_blind", S), ("review_faithful", S)]
    d = row(rep, "detail", O)
    assert (d["calls"], d["retries"], d["failed"]) == (4, 1, 1)
    assert d["cost_usd"] == pytest.approx(0.34)
    assert (d["input_tokens"], d["cache_write_tokens"], d["cache_read_tokens"],
            d["output_tokens"]) == (6, 8000, 18000, 9500)
    assert d["wall_s"] == pytest.approx(70.0)
    assert d["share"] == pytest.approx(0.68)


def test_totals_per_minute_per_candidate_per_approved(tmp_path):
    rep = job_report(make(tmp_path))
    t = rep["total"]
    assert (t["calls"], t["retries"], t["failed"]) == (7, 1, 1)
    assert t["cost_usd"] == pytest.approx(0.50)
    assert (t["cache_hits"], t["saved_usd"]) == (2, pytest.approx(0.14))
    assert t["cost_basis"] == ["list"]
    assert rep["minutes"] == 10.0
    assert rep["per_minute_usd"] == pytest.approx(0.05)
    assert (rep["candidates"], rep["per_candidate_usd"]) == (4, pytest.approx(0.125))
    assert (rep["approved"], rep["per_approved_usd"]) == (2, pytest.approx(0.25))
    assert sum(r["share"] for r in rep["rows"]) == pytest.approx(1.0)


def test_one_run_only(tmp_path):
    rep = job_report(make(tmp_path), run="r2")
    assert rep["run"] == "r2"
    assert [(r["pass"], r["calls"]) for r in rep["rows"]] == [("detail", 1)]
    assert rep["total"]["cost_usd"] == pytest.approx(0.12)
    assert rep["total"]["saved_usd"] == pytest.approx(0.14)
    assert [r["run"] for r in rep["runs"]] == ["r2"]
    assert rep["local"] == []                    # transcription is not part of any run


def test_unknown_run_is_a_lookup_error_naming_the_log(tmp_path):
    job = make(tmp_path)
    with pytest.raises(LookupError, match="no run nope"):
        job_report(job, run="nope")


def test_runs_local_steps_and_limit_events(tmp_path):
    rep = job_report(make(tmp_path))
    assert [(r["run"], r["command"], r["exit_code"], r["calls"]) for r in rep["runs"]] == [
        ("r1", "analyze", 2, 6), ("r2", "analyze", 0, 1), ("r3", "render", 0, 0)]
    assert rep["runs"][0]["cost_usd"] == pytest.approx(0.38)
    assert rep["runs"][1]["saved_usd"] == pytest.approx(0.14)
    assert rep["local"] == [{"step": "transcribe", "runs": 1, "wall_s": 95.0},
                            {"step": "render", "runs": 1, "wall_s": 45.5}]
    assert [(l["ts"], l["pass"], l["model"]) for l in rep["limits"]] == [(190.0, "detail", O)]
    assert LIMIT in rep["limits"][0]["error"]
    assert rep["notes"] == ["1 calls have no cost (failed before reporting one, or no "
                            "pricing.toml price for the model)."]   # the limit call


def test_a_log_from_before_s4_is_reported_with_what_it_has_and_notes(tmp_path):
    old = [
        {"ts": 1.0, "kind": "transcreve", "returncode": 0},
        {"ts": 2.0, "kind": "llm", "backend": "claude-cli", "model": H, "ok": True,
         "input_tokens": 9, "output_tokens": 5550, "cost_usd": 0.039583},
        {"ts": 3.0, "kind": "llm", "backend": "claude-cli", "model": O, "ok": True,
         "input_tokens": 2, "output_tokens": 3965, "cost_usd": 0.141044},
        {"ts": 4.0, "kind": "llm", "backend": "claude-cli", "model": O, "ok": False,
         "error": "bad", "error_kind": "schema"},
        {"ts": 5.0, "kind": "llm", "backend": "claude-cli", "model": "other-model", "ok": True,
         "input_tokens": 1, "output_tokens": 1, "cost_usd": 0.01},
    ]
    prov = {"scan": {"backend": "claude-cli", "model": H},
            "detail": {"backend": "claude-cli", "model": O},
            "review": {"backend": "claude-cli", "model": S}}
    job = make(tmp_path, events=old, provenance=prov)
    job.log_path.write_text(job.log_path.read_text() + "{broken\n", encoding="utf-8")
    rep = job_report(job)
    assert [(r["pass"], r["model"], r["calls"]) for r in rep["rows"]] == [
        ("scan", H, 1), ("detail", O, 2), (UNKNOWN_PASS, "other-model", 1)]
    assert rep["total"]["cost_usd"] == pytest.approx(0.190627)
    assert row(rep, "detail", O)["failed"] == 1
    assert row(rep, "scan", H)["cache_write_tokens"] == 0
    assert row(rep, "scan", H)["wall_s"] is None and rep["total"]["wall_s"] is None
    notes = " ".join(rep["notes"])
    assert "4 of 4 calls were logged before S4" in notes
    assert "pass inferred from the model" in notes and "3 calls" in notes
    assert "1 calls have no cost" in notes
    assert "1 unreadable lines" in notes
    assert "transcription time was not logged" in notes
    assert rep["local"] == [{"step": "transcribe", "runs": 1, "wall_s": None}]


def test_a_job_without_llm_events_duration_or_candidates_is_all_zero_and_none(tmp_path):
    job = make(tmp_path, events=[], duration=None, candidates=None)
    rep = job_report(job)
    assert rep["rows"] == [] and rep["total"]["cost_usd"] == 0.0
    assert rep["minutes"] is None and rep["per_minute_usd"] is None
    assert rep["candidates"] is None and rep["per_candidate_usd"] is None
    assert rep["approved"] == 0 and rep["per_approved_usd"] is None
    assert any("no duration" in n for n in rep["notes"])
