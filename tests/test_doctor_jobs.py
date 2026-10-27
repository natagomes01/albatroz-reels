import subprocess

import pytest

from shorts import machine
from shorts.config import AppConfig
from shorts.doctor_jobs import extra_checks


@pytest.fixture(autouse=True)
def mac_keychain(monkeypatch):
    """These runners fake `security`: check the Mac path on any machine."""
    monkeypatch.setattr(machine, "MAC", True)


def test_extra_checks_report_each_item(tmp_path):
    script = tmp_path / "transcreve.py"
    script.write_text("# --palavras supported\n", encoding="utf-8")
    a = AppConfig(media_root=tmp_path / "media", jobs_dir=tmp_path / "jobs",
                  backends={"scan": {"backend": "claude-cli", "model": "m"},
                            "detail": {"backend": "anthropic-api", "model": "m"}},
                  backup_auto=True, transcreve={"script": str(script)})

    def runner(cmd, **kw):
        if cmd[0] == "claude":
            return subprocess.CompletedProcess(cmd, 0, stdout="2.1.284 (Claude Code)", stderr="")
        if cmd[0] == "security":
            return subprocess.CompletedProcess(cmd, 44, stdout="", stderr="not found")
        if cmd[:2] == ["rclone", "listremotes"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="gdrive:\n", stderr="")
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="")
    result = extra_checks(a, runner=runner)
    checks = {c.name: c.ok for c in result}
    assert checks["claude CLI"] is True
    assert checks["Keychain: anthropic-api"] is False
    assert checks["rclone remote"] is True
    assert checks["transcreve (config.toml [transcreve])"] is True
    assert "media root writable" not in checks          # plan 1's run_doctor() already checks it


def test_transcreve_check_skipped_when_config_matches_plan_1_default(tmp_path):
    from shorts.doctor import TRANSCREVE
    a = AppConfig(media_root=tmp_path / "media", jobs_dir=tmp_path / "jobs", backends={},
                  transcreve={"script": str(TRANSCREVE)})
    runner = lambda cmd, **k: subprocess.CompletedProcess(cmd, 1, "", "")  # noqa: E731
    assert [c.name for c in extra_checks(a, runner=runner)] == [
        "UVR (audio-separator)", "UVR model", "Keychain: pixabay-api",
        "B-roll User-Agent"]


def test_missing_rclone_is_a_warning_not_a_failure(tmp_path):
    a = AppConfig(media_root=tmp_path / "media", jobs_dir=tmp_path / "jobs", backends={},
                  backup_auto=True)

    def runner(cmd, **kw):
        raise FileNotFoundError(cmd[0])
    (chk,) = [c for c in extra_checks(a, runner=runner) if c.name == "rclone remote"]
    assert chk.ok is False and chk.required is False


def test_dereverb_checks(tmp_path):
    from shorts.dereverb import DereverbConfig

    class Done:
        def __init__(self, code, out=""):
            self.returncode, self.stdout, self.stderr = code, out, ""

    models = tmp_path / "models"
    models.mkdir()
    cfg = DereverbConfig(model_dir=models, separator=tmp_path / "sep")
    app = AppConfig(media_root=tmp_path, jobs_dir=tmp_path, backends={}, dereverb=cfg)

    def runner_ok(cmd, **kw):
        return Done(0, "audio-separator 0.47.0")
    checks = {c.name: c for c in extra_checks(app, runner=runner_ok)}
    assert checks["UVR (audio-separator)"].ok and "0.47.0" in checks["UVR (audio-separator)"].detail
    assert not checks["UVR model"].ok and "new-machine-setup" in checks["UVR model"].detail
    (models / "UVR-DeEcho-DeReverb.pth").write_bytes(b"x")

    def runner_missing(cmd, **kw):
        if cmd[-1] == "--version":
            raise FileNotFoundError(cmd[0])
        return Done(0)
    checks = {c.name: c for c in extra_checks(app, runner=runner_missing)}
    assert not checks["UVR (audio-separator)"].ok and checks["UVR model"].ok
    assert "new-machine-setup" in checks["UVR (audio-separator)"].detail


def test_broll_checks_are_warnings(tmp_path):
    from shorts.broll.model import BrollConfig

    def runner(cmd, **kw):
        if cmd[0] == "security" and cmd[-1] == "pixabay-api":
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        if cmd[0] == "security":
            return subprocess.CompletedProcess(cmd, 44, stdout="", stderr="not found")
        return subprocess.CompletedProcess(cmd, 0, stdout="x", stderr="")
    a = AppConfig(media_root=tmp_path, jobs_dir=tmp_path, backends={})
    checks = {c.name: c for c in extra_checks(a, runner=runner)}
    assert "Keychain: pexels-api" not in checks and checks["Keychain: pixabay-api"].ok
    assert not checks["B-roll User-Agent"].ok
    assert all(not checks[n].required for n in ("Keychain: pixabay-api", "B-roll User-Agent"))
    missing = {c.name: c for c in extra_checks(a, runner=lambda cmd, **kw: subprocess.CompletedProcess(
        cmd, 44 if cmd[0] == "security" else 0, stdout="x", stderr=""))}
    assert not missing["Keychain: pixabay-api"].ok and "new-machine-setup" in missing["Keychain: pixabay-api"].detail
    a2 = AppConfig(media_root=tmp_path, jobs_dir=tmp_path, backends={},
                   broll=BrollConfig(user_agent="albatroz-shorts (nata@example.com)"))
    assert {c.name: c for c in extra_checks(a2, runner=runner)}["B-roll User-Agent"].ok
