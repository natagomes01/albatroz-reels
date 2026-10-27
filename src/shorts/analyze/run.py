"""`shorts analyze`: scan -> detail -> reviews -> dedupe -> candidates.json (spec 6)."""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from shorts import jobs
from shorts.analyze.candidates import Candidate, assign_ids, dedupe, group_by_hook
from shorts.analyze.detail import run_detail
from shorts.analyze.llmcache import cache_fns
from shorts.analyze.profile import load_profile
from shorts.analyze.prompts import load_prompt
from shorts.analyze.reviews import run_reviews
from shorts.analyze.scan import run_scan, select
from shorts.analyze.windows import build_windows
from shorts.llm.base import get_backend
from shorts.llm.context import llm_context
from shorts.words import load_words, sentences

PROMPT_NAMES = ("scan", "detail", "review_blind", "review_faithful")


class ReviewInProgress(Exception):
    pass


def _has_decisions(job: jobs.Job) -> bool:
    state = jobs.read_json(job.review_json, {}) or {}
    return any(v for v in (state.get("decisions") or {}).values())


def _guard_review(job: jobs.Job, force: bool) -> None:
    if not _has_decisions(job):
        return
    if not force:
        raise ReviewInProgress(
            f"{job.review_json} already holds review decisions; rerunning analyze could change "
            f"the candidate list under them. Use `shorts analyze {job.id} --force` to archive the "
            f"review and start over.")
    stamp = datetime.now().strftime("%y%m%d-%H%M%S")
    os.replace(job.review_json, job.root / f"review.{stamp}.json")


def run_analyze(job, app, channel, repo_root: Path, backends: dict | None = None,
                force: bool = False, over_ceiling=None) -> dict:
    """`over_ceiling(qualified, ceiling) -> bool` is asked when more windows than `scan_ceiling`
    score at least `scan_threshold`: True sends all of them to detail, False (or no callback)
    keeps the best `scan_ceiling`."""
    _guard_review(job, force)
    log = lambda event: jobs.log_event(job, **event)
    backends = backends or {p: get_backend(p, app, log=log) for p in ("scan", "detail", "review")}
    words = load_words(job.words_json)
    sents = sentences(words)
    meta = jobs.read_json(job.job_json, {}) or {}
    duration = float(meta.get("duration") or (words[-1].t + 1.0 if words else 0.0))
    profile = load_profile(channel, repo_root)
    windows = build_windows(words, sents)

    get, put = cache_fns(job, "scan", backends["scan"])
    with llm_context(pass_name="scan"):
        scan = run_scan(windows, profile, backends["scan"], cache=get, store=put, log=log)
    jobs.write_json_atomic(job.scan_json, {"windows": [
        {"id": w.id, "start": w.start, "end": w.end, "score": r.score, "reason": r.reason}
        for w, r in zip(windows, scan)]})
    chosen = select(scan, app.scan_threshold, app.scan_ceiling)
    qualified = len(select(scan, app.scan_threshold, None))
    if qualified > app.scan_ceiling:
        accepted = bool(over_ceiling and over_ceiling(qualified, app.scan_ceiling))
        if accepted:
            chosen = select(scan, app.scan_threshold, None)
        log({"kind": "scan_ceiling", "qualified": qualified, "ceiling": app.scan_ceiling,
             "asked": over_ceiling is not None, "sent_to_detail": len(chosen)})

    cands: list[Candidate] = []
    if chosen:
        get, put = cache_fns(job, "detail", backends["detail"])
        with llm_context(pass_name="detail"):
            cands = run_detail(chosen, windows, words, sents, profile, backends["detail"],
                               channel.weights, duration, cache=get, store=put, log=log)
        assign_ids(cands)                                   # stable ids before the reviews
        get, put = cache_fns(job, "review", backends["review"])   # reviews name their own passes
        run_reviews(cands, words, backends["review"], cache=get, store=put, log=log)
        cands = dedupe(cands)                               # after reviews: prefer survivors
    groups = group_by_hook(cands)
    cands.sort(key=lambda c: c.total, reverse=True)
    provenance = {
        "prompts": {n: load_prompt(n)[1] for n in PROMPT_NAMES},
        "llm": {p: {"backend": getattr(b, "name", type(b).__name__), "model": b.model}
                for p, b in backends.items()},
    }
    jobs.write_json_atomic(job.candidates_json, {
        "candidates": [c.to_dict() for c in cands], "groups": groups,
        "weights": channel.weights, "profile_digest": profile.digest(), **provenance})
    fix = _caption_pass(job, app, channel, repo_root, backends, log)
    return {"candidates": len(cands), "windows": len(windows), "selected": len(chosen),
            "fixes": fix.get("edits", 0), "fix_dropped": fix.get("dropped", 0),
            "fix_error": fix.get("error"), "fix_error_kind": fix.get("error_kind")}


def _caption_pass(job, app, channel, repo_root: Path, backends: dict, log) -> dict:
    """The caption context pass runs last and never blocks the analysis (caption spec 4.1, 9):
    on failure candidates.json is already written and the review page shows raw words."""
    from shorts.analyze.fixwords import run_fixwords
    try:
        return run_fixwords(job, app, channel, repo_root, backends=backends)
    except Exception as e:  # noqa: BLE001 (a usage limit, a missing backend, a bad reply)
        kind = getattr(e, "kind", None)
        log({"kind": "error", "stage": "fixwords", "error": str(e)[:500], "error_kind": kind})
        return {"edits": 0, "dropped": 0, "error": f"{type(e).__name__}: {e}"[:300],
                "error_kind": kind}
