"""Small text/time helpers shared by the analysis passes and the review page."""
from __future__ import annotations

from shorts.timeline import Span
from shorts.words import Word


def word_end(words: list[Word], i: int, cap: float = 1.0) -> float:
    """Words only carry a start time; a word ends at the next start, at most `cap` s later."""
    if i + 1 < len(words):
        return min(words[i + 1].t, words[i].t + cap)
    return words[i].t + 0.5


def text_of(words: list[Word], first: int, last: int) -> str:
    return " ".join(w.w for w in words[first:last + 1])


def fmt_ts(seconds: float) -> str:
    s = int(seconds)
    h, rest = divmod(s, 3600)
    m, s = divmod(rest, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def words_in(words: list[Word], span: Span) -> tuple[int, int] | None:
    idx = [i for i, w in enumerate(words) if span.start <= w.t < span.end]
    return (idx[0], idx[-1]) if idx else None


def estimate_cut_duration(words: list[Word], spans: list[Span], trigger: float = 0.8,
                          keep: float = 0.5, keep_after_question: float = 0.8) -> float:
    """Clip duration after silence cutting, estimated from word gaps (no audio needed).
    Mirrors spec 10.2; the render uses the real silencedetect EDL."""
    total = 0.0
    for span in spans:
        total += span.duration
        rng = words_in(words, span)
        if rng is None:
            continue
        a, b = rng
        for i in range(a, b):
            gap = words[i + 1].t - word_end(words, i)
            if gap >= trigger:
                target = keep_after_question if words[i].w.rstrip()[-1:] in "?!" else keep
                total -= max(gap - target, 0.0)
    return total
