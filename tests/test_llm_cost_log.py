"""The per-call `llm` event (S4 spec 3, "Per-call record" and "API backends")."""
import pytest

from shorts.config import AppConfig
from shorts.llm.base import LLMBackend, LLMError, get_backend
from shorts.llm.context import current_context, llm_context
from shorts.pricing import ModelPrice, PriceTable

SCHEMA = {"type": "object", "required": ["n"], "properties": {"n": {"type": "integer"}},
          "additionalProperties": False}
PRICES = PriceTable("2026-09-30", "fixture", {
    "m": ModelPrice(input=1.0, output=5.0, cache_write_5m=1.25, cache_write_1h=2.0, cache_read=0.1)})
FULL = {"input_tokens": 9, "cache_creation_input_tokens": 6648,
        "cache_creation_1h_input_tokens": 6648, "cache_read_input_tokens": 0,
        "output_tokens": 41, "thinking_tokens": 34, "duration_ms": 4210, "duration_api_ms": 3890}


class Fake(LLMBackend):
    name = "fake"

    def __init__(self, replies, usage, **kw):
        super().__init__("m", **kw)
        self.replies, self.usage = list(replies), usage

    def _call(self, system, user, schema):
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return r, dict(self.usage)


def test_event_has_every_field_with_reported_cost_and_table_cross_check():
    logged = []
    b = Fake([{"n": 1}], {**FULL, "cost_usd": 0.01351, "cost_basis": "list"},
             log=logged.append, prices=PRICES)
    with llm_context(pass_name="scan", job="260927-a", run="r1"):
        b.complete("s", "u", SCHEMA)
    e = logged[0]
    assert list(e)[:8] == ["kind", "pass", "job", "run", "backend", "model", "attempt", "ok"]
    assert (e["kind"], e["pass"], e["job"], e["run"]) == ("llm", "scan", "260927-a", "r1")
    assert (e["backend"], e["model"], e["attempt"], e["ok"]) == ("fake", "m", 1, True)
    for k, v in FULL.items():
        assert e[k] == v
    assert e["cost_usd"] == 0.01351 and e["cost_basis"] == "list"
    assert e["cost_table_usd"] == pytest.approx(0.01351)
    assert isinstance(e["wall_ms"], int) and e["wall_ms"] >= 0
    assert b.last_cost_usd == 0.01351


def test_api_backend_without_reported_cost_takes_the_table_cost():
    logged = []
    b = Fake([{"n": 1}], {"input_tokens": 1_000_000, "output_tokens": 100_000},
             log=logged.append, prices=PRICES)
    b.complete("s", "u", SCHEMA)
    e = logged[0]
    assert e["cost_usd"] == pytest.approx(1.5) and e["cost_basis"] == "table"
    assert e["cost_table_usd"] == pytest.approx(1.5)
    assert e["cache_read_input_tokens"] is None          # the key is always there


def test_no_reported_cost_and_no_price_gives_none_not_zero():
    logged = []
    Fake([{"n": 1}], {"input_tokens": 5}, log=logged.append).complete("s", "u", SCHEMA)
    assert logged[0]["cost_usd"] is None and logged[0]["cost_basis"] is None
    assert logged[0]["cost_table_usd"] is None
    assert (logged[0]["pass"], logged[0]["job"], logged[0]["run"]) == (None, None, None)


def test_schema_retries_are_separate_attempts_each_with_its_cost():
    logged = []
    b = Fake([{"n": "x"}, {"n": 2}], {"output_tokens": 10, "cost_usd": 0.25}, log=logged.append)
    assert b.complete("s", "u", SCHEMA) == {"n": 2}
    assert [e["attempt"] for e in logged] == [1, 2]
    assert [e["ok"] for e in logged] == [True, True]      # the call worked; the answer did not
    assert b.last_cost_usd == 0.5                         # both attempts are spent money


def test_failed_call_with_a_cost_is_logged_not_ok_and_counted():
    logged = []
    err = LLMError("overloaded", "transient", usage={"output_tokens": 3, "cost_usd": 0.02})
    b = Fake([err, {"n": 4}], {"cost_usd": 0.1}, log=logged.append, sleep=lambda s: None)
    b.complete("s", "u", SCHEMA)
    assert [(e["attempt"], e["ok"]) for e in logged] == [(1, False), (2, True)]
    assert logged[0]["cost_usd"] == 0.02 and logged[0]["error_kind"] == "transient"
    assert logged[0]["error"] == "overloaded"
    assert b.last_cost_usd == pytest.approx(0.12)


def test_last_cost_resets_per_complete_call():
    b = Fake([{"n": 1}, {"n": 2}], {"cost_usd": 0.3})
    b.complete("s", "u", SCHEMA)
    b.complete("s", "u", SCHEMA)
    assert b.last_cost_usd == 0.3


def test_more_than_ten_percent_apart_warns_once_per_backend():
    warned = []
    usage = {"input_tokens": 1_000_000, "cost_usd": 1.2}          # table says 1.0
    b = Fake([{"n": 1}, {"n": 1}], usage, prices=PRICES, warn=warned.append)
    b.complete("s", "u", SCHEMA)
    b.complete("s", "u", SCHEMA)
    assert len(warned) == 1
    assert "10%" in warned[0] and "pricing.toml" in warned[0] and "2026-09-30" in warned[0]


def test_within_ten_percent_does_not_warn():
    warned = []
    b = Fake([{"n": 1}], {"input_tokens": 1_000_000, "cost_usd": 1.05}, prices=PRICES,
             warn=warned.append)
    b.complete("s", "u", SCHEMA)
    assert warned == []


def test_context_nests_and_restores():
    assert current_context() == {"pass": None, "job": None, "run": None}
    with llm_context(job="j", run="r"):
        with llm_context(pass_name="detail"):
            assert current_context() == {"pass": "detail", "job": "j", "run": "r"}
        assert current_context()["pass"] is None
    assert current_context() == {"pass": None, "job": None, "run": None}


def test_get_backend_hands_the_price_table_to_the_backend(tmp_path):
    p = tmp_path / "pricing.toml"
    p.write_text('verified_on = "2026-09-30"\nsource = "fixture"\n[models.claude-haiku-4-5]\n'
                 'input = 1.0\noutput = 5.0\ncache_write_5m = 1.25\ncache_write_1h = 2.0\n'
                 'cache_read = 0.1\n', encoding="utf-8")
    app = AppConfig(media_root=tmp_path, jobs_dir=tmp_path, pricing_path=p,
                    backends={"scan": {"model": "claude-haiku-4-5"}})
    b = get_backend("scan", app)
    assert b.prices.for_model("claude-haiku-4-5").output == 5.0
    app2 = AppConfig(media_root=tmp_path, jobs_dir=tmp_path,
                     backends={"scan": {"model": "claude-haiku-4-5"}})
    assert get_backend("scan", app2).prices is None


def test_llm_event_with_a_job_field_goes_through_log_event(tmp_path):
    import json

    from shorts import jobs
    job = jobs.create_job(tmp_path, "260927-a", {"channel": "c"})
    b = Fake([{"n": 1}], {"cost_usd": 0.1}, log=lambda ev: jobs.log_event(job, **ev))
    with llm_context(job=job.id, run="r1"):
        b.complete("s", "u", SCHEMA)
    line = json.loads(job.log_path.read_text(encoding="utf-8").splitlines()[0])
    assert line["job"] == "260927-a" and line["run"] == "r1" and "ts" in line


def test_a_failed_call_with_empty_usage_has_no_cost_not_zero():
    logged = []
    b = Fake([LLMError("boom", "fatal")], {}, log=logged.append, prices=PRICES)
    with pytest.raises(LLMError):
        b.complete("s", "u", SCHEMA)
    e = logged[0]
    assert (e["cost_usd"], e["cost_table_usd"], e["cost_basis"]) == (None, None, None)
    assert b.last_cost_usd is None
