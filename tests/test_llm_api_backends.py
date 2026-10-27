from types import SimpleNamespace

import pytest

from shorts.config import AppConfig
from shorts.llm.anthropic_api import AnthropicApiBackend
from shorts.llm.base import get_backend
from shorts.llm.claude_cli import ClaudeCliBackend
from shorts.llm.openai_compat import OpenAICompatBackend

SCHEMA = {"type": "object", "required": ["n"], "properties": {"n": {"type": "integer"}}}


class FakeAnthropic:
    def __init__(self):
        self.kwargs = None
        self.messages = self

    def create(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text="x"),
                     SimpleNamespace(type="tool_use", name="emit_result", input={"n": 3})],
            usage=SimpleNamespace(input_tokens=50, output_tokens=5))


class FakeOpenAI:
    def __init__(self):
        self.kwargs = None
        self.chat = SimpleNamespace(completions=self)

    def create(self, **kwargs):
        self.kwargs = kwargs
        msg = SimpleNamespace(content='{"n": 4}')
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)],
                               usage=SimpleNamespace(prompt_tokens=60, completion_tokens=6))


def test_anthropic_forces_tool_with_schema():
    fake = FakeAnthropic()
    out = AnthropicApiBackend("claude-opus-5-5", client=fake).complete("S", "U", SCHEMA)
    assert out == {"n": 3}
    assert fake.kwargs["tool_choice"] == {"type": "tool", "name": "emit_result"}
    assert fake.kwargs["tools"][0]["input_schema"] == SCHEMA
    assert fake.kwargs["system"] == "S"


def test_openai_uses_json_schema_response_format():
    fake = FakeOpenAI()
    out = OpenAICompatBackend("gpt-x", base_url="http://x", client=fake).complete("S", "U", SCHEMA)
    assert out == {"n": 4}
    assert fake.kwargs["response_format"]["type"] == "json_schema"
    assert fake.kwargs["messages"][0] == {"role": "system", "content": "S"}


def _app(backends):
    return AppConfig(media_root=__import__("pathlib").Path("/tmp/m"),
                     jobs_dir=__import__("pathlib").Path("/tmp/j"), backends=backends)


def test_get_backend_default_is_claude_cli():
    b = get_backend("scan", _app({"scan": {"model": "claude-haiku-4-5"}}))
    assert isinstance(b, ClaudeCliBackend) and b.model == "claude-haiku-4-5"


def test_get_backend_unknown_pass():
    from shorts.llm.base import LLMError
    with pytest.raises(LLMError, match="no \\[backends.detail\\]"):
        get_backend("detail", _app({}))


@pytest.mark.live
def test_live_anthropic_api_smoke():
    out = AnthropicApiBackend("claude-haiku-4-5").complete("Return the tool call.", "n = 5", SCHEMA)
    assert out == {"n": 5}
