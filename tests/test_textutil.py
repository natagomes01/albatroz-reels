from shorts.analyze.textutil import (estimate_cut_duration, fmt_ts, text_of, word_end, words_in)
from shorts.timeline import Span
from shorts.words import Word


def W(*pairs):
    return [Word(t=t, w=w, p=1.0) for t, w in pairs]


def test_word_end_caps_and_last_word():
    ws = W((0.0, "a"), (0.3, "b"), (5.0, "c"))
    assert word_end(ws, 0) == 0.3
    assert word_end(ws, 1) == 1.3          # capped at 1.0 s
    assert word_end(ws, 2) == 5.5          # last word: +0.5


def test_text_of_and_fmt_ts():
    ws = W((0, "Olá,"), (1, "mundo."))
    assert text_of(ws, 0, 1) == "Olá, mundo."
    assert fmt_ts(65.4) == "01:05"
    assert fmt_ts(3725) == "1:02:05"


def test_words_in_span():
    ws = W((0, "a"), (1, "b"), (2, "c"), (3, "d"))
    assert words_in(ws, Span(0.5, 2.5)) == (1, 2)
    assert words_in(ws, Span(10, 11)) is None


def test_estimate_cut_duration_shortens_long_gaps():
    ws = W((0, "a"), (0.4, "b"), (3.0, "c?"), (6.0, "d"), (6.4, "e"))
    # gaps from word_end: b ends 1.4 -> c at 3.0 (1.6 s gap -> 0.5); c? ends 4.0 -> d at 6.0 (2.0 s -> 0.8)
    est = estimate_cut_duration(ws, [Span(0.0, 6.9)])
    assert abs(est - (6.9 - 1.1 - 1.2)) < 1e-6
