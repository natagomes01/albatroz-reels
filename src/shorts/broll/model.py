"""B-roll moments (S8B spec 4): shape, validation, anchoring to words and the timing rules.

A moment is anchored to RAW word indices of words.json (owner fixes never shift them), so its
class time comes from the words and its clip time from the clip's EDL: silence cuts move it with
its words.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass

from shorts.analyze.textutil import word_end
from shorts.timeline import Span, TimeMap
from shorts.words import Word

LAYOUTS = ("full", "split")
FITS = ("cover", "whole")
PANS = ("ltr", "rtl", "ttb", "btt", "still")
ORIGINS = ("llm", "owner")
SOURCES = ("commons", "pexels", "pixabay", "own")
MEDIA_KINDS = ("image", "video")
MAX_MOMENTS = 6
MAX_TERMS = 3
MAX_TERM = 80
MAX_NOTE = 200
MAX_TEXT = 500
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,119}$")
_ID = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
_PICK_TEXT = ("id", "download_url", "title", "author", "license", "license_url", "page_url")
EPS = 1e-6


@dataclass(frozen=True)
class BrollConfig:
    user_agent: str = "albatroz-shorts (set your contact here)"
    candidates: int = 6
    min_fill_px: int = 1080
    max_still_px: int = 4096
    thumb_width: int = 320
    pan_px_per_s: float = 40.0
    split_face_y: int = 1250
    insert_max_s: float = 10.0
    max_inserts: int = 3
    max_share: float = 0.50
    head_s: float = 3.0
    tail_s: float = 2.0
    upload_max_mb: int = 200


PLACEHOLDER_AGENT = BrollConfig().user_agent


def check_name(name) -> str:
    """A plain file name inside the job's B-roll folder: no path, no leading dot."""
    if not isinstance(name, str) or not _NAME.match(name) or name in (".", ".."):
        raise ValueError(f"unsafe B-roll file name: {name!r}")
    return name


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _pick(p) -> dict:
    if not isinstance(p, dict):
        raise ValueError("pick must be an object or null")
    if p.get("source") not in SOURCES:
        raise ValueError(f"pick source must be one of {SOURCES}")
    if p.get("kind") not in MEDIA_KINDS:
        raise ValueError(f"pick kind must be one of {MEDIA_KINDS}")
    out = {"source": p["source"], "kind": p["kind"], "file": check_name(p.get("file"))}
    for k in ("w", "h"):
        v = p.get(k)
        if not isinstance(v, int) or isinstance(v, bool) or v <= 0:
            raise ValueError(f"pick {k} must be a positive integer")
        out[k] = v
    d = p.get("duration")
    if d is not None and (not _num(d) or d < 0):
        raise ValueError("pick duration must be a number of seconds or null")
    out["duration"] = d
    for k in _PICK_TEXT:
        v = p.get(k, "")
        if not isinstance(v, str) or len(v) > MAX_TEXT:
            raise ValueError(f"pick {k} must be text of at most {MAX_TEXT} characters")
        out[k] = v
    return out


def validate_moments(value, n_words: int) -> list[dict]:
    """A cleaned copy of a clip's moment list, or ValueError (nothing is written before this)."""
    if not isinstance(value, list):
        raise ValueError("broll must be a list of moments")
    if len(value) > MAX_MOMENTS:
        raise ValueError(f"broll holds at most {MAX_MOMENTS} moments")
    out, seen = [], set()
    for m in value:
        if not isinstance(m, dict):
            raise ValueError("a moment must be an object")
        mid = m.get("id")
        if not isinstance(mid, str) or not _ID.match(mid):
            raise ValueError(f"bad moment id {mid!r}")
        if mid in seen:
            raise ValueError(f"moment ids must be unique ({mid})")
        seen.add(mid)
        first, last = m.get("first"), m.get("last")
        for v in (first, last):
            if not isinstance(v, int) or isinstance(v, bool) or not 0 <= v < n_words:
                raise ValueError(f"moment {mid}: word index {v!r} is out of range")
        if first > last:
            raise ValueError(f"moment {mid}: first word is after the last")
        for key, allowed in (("origin", ORIGINS), ("layout", LAYOUTS), ("fit", FITS), ("pan", PANS)):
            if m.get(key) not in allowed:
                raise ValueError(f"moment {mid}: {key} must be one of {allowed}")
        focus = m.get("focus")
        if (not isinstance(focus, list) or len(focus) != 2
                or not all(_num(v) and 0 <= v <= 1 for v in focus)):
            raise ValueError(f"moment {mid}: focus must be [x, y] between 0 and 1")
        terms = m.get("terms")
        if not isinstance(terms, list) or len(terms) > MAX_TERMS or not all(isinstance(t, str) for t in terms):
            raise ValueError(f"moment {mid}: terms must be a list of at most {MAX_TERMS} texts")
        terms = [" ".join(t.split()) for t in terms]
        if any(len(t) > MAX_TERM for t in terms):
            raise ValueError(f"moment {mid}: a search term is longer than {MAX_TERM} characters")
        note = m.get("note", "")
        if not isinstance(note, str) or len(note) > MAX_NOTE:
            raise ValueError(f"moment {mid}: note must be text of at most {MAX_NOTE} characters")
        pick = m.get("pick")
        out.append({"id": mid, "origin": m["origin"], "first": first, "last": last,
                    "layout": m["layout"], "fit": m["fit"], "pan": m["pan"],
                    "focus": [float(focus[0]), float(focus[1])], "terms": [t for t in terms if t],
                    "note": note, "pick": None if pick is None else _pick(pick)})
    return out


def target_size(layout: str) -> tuple[int, int]:
    return (1080, 1920) if layout == "full" else (1080, 960)


def fill_ok(w: int, h: int, layout: str, fit: str, min_px: int) -> bool:
    """Spec 3: the image dimension that sets the scale for its space is at least `min_px`
    ("cover": the one that limits the fill; "whole": the long side)."""
    if fit == "whole":
        return max(w, h) >= min_px
    tw, th = target_size(layout)
    return h >= min_px if th / h >= tw / w else w >= min_px


def pick_defaults(moment: dict, pick: dict, cfg: BrollConfig) -> tuple[str, str]:
    """(fit, pan) when a candidate is picked (spec 3, 5.5): a still that passes only the "whole"
    minimum comes in as "whole"; a still in "cover" pans in reading direction on the axis where it
    overflows; videos and "whole" never move."""
    fit = moment["fit"]
    if (pick["kind"] == "image" and fit == "cover"
            and not fill_ok(pick["w"], pick["h"], moment["layout"], "cover", cfg.min_fill_px)):
        fit = "whole"
    if pick["kind"] == "video" or fit == "whole":
        return fit, "still"
    tw, th = target_size(moment["layout"])
    if abs(pick["w"] / pick["h"] - tw / th) < 1e-9:
        return fit, "still"                 # same shape as the space: nothing to pan over
    return fit, ("ltr" if pick["w"] / pick["h"] > tw / th else "ttb")


def moment_span(words: list[Word], m: dict) -> Span:
    return Span(words[m["first"]].t, word_end(words, m["last"]))


def in_clip(words: list[Word], m: dict, spans: list[Span]) -> bool:
    """Both anchor words start inside the clip's segments."""
    def inside(t: float) -> bool:
        return any(s.start <= t < s.end for s in spans)
    return inside(words[m["first"]].t) and inside(words[m["last"]].t)


def clip_range(words: list[Word], m: dict, tm: TimeMap) -> tuple[float, float]:
    sp = moment_span(words, m)
    a = tm.snap_to_clip(sp.start)
    b = min(tm.snap_to_clip(sp.end), tm.duration)
    return a, max(a, b)


def _own_problems(a: float, b: float, clip_len: float, cfg: BrollConfig,
                  suggested: bool = False) -> list[str]:
    """`insert_max_s` caps what the LLM suggests; there is no minimum, and by hand no cap."""
    out = []
    if suggested and b - a > cfg.insert_max_s + EPS:
        out.append(f"longer than {cfg.insert_max_s:g} s")
    if a < cfg.head_s - EPS:
        out.append(f"starts in the first {cfg.head_s:g} s")
    if b > clip_len - cfg.tail_s + EPS:
        out.append(f"ends in the last {cfg.tail_s:g} s")
    return out


def rule_problems(ranges: dict[str, tuple[float, float]], clip_len: float,
                  cfg: BrollConfig) -> dict[str, list[str]]:
    """Every timing rule each moment breaks (spec 4), for the page's amber warnings."""
    probs = {k: _own_problems(a, b, clip_len, cfg) for k, (a, b) in ranges.items()}
    order = sorted(ranges, key=lambda k: ranges[k][0])
    for prev, cur in zip(order, order[1:]):
        if ranges[cur][0] < ranges[prev][1] - EPS:
            probs[cur].append(f"overlaps {prev}")
    for k in order[cfg.max_inserts:]:
        probs[k].append(f"more than {cfg.max_inserts} moments")
    total = sum(b - a for a, b in ranges.values())
    if clip_len > 0 and total > cfg.max_share * clip_len + EPS:
        for k in probs:
            probs[k].append(f"together over {cfg.max_share:.0%} of the clip")
    return probs


def keep_valid(ranges: dict[str, tuple[float, float]], clip_len: float,
               cfg: BrollConfig) -> tuple[list[str], dict[str, str]]:
    """The LLM's moments that pass every rule, taken greedily in start order (spec 4: hard rules)."""
    kept: list[str] = []
    dropped: dict[str, str] = {}
    total = 0.0
    for k in sorted(ranges, key=lambda k: ranges[k][0]):
        a, b = ranges[k]
        own = _own_problems(a, b, clip_len, cfg, suggested=True)
        if own:
            dropped[k] = own[0]
        elif kept and a < ranges[kept[-1]][1] - EPS:
            dropped[k] = f"overlaps {kept[-1]}"
        elif len(kept) >= cfg.max_inserts:
            dropped[k] = f"more than {cfg.max_inserts} moments"
        elif total + (b - a) > cfg.max_share * clip_len + EPS:
            dropped[k] = f"together over {cfg.max_share:.0%} of the clip"
        else:
            kept.append(k)
            total += b - a
    return kept, dropped


def next_owner_id(moments: list[dict]) -> str:
    nums = [int(m["id"][1:]) for m in moments if re.fullmatch(r"o\d+", m.get("id", ""))]
    return f"o{max(nums, default=0) + 1}"
