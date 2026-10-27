# tests/test_reviews.py
import pytest

from shorts.llm.base import LLMError
from shorts.analyze.candidates import Candidate, SegmentRef
from shorts.analyze.reviews import clip_text, run_reviews, verdict
from shorts.timeline import Span
from shorts.words import Word

WS = [Word(i * 1.0, f"w{i}", 1.0) for i in range(600)]


def cand(cid, spans, controversy=1, out_of_order=False, too_long=False):
    segs = [SegmentRef("w1", "", "", Span(*s), Span(*s)) for s in spans]
    dim = {"score": 5, "why": ""}
    return Candidate(id=cid, window_id="w1", segments=segs, title="t", hook="h",
                     scores={k: dim for k in ("hook", "value", "conversation", "emotion")},
                     controversy=controversy, controversy_why="", who_reacts="", emphasis=[],
                     hook_id="h", out_of_order=out_of_order, too_long=too_long)


class Stub:
    model = "stub"

    def __init__(self):
        self.calls = []

    def complete(self, system, user, schema):
        self.calls.append((system, user))
        ids = [line.split("]")[0][2:] for line in user.splitlines() if line.startswith("[#")]
        if "stands_alone" in str(schema):
            return {"results": [{"id": i, "stands_alone": i != "c02", "why": "w",
                                 "suggest_earlier_start": i == "c02"} for i in ids]}
        return {"results": [{"id": i, "faithful": i != "c03", "why": "w"} for i in ids]}


def test_clip_text_joins_segments():
    c = cand("c01", [(0, 3), (10, 12)])
    assert clip_text(c, WS) == "w0 w1 w2 [...] w10 w11"


def test_reviews_batched_and_blind_sees_only_clip_text():
    cs = [cand(f"c{n:02d}", [(n * 50, n * 50 + 40)]) for n in range(1, 8)]
    stub = Stub()
    run_reviews(cs, WS, stub, batch=5)
    assert len(stub.calls) == 4          # 2 blind batches + 2 faithful batches
    blind_user = stub.calls[0][1]
    assert "Context" not in blind_user
    faithful_user = next(u for s, u in stub.calls if "fidelity" in s)
    assert "Context around segment 1" in faithful_user
    by = {c.id: c for c in cs}
    assert by["c01"].verdict == "publish"
    assert by["c02"].verdict == "review" and "blind_failed" in by["c02"].warnings
    assert by["c03"].verdict == "drop" and "faithful_failed" in by["c03"].warnings


def test_verdict_rules():
    c = cand("c09", [(0, 40)], controversy=2, out_of_order=True, too_long=True)
    c.too_short = True
    c.blind = {"stands_alone": True, "why": ""}
    c.faithful = {"faithful": True, "why": ""}
    v, warns = verdict(c)
    assert v == "review"
    assert set(warns) == {"controversy_2", "out_of_order", "too_long", "too_short"}


def test_schema_sent_pins_the_batch_ids():
    cs = [cand(f"c{n:02d}", [(n * 50, n * 50 + 40)]) for n in range(1, 4)]
    seen = []

    class Spy(Stub):
        def complete(self, system, user, schema):
            seen.append(schema)
            return super().complete(system, user, schema)
    run_reviews(cs, WS, Spy(), batch=5)
    arr = seen[0]["properties"]["results"]
    assert arr["minItems"] == arr["maxItems"] == 3
    assert arr["items"]["properties"]["id"]["enum"] == ["c01", "c02", "c03"]


def test_a_missing_answer_is_review_missing_never_drop():
    cs = [cand("c01", [(0, 40)]), cand("c05", [(100, 140)])]

    class Partial(Stub):
        def complete(self, system, user, schema):
            out = super().complete(system, user, schema)
            out["results"] = [r for r in out["results"] if r["id"] != "c05"]
            return out
    logs = []
    run_reviews(cs, WS, Partial(), batch=5, log=logs.append)
    c05 = cs[1]
    assert c05.verdict == "review" and "review_missing" in c05.warnings
    assert any(e["kind"] == "review_missing" for e in logs)


def test_schema_failure_after_retries_marks_the_batch_review_missing():
    cs = [cand("c01", [(0, 40)]), cand("c05", [(100, 140)])]

    class Broken(Stub):
        def complete(self, system, user, schema):
            raise LLMError("reply did not match the schema", "schema")
    run_reviews(cs, WS, Broken(), batch=5)
    assert all(c.verdict == "review" and "review_missing" in c.warnings for c in cs)


def test_usage_limit_still_stops_the_stage():
    class Limited(Stub):
        def complete(self, system, user, schema):
            raise LLMError("You've hit your limit", "limit")
    with pytest.raises(LLMError):
        run_reviews([cand("c01", [(0, 40)])], WS, Limited(), batch=5)
