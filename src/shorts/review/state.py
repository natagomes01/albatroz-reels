"""Review page state: read candidates, merge Natã's decisions into review.json (spec 7)."""
from __future__ import annotations

import copy
import math
import re
import threading
from collections import deque

from shorts import jobs
from shorts.broll.model import MAX_MOMENTS, BrollConfig, in_clip, pick_defaults, validate_moments
from shorts.analyze.boundaries import validate_spans
from shorts.analyze.textutil import estimate_cut_duration, text_of
from shorts.dereverb import DEFAULT_LEVELS, check_level
from shorts.timeline import Span
from shorts.wordfix import active_edits, anchors, read_edits
from shorts.words import load_words, sentences

STATUSES = ("approved", "rejected", "pending")
MAX_WORD = 40
MAX_TITLE = 60      # spec 6.3
_LOCK = threading.Lock()
UNDO_LIMIT = 100    # review spec 4.1
# (review.json path, clip id) -> (undo, redo) stacks of whole decision-entry snapshots. In memory
# only: closing `shorts review` clears them, review.json already holds the last state.
_HISTORY: dict[tuple[str, str], tuple[deque, deque]] = {}
# review.json path -> id of the clip changed, undone or redone last, so a reloaded page keeps its
# undo and redo keys pointed at the same clip. In memory only, like the stacks.
_LAST: dict[str, str] = {}


class NothingToUndo(ValueError):
    """Undo or redo on an empty stack; the server answers 409 and writes nothing."""


def _review(job) -> dict:
    return jobs.read_json(job.review_json, {"decisions": {}})


def _estimate(words, spans) -> float:
    return round(estimate_cut_duration(words, [Span(a, b) for a, b in spans]), 1)


def _clip_ids(job) -> set[str]:
    data = jobs.read_json(job.candidates_json, {"candidates": []})
    return {c["id"] for c in data["candidates"]}


def _duration(job, words) -> float:
    meta = jobs.read_json(job.job_json, {}) or {}
    return float(meta.get("duration") or (words[-1].t + 1.0 if words else 0.0))


def clean_word(text: str) -> str:
    """A word fix is burned into the video: no ASS override braces, no backslashes (\\N is an
    ASS line break), no newlines."""
    text = re.sub(r"[\r\n\t]", " ", str(text))
    text = re.sub(r"[{}\\]", "", text)
    return " ".join(text.split())[:MAX_WORD]


def _auto(job, words) -> tuple[list[dict], dict[str, dict]]:
    """Automatic caption fixes for the page (caption spec 7): each edit with the transcribed text
    it replaces, and per raw slot the text shown there and the edit it belongs to. Only the edits
    the render can apply (in range, no overlap: `active_edits`); owner fixes are per clip, so they
    are not filtered here."""
    edits: list[dict] = []
    slots: dict[str, dict] = {}
    for e in active_edits(len(words), read_edits(job), None):
        k = len(edits)
        edits.append({**e.to_dict(), "original": text_of(words, e.first, e.last)})
        placed = anchors(e)
        for s in range(e.first, e.last + 1):
            slots[str(s)] = {"text": " ".join(placed.get(s, [])), "edit": k}
    return edits, slots


def _stacks(job, clip_id: str) -> tuple[deque, deque]:
    key = (str(job.review_json), clip_id)
    return _HISTORY.setdefault(key, (deque(maxlen=UNDO_LIMIT), deque(maxlen=UNDO_LIMIT)))


def history_counts(job, clip_id: str) -> dict:
    undo_stack, redo_stack = _stacks(job, clip_id)
    return {"undo": len(undo_stack), "redo": len(redo_stack)}


def _record(job, clip_id: str, before: dict, entry: dict) -> None:
    """One step (review spec 3): push the entry as it was, unless nothing changed."""
    if entry != before:
        undo_stack, redo_stack = _stacks(job, clip_id)
        undo_stack.append(before)
        redo_stack.clear()
        _LAST[str(job.review_json)] = clip_id


def _snapped(job, clip_id: str) -> list:
    data = jobs.read_json(job.candidates_json, {"candidates": []})
    c = next((c for c in data["candidates"] if c.get("id") == clip_id), None)
    return [s["snapped"] for s in c.get("segments", [])] if c else []


def _reply(job, clip_id: str, entry: dict, extra: dict | None = None) -> dict:
    """What every save, undo and redo answers: the whole entry, its estimated duration and the
    clip's history counts, so the page replaces its copy instead of patching it."""
    out = copy.deepcopy(entry)
    spans = entry.get("segments") or _snapped(job, clip_id)
    if spans:
        out["estimated_duration"] = _estimate(load_words(job.words_json), spans)
    return {**out, **(extra or {}), **history_counts(job, clip_id)}


def load_state(job) -> dict:
    meta = jobs.read_json(job.job_json, {})
    data = jobs.read_json(job.candidates_json, {"candidates": [], "groups": {}})
    words = load_words(job.words_json)
    review = _review(job)
    cands = []
    for c in data["candidates"]:
        d = review["decisions"].get(c["id"], {})
        spans = d.get("segments") or [s["snapped"] for s in c["segments"]]
        clip_meta = jobs.read_json(job.clip_dir(c["id"]) / "meta.json", {})
        cands.append({**c, "estimated_duration": _estimate(words, spans),
                      "clip_warnings": clip_meta.get("warnings", []),
                      **history_counts(job, c["id"])})
    auto_edits, auto_slots = _auto(job, words)
    return {"job": job.id, "channel": meta.get("channel"), "format": meta.get("format"),
            "warnings": meta.get("warnings", []), "candidates": cands,
            "groups": data.get("groups", {}), "review": review,
            "words": [[w.t, w.w] for w in words],
            "sentences": [[s.first, s.last] for s in sentences(words)],
            "auto_edits": auto_edits, "auto_slots": auto_slots,
            "last_clip": _LAST.get(str(job.review_json))}


def apply_decision(job, clip_id: str, status: str) -> dict:
    if status not in STATUSES:
        raise ValueError(f"status must be one of {STATUSES}")
    if clip_id not in _clip_ids(job):
        raise ValueError(f"unknown clip {clip_id!r}")
    with _LOCK:
        review = _review(job)
        entry = review["decisions"].setdefault(clip_id, {})
        before = copy.deepcopy(entry)
        entry["status"] = status
        jobs.write_json_atomic(job.review_json, review)
        _record(job, clip_id, before, entry)
        return _reply(job, clip_id, entry)


def _validated(job, edit, levels=DEFAULT_LEVELS) -> dict:
    """Return a cleaned copy of `edit` or raise ValueError; nothing is written before this passes."""
    if not isinstance(edit, dict):
        raise ValueError("edit must be a JSON object")
    allowed = {"title", "hook", "segments", "word_fixes", "use_auto", "dereverb", "broll"}
    unknown = set(edit) - allowed
    if unknown:
        raise ValueError(f"unknown edit keys: {sorted(unknown)}")
    out: dict = {}
    for k in ("title", "hook"):
        if k in edit:
            if not isinstance(edit[k], str):
                raise ValueError(f"{k} must be text")
            out[k] = " ".join(edit[k].split())
            if not out[k]:
                raise ValueError(f"{k} cannot be empty")
            if k == "title" and len(out[k]) > MAX_TITLE:
                raise ValueError(f"title is longer than {MAX_TITLE} characters")
    words = None
    if "segments" in edit:
        segs = edit["segments"]
        if not isinstance(segs, list) or not all(
                isinstance(x, list) and len(x) == 2 and all(isinstance(v, (int, float)) and not isinstance(v, bool)
                        and math.isfinite(v) for v in x)
                for x in segs):
            raise ValueError("segments must be a list of [start, end] numbers")
        words = load_words(job.words_json)
        spans = [Span(float(a), float(b)) for a, b in segs]
        reason = validate_spans(spans, _duration(job, words))
        if reason:
            raise ValueError(reason)
        out["segments"] = [[s.start, s.end] for s in spans]
    if "word_fixes" in edit:
        fixes = edit["word_fixes"]
        if not isinstance(fixes, dict):
            raise ValueError("word_fixes must be an object {index: text}")
        words = words or load_words(job.words_json)
        clean = {}
        for i, text in fixes.items():
            try:
                idx = int(i)
            except (TypeError, ValueError):
                raise ValueError(f"word index {i!r} is not a number") from None
            if not 0 <= idx < len(words):
                raise ValueError(f"word index {idx} is out of range")
            if text is None:
                clean[str(idx)] = None    # erase the owner's fix of this slot (review spec 4.3)
                continue
            if not isinstance(text, str):
                raise ValueError(f"word {idx} text must be a string")
            if text == "":
                clean[str(idx)] = ""      # drop this slot: its time goes to the previous word
                continue
            fixed = clean_word(text)
            if not fixed:
                raise ValueError(f"word {idx} cannot be empty")
            clean[str(idx)] = fixed
        out["word_fixes"] = clean
    if "use_auto" in edit:
        vals = edit["use_auto"]
        if not isinstance(vals, list) or not all(
                isinstance(v, int) and not isinstance(v, bool) and v >= 0 for v in vals):
            raise ValueError("use_auto must be a list of word indices")
        out["use_auto"] = sorted(set(vals))     # review spec 4.4: the whole list, replaced
    if "dereverb" in edit:      # S8 audio spec 3: None drops the clip's override
        v = edit["dereverb"]
        out["dereverb"] = None if v is None else check_level(v, levels)
    if "broll" in edit:         # S8B spec 6: the whole moment list, replaced
        words = words or load_words(job.words_json)
        out["broll"] = validate_moments(edit["broll"], len(words))
    return out


def apply_edit(job, clip_id: str, edit, levels=DEFAULT_LEVELS) -> dict:
    if clip_id not in _clip_ids(job):
        raise ValueError(f"unknown clip {clip_id!r}")
    clean = _validated(job, edit, levels)
    with _LOCK:
        review = _review(job)
        entry = review["decisions"].setdefault(clip_id, {})
        before = copy.deepcopy(entry)
        for k, v in clean.items():
            if k == "word_fixes":
                fixes = entry.setdefault("word_fixes", {})
                for i, text in v.items():
                    if text is None:
                        fixes.pop(i, None)
                    else:
                        fixes[i] = text
                if not fixes:
                    entry.pop("word_fixes")
            elif k == "use_auto" and not v:
                entry.pop("use_auto", None)
            elif k == "dereverb" and v is None:
                entry.pop("dereverb", None)
            elif k == "broll" and not v:
                entry.pop("broll", None)
            else:
                entry[k] = v
        dropped = _drop_moments_outside(job, clip_id, entry) if "segments" in clean or "broll" in clean else []
        jobs.write_json_atomic(job.review_json, review)
        _record(job, clip_id, before, entry)
        return _reply(job, clip_id, entry, {"broll_dropped": dropped} if dropped else None)


def _drop_moments_outside(job, clip_id: str, entry: dict) -> list[str]:
    """S8B spec 4: a cut change, a merge or a direct edit drops the moments whose words are not in
    the clip, in the same step. Without an edited cut the snapped candidate segments apply."""
    moments = entry.get("broll") or []
    if not moments:
        return []
    words = load_words(job.words_json)
    spans = [Span(*s) for s in entry.get("segments") or _snapped(job, clip_id)]
    if not spans:
        return []
    keep = [m for m in moments if in_clip(words, m, spans)]
    gone = [m["id"] for m in moments if m not in keep]
    if keep:
        entry["broll"] = keep
    else:
        entry.pop("broll", None)
    return gone


def _save_moments(job, clip_id: str, change) -> dict:
    """Read, change and write one clip's moment list under the lock, as one undo step."""
    if clip_id not in _clip_ids(job):
        raise ValueError(f"unknown clip {clip_id!r}")
    n_words = len(load_words(job.words_json))
    with _LOCK:
        review = _review(job)
        entry = review["decisions"].setdefault(clip_id, {})
        before = copy.deepcopy(entry)
        moments = validate_moments(change(copy.deepcopy(entry.get("broll") or [])), n_words)
        if moments:
            entry["broll"] = moments
        else:
            entry.pop("broll", None)
        dropped = _drop_moments_outside(job, clip_id, entry)
        jobs.write_json_atomic(job.review_json, review)
        _record(job, clip_id, before, entry)
        return _reply(job, clip_id, entry, {"broll_dropped": dropped} if dropped else None)


def merge_suggestion(job, clip_id: str, moments: list[dict]) -> dict:
    """S8B spec 5.7: new LLM moments replace the clip's earlier suggested ones; the owner's stay."""
    def change(current: list[dict]) -> list[dict]:
        own = [m for m in current if m.get("origin") == "owner"]
        new = [m for m in moments if m.get("origin") == "llm"]
        return own + new[:max(MAX_MOMENTS - len(own), 0)]
    return _save_moments(job, clip_id, change)


def set_pick(job, clip_id: str, moment_id: str, pick: dict, cfg: BrollConfig = BrollConfig()) -> dict:
    """The owner picked a candidate or an own file: store it and set fit and pan (spec 3, 5.5)."""
    def change(current: list[dict]) -> list[dict]:
        m = next((m for m in current if m.get("id") == moment_id), None)
        if m is None:
            raise ValueError(f"unknown moment {moment_id!r}")
        m["pick"] = validate_moments([{**m, "pick": pick}], 10 ** 9)[0]["pick"]
        m["fit"], m["pan"] = pick_defaults(m, m["pick"], cfg)
        return current
    return _save_moments(job, clip_id, change)


def set_class_strength(job, value, levels) -> dict:
    """The class strength (S8 audio spec 3): top level of review.json, outside every clip's
    undo history; changing it marks every clip that follows the class out of date."""
    v = check_level(value, levels)
    with _LOCK:
        review = _review(job)
        review["dereverb"] = v
        jobs.write_json_atomic(job.review_json, review)
    return {"dereverb": v}


def _step(job, clip_id: str, back: bool) -> dict:
    """Undo (back) or redo one step of one clip (review spec 4.1). The file is written before the
    stacks move, so a failed write changes nothing."""
    if clip_id not in _clip_ids(job):
        raise ValueError(f"unknown clip {clip_id!r}")
    with _LOCK:
        undo_stack, redo_stack = _stacks(job, clip_id)
        src, dst = (undo_stack, redo_stack) if back else (redo_stack, undo_stack)
        if not src:
            raise NothingToUndo("nothing to undo" if back else "nothing to redo")
        review = _review(job)
        current = copy.deepcopy(review["decisions"].get(clip_id, {}))
        entry = copy.deepcopy(src[-1])
        if entry:
            review["decisions"][clip_id] = entry
        else:
            review["decisions"].pop(clip_id, None)
        jobs.write_json_atomic(job.review_json, review)
        src.pop()
        dst.append(current)
        _LAST[str(job.review_json)] = clip_id
        return _reply(job, clip_id, entry)


def undo(job, clip_id: str) -> dict:
    return _step(job, clip_id, back=True)


def redo(job, clip_id: str) -> dict:
    return _step(job, clip_id, back=False)
