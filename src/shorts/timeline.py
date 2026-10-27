"""Spans, the edit decision list (silence cutting) and class <-> clip time mapping."""
from __future__ import annotations

import bisect
import math
from dataclasses import dataclass

from shorts.words import Word


@dataclass(frozen=True)
class Span:
    start: float
    end: float

    @property
    def duration(self) -> float:
        return self.end - self.start


def _word_before(words: list[Word], t: float) -> Word | None:
    times = [w.t for w in words]
    i = bisect.bisect_right(times, t) - 1
    return words[i] if i >= 0 else None


def build_edl(
    segments: list[Span],
    silences: list[Span],
    words: list[Word],
    trigger: float = 0.8,
    keep: float = 0.5,
    keep_after_question: float = 0.8,
    fps: float = 30.0,
) -> list[Span]:
    """Kept spans (class timeline), in playback order, across all segments.

    A silence of `trigger` seconds or more inside a segment is shortened to `keep`
    seconds (half on each side); after a word ending in ? or ! it keeps
    `keep_after_question` seconds instead (rhetorical pause, spec 10.2).

    Every boundary is snapped to the segment's frame grid (seg.start + k/fps): the render
    keeps whole video frames but cuts audio sample-exact, so off-grid boundaries would let
    audio and video drift up to one frame per cut.
    """

    def grid(seg: Span, t: float) -> float:
        return round(seg.start + math.floor((t - seg.start) * fps + 0.5) / fps, 6)

    kept: list[Span] = []
    for raw in segments:
        seg = Span(raw.start, grid(raw, raw.end))
        cuts: list[Span] = []
        for sil in sorted(silences, key=lambda s: s.start):
            s, e = max(sil.start, seg.start), min(sil.end, seg.end)
            if e - s < trigger:
                continue
            prev = _word_before(words, s)
            tail = prev.w.rstrip()[-1:] if prev is not None else ""
            k = keep_after_question if tail and tail in "?!" else keep
            if e - s <= k:
                continue
            cuts.append(Span(s + k / 2, e - k / 2))
        cursor = seg.start
        for c in cuts:
            a, b = grid(seg, c.start), grid(seg, c.end)
            if a > cursor:
                kept.append(Span(cursor, a))
            cursor = max(cursor, b)
        if seg.end > cursor:
            kept.append(Span(cursor, seg.end))
    return kept


class TimeMap:
    """Maps the class timeline to the cut clip's timeline through an EDL."""

    def __init__(self, edl: list[Span]):
        if not edl:
            raise ValueError("empty EDL")
        self.edl = list(edl)
        self._offsets: list[float] = []
        acc = 0.0
        for span in self.edl:
            self._offsets.append(acc)
            acc += span.duration
        self._duration = acc

    @property
    def duration(self) -> float:
        return self._duration

    def to_clip(self, t: float) -> float | None:
        """Clip time for class time t; None when t falls in a removed gap or outside the clip."""
        last = len(self.edl) - 1
        for i, span in enumerate(self.edl):
            inside = span.start <= t < span.end or (i == last and t == span.end)
            if inside:
                return self._offsets[i] + (t - span.start)
        return None

    def to_class(self, t_clip: float) -> float:
        """Class time for clip time t_clip (clamped to the clip)."""
        t_clip = min(max(t_clip, 0.0), self._duration)
        i = bisect.bisect_right(self._offsets, t_clip) - 1
        i = max(0, min(i, len(self.edl) - 1))
        return self.edl[i].start + (t_clip - self._offsets[i])

    def cut_points(self) -> list[float]:
        """Clip-time instants where two kept spans join."""
        return self._offsets[1:]

    def snap_to_clip(self, t: float) -> float:
        """Like to_clip, but a time inside a removed gap snaps to the next kept instant."""
        mapped = self.to_clip(t)
        if mapped is not None:
            return mapped
        for i, span in enumerate(self.edl):
            if t < span.start:
                return self._offsets[i]
        return self._duration


def group_edl(edl: list[Span], segments: list[Span] | None = None) -> list[tuple[Span, list[Span]]]:
    """Kept spans grouped by the segment that holds them, in playback order.

    Each group is (read window, spans): the window is the smallest class-time range covering
    its spans, so the render and the loudness pass seek straight to each segment once, in the
    order it plays. Without `segments` the whole EDL is one group (plan 1's behaviour).
    """
    if not edl:
        raise ValueError("empty EDL")
    if not segments:
        return [(Span(edl[0].start, edl[-1].end), list(edl))]
    groups: list[tuple[Span, list[Span]]] = []
    for seg in segments:
        # a span belongs to the segment it starts in: build_edl snaps each segment's end to
        # its frame grid, which can land up to half a frame past the raw segment end
        spans = [s for s in edl if seg.start - 1e-6 <= s.start < seg.end]
        if spans:
            groups.append((Span(spans[0].start, spans[-1].end), spans))
    if sum(len(spans) for _, spans in groups) != len(edl):
        raise ValueError("EDL spans outside the given segments")
    return groups
