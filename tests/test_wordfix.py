import random

import pytest

from shorts.wordfix import Edit, active_edits, anchors, effective_words
from shorts.words import Word

# The 10-minute sample around 393 s: slots 1089-1092 (spec 4.5 worked example).
SAMPLE = [Word(round(i * 0.3, 2), f"x{i}", 0.99) for i in range(1089)] + [
    Word(393.43, "la", 0.41), Word(393.89, "massa", 0.38), Word(394.07, "bactamia.", 0.52),
    Word(395.71, "Meu", 0.97)]
ARAMAIC = Edit(1089, 1091, ("lamá", "sabactâni?"), "foreign_term", "citação aramaica", 0.93)


def test_worked_example_merge_three_slots_into_two_tokens():
    out = effective_words(SAMPLE, [ARAMAIC], {})
    assert out[1089:] == [Word(393.43, "lamá", 0.41), Word(393.89, "sabactâni?", 0.38),
                          Word(395.71, "Meu", 0.97)]
    assert out[:1089] == SAMPLE[:1089] and len(out) == len(SAMPLE) - 1


def test_worked_example_split_one_slot_by_characters():
    raw = [Word(10.0, "quandoquer", 0.7), Word(10.5, "vier", 0.9)]
    out = effective_words(raw, [Edit(0, 0, ("quando", "quer"))], {})
    assert out == [Word(10.0, "quando", 0.7), Word(10.3, "quer", 0.7), Word(10.5, "vier", 0.9)]


def test_anchors():
    assert anchors(ARAMAIC) == {1089: ["lamá"], 1090: ["sabactâni?"]}
    assert anchors(Edit(0, 0, ("quando", "quer"))) == {0: ["quando", "quer"]}
    assert anchors(Edit(5, 8, ("a",))) == {5: ["a"]}


@pytest.mark.parametrize("n,k", [(2, 1), (3, 1), (3, 2), (4, 2), (4, 3), (5, 2), (12, 1)])
def test_merge_anchors_each_token_to_a_raw_slot(n, k):
    raw = [Word(float(i), f"w{i}", 0.5 + i / 100) for i in range(20)]
    out = effective_words(raw, [Edit(2, 1 + n, tuple(f"t{m}" for m in range(k)))], {})
    assert len(out) == 20 - n + k
    got = out[2:2 + k]
    assert [w.t for w in got] == [float(2 + (m * n) // k) for m in range(k)]
    assert [w.p for w in got] == [raw[2 + (m * n) // k].p for m in range(k)]
    assert out[:2] == raw[:2] and out[2 + k:] == raw[2 + n:]


@pytest.mark.parametrize("n,k", [(1, 2), (1, 3), (2, 3), (2, 5), (3, 7)])
def test_split_shares_the_slot_by_characters(n, k):
    raw = [Word(float(i), f"w{i}", 0.9) for i in range(10)]
    toks = tuple("x" * (m + 1) for m in range(k))
    out = effective_words(raw, [Edit(3, 2 + n, toks)], {})
    got = out[3:3 + k]
    assert [w.w for w in got] == list(toks)
    assert got[0].t == 3.0 and all(3.0 <= w.t < 3.0 + n for w in got)
    assert [w.t for w in got] == sorted(w.t for w in got)
    assert out[3 + k:] == raw[3 + n:]


def test_split_on_the_last_slot_of_the_class_uses_half_a_second():
    raw = [Word(0.0, "a", 1.0), Word(1.0, "bc", 1.0)]
    out = effective_words(raw, [Edit(1, 1, ("b", "c"))], {})
    assert [w.t for w in out] == [0.0, 1.0, 1.25]


def test_owner_fix_anywhere_in_the_range_cancels_the_automatic_edit():
    out = effective_words(SAMPLE, [ARAMAIC], {"1090": "maça"})
    assert [w.w for w in out[1089:]] == ["la", "maça", "bactamia.", "Meu"]
    out = effective_words(SAMPLE, [ARAMAIC], {"1091": ""})      # a drop is an owner fix too
    assert [w.w for w in out[1089:]] == ["la", "massa", "Meu"]
    assert active_edits(len(SAMPLE), [ARAMAIC], {"1089": "lá"}) == []


def test_owner_fix_outside_the_range_keeps_the_automatic_edit():
    out = effective_words(SAMPLE, [ARAMAIC], {"1092": "Meu!"})
    assert [w.w for w in out[1089:]] == ["lamá", "sabactâni?", "Meu!"]


def test_empty_fix_drops_the_slot_and_keeps_every_other_time():
    raw = [Word(0.0, "a", 1.0), Word(0.4, "é", 1.0), Word(0.9, "b", 1.0)]
    assert effective_words(raw, [], {"1": ""}) == [raw[0], raw[2]]


def test_dropped_first_slot_starts_the_clip_at_the_next_kept_word():
    raw = [Word(10.0, "né", 1.0), Word(10.3, "então", 1.0), Word(10.8, "Deus", 1.0)]
    out = effective_words(raw, [], {"0": ""})
    clip = [w for w in out if 10.0 <= w.t < 11.0]
    assert clip == [raw[1], raw[2]] and clip[0].t == 10.3


def test_manual_keys_that_are_not_slots_are_ignored():
    raw = [Word(0.0, "a", 1.0), Word(1.0, "b", 1.0)]
    assert effective_words(raw, [], {"abc": "x", "99": "y", "-1": "z"}) == raw


def test_bad_or_overlapping_edits_are_skipped():
    raw = [Word(float(i), f"w{i}", 0.9) for i in range(5)]
    edits = [Edit(3, 9, ("x",)), Edit(1, 2, ("a",)), Edit(2, 3, ("b",)), Edit(4, 3, ("c",))]
    assert [w.w for w in effective_words(raw, edits, {})] == ["w0", "a", "w3", "w4"]


def test_effective_words_stay_sorted_and_untouched_words_keep_their_time():
    rnd = random.Random(7)
    raw = [Word(round(i * 0.37, 3), f"w{i}", 0.9) for i in range(200)]
    for _ in range(50):
        edits, pos = [], 0
        while pos < 190:
            first = pos + rnd.randint(0, 6)
            last = min(first + rnd.randint(0, 3), 199)
            edits.append(Edit(first, last, tuple(f"t{first}x{m}" for m in range(rnd.randint(1, 5)))))
            pos = last + 1
        out = effective_words(raw, edits, {})
        times = [w.t for w in out]
        assert times == sorted(times)
        edited = {s for e in edits for s in range(e.first, e.last + 1)}
        assert [w for w in out if w.w.startswith("w")] == [raw[i] for i in range(200) if i not in edited]


def test_edit_round_trips_through_a_dict():
    assert Edit.from_dict(ARAMAIC.to_dict()) == ARAMAIC
    assert ARAMAIC.to_dict() == {"first": 1089, "last": 1091, "tokens": ["lamá", "sabactâni?"],
                                 "kind": "foreign_term", "reason": "citação aramaica",
                                 "confidence": 0.93}


def test_prefer_auto_makes_the_suggestion_win_over_an_owner_fix_in_its_range():
    manual = {"1090": "maça", "1092": "Meu!"}
    out = effective_words(SAMPLE, [ARAMAIC], manual, prefer_auto={1089})
    assert [w.w for w in out[1089:]] == ["lamá", "sabactâni?", "Meu!"]   # the fix outside stays
    assert active_edits(len(SAMPLE), [ARAMAIC], manual, prefer_auto={1089}) == [ARAMAIC]


def test_prefer_auto_restores_a_slot_the_owner_dropped_inside_the_range():
    out = effective_words(SAMPLE, [ARAMAIC], {"1091": ""}, prefer_auto={1089})
    assert [w.w for w in out[1089:]] == ["lamá", "sabactâni?", "Meu"]


def test_prefer_auto_index_that_starts_no_edit_is_ignored():
    out = effective_words(SAMPLE, [ARAMAIC], {"1090": "maça"}, prefer_auto={1090, 5})
    assert [w.w for w in out[1089:]] == ["la", "maça", "bactamia.", "Meu"]
    assert active_edits(len(SAMPLE), [ARAMAIC], {"1090": "maça"}, prefer_auto={1090}) == []


def test_owner_overridden_edit_still_claims_its_range():
    a = Edit(5, 7, ("a",), "mishearing", "", 0.9)
    b = Edit(7, 9, ("b",), "mishearing", "", 0.9)
    assert active_edits(20, [a, b], {"6": "x"}) == []
    assert active_edits(20, [a, b], {"6": "x"}, {5}) == [a]
