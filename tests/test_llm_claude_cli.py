import json
import os
import subprocess
from pathlib import Path

import pytest

from shorts.llm.base import LLMError
from shorts.llm.claude_cli import ClaudeCliBackend, classify

FIX = Path(__file__).parent / "fixtures" / "llm"
SCHEMA = {"type": "object", "required": ["n"], "properties": {"n": {"type": "integer"}}}
REPO = Path(__file__).resolve().parents[1]


def fake_run(stdout, returncode=0, stderr=""):
    calls = []

    def run(cmd, **kw):
        calls.append((cmd, kw))
        return subprocess.CompletedProcess(cmd, returncode, stdout=stdout, stderr=stderr)
    return run, calls


def test_build_cmd_has_every_required_and_isolation_flag():
    cmd = ClaudeCliBackend("claude-haiku-4-5").build_cmd("SYS", SCHEMA)
    assert cmd[:2] == ["claude", "-p"]
    for flag in ["--model", "--system-prompt", "--json-schema", "--output-format",
                 "--tools", "--no-session-persistence", "--setting-sources",
                 "--strict-mcp-config", "--disallowedTools"]:
        assert flag in cmd
    assert "--bare" not in cmd                       # would disable OAuth (Max plan)
    assert "--mcp-config" not in cmd
    assert cmd[cmd.index("--model") + 1] == "claude-haiku-4-5"
    assert cmd[cmd.index("--output-format") + 1] == "json"
    assert cmd[cmd.index("--tools") + 1] == ""
    assert cmd[cmd.index("--setting-sources") + 1] == "project"
    assert cmd[cmd.index("--disallowedTools") + 1] == "mcp__*"
    assert json.loads(cmd[cmd.index("--json-schema") + 1]) == SCHEMA


def test_child_env_drops_api_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-should-not-leak")
    monkeypatch.setenv("PATH", "/usr/bin")
    env = ClaudeCliBackend("m").child_env()
    assert "ANTHROPIC_API_KEY" not in env
    assert env["PATH"] == "/usr/bin"


def test_runs_in_an_empty_temp_cwd_outside_the_repo(monkeypatch):
    run, calls = fake_run((FIX / "claude_cli_ok.json").read_text(encoding="utf-8"))
    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-x")
    ClaudeCliBackend("m").complete("S", "USER", SCHEMA)
    kw = calls[0][1]
    cwd = Path(kw["cwd"])
    assert REPO not in cwd.parents and cwd != REPO
    assert not cwd.exists()                          # removed after the call
    assert "ANTHROPIC_API_KEY" not in kw["env"]


def test_structured_output_field_and_stdin(monkeypatch):
    run, calls = fake_run((FIX / "claude_cli_ok.json").read_text(encoding="utf-8"))
    monkeypatch.setattr(subprocess, "run", run)
    logged = []
    assert ClaudeCliBackend("m", log=logged.append).complete("S", "USER", SCHEMA) == {"n": 7}
    assert calls[0][1]["input"] == "USER"
    assert logged[0]["input_tokens"] == 1200


def test_falls_back_to_result_text(monkeypatch):
    run, _ = fake_run((FIX / "claude_cli_result_text.json").read_text(encoding="utf-8"))
    monkeypatch.setattr(subprocess, "run", run)
    assert ClaudeCliBackend("m").complete("S", "U", SCHEMA) == {"n": 8}


def test_usage_limit_raises_limit(monkeypatch):
    run, _ = fake_run((FIX / "claude_cli_limit.json").read_text(encoding="utf-8"), returncode=1)
    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(LLMError) as e:
        ClaudeCliBackend("m", sleep=lambda s: None).complete("S", "U", SCHEMA)
    assert e.value.kind == "limit"
    assert "hit your limit" in str(e.value)


def test_missing_binary_is_fatal(monkeypatch):
    def run(cmd, **kw):
        raise FileNotFoundError("claude")
    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(LLMError) as e:
        ClaudeCliBackend("m").complete("S", "U", SCHEMA)
    assert e.value.kind == "fatal" and "claude" in str(e.value)


@pytest.mark.parametrize("text,kind", [
    ("Claude AI usage limit reached", "limit"),
    ("You've hit your limit · resets 3pm", "limit"),
    ("You have reached your usage limit", "limit"),
    ("API Error: 529 Overloaded", "transient"),
    ("rate_limit_error", "transient"),
    ("Request timed out", "transient"),
    ("Invalid model name", "fatal"),
])
def test_classify(text, kind):
    assert classify(text) == kind


@pytest.mark.live
def test_live_claude_cli_smoke():
    out = ClaudeCliBackend("claude-haiku-4-5").complete(
        "Return JSON only.", "Give n = 5.", SCHEMA)
    assert out == {"n": 5}


@pytest.mark.live
def test_live_claude_cli_is_isolated(tmp_path):
    """Same flags as build_cmd, streamed, to read the init event: no tools, no MCP servers,
    OAuth billing, and no global CLAUDE.md rules reaching the model."""
    b = ClaudeCliBackend("claude-haiku-4-5")
    cmd = b.build_cmd("You answer questions about your own context truthfully.", SCHEMA)
    cmd = [c for c in cmd]
    i = cmd.index("--output-format")
    cmd[i + 1] = "stream-json"
    cmd.insert(i + 2, "--verbose")
    j = cmd.index("--json-schema")
    del cmd[j:j + 2]
    probe = ("If any instructions in your context tell you how to start your answers, quote that "
             "rule verbatim. Otherwise reply exactly: NO-RULES")
    r = subprocess.run(cmd, input=probe, capture_output=True, text=True, cwd=tmp_path,
                       env=b.child_env(), timeout=300)
    events = [json.loads(l) for l in r.stdout.splitlines() if l.strip().startswith("{")]
    init = next(e for e in events if e.get("type") == "system" and e.get("subtype") == "init")
    assert init["tools"] == []
    assert init["mcp_servers"] == []
    assert init.get("apiKeySource") in (None, "none")
    result = next(e for e in events if e.get("type") == "result")
    assert "NO-RULES" in result["result"]
