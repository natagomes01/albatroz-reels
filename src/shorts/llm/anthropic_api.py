"""Anthropic SDK backend for unattended runs; key from the Keychain (spec 4.6)."""
from __future__ import annotations

from shorts.keychain import get_secret
from shorts.llm.base import LLMBackend, LLMError


class AnthropicApiBackend(LLMBackend):
    name = "anthropic-api"
    max_tokens = 8000

    def __init__(self, model: str, key_service: str = "anthropic-api", log=None, client=None, **kw):
        super().__init__(model, log=log, **kw)
        self.key_service = key_service
        self._client = client

    def _get_client(self):
        if self._client is None:
            import anthropic
            self._client = anthropic.Anthropic(api_key=get_secret(self.key_service))
        return self._client

    def _call(self, system, user, schema):
        try:
            import anthropic
            transient = (anthropic.RateLimitError, anthropic.APIConnectionError,
                         anthropic.InternalServerError, anthropic.APITimeoutError)
        except ImportError:  # pragma: no cover
            transient = ()
        try:
            resp = self._get_client().messages.create(
                model=self.model, max_tokens=self.max_tokens, system=system,
                messages=[{"role": "user", "content": user}],
                tools=[{"name": "emit_result", "description": "Return the result.",
                        "input_schema": schema}],
                tool_choice={"type": "tool", "name": "emit_result"})
        except transient as e:
            raise LLMError(str(e), "transient") from e
        except Exception as e:
            status = getattr(e, "status_code", None)
            raise LLMError(str(e), "transient" if status in (429, 500, 502, 503, 529) else "fatal") from e
        block = next((b for b in resp.content if getattr(b, "type", "") == "tool_use"), None)
        if block is None:
            raise LLMError("no tool_use block in the response", "schema")
        return block.input, api_usage(resp.usage)


def api_usage(u) -> dict:
    """Token counts of an Anthropic API response; fields the SDK object lacks give None."""
    split = getattr(u, "cache_creation", None)
    return {"input_tokens": getattr(u, "input_tokens", None),
            "cache_creation_input_tokens": getattr(u, "cache_creation_input_tokens", None),
            "cache_creation_1h_input_tokens": (getattr(split, "ephemeral_1h_input_tokens", None)
                                               if split is not None else None),
            "cache_read_input_tokens": getattr(u, "cache_read_input_tokens", None),
            "output_tokens": getattr(u, "output_tokens", None)}
