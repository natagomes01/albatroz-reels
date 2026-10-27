"""The B-roll suggestion pass (S8B spec 5): Haiku proposes moments and English search terms from
the clip's words; the code enforces the timing rules and searches the sources. The model never
sees an image, so it never picks one."""
from __future__ import annotations

import json
from pathlib import Path

from shorts import jobs
from shorts.analyze import schemas
from shorts.analyze.llmcache import cache_fns
from shorts.analyze.prompts import load_prompt
from shorts.broll import paths, timing
from shorts.broll.model import BrollConfig, clip_range, keep_valid
from shorts.broll.search import search_moment
from shorts.broll.sources import http_fetch
from shorts.llm.base import LLMError
from shorts.llm.context import llm_context
from shorts.timeline import Span, TimeMap
from shorts.words import Word, load_words

PASS = "broll"
RESULT_VERSION = 1
SHAPE_ERROR = "the model's reply had the wrong shape; Try again"


def read_result(job, clip_id: str) -> dict | None:
    try:
        data = jobs.read_json(paths.result_path(job, clip_id))
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def write_result(job, clip_id: str, data: dict) -> None:
    jobs.write_json_atomic(paths.result_path(job, clip_id), data)


def clip_lines(raw: list[Word], fixes: dict, spans: list[Span], tm: TimeMap) -> list[tuple[int, float, str]]:
    """(raw index, clip seconds, text) of every word inside the clip, with the owner's fixes;
    a word the owner removed is left out."""
    out = []
    for i, w in enumerate(raw):
        if not any(s.start <= w.t < s.end for s in spans):
            continue
        text = fixes.get(str(i), w.w)
        if text == "":
            continue
        out.append((i, round(tm.snap_to_clip(w.t), 1), text))
    return out


def build_request(lines, topic: str, channel, cfg: BrollConfig, clip_len: float) -> str:
    rules = (f"- each moment lasts as long as its pacing needs, at most {cfg.insert_max_s:g} s: a calm passage can hold an image 5 to 10 s, and when the delivery is quick or two or three images follow one another, make each one short (there is no minimum);\n"
             f"- at most {cfg.max_inserts} moments, together at most {cfg.max_share:.0%} of the clip "
             f"({clip_len:.1f} s long);\n"
             f"- no moment starts before {cfg.head_s:g} s or ends after {clip_len - cfg.tail_s:.1f} s;\n"
             f"- moments do not overlap.")
    words = "\n".join(f"{i}|{t:.1f}|{text}" for i, t, text in lines)
    return (f"Channel: {channel.id} (content language: {channel.language})\n"
            f"Class topic: {topic or '(not given)'}\n\n"
            f"Timing rules:\n{rules}\n\n"
            f"Clip words, one per line as index|seconds|word:\n{words}\n")


def _topic(job) -> str:
    try:
        sheet = jobs.read_json(job.class_sheet_json) or {}
    except ValueError:
        sheet = {}
    topic = str((sheet.get("sheet") or {}).get("topic") or "").strip()
    return " ".join((topic or str((jobs.read_json(job.job_json, {}) or {}).get("topic", ""))).split())


def _moments_from(data: dict, lines, raw: list[Word], tm: TimeMap, cfg: BrollConfig):
    """The model's proposals (p1, p2, ...) checked against the clip and the rules; the kept ones
    renumbered s1, s2, ... in start order. Returns (moments, kinds, dropped reasons by p-id)."""
    inside = {i for i, _, _ in lines}
    props: dict[str, dict] = {}
    kinds: dict[str, str] = {}
    dropped: dict[str, str] = {}
    for n, m in enumerate(data.get("moments") or [], start=1):
        pid = f"p{n}"
        if m["first"] not in inside or m["last"] not in inside or m["first"] > m["last"]:
            dropped[pid] = "word index outside the clip"
            continue
        own = m["kind"] == "own"
        props[pid] = {"id": pid, "origin": "llm", "first": m["first"], "last": m["last"],
                      "layout": m["layout"], "fit": "whole" if own else "cover", "pan": "still",
                      "focus": [0.5, 0.5],
                      "terms": [] if own else [" ".join(t.split())[:80] for t in m["terms"] if t.strip()][:3],
                      "note": " ".join(m["note"].split())[:200], "pick": None}
        kinds[pid] = m["kind"]
    ranges = {pid: clip_range(raw, p, tm) for pid, p in props.items()}
    kept, rule_dropped = keep_valid(ranges, tm.duration, cfg)
    dropped.update(rule_dropped)
    moments, out_kinds = [], {}
    for k, pid in enumerate(kept, start=1):
        moments.append({**props[pid], "id": f"s{k}"})
        out_kinds[f"s{k}"] = kinds[pid]
    return moments, out_kinds, dropped


def search_for(job, app, moment: dict, kind: str, duration: float, keys: dict, fetch=http_fetch,
               now: float | None = None) -> tuple[list[dict], list[str]]:
    """Candidates (as dicts) and source errors for one moment; also used by the page's own search."""
    cands, errors = search_moment(moment["terms"], kind, moment["layout"], duration, app.broll, keys,
                                  fetch, paths.search_dir(app, job), paths.thumbs_dir(app, job), now)
    return [c.to_dict() for c in cands], errors


def suggest_clip(job, app, channel, plan, backend, keys: dict, fetch=http_fetch, force: bool = False,
                 clip_map_fn=None, now: float | None = None) -> dict:
    from shorts.stages import effective_clip_words      # stages imports clip; keep it lazy
    cfg = app.broll
    raw = load_words(job.words_json)
    master = Path(jobs.read_json(job.job_json)["master"])
    tm = (clip_map_fn or timing.clip_map)(job, plan.id, channel, plan.spans,
                                          effective_clip_words(job, plan), master)
    lines = clip_lines(raw, plan.decision.get("word_fixes") or {}, plan.spans, tm)
    if not lines:
        raise ValueError(f"{plan.id}: no words inside the clip")
    system, prompt_hash = load_prompt("broll")
    user = build_request(lines, _topic(job), channel, cfg, tm.duration)
    key = jobs.stage_key(jobs.LLM_CACHE_VERSION, stage=PASS, prompt=prompt_hash, model=backend.model, user=user)
    get, put = cache_fns(job, PASS, backend)
    errors: list[str] = []
    with llm_context(pass_name=PASS):
        data = None if force else get(key)
        fresh = data is None
        if fresh:
            try:
                data = backend.complete(system, user, schemas.BROLL)
            except LLMError as e:
                if e.kind != "schema":
                    raise                 # usage limit or fatal: stop, nothing written
                errors.append(SHAPE_ERROR)
                data, fresh = {"moments": []}, False
    moments, kinds, dropped = _moments_from(data, lines, raw, tm, cfg)
    for pid, reason in dropped.items():
        jobs.log_event(job, kind="broll_dropped", clip=plan.id, moment=pid, reason=reason)
    if fresh:
        put(key, data)
    candidates: dict[str, list[dict]] = {}
    for m in moments:
        if kinds[m["id"]] == "own":
            continue
        a, b = clip_range(raw, m, tm)
        found, errs = search_for(job, app, m, kinds[m["id"]], b - a, keys, fetch, now)
        candidates[m["id"]] = found
        errors += [f"{m['id']}: {e}" for e in errs]
    result = {"version": RESULT_VERSION, "model": backend.model, "prompt_hash": prompt_hash,
              "moments": moments, "kinds": kinds, "candidates": candidates, "errors": errors}
    write_result(job, plan.id, result)
    return json.loads(json.dumps(result))   # the same shape read_result gives back
