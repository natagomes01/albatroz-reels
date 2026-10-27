"""Pass 3: blind self-containment and faithful-with-context reviews (spec 6.5)."""
from __future__ import annotations

from shorts import jobs
from shorts.analyze import schemas
from shorts.analyze.prompts import load_prompt
from shorts.analyze.textutil import text_of, words_in
from shorts.llm.base import LLMError
from shorts.llm.context import llm_context
from shorts.timeline import Span

AROUND = 90.0  # 3 minutes around each segment


def clip_text(c, words) -> str:
    parts = []
    for sp in c.spans():
        rng = words_in(words, sp)
        parts.append(text_of(words, *rng) if rng else "")
    return " [...] ".join(parts)


def _blind_user(batch, words) -> str:
    return "\n".join(f"[#{c.id}]\n{clip_text(c, words)}\n" for c in batch)


def _faithful_user(batch, words) -> str:
    out = []
    for c in batch:
        out.append(f"[#{c.id}]\nClip:\n{clip_text(c, words)}")
        for n, sp in enumerate(c.spans(), 1):
            rng = words_in(words, Span(max(sp.start - AROUND, 0.0), sp.end + AROUND))
            out.append(f"Context around segment {n}:\n{text_of(words, *rng) if rng else ''}")
        out.append("")
    return "\n".join(out)


def verdict(c) -> tuple[str, list[str]]:
    warns = []
    missing = c.blind is None or c.faithful is None
    if missing:
        warns.append("review_missing")
    if c.blind is not None and not c.blind.get("stands_alone"):
        warns.append("blind_failed")
    faithful_failed = c.faithful is not None and not c.faithful.get("faithful")
    if faithful_failed:
        warns.append("faithful_failed")
    if c.controversy == 2:
        warns.append("controversy_2")
    if c.out_of_order:
        warns.append("out_of_order")
    if c.too_long:
        warns.append("too_long")
    if getattr(c, "too_short", False):
        warns.append("too_short")
    if faithful_failed:
        return "drop", warns            # only an explicit faithful: false drops a clip
    if warns:
        return "review", warns
    return "publish", warns


def _pass(name, schema, user_fn, cands, words, backend, batch, cache, store, log):
    # Both reviews share one backend, so the pass name is set here, not by the caller (S4).
    with llm_context(pass_name=name):
        return _run_pass(name, schema, user_fn, cands, words, backend, batch, cache, store, log)


def _run_pass(name, schema, user_fn, cands, words, backend, batch, cache, store, log):
    system, prompt_hash = load_prompt(name)
    results: dict[str, dict] = {}
    for i in range(0, len(cands), batch):
        chunk = cands[i:i + batch]
        if not chunk:
            continue
        ids = [c.id for c in chunk]
        user = user_fn(chunk, words)
        key = jobs.stage_key(jobs.LLM_CACHE_VERSION, stage=name, user=user, prompt=prompt_hash,
                             model=backend.model)
        data = cache(key) if cache else None
        if data is None:
            try:
                data = backend.complete(system, user, schemas.for_batch(schema, "results", ids))
            except LLMError as e:
                if e.kind != "schema":
                    raise                   # usage limit / fatal: stop, the rerun resumes from cache
                if log:
                    log({"kind": "review_missing", "pass": name, "ids": ids, "reason": str(e)[:300]})
                continue                    # nothing cached: the rerun tries this batch again
            got = {r["id"] for r in data["results"]}
            if set(ids) <= got and store:
                store(key, data)            # only complete batches are cached
        for r in data["results"]:
            if r["id"] in ids:
                results[r["id"]] = r
        missing = [i for i in ids if i not in results]
        if missing and log:
            log({"kind": "review_missing", "pass": name, "ids": missing})
    return results


def run_reviews(cands, words, backend, batch: int = 5, cache=None, store=None, log=None) -> None:
    blind = _pass("review_blind", schemas.REVIEW_BLIND, _blind_user, cands, words, backend,
                  batch, cache, store, log)
    faithful = _pass("review_faithful", schemas.REVIEW_FAITHFUL, _faithful_user, cands, words,
                     backend, batch, cache, store, log)
    for c in cands:
        c.blind = blind.get(c.id)
        c.faithful = faithful.get(c.id)
        c.verdict, c.warnings = verdict(c)
