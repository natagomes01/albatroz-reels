# tests/test_boundaries.py
import pytest

from shorts.analyze.boundaries import SnapError, snap_candidate, snap_segment, validate_spans
from shorts.analyze.windows import Window
from shorts.timeline import Span
from shorts.words import Word, sentences


def cls(n_sent=30, per=10, step=0.5, gap=1.0):
    ws, t = [], 0.0
    for s in range(n_sent):
        for k in range(per):
            ws.append(Word(t=round(t, 3), w=f"p{s}q{k}" + ("." if k == per - 1 else ""), p=1.0))
            t += step
        t += gap
    return ws


WS = cls()
SENTS = sentences(WS)
DUR = WS[-1].t + 1.0
WHOLE = Window("w1", 0, len(WS) - 1, 0.0, WS[-1].t, "")
WIN = {"w1": WHOLE}


def phrase(s, k0, n=6):
    return " ".join(f"p{s}q{k}" for k in range(k0, k0 + n))


def test_snap_pads_without_entering_neighbors():
    prop, snap, a, b = snap_segment(WS, phrase(2, 0), phrase(3, 4), WHOLE)
    assert WS[a].w == "p2q0" and WS[b].w == "p3q9."
    assert snap.start == pytest.approx(WS[a].t - 0.35)
    assert snap.end == pytest.approx(WS[b].t + 1.0 + 0.45)   # word_end caps at +1.0 s, then +0.45
    assert prop.start == WS[a].t


def test_padding_clamped_by_neighbor_word():
    ws = [Word(0.0, "a", 1), Word(0.2, "b", 1), Word(0.4, "c", 1), Word(0.6, "d", 1),
          Word(0.8, "e", 1), Word(1.0, "f", 1), Word(1.2, "g.", 1), Word(1.4, "h", 1)]
    _, snap, _, _ = snap_segment(ws, "b c d e f g", "b c d e f g", None)
    assert snap.start == pytest.approx(0.2)    # word_end(a) = 0.2, not 0.2 - 0.35
    assert snap.end == pytest.approx(1.4)      # next word h starts at 1.4


def test_accents_and_punctuation_are_ignored():
    ws = [Word(0.0, "Não", 1), Word(0.3, "é", 1), Word(0.6, "óbvio?", 1)] + \
         [Word(1.0 + i * 0.3, f"x{i}", 1) for i in range(6)]
    _, _, a, b = snap_segment(ws, "nao e obvio", "x3 x4 x5", None)
    assert (a, b) == (0, 8)


def test_hyphenated_and_contracted_words_match():
    ws = [Word(i * 0.4, w, 1) for i, w in enumerate(
        ["Isso", "chama-se", "tradição,", "e", "don't", "forget", "it.", "Fim", "aqui."])]
    _, _, a, b = snap_segment(ws, "isso chama se tradicao", "don't forget it", None)
    assert (a, b) == (0, 6)


def test_not_found_raises_with_reason():
    with pytest.raises(SnapError, match="first_words not found"):
        snap_segment(WS, "palavras que nao existem aqui", phrase(3, 4), WHOLE)
    with pytest.raises(SnapError, match="last_words not found"):
        snap_segment(WS, phrase(2, 0), "nada disso existe", WHOLE)


def _repeat_class():
    # The same 6-word phrase at 12:00 and at 13:10; the window is 13:00-15:00.
    rep = ["mesma", "frase", "dita", "duas", "vezes", "aqui."]
    ws, t = [], 0.0
    while t < 1000:
        ws.append(Word(round(t, 2), f"f{len(ws)}", 1)); t += 0.5
    ws = [w for w in ws if not (720 <= w.t < 723.5 or 790 <= w.t < 793.5)]
    for base in (720.0, 790.0):
        ws += [Word(base + i * 0.5, x, 1) for i, x in enumerate(rep)]
    return sorted(ws, key=lambda w: w.t)


def test_repeated_phrase_prefers_the_match_inside_the_window():
    ws = _repeat_class()
    win = Window("w7", 0, 0, 780.0, 900.0, "")
    _, _, a, _ = snap_segment(ws, "mesma frase dita duas vezes aqui", "f1700 f1701", win)
    assert ws[a].t == pytest.approx(790.0)


def test_two_matches_inside_the_window_is_ambiguous():
    ws = _repeat_class()
    win = Window("w7", 0, 0, 700.0, 820.0, "")
    with pytest.raises(SnapError, match="ambiguous"):
        snap_segment(ws, "mesma frase dita duas vezes aqui", "f1700 f1701", win)


def test_last_words_must_be_within_90_s():
    with pytest.raises(SnapError, match="last_words not found"):
        snap_segment(WS, phrase(0, 0), phrase(20, 0), WHOLE)     # sentence 20 is ~120 s later


def test_validate_spans():
    assert validate_spans([Span(0, 10)], 100) is None
    assert validate_spans([Span(50, 60), Span(0, 10)], 100) is None       # out of order is fine
    assert "overlap" in validate_spans([Span(0, 10), Span(5, 20)], 100)
    assert "overlap" in validate_spans([Span(50, 60), Span(55, 70)], 100)
    assert "1 to 3" in validate_spans([], 100)
    assert "1 to 3" in validate_spans([Span(i, i + 1) for i in range(0, 8, 2)], 100)
    assert "outside" in validate_spans([Span(-1, 10)], 100)
    assert "outside" in validate_spans([Span(90, 101)], 100)
    assert "empty" in validate_spans([Span(10, 10)], 100)


def test_short_total_extends_last_segment_by_sentence():
    raw = {"segments": [{"window_id": "w1", "first_words": phrase(2, 0), "last_words": phrase(2, 4)}]}
    r = snap_candidate(raw, WS, SENTS, WIN, DUR)        # one sentence = ~5 s
    assert not r.too_long and not r.too_short
    assert sum(s.snapped.duration for s in r.segments) >= 30


def test_extension_never_grows_into_another_segment():
    # Cold open: hook from sentence 10, body from sentence 3; extending the last (body)
    # segment must stop before sentence 10.
    raw = {"segments": [
        {"window_id": "w1", "first_words": phrase(10, 0), "last_words": phrase(10, 4)},
        {"window_id": "w1", "first_words": phrase(8, 0), "last_words": phrase(8, 4)},
    ]}
    r = snap_candidate(raw, WS, SENTS, WIN, DUR)
    hook, body = r.segments[0].snapped, r.segments[1].snapped
    assert body.end <= hook.start
    assert r.too_short                                   # 2 sentences only, cannot reach 30 s


def test_long_total_trims_back_or_flags_and_restores_the_end():
    raw = {"segments": [{"window_id": "w1", "first_words": phrase(0, 0), "last_words": phrase(8, 4)}]}
    r = snap_candidate(raw, WS, SENTS, WIN, DUR)          # 9 sentences ~ 54 s: fits
    assert not r.too_long and sum(s.snapped.duration for s in r.segments) <= 60
    # Two ~35 s segments (70 s total). The last one has no sentence end inside it, so no trim
    # fits: the candidate is flagged too_long and keeps its ORIGINAL end.
    ws = [Word(i * 0.25, f"z{i}" + ("." if i in (139, 339) else ""), 1) for i in range(400)]
    raw2 = {"segments": [
        {"window_id": "w1", "first_words": "z0 z1 z2 z3 z4 z5", "last_words": "z134 z135 z136 z137 z138 z139"},
        {"window_id": "w1", "first_words": "z200 z201 z202 z203 z204 z205", "last_words": "z334 z335 z336 z337 z338 z339"},
    ]}
    win = Window("w1", 0, 399, 0.0, 100.0, "")
    r2 = snap_candidate(raw2, ws, sentences(ws), {"w1": win}, 100.0)
    assert r2.too_long is True
    assert r2.segments[-1].snapped.end >= ws[339].t          # original end restored, not a partial trim


def test_a_single_segment_over_60_s_is_dropped():
    raw = {"segments": [{"window_id": "w1", "first_words": phrase(0, 0), "last_words": phrase(11, 4)}]}
    with pytest.raises(SnapError, match="longer than 60 s"):
        snap_candidate(raw, WS, SENTS, WIN, DUR)          # ~72 s proposed


def test_overlapping_segments_are_rejected():
    raw = {"segments": [
        {"window_id": "w1", "first_words": phrase(2, 0), "last_words": phrase(3, 4)},
        {"window_id": "w1", "first_words": phrase(3, 0), "last_words": phrase(4, 4)},
    ]}
    with pytest.raises(SnapError, match="overlap"):
        snap_candidate(raw, WS, SENTS, WIN, DUR)


def test_near_miss_quote_is_not_found():
    bad = "p2q0 p2q1 p2qX p2q3 p2q4 p2q5"          # one wrong word in an otherwise intact quote
    with pytest.raises(SnapError, match="first_words not found"):
        snap_segment(WS, bad, phrase(3, 4), WHOLE)


def test_not_found_quote_propagates_through_snap_candidate():
    raw = {"segments": [{"window_id": "w1", "first_words": "invented quote that is not there",
                         "last_words": phrase(3, 4)}]}
    with pytest.raises(SnapError, match="first_words not found"):
        snap_candidate(raw, WS, SENTS, WIN, DUR)


def test_unknown_window_id_is_rejected():
    raw = {"segments": [{"window_id": "w99", "first_words": phrase(2, 0), "last_words": phrase(2, 4)}]}
    with pytest.raises(SnapError, match="unknown window_id 'w99'"):
        snap_candidate(raw, WS, SENTS, WIN, DUR)


@pytest.mark.parametrize("seg", [
    {"first_words": phrase(2, 0), "last_words": phrase(2, 4)},
    {"window_id": "w1", "last_words": phrase(2, 4)},
    {"window_id": "w1", "first_words": phrase(2, 0)},
    {"window_id": "w1", "first_words": None, "last_words": phrase(2, 4)},
    {"window_id": "w1", "first_words": phrase(2, 0), "last_words": 5},
    "not a dict",
])
def test_malformed_segment_raises_snap_error(seg):
    with pytest.raises(SnapError, match="malformed"):
        snap_candidate({"segments": [seg]}, WS, SENTS, WIN, DUR)


def test_malformed_candidate_raises_snap_error():
    for raw in ({}, {"segments": []}, {"segments": "x"}, None):
        with pytest.raises(SnapError, match="malformed"):
            snap_candidate(raw, WS, SENTS, WIN, DUR)


def test_last_words_repeated_in_search_range_is_ambiguous():
    tail = ["amen", "amen", "we", "say", "amen", "today."]
    ws = [Word(i * 0.4, f"a{i}", 1) for i in range(6)]
    ws += [Word(2.4 + i * 0.4, w, 1) for i, w in enumerate(tail)]
    ws += [Word(5.0 + i * 0.4, f"b{i}", 1) for i in range(4)]
    ws += [Word(7.0 + i * 0.4, w, 1) for i, w in enumerate(tail)]
    with pytest.raises(SnapError, match="last_words ambiguous"):
        snap_segment(ws, "a0 a1 a2 a3 a4 a5", " ".join(tail), None)
