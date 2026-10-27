"""Claude Code headless mode: uses Natã's Max plan (spec 4.6).

Isolation (verified on Claude Code 2.1.284, 2026-09-29): the call runs in a fresh empty temp
directory with `--setting-sources project --strict-mcp-config --disallowedTools "mcp__*"
--tools ""`, so no MCP server, hook, user setting or global CLAUDE.md reaches it, and without
ANTHROPIC_API_KEY in the environment, so it bills the Max plan through OAuth. `--bare` is not
used because it disables OAuth.

Envelope (`--output-format json --json-schema`, verified): the validated object is in
`structured_output`; `result` carries the same object as text and is only a fallback.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile

from shorts.llm.base import LLMBackend, LLMError

_LIMIT = ("usage limit", "limit reached", "hit your limit", "reached your limit", "quota")
_TRANSIENT = ("overloaded", "529", "rate_limit", "rate limit", "timed out", "timeout",
              "econnreset", "network", "503", "502")
_STRIPPED_ENV = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL")


def classify(text: str) -> str:
    low = text.lower()
    if any(k in low for k in _LIMIT):
        return "limit"
    if any(k in low for k in _TRANSIENT):
        return "transient"
    return "fatal"


def usage_from_envelope(env: dict) -> dict:
    """Every usage field of a `claude -p --output-format json` envelope (verified 30/09/2026).

    Tokens come from `usage`; `modelUsage` (one entry per model, camelCase) fills what `usage`
    lacks and gives `costBasis` ("list": Claude Code prices the call at API list price whatever
    the plan). Missing keys give None, never an error.
    """
    u = env.get("usage") or {}
    models = [m for m in (env.get("modelUsage") or {}).values() if isinstance(m, dict)]

    def from_models(key):
        values = [m[key] for m in models if m.get(key) is not None]
        return sum(values) if values else None

    def pick(usage_key, model_key):
        value = u.get(usage_key)
        return value if value is not None else from_models(model_key)

    creation = pick("cache_creation_input_tokens", "cacheCreationInputTokens")
    split = u.get("cache_creation") or {}
    if split:
        one_hour = split.get("ephemeral_1h_input_tokens") or 0
    else:
        # Claude Code writes 1-hour cache entries: on 30/09/2026 a haiku call's total_cost_usd
        # (0.01351) matched 9 input + 6648 cache-write tokens at the 1-hour price + 41 output.
        one_hour = creation
    thinking = (u.get("output_tokens_details") or {}).get("thinking_tokens")
    if thinking is None:
        thinking = from_models("thinkingTokens")
    return {"input_tokens": pick("input_tokens", "inputTokens"),
            "cache_creation_input_tokens": creation,
            "cache_creation_1h_input_tokens": one_hour,
            "cache_read_input_tokens": pick("cache_read_input_tokens", "cacheReadInputTokens"),
            "output_tokens": pick("output_tokens", "outputTokens"),
            "thinking_tokens": thinking,
            "duration_ms": env.get("duration_ms"),
            "duration_api_ms": env.get("duration_api_ms"),
            "cost_usd": env.get("total_cost_usd"),
            "cost_basis": next((m["costBasis"] for m in models if m.get("costBasis")), None)}


class ClaudeCliBackend(LLMBackend):
    name = "claude-cli"
    timeout_s = 900

    def build_cmd(self, system: str, schema: dict) -> list[str]:
        return ["claude", "-p",
                "--model", self.model,
                "--system-prompt", system,
                "--json-schema", json.dumps(schema, ensure_ascii=False),
                "--output-format", "json",
                "--tools", "",
                "--setting-sources", "project",
                "--strict-mcp-config",
                "--disallowedTools", "mcp__*",
                "--no-session-persistence"]

    def child_env(self) -> dict[str, str]:
        return {k: v for k, v in os.environ.items() if k not in _STRIPPED_ENV}

    def _call(self, system: str, user: str, schema: dict):
        cwd = tempfile.mkdtemp(prefix="shorts-llm-")
        try:
            try:
                r = subprocess.run(self.build_cmd(system, schema), input=user,
                                   capture_output=True, text=True, encoding="utf-8", timeout=self.timeout_s,
                                   cwd=cwd, env=self.child_env())
            except FileNotFoundError as e:
                raise LLMError("the `claude` CLI is not on PATH (install Claude Code and log in)",
                               "fatal") from e
            except subprocess.TimeoutExpired as e:
                raise LLMError(f"claude -p timed out after {self.timeout_s}s", "transient") from e
        finally:
            shutil.rmtree(cwd, ignore_errors=True)
        try:
            env = json.loads(r.stdout) if r.stdout.strip() else {}
        except json.JSONDecodeError:
            env = {}
        if r.returncode != 0 or env.get("is_error"):
            text = f"{env.get('result', '')} {r.stderr}".strip() or f"exit {r.returncode}"
            raise LLMError(f"claude -p failed: {text[:500]}", classify(text),
                           usage=usage_from_envelope(env))
        payload = env.get("structured_output")
        if payload is None:
            payload = env.get("result", "")
        return payload, usage_from_envelope(env)
