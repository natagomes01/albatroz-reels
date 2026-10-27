"""Opt-in cost question before analyze (S4 spec 6, decision 1)."""
import json

import pytest

from shorts import jobs
from shorts.config import load_config
from shorts.cost import estimate_cost
from test_cli_jobs import _env
from test_cost_report import H, llm


def setup(tmp_path, threshold=None, earlier=True):
    base = _env(tmp_path)
    cfg = tmp_path / "config.toml"
    if threshold is not None:
        cfg.write_text(cfg.read_text() + f"cost_confirm_above_usd = {threshold}\n", encoding="utf-8")
    job = jobs.load_job("260927-a", tmp_path / "jobs")
    jobs.write_json_atomic(job.job_json, {**jobs.read_json(job.job_json), "duration": 600.0})
    if earlier:   # an earlier 20-minute class that cost $2.00: $0.10 per class minute
        old = jobs.create_job(tmp_path / "jobs", "260926-old", {"channel": "catholic-br",
                                                                 "duration": 1200.0})
        old.log_path.write_text(json.dumps(llm("detail", H, "r0", 2.0)) + "\n", encoding="utf-8")
    return base


@pytest.fixture
def analyzed(monkeypatch):
    import shorts.analyze.run as run_mod
    calls = []

    def fake(*a, **k):
        calls.append(1)
        return {"candidates": 0, "windows": 3, "selected": 0}
    monkeypatch.setattr(run_mod, "run_analyze", fake)
    return calls


def answer(monkeypatch, text):
    asked = []

    def fake_input(prompt):
        asked.append(prompt)
        if text is EOFError:
            raise EOFError
        return text
    monkeypatch.setattr("builtins.input", fake_input)
    return asked


def test_config_key_defaults_to_zero(tmp_path):
    (tmp_path / "config.toml").write_text('media_root = "m"\n', encoding="utf-8")
    assert load_config(tmp_path / "config.toml").cost_confirm_above_usd == 0.0
    (tmp_path / "config.toml").write_text('media_root = "m"\ncost_confirm_above_usd = 2.5\n', encoding="utf-8")
    assert load_config(tmp_path / "config.toml").cost_confirm_above_usd == 2.5


def test_estimate_uses_earlier_jobs_cost_per_class_minute(tmp_path):
    setup(tmp_path)
    assert estimate_cost(tmp_path / "jobs", 10.0, exclude="260927-a") == pytest.approx(1.0)
    assert estimate_cost(tmp_path / "jobs", 10.0, exclude="260926-old") is None
    assert estimate_cost(tmp_path / "jobs", None) is None


def test_default_never_asks(tmp_path, monkeypatch, analyzed, capsys):
    from shorts.cli import main
    base = setup(tmp_path)
    asked = answer(monkeypatch, "n")
    assert main([*base, "analyze", "260927-a"]) == 0
    assert asked == [] and analyzed == [1]
    assert "Estimated" not in capsys.readouterr().out


def test_estimate_above_threshold_asks_and_no_cancels(tmp_path, monkeypatch, analyzed, capsys):
    from shorts.cli import main
    base = setup(tmp_path, threshold=0.5)
    asked = answer(monkeypatch, "n")
    assert main([*base, "analyze", "260927-a"]) == 1
    captured = capsys.readouterr()
    assert "Estimated LLM cost: $1.00 API-equivalent for 10.0 class minutes" in captured.out
    assert asked and asked[0].endswith("Continue? [y/N] ")
    assert analyzed == [] and "cancelled" in captured.err


def test_yes_answer_runs(tmp_path, monkeypatch, analyzed):
    from shorts.cli import main
    base = setup(tmp_path, threshold=0.5)
    answer(monkeypatch, "y")
    assert main([*base, "analyze", "260927-a"]) == 0 and analyzed == [1]


def test_no_terminal_input_counts_as_no(tmp_path, monkeypatch, analyzed):
    from shorts.cli import main
    base = setup(tmp_path, threshold=0.5)
    answer(monkeypatch, EOFError)
    assert main([*base, "analyze", "260927-a"]) == 1 and analyzed == []


@pytest.mark.parametrize("sub", ["analyze", "run"])
def test_yes_flag_skips_the_question(tmp_path, monkeypatch, analyzed, sub):
    import shorts.stages as stages
    from shorts.cli import main
    base = setup(tmp_path, threshold=0.5)
    monkeypatch.setattr(stages, "next_stage", lambda job, app=None, channel=None: "analyze")
    asked = answer(monkeypatch, "n")
    assert main([*base, sub, "260927-a", "--yes"]) == 0
    assert asked == [] and analyzed == [1]


def test_estimate_below_threshold_prints_it_without_asking(tmp_path, monkeypatch, analyzed,
                                                          capsys):
    from shorts.cli import main
    base = setup(tmp_path, threshold=5)
    asked = answer(monkeypatch, "n")
    assert main([*base, "analyze", "260927-a"]) == 0
    assert asked == [] and "Estimated LLM cost: $1.00" in capsys.readouterr().out


def test_no_earlier_job_means_no_estimate_and_no_question(tmp_path, monkeypatch, analyzed):
    from shorts.cli import main
    base = setup(tmp_path, threshold=0.5, earlier=False)
    asked = answer(monkeypatch, "n")
    assert main([*base, "analyze", "260927-a"]) == 0
    assert asked == [] and analyzed == [1]
