from shorts.analyze.candidates import (Candidate, SegmentRef, assign_ids, dedupe, group_by_hook,
                                       overlap, total)
from shorts.timeline import Span

W = {"hook": .30, "value": .25, "conversation": .25, "emotion": .20}


def cand(spans, s=(7, 7, 7, 7), cid="x"):
    segs = [SegmentRef("w1", "a", "b", Span(*sp), Span(*sp)) for sp in spans]
    dims = dict(zip(["hook", "value", "conversation", "emotion"],
                    [{"score": v, "why": ""} for v in s]))
    c = Candidate(id=cid, window_id="w1", segments=segs, title="t", hook="h", scores=dims,
                  controversy=1, controversy_why="", who_reacts="", emphasis=[], hook_id="h1",
                  out_of_order=False)
    c.total = total(c, W)
    return c


def test_total_weighted_0_to_100():
    assert total(cand([(0, 40)], (10, 10, 10, 10)), W) == 100.0
    # (8*.30 + 6*.25 + 4*.25 + 10*.20) * 10 = (2.4 + 1.5 + 1.0 + 2.0) * 10 = 69.0
    assert total(cand([(0, 40)], (8, 6, 4, 10)), W) == 69.0


def test_overlap_across_segments():
    a = cand([(0, 20), (100, 120)])
    b = cand([(10, 30), (110, 115)])
    assert overlap(a, b) == 15.0


def test_dedupe_at_80_percent_keeps_higher_total():
    hi = cand([(0, 40)], (9, 9, 9, 9), "hi")
    lo = cand([(4, 44)], (5, 5, 5, 5), "lo")      # overlap 36 of 40 = 90%
    keep = cand([(0, 30)], (6, 6, 6, 6), "keep")   # overlap with hi 30 of 30 = 100% -> dup
    other = cand([(20, 60)], (6, 6, 6, 6), "other")  # overlap with hi 20 of 40 = 50% -> kept
    ids = [c.id for c in dedupe([lo, hi, keep, other])]
    assert ids == ["hi", "other"]


def test_dedupe_prefers_a_kept_variant_over_a_dropped_one():
    dropped = cand([(0, 40)], (9, 9, 9, 9), "dropped")
    dropped.verdict = "drop"
    kept = cand([(2, 42)], (6, 6, 6, 6), "kept")          # 95% overlap, lower total
    assert [c.id for c in dedupe([dropped, kept])] == ["kept"]


def test_shared_hook_is_not_duplicate():
    a = cand([(0, 8), (100, 140)], cid="a")
    b = cand([(0, 8), (300, 340)], cid="b")
    assert [c.id for c in dedupe([a, b])] == ["a", "b"]
    groups = group_by_hook([a, b])
    assert list(groups.values()) == [["a", "b"]]
    assert a.hook_id == b.hook_id


def test_group_by_llm_hook_id_even_when_starts_differ():
    a = cand([(10, 50)], cid="a")
    b = cand([(200, 240)], cid="b")
    c = cand([(400, 440)], cid="c")
    a.llm_hook_id = b.llm_hook_id = "w3:h1"
    c.llm_hook_id = "w9:h1"                               # same raw id, other window: not grouped
    groups = group_by_hook([a, b, c])
    assert sorted(sorted(g) for g in groups.values()) == [["a", "b"], ["c"]]


def test_ids_are_stable_across_reruns_and_orders():
    a, b = cand([(0, 40)], (5, 5, 5, 5)), cand([(50, 90)], (9, 9, 9, 9))
    assign_ids([a, b])
    a2, b2 = cand([(0, 40)], (9, 9, 9, 9)), cand([(50, 90)], (1, 1, 1, 1))   # rescored, reordered
    assign_ids([b2, a2])
    assert (a.id, b.id) == (a2.id, b2.id)
    assert a.id != b.id and a.id.startswith("c") and len(a.id) == 7
    c = cand([(0.04, 40.02)])                              # rounds to the same spans as a
    d = cand([(0.04, 40.02)])
    assign_ids([c, d])
    assert c.id == a.id and d.id == a.id + "-2"


def test_roundtrip():
    b = cand([(50, 90)], (9, 9, 9, 9))
    assign_ids([b])
    again = Candidate.from_dict(b.to_dict())
    assert again.segments[0].snapped == Span(50, 90) and again.total == b.total
    assert again.duration() == 40 and again.id == b.id
