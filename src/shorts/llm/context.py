"""Who is calling the LLM: pass, job and run (S4 spec 3, "Per-call record").

Callers set these with `llm_context(...)`; `LLMBackend.complete` and the analyze cache read them
with `current_context()`. A context variable instead of new parameters: every pass keeps its
signature, and a nested block (a pass inside a run) adds its field and restores on exit.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar

FIELDS = ("pass", "job", "run")
_CTX: ContextVar[dict] = ContextVar("shorts_llm_context", default={})


@contextmanager
def llm_context(*, pass_name: str | None = None, job: str | None = None, run: str | None = None):
    given = {"pass": pass_name, "job": job, "run": run}
    token = _CTX.set({**_CTX.get(), **{k: v for k, v in given.items() if v is not None}})
    try:
        yield
    finally:
        _CTX.reset(token)


def current_context() -> dict:
    """Always the three keys, None where unset."""
    ctx = _CTX.get()
    return {k: ctx.get(k) for k in FIELDS}
