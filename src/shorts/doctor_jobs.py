"""Plan-2 checks for `shorts doctor` (spec 11)."""
from __future__ import annotations

import subprocess
from pathlib import Path

from shorts import keychain
from shorts.backup import rclone_remote_ok
from shorts.broll.model import PLACEHOLDER_AGENT
from shorts.broll.search import KEY_SERVICES
from shorts.dereverb import SETUP_DOC
from shorts.doctor import TRANSCREVE, Check


def extra_checks(app, runner=subprocess.run) -> list[Check]:
    """Checks plan 1's run_doctor() does not make: LLM backends, Keychain secrets, rclone."""
    out: list[Check] = []
    kinds = {cfg.get("backend", "claude-cli") for cfg in app.backends.values()}
    if "claude-cli" in kinds:
        try:
            r = runner(["claude", "--version"], capture_output=True, text=True)
            out.append(Check("claude CLI", r.returncode == 0, r.stdout.strip() or r.stderr.strip()))
        except FileNotFoundError:
            out.append(Check("claude CLI", False, "not on PATH: install Claude Code and log in"))
    services = {cfg.get("key_service", "anthropic-api") for cfg in app.backends.values()
                if cfg.get("backend") == "anthropic-api"}
    services |= {cfg["key_service"] for cfg in app.backends.values()
                 if cfg.get("backend") == "openai-compatible" and cfg.get("key_service")}
    for s in sorted(services):
        found = keychain.has_secret(s, runner)
        out.append(Check(f"Keychain: {s}", found, "found" if found else f"missing: {keychain.add_hint(s)}"))
    if app.backup_auto:
        ok, why = rclone_remote_ok(app.backup_remote, runner=runner)
        out.append(Check("rclone remote", ok, why, required=False))  # rclone is optional
    # plan 1 checks TRANSCREVE; `shorts ingest` runs the script named in config.toml, so check it too
    script = Path((app.transcreve or {}).get("script", str(TRANSCREVE))).expanduser()
    if script != TRANSCREVE:
        has_flag = script.exists() and "--palavras" in script.read_text(encoding="utf-8")
        out.append(Check("transcreve (config.toml [transcreve])", has_flag, str(script)))
    # S8 audio: UVR runs as its own program, from the uv tool install the runbook describes
    cfg = app.dereverb
    exe = Path(cfg.separator).expanduser()
    try:
        r = runner([str(exe), "--version"], capture_output=True, text=True)
        ok = r.returncode == 0
        detail = (r.stdout.strip() or r.stderr.strip() or str(exe)) if ok else f"{exe} --version failed; see {SETUP_DOC}"
    except OSError:
        ok, detail = False, f"{exe} not found; see {SETUP_DOC}"
    out.append(Check("UVR (audio-separator)", ok, detail))
    model = Path(cfg.model_dir).expanduser() / cfg.model
    out.append(Check("UVR model", model.exists(), str(model) if model.exists() else f"{model} missing; see {SETUP_DOC}"))
    # S8B: B-roll works without these (Commons and own files only), so they only warn
    broll_doc = "documentation/runbooks/new-machine-setup.md, section B-roll keys"
    for name, service in KEY_SERVICES.items():
        if name == "pexels":        # Pexels no longer issues API keys: no warning (the code still uses a key if one exists)
            continue
        found = keychain.has_secret(service, runner)
        out.append(Check(f"Keychain: {service}", found,
                         "found" if found else f"missing: {name.capitalize()} search is off; see {broll_doc}",
                         required=False))
    agent = app.broll.user_agent.strip()
    agent_ok = bool(agent) and agent != PLACEHOLDER_AGENT
    out.append(Check("B-roll User-Agent", agent_ok,
                     agent if agent_ok else "set [broll] user_agent in config.toml with your contact "
                                            "(Wikimedia Commons asks for it)", required=False))
    return out
