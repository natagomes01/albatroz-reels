"""One interface for every LLM pass (spec 4.6, 6.7); per-call cost record (S4 spec 3)."""
from __future__ import annotations

import json
import re
import sys
import time
from abc import ABC, abstractmethod
from typing import Callable

import jsonschema

from shorts.llm.context import current_context
from shorts.pricing import PriceTable, cost_from_usage, load_pricing

# Token and time fields every `llm` event carries (None when the backend did not report one).
USAGE_FIELDS = ("input_tokens", "cache_creation_input_tokens", "cache_creation_1h_input_tokens",
                "cache_read_input_tokens", "output_tokens", "thinking_tokens",
                "duration_ms", "duration_api_ms")
MISMATCH_SHARE = 0.10   # reported vs pricing.toml cost further apart than this prints a warning


class LLMError(Exception):
    def __init__(self, message: str, kind: str = "fatal", usage: dict | None = None):
        super().__init__(message)
        self.kind = kind  # transient | limit | schema | fatal
        self.usage = dict(usage or {})  # what the failed call reported (tokens, cost), if anything


_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.S)


def parse_json_payload(payload) -> object:
    if isinstance(payload, (dict, list)):
        return payload
    if not isinstance(payload, str):
        raise ValueError(f"unexpected payload type {type(payload).__name__}")
    return json.loads(_FENCE.sub("", payload.strip()))


def _stderr_warn(msg: str) -> None:
    print(f"warning: {msg}", file=sys.stderr)


class LLMBackend(ABC):
    name = "base"

    def __init__(self, model: str, *, log: Callable[[dict], None] | None = None,
                 sleep: Callable[[float], None] = time.sleep,
                 schema_retries: int = 2, transient_retries: int = 3,
                 prices: PriceTable | None = None,
                 warn: Callable[[str], None] | None = None):
        self.model = model
        self.log = log or (lambda event: None)
        self.sleep = sleep
        self.schema_retries = schema_retries
        self.transient_retries = transient_retries
        self.prices = prices
        self.warn = warn or _stderr_warn
        self.last_cost_usd: float | None = None   # every attempt of the last complete() call
        self._mismatch_warned = False

    @abstractmethod
    def _call(self, system: str, user: str, schema: dict) -> tuple[object, dict]:
        """Return (payload, usage). Raise LLMError(kind=..., usage=...) on failure."""

    def _cost(self, usage: dict) -> tuple[float | None, float | None, str | None]:
        """(cost_usd, cost_table_usd, cost_basis). A reported cost wins; the table is the
        cross-check, or the cost itself when nothing was reported (the API backends)."""
        price = self.prices.for_model(self.model) if self.prices else None
        has_tokens = any(usage.get(k) is not None for k in (
            "input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens",
            "output_tokens"))
        table = round(cost_from_usage(usage, price), 6) if price and has_tokens else None
        reported = usage.get("cost_usd")
        if reported is not None:
            if (table is not None and not self._mismatch_warned
                    and abs(table - reported) > MISMATCH_SHARE * reported):
                self._mismatch_warned = True
                self.warn(f"{self.model}: reported cost ${reported:.4f} and pricing.toml cost "
                          f"${table:.4f} differ by more than 10%; check pricing.toml "
                          f"(verified_on {self.prices.verified_on}) or the reported cost")
            return reported, table, usage.get("cost_basis") or "reported"
        if table is not None:
            return table, table, "table"
        return None, None, None

    def _record(self, usage: dict, attempt: int, started: float, error: LLMError | None = None):
        cost, table, basis = self._cost(usage)
        if cost is not None:
            self.last_cost_usd = round((self.last_cost_usd or 0.0) + cost, 6)
        event = {"kind": "llm", **current_context(), "backend": self.name, "model": self.model,
                 "attempt": attempt, "ok": error is None}
        event.update({k: usage.get(k) for k in USAGE_FIELDS})
        event.update(wall_ms=int((time.monotonic() - started) * 1000), cost_usd=cost,
                     cost_table_usd=table, cost_basis=basis)
        if error is not None:
            event.update(error=str(error), error_kind=error.kind)
        self.log(event)

    def complete(self, system: str, user: str, schema: dict) -> dict:
        prompt = user
        schema_failures = 0
        transient_failures = 0
        attempt = 0
        self.last_cost_usd = None
        while True:
            attempt += 1
            started = time.monotonic()
            try:
                payload, usage = self._call(system, prompt, schema)
            except LLMError as e:
                self._record(e.usage, attempt, started, error=e)
                if e.kind == "schema" and schema_failures < self.schema_retries:
                    schema_failures += 1
                    continue
                if e.kind == "transient" and transient_failures < self.transient_retries:
                    self.sleep(2 * 4 ** transient_failures)  # 2, 8, 32 s
                    transient_failures += 1
                    continue
                raise
            self._record(usage, attempt, started)
            try:
                data = parse_json_payload(payload)
                jsonschema.validate(data, schema)
                return data
            except (ValueError, jsonschema.ValidationError) as err:
                if schema_failures >= self.schema_retries:
                    raise LLMError(f"response did not match the schema after "
                                   f"{schema_failures + 1} attempts: {err}", "schema") from err
                schema_failures += 1
                msg = err.message if isinstance(err, jsonschema.ValidationError) else str(err)
                prompt = (f"{user}\n\nYour previous answer did not match the schema: {msg}\n"
                          f"Answer again with JSON only, matching the schema exactly.")


def get_backend(pass_name: str, app, log=None) -> LLMBackend:
    cfg = dict(app.backends.get(pass_name) or {})
    if not cfg:
        raise LLMError(f"no [backends.{pass_name}] in config.toml", "fatal")
    kind = cfg.get("backend", "claude-cli")
    model = cfg["model"]
    pricing_path = getattr(app, "pricing_path", None)
    prices = load_pricing(pricing_path) if pricing_path else None
    if kind == "claude-cli":
        from shorts.llm.claude_cli import ClaudeCliBackend
        return ClaudeCliBackend(model, log=log, prices=prices)
    if kind == "anthropic-api":
        from shorts.llm.anthropic_api import AnthropicApiBackend
        return AnthropicApiBackend(model, key_service=cfg.get("key_service", "anthropic-api"),
                                   log=log, prices=prices)
    if kind == "openai-compatible":
        from shorts.llm.openai_compat import OpenAICompatBackend
        return OpenAICompatBackend(model, base_url=cfg["base_url"],
                                   key_service=cfg.get("key_service"), log=log, prices=prices)
    raise LLMError(f"unknown backend '{kind}' for pass '{pass_name}'", "fatal")
