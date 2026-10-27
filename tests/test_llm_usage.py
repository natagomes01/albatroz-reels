"""Every usage field each backend returns (S4 spec 3, "Per-call record")."""
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from shorts.llm.anthropic_api import AnthropicApiBackend
from shorts.llm.base import LLMError
from shorts.llm.claude_cli import ClaudeCliBackend, usage_from_envelope
from shorts.llm.openai_compat import OpenAICompatBackend

FIX = Path(__file__).parent / "fixtures" / "llm"
SCHEMA = {"type": "object", "required": ["n"], "properties": {"n": {"type": "integer"}}}


def test_full_envelope_gives_every_token_field_duration_cost_and_basis():
    env = json.loads((FIX / "claude_cli_full.json").read_text(encoding="utf-8"))
    assert usage_from_envelope(env) == {
        "input_tokens": 9, "cache_creation_input_tokens": 6648,
        "cache_creation_1h_input_tokens": 6648,   # no TTL split in the envelope: 1-hour writes
        "cache_read_input_tokens": 0, "output_tokens": 41, "thinking_tokens": 34,
        "duration_ms": 4210, "duration_api_ms": 3890,
        "cost_usd": 0.01351, "cost_basis": "list"}


def test_ttl_split_in_usage_wins_over_the_one_hour_default():
    env = {"usage": {"cache_creation_input_tokens": 100,
                     "cache_creation": {"ephemeral_5m_input_tokens": 70,
                                        "ephemeral_1h_input_tokens": 30}}}
    assert usage_from_envelope(env)["cache_creation_1h_input_tokens"] == 30


def test_model_usage_fills_fields_missing_from_usage_and_sums_models():
    env = {"modelUsage": {
        "claude-opus-5-5": {"inputTokens": 5, "outputTokens": 100, "cacheReadInputTokens": 10,
                            "cacheCreationInputTokens": 200, "thinkingTokens": 60,
                            "costBasis": "list"},
        "claude-haiku-4-5": {"inputTokens": 1, "outputTokens": 2, "cacheReadInputTokens": 0,
                             "cacheCreationInputTokens": 0}}}
    u = usage_from_envelope(env)
    assert (u["input_tokens"], u["output_tokens"], u["cache_read_input_tokens"]) == (6, 102, 10)
    assert u["cache_creation_input_tokens"] == 200 and u["thinking_tokens"] == 60
    assert u["cost_basis"] == "list" and u["cost_usd"] is None


def test_an_empty_envelope_gives_none_everywhere_never_a_key_error():
    u = usage_from_envelope({})
    assert set(u.values()) == {None}
    assert "cache_read_input_tokens" in u and "duration_api_ms" in u


def test_claude_cli_call_returns_the_full_usage(monkeypatch):
    stdout = (FIX / "claude_cli_full.json").read_text(encoding="utf-8")
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(
        cmd, 0, stdout=stdout, stderr=""))
    payload, usage = ClaudeCliBackend("claude-haiku-4-5")._call("S", "U", SCHEMA)
    assert payload == {"n": 5}
    assert usage["cache_creation_input_tokens"] == 6648 and usage["cost_usd"] == 0.01351


def test_a_failed_claude_cli_call_carries_its_usage_and_cost(monkeypatch):
    env = {"type": "result", "is_error": True, "result": "API Error: 529 Overloaded",
           "total_cost_usd": 0.02, "usage": {"input_tokens": 3, "output_tokens": 0,
                                              "cache_creation_input_tokens": 5000}}
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(
        cmd, 1, stdout=json.dumps(env), stderr=""))
    with pytest.raises(LLMError) as e:
        ClaudeCliBackend("m")._call("S", "U", SCHEMA)
    assert e.value.kind == "transient"
    assert e.value.usage["cost_usd"] == 0.02 and e.value.usage["cache_creation_input_tokens"] == 5000


def test_llm_error_usage_defaults_to_an_empty_dict():
    assert LLMError("x").usage == {} and LLMError("x", "limit").kind == "limit"


def test_anthropic_api_usage_includes_cache_columns_and_ttl_split():
    usage = SimpleNamespace(input_tokens=50, output_tokens=5, cache_creation_input_tokens=400,
                            cache_read_input_tokens=1000,
                            cache_creation=SimpleNamespace(ephemeral_5m_input_tokens=400,
                                                           ephemeral_1h_input_tokens=0))
    resp = SimpleNamespace(content=[SimpleNamespace(type="tool_use", input={"n": 3})], usage=usage)
    client = SimpleNamespace(messages=SimpleNamespace(create=lambda **kw: resp))
    _, u = AnthropicApiBackend("claude-opus-5-5", client=client)._call("S", "U", SCHEMA)
    assert u == {"input_tokens": 50, "cache_creation_input_tokens": 400,
                 "cache_creation_1h_input_tokens": 0, "cache_read_input_tokens": 1000,
                 "output_tokens": 5}


def test_anthropic_api_usage_without_cache_fields_gives_none():
    resp = SimpleNamespace(content=[SimpleNamespace(type="tool_use", input={"n": 3})],
                           usage=SimpleNamespace(input_tokens=50, output_tokens=5))
    client = SimpleNamespace(messages=SimpleNamespace(create=lambda **kw: resp))
    _, u = AnthropicApiBackend("m", client=client)._call("S", "U", SCHEMA)
    assert u["input_tokens"] == 50 and u["cache_read_input_tokens"] is None
    assert u["cache_creation_1h_input_tokens"] is None


def test_openai_usage_separates_cached_prompt_tokens():
    usage = SimpleNamespace(prompt_tokens=100, completion_tokens=7,
                            prompt_tokens_details=SimpleNamespace(cached_tokens=40))
    resp = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"n": 1}'))],
                           usage=usage)
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
        create=lambda **kw: resp)))
    _, u = OpenAICompatBackend("gpt-x", base_url="http://x", client=client)._call("S", "U", SCHEMA)
    assert u == {"input_tokens": 60, "cache_read_input_tokens": 40, "output_tokens": 7}


def test_repo_pricing_table_agrees_with_a_real_envelope_no_mismatch_warning(monkeypatch):
    # Intentionally uses the REPO's pricing.toml (not a fixture table): a future price drift in
    # pricing.toml makes this fail, which is the point.
    from shorts.config import load_config
    from shorts.pricing import load_pricing
    root = Path(__file__).parent.parent
    prices = load_pricing(load_config(root / "config.toml").pricing_path)
    stdout = (FIX / "claude_cli_full.json").read_text(encoding="utf-8")
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(
        cmd, 0, stdout=stdout, stderr=""))
    warnings, logged = [], []
    b = ClaudeCliBackend("claude-haiku-4-5", prices=prices, warn=warnings.append,
                         log=logged.append)
    b.complete("S", "U", SCHEMA)
    assert warnings == []
    assert logged[0]["cost_usd"] == 0.01351
