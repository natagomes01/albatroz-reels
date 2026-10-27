"""OpenAI-compatible backend: OpenAI, Gemini's compatible endpoint, OpenRouter, Ollama (spec 4.6)."""
from __future__ import annotations

from shorts.keychain import get_secret
from shorts.llm.base import LLMBackend, LLMError


class OpenAICompatBackend(LLMBackend):
    name = "openai-compatible"

    def __init__(self, model: str, base_url: str, key_service: str | None = None,
                 log=None, client=None, **kw):
        super().__init__(model, log=log, **kw)
        self.base_url = base_url
        self.key_service = key_service
        self._client = client

    def _get_client(self):
        if self._client is None:
            import openai
            key = get_secret(self.key_service) if self.key_service else "not-needed"
            self._client = openai.OpenAI(base_url=self.base_url, api_key=key)
        return self._client

    def _call(self, system, user, schema):
        try:
            resp = self._get_client().chat.completions.create(
                model=self.model,
                messages=[{"role": "system", "content": system},
                          {"role": "user", "content": user}],
                response_format={"type": "json_schema",
                                 "json_schema": {"name": "result", "schema": schema}})
        except Exception as e:
            status = getattr(e, "status_code", None)
            raise LLMError(str(e), "transient" if status in (429, 500, 502, 503) else "fatal") from e
        usage = getattr(resp, "usage", None)
        prompt = getattr(usage, "prompt_tokens", None)
        cached = getattr(getattr(usage, "prompt_tokens_details", None), "cached_tokens", None)
        return resp.choices[0].message.content, {
            "input_tokens": prompt - cached if prompt is not None and cached else prompt,
            "cache_read_input_tokens": cached,
            "output_tokens": getattr(usage, "completion_tokens", None)}
