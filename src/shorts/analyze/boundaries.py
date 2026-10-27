"""Code, not the LLM, turns literal words into word-snapped spans (spec 6.4)."""
from __future__ import annotations

import bisect
from dataclasses import dataclass

from shorts.analyze.candidates import SegmentRef
from shorts.analyze.textutil import word_end
from shorts.timeline import Span
from shorts.words import find_phrase_span

LEAD = 0.35
TAIL = 0.45
MIN_TOTAL = 30.0
MAX_TOTAL = 60.0
WINDOW_MARGIN = 60.0     # first_words searched inside the window ± this
LAST_WITHIN = 90.0       # last_words must start within this many seconds of the first word
MAX_SEGMENT = 60.0


class SnapError(Exception):
    pass


@dataclass(frozen=True)
class SnapResult:
    segments: list[SegmentRef]
    too_long: bool
    too_short: bool


def validate_spans(spans: list[Span], duration: float) -> str | None:
    if not 1 <= len(spans) <= 3:
        return f"a clip needs 1 to 3 segments, got {len(spans)}"
    for s in spans:
        if s.end <= s.start:
            return f"empty segment {s.start:.2f}-{s.end:.2f}"
        if s.start < 0 or s.end > duration + 1e-6:
            return f"segment {s.start:.2f}-{s.end:.2f} is outside the class (0-{duration:.2f})"
    ordered = sorted(spans, key=lambda s: s.start)
    for x, y in zip(ordered, ordered[1:]):
        if y.start < x.end:
            return f"segments overlap: {x.start:.2f}-{x.end:.2f} and {y.start:.2f}-{y.end:.2f}"
    return None


def _pad(words, a: int, b: int) -> Span:
    start = words[a].t - LEAD
    if a > 0:
        start = max(start, word_end(words, a - 1))
    end = word_end(words, b) + TAIL
    if b + 1 < len(words):
        end = min(end, words[b + 1].t)
    return Span(max(start, 0.0), end)


def _index_at(words, t: float) -> int:
    return bisect.bisect_left([w.t for w in words], t)


def _all_matches(words, phrase: str, lo: int, hi: int) -> list[tuple[int, int]]:
    out, i = [], lo
    while True:
        m = find_phrase_span(words, phrase, i, hi)
        if m is None:
            return out
        out.append(m)
        i = m[0] + 1


def snap_segment(words, first_words: str, last_words: str, window):
    if window is not None:
        lo = _index_at(words, window.start - WINDOW_MARGIN)
        hi = _index_at(words, window.end + WINDOW_MARGIN)
    else:
        lo, hi = 0, len(words)
    starts = _all_matches(words, first_words, lo, hi)
    if not starts:
        raise SnapError(f"first_words not found: {first_words!r}")
    if window is not None:
        inside = [m for m in starts if window.start <= words[m[0]].t <= window.end]
        pool = inside or starts
    else:
        pool = starts
    if len(pool) > 1:
        where = ", ".join(f"{words[m[0]].t:.1f}s" for m in pool)
        raise SnapError(f"first_words ambiguous ({len(pool)} matches at {where}): {first_words!r}")
    a = pool[0][0]
    end_before = _index_at(words, words[a].t + LAST_WITHIN)
    ends = _all_matches(words, last_words, a, end_before)
    if not ends:
        raise SnapError(f"last_words not found within {LAST_WITHIN:.0f} s after first_words: {last_words!r}")
    if len(ends) > 1:
        where = ", ".join(f"{words[m[0]].t:.1f}s" for m in ends)
        raise SnapError(f"last_words ambiguous ({len(ends)} matches at {where}): {last_words!r}")
    m = ends[0]
    b = m[1]
    proposed = Span(words[a].t, word_end(words, b))
    return proposed, _pad(words, a, b), a, b


def _sentence_of(sents, idx: int) -> int:
    for n, s in enumerate(sents):
        if s.first <= idx <= s.last:
            return n
    return len(sents) - 1


def snap_candidate(raw: dict, words, sents, windows_by_id, duration: float) -> SnapResult:
    parts = []  # [window_id, first_words, last_words, proposed, a, b]
    segments = raw.get("segments") if isinstance(raw, dict) else None
    if not isinstance(segments, list) or not segments:
        raise SnapError("malformed candidate: missing or empty segments")
    for seg in segments:
        if not isinstance(seg, dict):
            raise SnapError(f"malformed segment: {seg!r}")
        for key in ("window_id", "first_words", "last_words"):
            if not isinstance(seg.get(key), str):
                raise SnapError(f"malformed segment: {key} missing or not a string")
        if seg["window_id"] not in windows_by_id:
            raise SnapError(f"unknown window_id {seg['window_id']!r}")
        win = windows_by_id[seg["window_id"]]
        proposed, _, a, b = snap_segment(words, seg["first_words"], seg["last_words"], win)
        if proposed.duration > MAX_SEGMENT:
            raise SnapError(f"segment longer than 60 s ({proposed.duration:.1f} s): {seg['first_words']!r}")
        parts.append([seg["window_id"], seg["first_words"], seg["last_words"], proposed, a, b])

    def spans() -> list[Span]:
        return [_pad(words, p[4], p[5]) for p in parts]

    def total() -> float:
        return sum(s.duration for s in spans())

    reason = validate_spans(spans(), duration)
    if reason:
        raise SnapError(reason)

    last = parts[-1]
    others = [_pad(words, p[4], p[5]) for p in parts[:-1]]
    guard = 0
    while total() < MIN_TOTAL and guard < 20:
        n = _sentence_of(sents, last[5])
        if n + 1 >= len(sents):
            break
        new_b = sents[n + 1].last
        grown = _pad(words, last[4], new_b)
        if any(grown.start < o.end and o.start < grown.end for o in others):
            break                                   # would grow into another segment
        last[5] = new_b
        guard += 1

    too_long = False
    if total() > MAX_TOTAL:
        original_b = last[5]
        n = _sentence_of(sents, last[5])
        trimmed = False
        while n > 0:
            n -= 1
            cand_end = sents[n].last
            if cand_end < last[4]:
                break
            last[5] = cand_end
            if total() <= MAX_TOTAL:
                trimmed = True
                break
        if not trimmed:
            last[5] = original_b                    # never leave a half-trimmed ending
            too_long = True
    too_short = total() < MIN_TOTAL
    reason = validate_spans(spans(), duration)
    if reason:
        raise SnapError(reason)
    segs = [SegmentRef(p[0], p[1], p[2], p[3], _pad(words, p[4], p[5])) for p in parts]
    return SnapResult(segs, too_long, too_short)
