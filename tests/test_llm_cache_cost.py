"""Pass names reach the backend; cache hits log what they saved (S4 spec 3, "Cache hits")."""
import json

import pytest

from shorts import jobs
from shorts.analyze.llmcache import COST_KEY, cache_fns
from shorts.analyze.run import run_analyze
from shorts.llm.context import current_context, llm_context
from test_analyze_run import CH, REPO, Scripted, app, backends, make_job

COSTS = {"scan": 0.04, "detail": 0.11, "review_blind": 0.03, "review_faithful": 0.05}


class Costed(Scripted):
    """Scripted backend that records the pass of every call and reports a cost per pass."""

    def __init__(self, scan_scores):
        super().__init__(scan_scores)
        self.passes, self.last_cost_usd = [], None

    def complete(self, system, user, schema):
        p = current_context()["pass"]
        self.passes.append(p)
        self.last_cost_usd = COSTS[p]
        return super().complete(system, user, schema)


def events(job, kind):
    return [json.loads(l) for l in job.log_path.read_text(encoding="utf-8").splitlines()
            if json.loads(l)["kind"] == kind]


def test_every_call_runs_inside_its_pass_name(tmp_path):
    job = make_job(tmp_path)
    b = Costed({"w1": 90})
    run_analyze(job, app(tmp_path), CH, REPO, backends=backends(b))
    assert b.passes == ["scan", "detail", "review_blind", "review_faithful"]
    assert current_context()["pass"] is None                 # restored after the run


def test_cache_entries_store_the_cost_of_the_call_that_filled_them(tmp_path):
    job = make_job(tmp_path)
    run_analyze(job, app(tmp_path), CH, REPO, backends=backends(Costed({"w1": 90})))
    stored = {d: sorted(json.loads(f.read_text(encoding="utf-8"))[COST_KEY]
                        for f in (job.analyze_dir / "cache" / d).glob("*.json"))
              for d in ("scan", "detail", "review")}
    assert stored == {"scan": [0.04], "detail": [0.11], "review": [0.03, 0.05]}


def test_rerun_logs_one_cache_hit_per_call_with_saved_usd_and_spends_nothing(tmp_path):
    job = make_job(tmp_path)
    run_analyze(job, app(tmp_path), CH, REPO, backends=backends(Costed({"w1": 90})))
    first = json.loads(job.candidates_json.read_text(encoding="utf-8"))
    b2 = Costed({"w1": 90})
    with llm_context(run="r2"):
        run_analyze(job, app(tmp_path), CH, REPO, backends=backends(b2))
    assert b2.passes == []                                   # every answer came from the cache
    hits = events(job, "llm_cache_hit")
    assert [(h["pass"], h["saved_usd"]) for h in hits] == [
        ("scan", 0.04), ("detail", 0.11), ("review_blind", 0.03), ("review_faithful", 0.05)]
    assert all(h["run"] == "r2" and h["job"] == job.id for h in hits)
    assert json.loads(job.candidates_json.read_text(encoding="utf-8"))["candidates"] == first["candidates"]


def test_old_cache_entries_without_a_cost_still_hit_with_saved_none(tmp_path):
    job = make_job(tmp_path)
    get, put = cache_fns(job, "scan")                         # no backend: nothing to remember
    put("k1", {"windows": []})
    assert json.loads((job.analyze_dir / "cache" / "scan" / "k1.json").read_text(encoding="utf-8")) == {
        "windows": []}
    with llm_context(pass_name="scan"):
        assert get("k1") == {"windows": []}
    assert events(job, "llm_cache_hit")[0]["saved_usd"] is None


def test_a_miss_logs_nothing_and_the_cost_key_never_reaches_the_pass(tmp_path):
    job = make_job(tmp_path)
    backend = type("B", (), {"last_cost_usd": 0.2})()
    get, put = cache_fns(job, "detail", backend)
    assert get("missing") is None
    assert not job.log_path.exists() or events(job, "llm_cache_hit") == []
    data = {"candidates": []}
    put("k", data)
    assert data == {"candidates": []}                        # the caller's dict is not changed
    assert get("k") == {"candidates": []}
    hit = events(job, "llm_cache_hit")[0]
    assert hit["pass"] == "detail" and hit["saved_usd"] == 0.2   # dir name when no pass is set


def test_a_third_run_still_reports_the_original_scan_cost(tmp_path):
    job = make_job(tmp_path)
    run_analyze(job, app(tmp_path), CH, REPO, backends=backends(Costed({"w1": 90})))
    for run in ("r2", "r3"):                     # a hit must not rewrite the entry (cost dropped)
        with llm_context(run=run):
            run_analyze(job, app(tmp_path), CH, REPO, backends=backends(Costed({"w1": 90})))
    hits = [h for h in events(job, "llm_cache_hit") if h["run"] == "r3"]
    assert [(h["pass"], h["saved_usd"]) for h in hits] == [
        ("scan", 0.04), ("detail", 0.11), ("review_blind", 0.03), ("review_faithful", 0.05)]


def test_scan_with_one_hit_and_one_miss_keeps_each_entry_its_own_cost(tmp_path):
    from shorts.analyze.profile import ChannelProfile
    from shorts.analyze.scan import run_scan
    from shorts.analyze.windows import Window
    job = make_job(tmp_path)
    profile = ChannelProfile("catholic-br", "pt", "icp", "aud")
    wins = [Window(f"w{i}", 0, 0, i * 90.0, i * 90.0 + 120, f"text {i}") for i in (1, 2)]

    class B:
        model = "stub"
        last_cost_usd = None
        cost = 0.0

        def complete(self, system, user, schema):
            self.last_cost_usd = self.cost
            ids = [w.id for w in wins if f"[{w.id}]" in user]
            return {"windows": [{"id": i, "score": 50, "reason": "r"} for i in ids]}

    b = B()
    get, put = cache_fns(job, "scan", b)
    b.cost = 0.04
    run_scan(wins[1:], profile, b, batch_size=1, cache=get, store=put)
    b.cost = 0.09
    run_scan(wins, profile, b, batch_size=1, cache=get, store=put)      # w2 hits (after the w1 miss)
    stored = sorted(json.loads(f.read_text(encoding="utf-8"))[COST_KEY]
                    for f in (job.analyze_dir / "cache" / "scan").glob("*.json"))
    assert stored == [0.04, 0.09]
