"""`shorts cost` text and --all (S4 spec 3, "Report"): fits 80 columns, hand-checked numbers."""
import pytest

from shorts.cost import all_jobs, format_all, format_report, job_report, projection
from test_cost_report import H, O, S, llm, make


def lines_fit(text):
    return all(len(line) <= 80 for line in text.splitlines())


def test_report_text_fits_80_columns_and_shows_every_section(tmp_path):
    rep = job_report(make(tmp_path))
    text = format_report(rep, projection(rep, 100, 40))
    assert lines_fit(text)
    for piece in ("Job 260927-a (all runs), 10.0 class minutes", "not a bill",
                  "scan", "claude-haiku-4-5", "review_faithful", "cache write", "cache read",
                  "Total: $0.5000 for 7 calls (1 retries, 1 failed)",
                  "Cache: 2 hits saved $0.1400 (not counted as spent)",
                  "Per class minute:  $0.0500",
                  "Per candidate:     $0.1250 (4 candidates)",
                  "Per approved clip: $0.2500 (2 approved)",
                  "transcribe", "render", "$0.00 (local)",
                  "Plan use: 7 calls, 1 usage-limit event", "r1", "r3",
                  "Projection for 100 minutes: $5.00",
                  "capped at 40 windows (scan_ceiling)"):
        assert piece in text, piece


def test_detail_row_shows_its_numbers(tmp_path):
    text = format_report(job_report(make(tmp_path)))
    detail = [l for l in text.splitlines() if l.startswith("detail")]
    assert len(detail) == 2                               # the cost table and the token table
    assert "$0.3400" in detail[0] and "68%" in detail[0] and "70s" in detail[0]
    assert "18,000" in detail[1] and "9,500" in detail[1]


def test_long_model_names_are_cut_not_overflowing(tmp_path):
    long = "claude-some-very-long-model-name-2026"
    job = make(tmp_path, events=[llm("scan", long, "r1", 0.01)])
    text = format_report(job_report(job))
    assert lines_fit(text) and "claude-some-very~" in text


def test_projection_scales_per_minute_cost_and_warns_about_the_ceiling(tmp_path):
    rep = job_report(make(tmp_path))
    p = projection(rep, 100, 40)
    assert p["minutes"] == 100 and p["cost_usd"] == pytest.approx(5.0)
    assert "scan_ceiling" in p["warning"] and "overstates" in p["warning"]
    empty = job_report(make(tmp_path / "b", events=[], duration=None, candidates=None))
    assert projection(empty, 100, 40) is None
    assert "no cost per class minute" in format_report(empty, None, project_minutes=100)


def test_all_jobs_one_line_each_with_cost_per_minute(tmp_path):
    make(tmp_path, job_id="260927-a")
    make(tmp_path, job_id="260928-b", duration=1200.0,
         events=[llm("scan", H, "r9", 0.30), llm("detail", O, "r9", 0.90),
                 llm("review_blind", S, "r9", 0.20)])
    (tmp_path / "jobs" / "_manual").mkdir()
    rows = all_jobs(tmp_path / "jobs")
    assert [r["job"] for r in rows] == ["260927-a", "260928-b"]
    b = rows[1]
    assert (b["minutes"], b["calls"]) == (20.0, 3)
    assert b["cost_usd"] == pytest.approx(1.4) and b["per_minute_usd"] == pytest.approx(0.07)
    assert b["models"] == {"scan": H, "detail": O, "review_blind": S}
    text = format_all(rows)
    assert lines_fit(text)
    line_b = next(l for l in text.splitlines() if l.startswith("260928-b"))
    assert "$1.4000" in line_b and "$0.0700" in line_b and "haiku-4-5" in line_b
    assert "Total: $1.9000 over 2 jobs" in text


def test_all_jobs_on_an_empty_folder(tmp_path):
    assert all_jobs(tmp_path / "nothing") == []
    assert "No jobs" in format_all([])


def _corrupt_job(tmp_path, name="260929-bad", content="{not json"):
    d = tmp_path / "jobs" / name
    d.mkdir(parents=True)
    (d / "job.json").write_text(content, encoding="utf-8")


@pytest.mark.parametrize("content", ["{not json", "[1, 2]"])
def test_all_jobs_lists_a_bad_job_with_a_note_and_keeps_the_good_one(tmp_path, content):
    make(tmp_path, job_id="260927-a")
    _corrupt_job(tmp_path, content=content)
    rows = all_jobs(tmp_path / "jobs")
    assert [r["job"] for r in rows] == ["260927-a", "260929-bad"]
    bad = rows[1]
    assert bad["error"] and bad["calls"] == 0 and bad["cost_usd"] == 0
    assert bad["minutes"] is None and bad["per_minute_usd"] is None and bad["models"] == {}
    text = format_all(rows)
    assert lines_fit(text) and "260929-bad" in text and "unreadable" in text
    assert "Total: $0.5000 over 2 jobs" in text


def test_estimate_cost_ignores_an_unreadable_job(tmp_path):
    from shorts.cost import estimate_cost
    make(tmp_path, job_id="260927-a")
    _corrupt_job(tmp_path)
    assert estimate_cost(tmp_path / "jobs", 10.0) == pytest.approx(0.5)


def test_a_non_numeric_duration_means_unknown_minutes_not_a_crash(tmp_path):
    _corrupt_job(tmp_path, content='{"duration": "abc"}')
    (row,) = all_jobs(tmp_path / "jobs")
    assert row["minutes"] is None and not row.get("error")
