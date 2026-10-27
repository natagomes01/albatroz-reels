"""`shorts doctor`: check the machine before a long run (spec 11, plan-1 subset)."""
from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from shorts import machine
from shorts.config import AppConfig
from shorts.ffmpeg import FFMPEG, FFPROBE, video_encoder
from shorts.vision import detector_name

# transcreve's model folder: WHISPER_MODELOS when set, else ~/.cache/whisper-models
WHISPER_MODEL = (Path(os.environ.get("WHISPER_MODELOS") or "~/.cache/whisper-models").expanduser()
                 / "ggml-large-v3-turbo.bin")
TRANSCREVE = Path(os.environ.get("SHORTS_TRANSCREVE")
                  or Path(os.environ.get("ALBATROZ_DEV", "~/dev")) / "transcreve" / "transcreve.py").expanduser()
WARN_FREE_GB = 10   # below this: warn (a 2 h 4K master is 20-40 GB)
FAIL_FREE_GB = 3    # below this: fail (renders and temp files need room)


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str
    required: bool = True


def _output(cmd: list[str]) -> str:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"ERROR {exc}"
    return proc.stdout + proc.stderr


def check_ffmpeg() -> list[Check]:
    found = lambda exe: Path(exe).exists() or shutil.which(exe) is not None  # noqa: E731
    if not (found(FFMPEG) and found(FFPROBE)):
        missing = FFMPEG if not found(FFMPEG) else FFPROBE
        return [Check("ffmpeg-full", False, f"{missing} not found: {machine.install_hint('ffmpeg')}")]
    filters = _output([FFMPEG, "-hide_banner", "-filters"])
    encoders = _output([FFMPEG, "-hide_banner", "-encoders"])
    enc = video_encoder()
    has = lambda text, name: any(line.split()[1:2] == [name] for line in text.splitlines() if line.strip())  # noqa: E731
    return [
        Check("ffmpeg-full", True, FFMPEG),
        Check("libass (subtitles filter)", has(filters, "subtitles"), "needed for captions"),
        Check(enc, has(encoders, enc), "H.264 encoder (SHORTS_ENCODER)"),
        Check("zscale (HDR to SDR)", has(filters, "zscale"), "needed for iPhone HDR masters"),
    ]


def check_whisper() -> list[Check]:
    cli = shutil.which("whisper-cli")
    return [
        Check("whisper-cli", cli is not None, cli or machine.install_hint("whisper-cli")),
        Check("whisper model", WHISPER_MODEL.exists(), str(WHISPER_MODEL) + ("" if WHISPER_MODEL.exists()
              else " missing (set WHISPER_MODELOS to the folder that holds it)")),
    ]


def check_transcreve() -> Check:
    if not TRANSCREVE.exists():
        return Check("transcreve --palavras", False, f"{TRANSCREVE} not found (set SHORTS_TRANSCREVE)")
    help_text = _output([machine.default_python(), str(TRANSCREVE), "--help"])
    return Check("transcreve --palavras", "--palavras" in help_text, str(TRANSCREVE))


def _has_module(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def check_detector() -> list[Check]:
    """The detector this machine uses (vision.detector_name): Apple Vision through pyobjc, or the
    ONNX pair, whose model files download on the first track."""
    name = detector_name()
    if name == "vision":
        return [Check("detector: Apple Vision", _has_module("Vision"), "pyobjc-framework-Vision (pip install -e .)")]
    from shorts import detect_onnx
    libs = [m for m in ("cv2", "onnxruntime", "numpy") if not _has_module(m)]
    models = [detect_onnx.models_dir() / m.file for m in (detect_onnx.YUNET, detect_onnx.YOLOX_S)]
    absent = [p.name for p in models if not p.exists()]
    return [
        Check("detector: YuNet + YOLOX-S (ONNX)", not libs,
              "opencv-python-headless, onnxruntime" if not libs else f"missing {', '.join(libs)}: pip install -e ."),
        Check("detector models", not absent, str(detect_onnx.models_dir()) if not absent
              else f"{', '.join(absent)} not in {detect_onnx.models_dir()}; the first track downloads them",
              required=False),
    ]


def check_secret_store() -> Check:
    if machine.secret_store() == "keychain":
        return Check("secret store: Keychain", shutil.which("security") is not None, "security CLI")
    return Check("secret store: keyring", _has_module("keyring"),
                 "Windows Credential Manager through keyring (pip install -e .)", required=False)


def check_assets(repo_root: Path) -> list[Check]:
    font = repo_root / "assets" / "fonts" / "Anton-Regular.ttf"
    zone = repo_root / "assets" / "safe-zone.png"
    return [
        Check("Anton font", font.exists(), str(font)),
        Check("safe-zone template", zone.exists(), str(zone) + " (only for --safe-zone)", required=False),
    ]


def check_media_root(app: AppConfig) -> list[Check]:
    root = app.media_root
    try:
        (root / "renders").mkdir(parents=True, exist_ok=True)
        probe_file = root / ".doctor-write-test"
        probe_file.write_text("ok", encoding="utf-8")
        probe_file.unlink()
        writable = True
    except OSError as exc:
        return [Check("media root writable", False, f"{root}: {exc}")]
    free_gb = shutil.disk_usage(root).free / 1e9
    return [Check("media root writable", writable, str(root)), disk_check(free_gb)]


def disk_check(free_gb: float) -> Check:
    detail = f"{free_gb:.1f} GB free (warn below {WARN_FREE_GB}, fail below {FAIL_FREE_GB})"
    if free_gb < FAIL_FREE_GB:
        return Check("disk space", False, detail, required=True)
    return Check("disk space", free_gb >= WARN_FREE_GB, detail, required=False)


def run_doctor(repo_root: Path, app: AppConfig) -> int:
    """Print every check; exit code 1 when a required check fails."""
    from shorts.doctor_jobs import extra_checks  # imported here: doctor_jobs imports doctor

    checks = [*check_ffmpeg(), *check_whisper(), check_transcreve(), *check_detector(),
              check_secret_store(), *check_assets(repo_root),
              *check_media_root(app), *extra_checks(app)]
    failed = False
    for c in checks:
        mark = "ok  " if c.ok else ("FAIL" if c.required else "warn")
        print(f"[{mark}] {c.name}: {c.detail}")
        failed |= c.required and not c.ok
    return 1 if failed else 0
