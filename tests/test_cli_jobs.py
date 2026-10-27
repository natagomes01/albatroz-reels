import argparse

import pytest

from shorts import cli_jobs


def parser():
    p = argparse.ArgumentParser(prog="shorts")
    sub = p.add_subparsers(dest="command", required=True)
    cli_jobs.register(sub)
    return p


@pytest.mark.parametrize("argv", [
    ["ingest", "a.mp4", "--channel", "catholic-br", "--format", "solo-standing"],
    ["ingest", "a.mp4", "--channel", "catholic-br", "--format", "solo-standing", "--topic", "Salmo 22"],
    ["fixwords", "260927-a"], ["fixwords", "260927-a", "--all", "--force", "--topic", "Salmo 22"],
    ["analyze", "260927-a"], ["analyze", "260927-a", "--force"], ["review", "260927-a", "--no-browser"],
    ["track", "260927-a"], ["captions", "260927-a"], ["render", "260927-a", "--safe-zone"],
    ["render", "260927-a", "--clip", "c1", "--clip", "c2"], ["track", "260927-a", "--clip", "c1"],
    ["run", "260927-a"], ["backup"], ["backup", "260927-a", "--masters", "--dry-run"],
    ["clean", "260927-a"],
])
def test_subcommands_parse(argv):
    args = parser().parse_args(argv)
    assert callable(args.func)


def test_ingest_rejects_conversation(capsys):
    args = parser().parse_args(["ingest", "a.mp4", "--channel", "catholic-br",
                                "--format", "conversation"])
    assert args.func(args) == 2
    assert "phase 1b" in capsys.readouterr().err

def test_stage_exit_code_is_nonzero_when_a_clip_fails(monkeypatch, capsys, tmp_path):
    import shorts.stages as stages
    fake_job = type("J", (), {"log_path": tmp_path / "log.jsonl", "id": "260927-a"})()
    monkeypatch.setattr(cli_jobs, "_ctx", lambda args, ref=None: (None, None, fake_job, None))
    monkeypatch.setattr(stages, "run_clip_stage", lambda *a, **k: [
        {"clip": "c1", "error": "ffmpeg failed"},
        {"clip": "c2", "render": "/x/c2.mp4", "preview": None, "skipped": False}])
    args = parser().parse_args(["render", "260927-a"])
    assert args.func(args) == 1
    captured = capsys.readouterr()
    assert "c1: FAILED render" in captured.err and "c2: render done" in captured.out


def test_main_parser_dispatches_every_subcommand_through_func():
    from shorts.cli import build_parser
    for argv in (["doctor"], ["clip", "a.mp4", "--channel", "c", "--format", "solo-standing",
                              "--from", "0:10", "--to", "0:40"], ["render", "260927-a", "--safe-zone"],
                 ["track", "260927-a", "--preview"]):
        assert callable(build_parser().parse_args(argv).func)


def _env(tmp_path, master_exists=True, channel="catholic-br"):
    from shorts import jobs
    cfg = tmp_path / "config.toml"
    cfg.write_text(f'media_root = "{(tmp_path / "media").as_posix()}"\njobs_dir = "{(tmp_path / "jobs").as_posix()}"\n', encoding="utf-8")
    chans = tmp_path / "channels.toml"
    chans.write_text('[channels.catholic-br]\nlanguage = "pt"\n', encoding="utf-8")
    master = tmp_path / "m.mp4"
    if master_exists:
        master.write_bytes(b"x")
    jobs.create_job(tmp_path / "jobs", "260927-a", {"channel": channel, "format": "solo-standing",
                                                     "master": str(master)})
    return ["--config", str(cfg), "--channels", str(chans)]


@pytest.mark.parametrize("sub", ["analyze", "review", "track", "captions", "render", "run", "clean", "fixwords"])
def test_unknown_job_is_a_readable_error(tmp_path, capsys, sub):
    from shorts.cli import main
    base = _env(tmp_path)
    extra = ["--no-browser"] if sub == "review" else []
    assert main([*base, sub, "nope-job", *extra]) == 2
    assert "no job at" in capsys.readouterr().err


def test_channel_missing_from_channels_toml_is_a_readable_error(tmp_path, capsys):
    from shorts.cli import main
    base = _env(tmp_path, channel="ghost")
    assert main([*base, "render", "260927-a"]) == 2
    assert "ghost" in capsys.readouterr().err


@pytest.mark.parametrize("sub", ["render", "run"])
def test_moved_master_fails_with_its_path(tmp_path, capsys, sub):
    from shorts import jobs
    from shorts.cli import main
    base = _env(tmp_path, master_exists=False)
    job = jobs.load_job("260927-a", tmp_path / "jobs")
    jobs.write_json_atomic(job.words_json, {"version": 1, "words": [{"t": 0.0, "w": "a.", "p": 1}]})
    jobs.write_json_atomic(job.candidates_json, {"candidates": [{"id": "c01"}]})
    jobs.write_json_atomic(job.review_json, {"decisions": {"c01": {"status": "approved"}}})
    assert main([*base, sub, "260927-a"]) == 2
    assert str(tmp_path / "m.mp4") in capsys.readouterr().err


def test_safe_zone_render_prints_a_notice(tmp_path, monkeypatch, capsys):
    import shorts.stages as stages
    from shorts.cli import main
    base = _env(tmp_path)
    monkeypatch.setattr(stages, "run_clip_stage", lambda *a, **k: [
        {"clip": "c1", "render": "/x/c1.mp4", "preview": None, "skipped": False}])
    assert main([*base, "render", "260927-a", "--safe-zone"]) == 0
    assert "safe-zone" in capsys.readouterr().out


def test_analyze_limit_names_the_limit_and_says_rerun_resumes(tmp_path, monkeypatch, capsys):
    import shorts.analyze.run as run_mod
    from shorts.cli import main
    from shorts.llm.base import LLMError
    base = _env(tmp_path)

    def limit(*a, **k):
        raise LLMError("You've hit your limit", "limit")
    monkeypatch.setattr(run_mod, "run_analyze", limit)
    assert main([*base, "analyze", "260927-a"]) == 2
    err = capsys.readouterr().err
    assert "usage limit" in err and "hit your limit" in err
    assert "cached" in err and "shorts analyze 260927-a" in err


def test_analyze_zero_candidates_message(tmp_path, monkeypatch, capsys):
    import shorts.analyze.run as run_mod
    from shorts.cli import main
    base = _env(tmp_path)
    monkeypatch.setattr(run_mod, "run_analyze",
                        lambda *a, **k: {"candidates": 0, "windows": 7, "selected": 0})
    assert main([*base, "analyze", "260927-a"]) == 0
    out = capsys.readouterr().out
    assert "7 windows scanned" in out and "0 candidates" in out


def test_analyze_catch_all_is_short_but_keyboard_interrupt_passes(tmp_path, monkeypatch, capsys):
    import shorts.analyze.run as run_mod
    from shorts.cli import main
    base = _env(tmp_path)

    def bad(*a, **k):
        raise KeyError("scores")
    monkeypatch.setattr(run_mod, "run_analyze", bad)
    assert main([*base, "analyze", "260927-a"]) == 2
    err = capsys.readouterr().err
    assert "analyze failed: KeyError" in err and "Traceback" not in err

    def interrupted(*a, **k):
        raise KeyboardInterrupt
    monkeypatch.setattr(run_mod, "run_analyze", interrupted)
    with pytest.raises(KeyboardInterrupt):
        main([*base, "analyze", "260927-a"])


def test_run_passes_the_channel_to_next_stage(tmp_path, monkeypatch, capsys):
    import shorts.stages as stages
    from shorts.cli import main
    base = _env(tmp_path)
    seen = {}

    def fake_next(job, app=None, channel=None):
        seen["channel"] = channel
        return "done"
    monkeypatch.setattr(stages, "next_stage", fake_next)
    assert main([*base, "run", "260927-a"]) == 0
    assert seen["channel"] is not None and seen["channel"].id == "catholic-br"


def test_corrupt_review_json_is_a_readable_cli_error(tmp_path, capsys):
    from shorts import jobs
    from shorts.cli import main
    base = _env(tmp_path)
    job = jobs.load_job("260927-a", tmp_path / "jobs")
    jobs.write_json_atomic(job.words_json, {"version": 1, "words": [{"t": 0.0, "w": "a.", "p": 1}]})
    jobs.write_json_atomic(job.candidates_json, {"candidates": [{"id": "c01"}]})
    job.review_json.write_text("<<<<<<< HEAD\n", encoding="utf-8")
    assert main([*base, "render", "260927-a"]) == 2
    assert "review.json is not valid JSON" in capsys.readouterr().err


def test_ingest_passes_the_topic(tmp_path, monkeypatch):
    import shorts.ingest as ing
    from shorts.cli import main
    base = _env(tmp_path)
    seen = {}

    def fake_ingest(video, channel, fmt, app, **kw):
        seen.update(kw)
        return type("J", (), {"id": "x", "root": tmp_path})()
    monkeypatch.setattr(ing, "ingest", fake_ingest)
    assert main([*base, "ingest", "a.mp4", "--channel", "catholic-br", "--format", "solo-standing",
                 "--topic", "Salmo 22"]) == 0
    assert seen["topic"] == "Salmo 22"


def test_fixwords_passes_flags_and_prints_the_summary(tmp_path, monkeypatch, capsys):
    import shorts.analyze.fixwords as fx
    from shorts.cli import main
    base = _env(tmp_path)
    seen = {}

    def fake(job, app, channel, repo_root, **kw):
        seen.update(kw)
        return {"edits": 3, "dropped": 1, "chunks": 2, "total_chunks": 4, "rejected": 0}
    monkeypatch.setattr(fx, "run_fixwords", fake)
    assert main([*base, "fixwords", "260927-a", "--all", "--force", "--topic", "Salmo 22"]) == 0
    assert seen == {"all_chunks": True, "force": True, "topic": "Salmo 22"}
    assert "3 caption fixes (1 dropped) from 2 of 4 chunks" in capsys.readouterr().out
    assert main([*base, "fixwords", "260927-a"]) == 0
    assert seen["topic"] is None and seen["all_chunks"] is False


def test_fixwords_limit_names_the_limit_and_says_rerun_resumes(tmp_path, monkeypatch, capsys):
    import shorts.analyze.fixwords as fx
    from shorts.cli import main
    from shorts.llm.base import LLMError
    base = _env(tmp_path)

    def limit(*a, **k):
        raise LLMError("You've hit your limit", "limit")
    monkeypatch.setattr(fx, "run_fixwords", limit)
    assert main([*base, "fixwords", "260927-a"]) == 2
    err = capsys.readouterr().err
    assert "usage limit" in err and "hit your limit" in err and "shorts fixwords 260927-a" in err


def test_fixwords_rejected_chunks_are_reported(tmp_path, monkeypatch, capsys):
    import shorts.analyze.fixwords as fx
    from shorts.cli import main
    base = _env(tmp_path)
    monkeypatch.setattr(fx, "run_fixwords", lambda *a, **k: {
        "edits": 0, "dropped": 0, "chunks": 1, "total_chunks": 1, "rejected": 1})
    assert main([*base, "fixwords", "260927-a"]) == 0
    assert "1 chunk(s) rejected" in capsys.readouterr().err


def test_analyze_prints_caption_summary_and_a_warning_on_failure(tmp_path, monkeypatch, capsys):
    import shorts.analyze.run as run_mod
    from shorts.cli import main
    base = _env(tmp_path)
    monkeypatch.setattr(run_mod, "run_analyze", lambda *a, **k: {
        "candidates": 4, "windows": 7, "selected": 3, "fixes": 2, "fix_dropped": 1,
        "fix_error": None, "fix_error_kind": None})
    assert main([*base, "analyze", "260927-a"]) == 0
    assert "2 caption fixes (1 dropped)" in capsys.readouterr().out
    monkeypatch.setattr(run_mod, "run_analyze", lambda *a, **k: {
        "candidates": 4, "windows": 7, "selected": 3, "fixes": 0, "fix_dropped": 0,
        "fix_error": "LLMError: You've hit your limit", "fix_error_kind": "limit"})
    assert main([*base, "analyze", "260927-a"]) == 0
    err = capsys.readouterr().err
    assert "caption fixes skipped" in err and "shorts fixwords 260927-a" in err
    assert "limit resets" in err



def _fake_analyze_with_cost(job, *a, **k):
    from shorts import jobs
    from shorts.llm.context import current_context
    ctx = current_context()
    jobs.log_event(job, kind="llm", **ctx, ok=True, cost_usd=0.25)
    jobs.log_event(job, kind="llm_cache_hit", **{**ctx, "pass": "scan"}, saved_usd=0.5)
    return {"candidates": 1, "windows": 2, "selected": 1}


def _log(tmp_path):
    import json
    path = tmp_path / "jobs" / "260927-a" / "log.jsonl"
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines()]


def test_analyze_prints_the_run_cost_line_and_brackets_the_run(tmp_path, monkeypatch, capsys):
    import shorts.analyze.run as run_mod
    from shorts.cli import main
    base = _env(tmp_path)
    monkeypatch.setattr(run_mod, "run_analyze", _fake_analyze_with_cost)
    assert main([*base, "analyze", "260927-a"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[-1] == "LLM cost this run: $0.25 API-equivalent (1 calls, cache saved $0.50)"
    evs = _log(tmp_path)
    assert [e["kind"] for e in evs] == ["run_start", "llm", "llm_cache_hit", "run_end"]
    assert evs[0]["command"] == "analyze" and evs[0]["args"]["job"] == "260927-a"
    assert "func" not in evs[0]["args"]
    assert len({e["run"] for e in evs}) == 1 and evs[-1]["exit_code"] == 0


def test_run_that_analyzes_is_one_run_with_one_cost_line(tmp_path, monkeypatch, capsys):
    import shorts.analyze.run as run_mod
    import shorts.stages as stages
    from shorts.cli import main
    base = _env(tmp_path)
    monkeypatch.setattr(stages, "next_stage", lambda job, app=None, channel=None: "analyze")
    monkeypatch.setattr(run_mod, "run_analyze", _fake_analyze_with_cost)
    assert main([*base, "run", "260927-a"]) == 0
    out = capsys.readouterr().out
    assert out.count("LLM cost this run") == 1
    starts = [e for e in _log(tmp_path) if e["kind"] == "run_start"]
    assert [s["command"] for s in starts] == ["run"]


def test_a_failed_analyze_still_prints_what_it_spent(tmp_path, monkeypatch, capsys):
    import shorts.analyze.run as run_mod
    from shorts.cli import main
    from shorts.llm.base import LLMError
    base = _env(tmp_path)

    def spend_then_limit(job, *a, **k):
        _fake_analyze_with_cost(job)
        raise LLMError("You've hit your limit", "limit")
    monkeypatch.setattr(run_mod, "run_analyze", spend_then_limit)
    assert main([*base, "analyze", "260927-a"]) == 2
    assert "LLM cost this run: $0.25" in capsys.readouterr().out
    assert _log(tmp_path)[-1]["exit_code"] == 2


def test_no_llm_activity_prints_no_cost_line(tmp_path, monkeypatch, capsys):
    import shorts.analyze.run as run_mod
    from shorts.cli import main
    base = _env(tmp_path)
    monkeypatch.setattr(run_mod, "run_analyze",
                        lambda *a, **k: {"candidates": 0, "windows": 7, "selected": 0})
    assert main([*base, "analyze", "260927-a"]) == 0
    assert "LLM cost" not in capsys.readouterr().out


def test_local_stage_commands_write_run_boundaries_without_a_cost_line(tmp_path, monkeypatch,
                                                                         capsys):
    import shorts.stages as stages
    from shorts.cli import main
    base = _env(tmp_path)
    monkeypatch.setattr(stages, "run_clip_stage", lambda *a, **k: [
        {"clip": "c1", "render": "/x/c1.mp4", "preview": None, "skipped": False}])
    assert main([*base, "render", "260927-a"]) == 0
    assert "LLM cost" not in capsys.readouterr().out
    evs = _log(tmp_path)
    assert [e["kind"] for e in evs] == ["run_start", "run_end"]
    assert evs[0]["command"] == "render" and evs[1]["exit_code"] == 0


def _costed_env(tmp_path):
    import json
    from shorts import jobs
    from test_cost_report import EVENTS
    base = _env(tmp_path)
    job = jobs.load_job("260927-a", tmp_path / "jobs")
    jobs.write_json_atomic(job.job_json, {**jobs.read_json(job.job_json), "duration": 600.0})
    job.log_path.write_text("".join(json.dumps(e) + "\n" for e in EVENTS), encoding="utf-8")
    return base


def test_cost_prints_the_job_report(tmp_path, capsys):
    from shorts.cli import main
    base = _costed_env(tmp_path)
    assert main([*base, "cost", "260927-a", "--project", "100"]) == 0
    out = capsys.readouterr().out
    assert "Total: $0.5000 for 7 calls" in out and "Projection for 100 minutes: $5.00" in out
    assert all(len(l) <= 80 for l in out.splitlines())


def test_cost_json_and_run_filter(tmp_path, capsys):
    import json
    from shorts.cli import main
    base = _costed_env(tmp_path)
    assert main([*base, "cost", "260927-a", "--run", "r2", "--json", "--project", "50"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["run"] == "r2" and data["total"]["calls"] == 1
    assert data["projection"]["cost_usd"] == pytest.approx(0.6)   # $0.12 / 10 min x 50 min
    assert main([*base, "cost", "260927-a", "--json"]) == 0
    assert "projection" not in json.loads(capsys.readouterr().out)


def test_cost_all_lists_every_job(tmp_path, capsys):
    import json
    from shorts.cli import main
    base = _costed_env(tmp_path)
    assert main([*base, "cost", "--all"]) == 0
    assert "260927-a" in capsys.readouterr().out
    assert main([*base, "cost", "--all", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["jobs"][0]["job"] == "260927-a"


@pytest.mark.parametrize("argv,msg", [
    (["cost"], "name a job, or use --all"),
    (["cost", "260927-a", "--all"], "--all takes no job"),
    (["cost", "--all", "--project", "100"], "--all takes no job"),
    (["cost", "260927-a", "--run", "nope"], "no run nope"),
    (["cost", "nope-job"], "no job at"),
])
def test_cost_usage_errors_are_one_line(tmp_path, capsys, argv, msg):
    from shorts.cli import main
    base = _costed_env(tmp_path)
    assert main([*base, *argv]) == 2
    assert msg in capsys.readouterr().err


def test_cost_parses_every_flag():
    args = parser().parse_args(["cost", "260927-a", "--run", "r1", "--json", "--project", "90"])
    assert (args.job, args.run, args.json, args.project, args.all) == (
        "260927-a", "r1", True, 90.0, False)


def test_over_ceiling_question_answers(monkeypatch, capsys):
    from shorts.cli_jobs import _over_ceiling_question
    from types import SimpleNamespace
    ask = _over_ceiling_question(SimpleNamespace(yes=False))
    monkeypatch.setattr("builtins.input", lambda prompt="": "y")
    assert ask(45, 40) is True
    out = capsys.readouterr().out
    assert "45 windows" in out and "ceiling of 40" in out
    monkeypatch.setattr("builtins.input", lambda prompt="": "")
    assert ask(45, 40) is False and "Keeping the best 40" in capsys.readouterr().out

    def eof(prompt=""):
        raise EOFError
    monkeypatch.setattr("builtins.input", eof)
    assert ask(45, 40) is False                      # no terminal: the cheap side
    assert _over_ceiling_question(SimpleNamespace(yes=True))(45, 40) is True


def test_analyze_hands_the_question_to_run_analyze(tmp_path, monkeypatch):
    import shorts.analyze.run as run_mod
    from shorts.cli import main
    seen = {}

    def fake(job, *a, **k):
        seen["cb"] = k.get("over_ceiling")
        return {"candidates": 0, "windows": 1, "selected": 0}
    monkeypatch.setattr(run_mod, "run_analyze", fake)
    assert main([*_env(tmp_path), "analyze", "260927-a"]) == 0
    assert callable(seen["cb"])


def _clip_job(tmp_path):
    import json as _json
    cands = tmp_path / "candidates.json"
    cands.write_text(_json.dumps({"candidates": [{"id": "c1"}, {"id": "c2"}]}), encoding="utf-8")
    review = tmp_path / "review.json"
    review.write_text(_json.dumps({"decisions": {"c1": {"status": "approved"}}}), encoding="utf-8")
    return type("J", (), {"log_path": tmp_path / "log.jsonl", "id": "260927-a",
                          "candidates_json": cands, "review_json": review})()


def _fake_stage(monkeypatch, tmp_path):
    import shorts.stages as stages
    seen = {}

    def fake_run(*a, **k):
        seen["clip_ids"] = k.get("clip_ids")
        return [{"clip": c, "render": f"/x/{c}.mp4", "preview": None, "skipped": False}
                for c in sorted(k.get("clip_ids") or [])]

    monkeypatch.setattr(cli_jobs, "_ctx", lambda args, ref=None: (None, None, _clip_job(tmp_path), None))
    monkeypatch.setattr(stages, "run_clip_stage", fake_run)
    return seen


def test_clip_flag_passes_the_named_clip(monkeypatch, capsys, tmp_path):
    seen = _fake_stage(monkeypatch, tmp_path)
    args = parser().parse_args(["render", "260927-a", "--clip", "c1"])
    assert args.func(args) == 0
    assert seen["clip_ids"] == {"c1"} and "c1: render done" in capsys.readouterr().out


def test_clip_flag_refuses_pending_and_unknown_clips(monkeypatch, capsys, tmp_path):
    seen = _fake_stage(monkeypatch, tmp_path)
    args = parser().parse_args(["render", "260927-a", "--clip", "c2", "--clip", "zz"])
    assert args.func(args) == 1
    err = capsys.readouterr().err
    assert "c2: not approved, nothing rendered" in err and "zz: unknown clip" in err
    assert "clip_ids" not in seen                     # nothing left to render: the stage never ran


def test_clip_flag_renders_the_good_clip_and_still_exits_1(monkeypatch, capsys, tmp_path):
    seen = _fake_stage(monkeypatch, tmp_path)
    args = parser().parse_args(["render", "260927-a", "--clip", "c1", "--clip", "c2"])
    assert args.func(args) == 1
    out = capsys.readouterr()
    assert seen["clip_ids"] == {"c1"} and "c1: render done" in out.out
    assert "c2: not approved, nothing rendered" in out.err


def test_clip_flag_on_track_says_skipped(monkeypatch, capsys, tmp_path):
    _fake_stage(monkeypatch, tmp_path)
    args = parser().parse_args(["track", "260927-a", "--clip", "c2"])
    assert args.func(args) == 1
    assert "c2: not approved, skipped" in capsys.readouterr().err


def test_review_wires_the_render_queue(monkeypatch, tmp_path):
    import sys
    import shorts.review.server as server
    fake_job = type("J", (), {"id": "260927-a"})()
    monkeypatch.setattr(cli_jobs, "_ctx", lambda args, ref=None: ("APP", None, fake_job, "CH"))
    seen = {}
    monkeypatch.setattr(server, "serve", lambda job, **k: seen.update(k))
    args = parser().parse_args(["review", "260927-a", "--no-browser"])
    args.config, args.channels = tmp_path / "c.toml", tmp_path / "ch.toml"
    assert args.func(args) == 0
    assert seen["app"] == "APP" and seen["channel"] == "CH" and seen["open_browser"] is False
    assert seen["command"]("c1") == [sys.executable, "-m", "shorts.cli",
                                     "--config", str(tmp_path / "c.toml"),
                                     "--channels", str(tmp_path / "ch.toml"),
                                     "render", "260927-a", "--clip", "c1"]


def test_render_without_a_strength_says_what_to_do(tmp_path, monkeypatch, capsys):
    from shorts import jobs
    from shorts.config import AppConfig, ChannelConfig
    job = jobs.create_job(tmp_path / "jobs", "260927-a", {"channel": "catholic-br",
                                                         "format": "solo-standing", "master": "/m.mp4"})
    jobs.write_json_atomic(job.words_json, {"version": 1, "words": []})
    jobs.write_json_atomic(job.candidates_json, {"candidates": [{"id": "c01"}]})
    jobs.write_json_atomic(job.review_json, {"decisions": {"c01": {"status": "approved"}}})
    ch = ChannelConfig(id="catholic-br", language="pt", brand_dir=None, glossary="")
    app = AppConfig(media_root=tmp_path / "media", jobs_dir=tmp_path / "jobs", backends={})
    monkeypatch.setattr(cli_jobs, "_ctx", lambda args, ref=None: (app, {}, job, ch))
    monkeypatch.setattr(cli_jobs, "_master_problem", lambda job: None)
    code = cli_jobs._stage("render")(argparse.Namespace(job=job.id, clip=None, safe_zone=False))
    err = capsys.readouterr().err
    assert code == 1
    assert "choose the audio strength on the review page first" in err and "shorts review 260927-a" in err
