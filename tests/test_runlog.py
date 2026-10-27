"""Run boundaries and the per-run cost line (S4 spec 3, "Runs")."""
import json
import re
from datetime import datetime

import pytest

from shorts import jobs, runlog
from shorts.llm.context import current_context


def job(tmp_path):
    return jobs.create_job(tmp_path / "jobs", "260927-a", {"channel": "catholic-br",
                                                            "duration": 600.0})


def kinds(j):
    return [json.loads(l)["kind"] for l in j.log_path.read_text(encoding="utf-8").splitlines()]


def test_run_id_is_time_plus_four_hex():
    rid = runlog.new_run_id(datetime(2026, 9, 30, 14, 5, 9))
    assert re.fullmatch(r"260930-140509-[0-9a-f]{4}", rid)


def test_command_run_brackets_events_and_sets_the_context(tmp_path):
    j = job(tmp_path)
    with runlog.command_run(j, "analyze", {"job": "260927-a", "force": False}) as run:
        assert current_context() == {"pass": None, "job": j.id, "run": run.id}
        jobs.log_event(j, kind="llm", **current_context(), cost_usd=0.1)
        run.exit_code = 0
    assert current_context()["run"] is None
    evs, bad = runlog.read_log(j.log_path)
    assert bad == 0 and [e["kind"] for e in evs] == ["run_start", "llm", "run_end"]
    start, end = evs[0], evs[2]
    assert start["run"] == end["run"] == evs[1]["run"] == run.id
    assert start["command"] == "analyze" and start["args"] == {"job": "260927-a", "force": False}
    assert end["exit_code"] == 0 and end["wall_s"] >= 0 and end["job"] == j.id


def test_nested_command_run_reuses_the_outer_run_and_writes_nothing(tmp_path):
    j = job(tmp_path)
    with runlog.command_run(j, "run") as outer:
        with runlog.command_run(j, "analyze") as inner:
            assert inner.id == outer.id and inner.nested
        outer.exit_code = 0
    assert kinds(j) == ["run_start", "run_end"]


def test_an_exception_still_writes_run_end_with_a_failure_code(tmp_path):
    j = job(tmp_path)
    with pytest.raises(RuntimeError):
        with runlog.command_run(j, "analyze"):
            raise RuntimeError("boom")
    with pytest.raises(KeyboardInterrupt):
        with runlog.command_run(j, "analyze"):
            raise KeyboardInterrupt
    ends = [e for e in runlog.read_log(j.log_path)[0] if e["kind"] == "run_end"]
    assert [e["exit_code"] for e in ends] == [1, 130]


def test_read_log_skips_broken_lines_and_counts_them(tmp_path):
    p = tmp_path / "log.jsonl"
    p.write_text('{"kind": "llm"}\nnot json\n\n{"kind": "run_end"}\n[1, 2]\n', encoding="utf-8")
    evs, bad = runlog.read_log(p)
    assert [e["kind"] for e in evs] == ["llm", "run_end"] and bad == 2
    assert runlog.read_log(tmp_path / "missing.jsonl") == ([], 0)


def test_run_totals_counts_only_that_run_and_never_counts_saved_as_spent():
    evs = [{"kind": "llm", "run": "r1", "cost_usd": 0.5, "ok": True},
           {"kind": "llm", "run": "r1", "cost_usd": 0.02, "ok": False},
           {"kind": "llm", "run": "r1", "cost_usd": None, "ok": False},
           {"kind": "llm", "run": "r2", "cost_usd": 9.0},
           {"kind": "llm_cache_hit", "run": "r1", "saved_usd": 0.25},
           {"kind": "llm_cache_hit", "run": "r1", "saved_usd": None}]
    t = runlog.run_totals(evs, "r1")
    assert t == {"calls": 3, "cost_usd": pytest.approx(0.52), "cache_hits": 2,
                 "saved_usd": pytest.approx(0.25)}
    assert runlog.run_line(t) == (
        "LLM cost this run: $0.52 API-equivalent (3 calls, cache saved $0.25)")


def test_read_log_survives_a_truncated_multibyte_tail(tmp_path):
    p = tmp_path / "log.jsonl"
    p.write_bytes(b'{"kind": "a"}\n{"kind": "b", "x": "\xc3\xa7"}\n{"kind": "c", "x": "\xe2\x82')
    events, bad = runlog.read_log(p)
    assert [e["kind"] for e in events] == ["a", "b"] and bad == 1


def test_the_run_cost_covers_the_analysis_and_the_caption_corrections(tmp_path):
    """One analyze run: scan, detail, reviews AND class_sheet and caption_fix all land in the
    same run, so the one printed line is the total of the whole command."""
    from test_analyze_run import CH, REPO, WithCaptions, all_backends, app, make_job

    from shorts.analyze.run import run_analyze
    from shorts.llm.base import LLMBackend

    job = make_job(tmp_path)
    inner = WithCaptions({"w1": 90})

    class Costed(LLMBackend):
        name, calls = "costed", 0

        def _call(self, system, user, schema):
            Costed.calls += 1
            return inner.complete(system, user, schema), {"output_tokens": 1, "cost_usd": 0.1}

    b = Costed("stub", log=lambda ev: jobs.log_event(job, **ev))
    with runlog.command_run(job, "analyze", {}) as run:
        res = run_analyze(job, app(tmp_path), CH, REPO, backends=all_backends(b))
    assert res["fixes"] == 1
    events = runlog.read_log(job.log_path)[0]
    totals = runlog.run_totals(events, run.id)
    passes = {e["pass"] for e in events if e["kind"] == "llm"}
    assert {"scan", "detail", "class_sheet", "caption_fix"} <= passes
    assert totals["calls"] == Costed.calls
    assert totals["cost_usd"] == pytest.approx(0.1 * Costed.calls)
