"""Per-pass cache of LLM answers that remembers what each answer cost (S4 spec 3, "Cache hits").

`put` stores the answer plus `_cost_usd`, the cost of the call that produced it (read from
`backend.last_cost_usd`). `get` strips that key again, so a pass sees exactly the answer it
cached, and logs `llm_cache_hit` with `saved_usd`. Entries written before S4 have no cost key:
they still hit, with `saved_usd: null`.
"""
from __future__ import annotations

from shorts import jobs
from shorts.llm.context import current_context

COST_KEY = "_cost_usd"


def cache_fns(job: jobs.Job, cache_dir: str, backend=None):
    d = job.analyze_dir / "cache" / cache_dir

    def get(key):
        data = jobs.read_json(d / f"{key}.json")
        if data is None:
            return None
        saved = data.pop(COST_KEY, None) if isinstance(data, dict) else None
        ctx = current_context()
        jobs.log_event(job, kind="llm_cache_hit", **{**ctx, "pass": ctx["pass"] or cache_dir,
                                                     "job": ctx["job"] or job.id},
                       saved_usd=saved)
        return data

    def put(key, data):
        cost = getattr(backend, "last_cost_usd", None)
        stored = {**data, COST_KEY: cost} if cost is not None and isinstance(data, dict) else data
        jobs.write_json_atomic(d / f"{key}.json", stored)
    return get, put
