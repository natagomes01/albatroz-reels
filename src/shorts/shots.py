"""Shot planning (wide / close-up hard cuts) and the per-output-frame crop windows (spec 8.2)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from shorts.timeline import Span, TimeMap
from shorts.vision import Box
from shorts.words import Sentence, Word

CLOSE_ZOOM = {"solo-standing": 1.4, "solo-seated": 1.6}
FACE_ROW = 0.30  # face center sits at 30% of the close-up height
BODY_HEADROOM = 0.05  # without a face, the top of the body box sits 5% below the top edge


@dataclass(frozen=True)
class Shot:
    start: float  # clip timeline
    end: float
    kind: str  # "wide" | "close"


@dataclass(frozen=True)
class Crop:  # source px, integers
    x: int
    y: int
    w: int
    h: int


def _cut_candidates(tm: TimeMap, words: list[Word], sents: list[Sentence]) -> list[float]:
    """Clip-time instants where a cut is allowed: sentence starts and EDL joins."""
    points = set(tm.cut_points())
    for s in sents[1:]:
        t = tm.to_clip(words[s.first].t)
        if t is not None:
            points.add(round(max(t - 0.1, 0.0), 3))
    return sorted(p for p in points if 0.0 < p < tm.duration)


def _merge(labels: list[tuple[float, float, str]]) -> list[Shot]:
    shots: list[Shot] = []
    for a, b, kind in labels:
        if shots and shots[-1].kind == kind:
            shots[-1] = Shot(shots[-1].start, b, kind)
        else:
            shots.append(Shot(a, b, kind))
    return shots


MIN_FRAGMENT = 1.0  # a shot shorter than this is a flash, never acceptable


def settle_shots(shots: list[Shot], min_fragment: float = MIN_FRAGMENT) -> list[Shot]:
    """Merge adjacent shots of one kind; a fragment under `min_fragment` takes its neighbor's kind."""
    out = _merge([(s.start, s.end, s.kind) for s in shots])
    while len(out) > 1:
        i = min(range(len(out)), key=lambda k: out[k].end - out[k].start)
        if out[i].end - out[i].start >= min_fragment:
            break
        j = i - 1 if i > 0 else 1  # previous shot, else the next one
        out[i] = Shot(out[i].start, out[i].end, out[j].kind)
        out = _merge([(s.start, s.end, s.kind) for s in out])
    return out


def plan_shots(
    tm: TimeMap,
    words: list[Word],
    sents: list[Sentence],
    hook: Span | None,
    emphasis: list[Span],
    body_jumps: list[float],
    min_len: float = 4.0,
) -> list[Shot]:
    """Hard cuts between wide and close-up, only at sentence starts or EDL joins.

    The clip opens in close-up for the hook, emphasis spans go close, and a body jump at a
    cut point switches a wide shot to close-up to hide it. A close-up shorter than `min_len`
    grows into the next interval; a wide shot shorter than `min_len` becomes close-up.
    """
    bounds = [0.0, *_cut_candidates(tm, words, sents), tm.duration]
    close_ranges: list[tuple[float, float]] = []
    for span in ([hook] if hook else []) + list(emphasis):
        a, b = tm.snap_to_clip(span.start), tm.snap_to_clip(span.end)
        if b > a:
            close_ranges.append((a, b))
    kinds: list[str] = []
    for a, b in zip(bounds, bounds[1:]):
        close = any(a < cb and ca < b for ca, cb in close_ranges)  # interval overlaps a range
        kinds.append("close" if close else "wide")
    jumps = {round(j, 3) for j in body_jumps}
    for i in range(1, len(kinds)):
        if round(bounds[i], 3) in jumps and kinds[i - 1] == kinds[i] == "wide":
            kinds[i] = "close"
    kinds = _enforce_min_len(bounds, kinds, min_len)
    return _merge([(bounds[i], bounds[i + 1], k) for i, k in enumerate(kinds)])


def _runs(kinds: list[str]) -> list[tuple[int, int]]:
    """(first, last) interval index of each run of equal kinds."""
    runs: list[tuple[int, int]] = []
    start = 0
    for i in range(1, len(kinds) + 1):
        if i == len(kinds) or kinds[i] != kinds[start]:
            runs.append((start, i - 1))
            start = i
    return runs


def _enforce_min_len(bounds: list[float], kinds: list[str], min_len: float) -> list[str]:
    """Short close-ups grow forward (then backward) to min_len; short wides become close."""
    kinds = list(kinds)
    length = lambda r: bounds[r[1] + 1] - bounds[r[0]]  # noqa: E731
    for _ in range(len(kinds)):
        short_close = [r for r in _runs(kinds) if kinds[r[0]] == "close" and length(r) < min_len]
        if not short_close:
            break
        first, last = short_close[0]
        if last + 1 < len(kinds):
            kinds[last + 1] = "close"
        elif first > 0:
            kinds[first - 1] = "close"
        else:
            break
    for _ in range(len(kinds)):
        runs = _runs(kinds)
        short_wide = [r for r in runs if kinds[r[0]] == "wide" and length(r) < min_len]
        if not short_wide or len(runs) == 1:
            break
        first, last = short_wide[0]
        for i in range(first, last + 1):
            kinds[i] = "close"
    return kinds


def _even(v: float) -> int:
    return int(round(v / 2)) * 2


def crop_windows(
    shots: list[Shot],
    tm: TimeMap,
    fps: float,
    wide_cx: Callable[[float], float],
    face_at: Callable[[float], Box | None],
    src_w: int,
    src_h: int,
    fmt: str,
    body_at: Callable[[float], Box | None] | None = None,
    close_zoom: float | None = None,
) -> list[Crop]:
    """One Crop per OUTPUT frame (frame i at clip time i/fps).

    Wide: full height, 9:16 width, centred on the tracked x. Close-up: fixed size (zoom per
    format); its x follows the same smoothed path as the wide shot, so a walking speaker stays
    in frame; its y is fixed for the shot: face at the shot start (else midpoint) at FACE_ROW
    of the height, else the top of the body box minus BODY_HEADROOM, else the top of the frame.
    """
    wide_w, wide_h = _even(src_h * 9 / 16), _even(src_h)
    close_h = _even(src_h / (close_zoom or CLOSE_ZOOM[fmt]))
    close_w = _even(close_h * 9 / 16)
    close_y: dict[int, int] = {}
    for si, shot in enumerate(shots):
        if shot.kind != "close":
            continue
        t_start = tm.to_class(shot.start)
        t_mid = tm.to_class((shot.start + shot.end) / 2)
        face = face_at(t_start) or face_at(t_mid)
        body = body_at(t_start) if body_at is not None else None
        if face is not None:
            y = face.y + face.h / 2 - close_h * FACE_ROW
        elif body is not None:
            y = body.y - close_h * BODY_HEADROOM
        else:
            y = 0.0
        close_y[si] = int(round(min(max(y, 0), src_h - close_h)))
    n = int(round(tm.duration * fps))
    crops: list[Crop] = []
    si = 0
    for i in range(n):
        t = i / fps
        while si < len(shots) - 1 and t >= shots[si].end:
            si += 1
        cx = wide_cx(tm.to_class(t))
        if shots[si].kind == "close":
            x = min(max(cx - close_w / 2, 0), src_w - close_w)
            crops.append(Crop(int(round(x)), close_y[si], close_w, close_h))
        else:
            x = min(max(cx - wide_w / 2, 0), src_w - wide_w)
            crops.append(Crop(int(round(x)), 0, wide_w, wide_h))
    return crops


def assert_in_bounds(crops: list[Crop], src_w: int, src_h: int) -> None:
    """Every frame must have a window fully inside the source image (the 'door' lesson)."""
    for i, c in enumerate(crops):
        if c.w <= 0 or c.h <= 0 or c.x < 0 or c.y < 0 or c.x + c.w > src_w or c.y + c.h > src_h:
            raise ValueError(f"frame {i}: crop {c} outside {src_w}x{src_h}")
