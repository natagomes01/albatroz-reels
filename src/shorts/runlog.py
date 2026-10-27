"""Run boundaries in log.jsonl and the per-run cost line (S4 spec 3, "Runs").

A run is one command invocation on one job. `command_run` writes `run_start` and `run_end`
around it and puts the job and run id into the LLM context, so every `llm` and `llm_cache_hit`
event of the run carries the same `run`. The cost of a run is the sum of its `llm` events.
"""
from __future__ import annotations

import json
import secrets
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from shorts import jobs
from shorts.llm.context import current_context, llm_context


@dataclass
class Run:
    id: str
    command: str
    exit_code: int | None = None
    nested: bool = False      # True inside another command's run (`run` calling `analyze`)


def new_run_id(now: datetime | None = None) -> str:
    return f"{(now or datetime.now()).strftime('%y%m%d-%H%M%S')}-{secrets.token_hex(2)}"


@contextmanager
def command_run(job, command: str, args: dict | None = None):
    """Set `run.exit_code` before leaving; an exception records 1 (130 for Ctrl-C)."""
    active = current_context()["run"]
    if active:
        yield Run(active, command, nested=True)
        return
    run = Run(new_run_id(), command)
    jobs.log_event(job, kind="run_start", run=run.id, job=job.id, command=command,
                   args=args or {})
    started = time.monotonic()
    try:
        with llm_context(job=job.id, run=run.id):
            yield run
    except KeyboardInterrupt:
        run.exit_code = 130
        raise
    except BaseException:
        if run.exit_code is None:
            run.exit_code = 1
        raise
    finally:
        jobs.log_event(job, kind="run_end", run=run.id, job=job.id, command=command,
                       exit_code=run.exit_code, wall_s=round(time.monotonic() - started, 3))


def read_log(path: Path) -> tuple[list[dict], int]:
    """(events, number of unreadable lines). A missing log is ([], 0); a broken line (a crash
    mid-write, a merge marker) is skipped and counted, never an error."""
    path = Path(path)
    if not path.exists():
        return [], 0
    events, bad = [], 0
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            bad += 1
            continue
        if isinstance(event, dict):
            events.append(event)
        else:
            bad += 1
    return events, bad


def run_totals(events: list[dict], run_id: str) -> dict:
    calls = [e for e in events if e.get("kind") == "llm" and e.get("run") == run_id]
    hits = [e for e in events if e.get("kind") == "llm_cache_hit" and e.get("run") == run_id]
    return {"calls": len(calls),
            "cost_usd": sum(e.get("cost_usd") or 0.0 for e in calls),
            "cache_hits": len(hits),
            "saved_usd": sum(e.get("saved_usd") or 0.0 for e in hits)}


def run_line(totals: dict) -> str:
    return (f"LLM cost this run: ${totals['cost_usd']:.2f} API-equivalent "
            f"({totals['calls']} calls, cache saved ${totals['saved_usd']:.2f})")
