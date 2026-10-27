import json
from pathlib import Path

import pytest

from shorts.llm.base import LLMError
from shorts.analyze.profile import ChannelProfile
from shorts.analyze.scan import ScanResult, run_scan, select
from shorts.analyze.windows import Window

FIX = Path(__file__).parent / "fixtures" / "llm"
PROFILE = ChannelProfile("catholic-br", "pt", "icp", "aud")


class Stub:
    model = "stub"

    def __init__(self, replies):
        self.replies = list(replies)
        self.users = []

    def complete(self, system, user, schema):
        self.users.append(user)
        return self.replies.pop(0)


def wins(n):
    return [Window(f"w{i}", 0, 0, i * 90.0, i * 90.0 + 120, f"text {i}") for i in range(1, n + 1)]


def test_scan_batches_and_returns_all_ids():
    stub = Stub([json.loads((FIX / "scan_batch.json").read_text(encoding="utf-8"))])
    res = run_scan(wins(2), PROFILE, stub, batch_size=10)
    assert [(r.id, r.score) for r in res] == [("w1", 82), ("w2", 35)]
    assert "Content language: pt" in stub.users[0]
    assert "[w1]" in stub.users[0] and "[w2]" in stub.users[0]


def test_schema_sent_pins_the_batch_ids():
    stub = Stub([{"windows": [{"id": "w1", "score": 70, "reason": "r"},
                              {"id": "w2", "score": 20, "reason": "r"}]}])
    seen = []
    orig = stub.complete

    def complete(system, user, schema):
        seen.append(schema)
        return orig(system, user, schema)
    stub.complete = complete
    run_scan(wins(2), PROFILE, stub)
    items = seen[0]["properties"]["windows"]
    assert items["minItems"] == items["maxItems"] == 2
    assert items["items"]["properties"]["id"]["enum"] == ["w1", "w2"]


def test_a_missing_window_is_an_error_never_a_silent_zero():
    # A backend that skipped validation (or a stub) returns only w1: the stage must stop,
    # not score w2 as 0 and report "no window reached the threshold" (review M2).
    stub = Stub([{"windows": [{"id": "w1", "score": 70, "reason": "r"}]}])
    with pytest.raises(LLMError) as e:
        run_scan(wins(2), PROFILE, stub)
    assert e.value.kind == "schema" and "w2" in str(e.value)


def test_batches_of_ten():
    ws = wins(25)
    replies = [{"windows": [{"id": w.id, "score": 10, "reason": "r"} for w in ws[i:i + 10]]}
               for i in range(0, 25, 10)]
    stub = Stub(replies)
    res = run_scan(ws, PROFILE, stub, batch_size=10)
    assert len(stub.users) == 3 and len(res) == 25


def test_cache_skips_llm():
    store = {}
    stub = Stub([{"windows": [{"id": "w1", "score": 61, "reason": "r"}]}])
    run_scan(wins(1), PROFILE, stub, cache=store.get, store=store.__setitem__)
    stub2 = Stub([])
    res = run_scan(wins(1), PROFILE, stub2, cache=store.get, store=store.__setitem__)
    assert res[0].score == 61 and stub2.users == []


def test_select_threshold_and_ceiling():
    rs = [ScanResult(f"w{i}", s, "") for i, s in enumerate([90, 59, 60, 75, 100])]
    assert [r.score for r in select(rs, 60, 40)] == [100, 90, 75, 60]
    assert [r.score for r in select(rs, 60, 2)] == [100, 90]
    assert select([ScanResult("w1", 10, "")], 60, 40) == []


def test_duplicate_ids_in_a_reply_are_a_schema_error_and_not_cached():
    # for_batch does not enforce uniqueness: [w1, w1] satisfies minItems/maxItems/enum.
    store = {}
    stub = Stub([{"windows": [{"id": "w1", "score": 70, "reason": "r"},
                              {"id": "w1", "score": 20, "reason": "r"}]}])
    with pytest.raises(LLMError) as e:
        run_scan(wins(2), PROFILE, stub, cache=store.get, store=store.__setitem__)
    assert e.value.kind == "schema" and store == {}


def test_no_windows_makes_no_llm_call():
    stub = Stub([])
    assert run_scan([], PROFILE, stub) == [] and stub.users == []


def test_no_ceiling_keeps_every_window_at_or_above_the_threshold():
    rs = [ScanResult(f"w{i}", s, "") for i, s in enumerate([100, 90, 75, 60, 59])]
    assert [r.score for r in select(rs, 60, None)] == [100, 90, 75, 60]
