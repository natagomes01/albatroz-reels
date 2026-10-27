"""Pass 1: score every window 0-100 (spec 6.2)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from shorts import jobs
from shorts.analyze import schemas
from shorts.analyze.prompts import load_prompt
from shorts.llm.base import LLMError


@dataclass(frozen=True)
class ScanResult:
    id: str
    score: int
    reason: str


def batch_key(batch, profile_digest: str, prompt_hash: str, model: str) -> str:
    return jobs.stage_key(jobs.LLM_CACHE_VERSION, stage="scan",
                          windows=[(w.id, w.start, w.end, w.text) for w in batch],
                          profile=profile_digest, prompt=prompt_hash, model=model)


def _user(batch, profile) -> str:
    parts = [profile.as_prompt_block(), "\n# Windows\n"]
    for w in batch:
        parts.append(f"{w.label()}\n{w.text}\n")
    return "\n".join(parts)


def run_scan(windows, profile, backend, batch_size: int = 10,
             cache: Callable[[str], dict | None] | None = None,
             store: Callable[[str, dict], None] | None = None, log=None) -> list[ScanResult]:
    system, prompt_hash = load_prompt("scan")
    out: list[ScanResult] = []
    for i in range(0, len(windows), batch_size):
        batch = windows[i:i + batch_size]
        key = batch_key(batch, profile.digest(), prompt_hash, backend.model)
        ids = [w.id for w in batch]
        data = cache(key) if cache else None
        missed = data is None
        if missed:
            data = backend.complete(system, _user(batch, profile),
                                    schemas.for_batch(schemas.SCAN, "windows", ids))
        got = {r["id"]: r for r in data["windows"]}
        missing = [i for i in ids if i not in got]
        if missing:
            # The per-batch schema already made the backend retry twice; getting here means the
            # reply is still incomplete. Stop the stage: a silent 0 would hide good windows.
            if log:
                log({"kind": "scan_missing_windows", "windows": missing})
            raise LLMError(f"scan reply is missing windows {missing}", "schema")
        if len(data["windows"]) != len(ids):
            # for_batch does not enforce uniqueness, so [w1, w1] passes it; the dict above
            # would silently keep one score per id. Stop before caching a bad reply.
            if log:
                log({"kind": "scan_duplicate_windows"})
            raise LLMError("scan reply repeats a window id", "schema")
        if store and missed:      # a hit must not rewrite the entry: it would lose its cost
            store(key, data)
        for w in batch:
            r = got[w.id]
            out.append(ScanResult(w.id, int(r["score"]), r["reason"]))
    return out


def select(results: list[ScanResult], threshold: int = 60,
           ceiling: int | None = 40) -> list[ScanResult]:
    """Windows scoring at least `threshold`, best first, at most `ceiling` of them (None: all)."""
    kept = [r for r in results if r.score >= threshold]
    kept.sort(key=lambda r: r.score, reverse=True)
    return kept if ceiling is None else kept[:ceiling]
