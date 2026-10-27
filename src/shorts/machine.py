"""Where shorts is running, decided in one place. Every default that depends on the OS lives here;
the rest of the code asks this module and never reads sys.platform itself.

macOS (the M1): Apple Vision, VideoToolbox, Homebrew's ffmpeg-full, the Keychain.
Windows (the PC, since 23/10/26): YuNet + YOLOX-S in ONNX, libx264, ffmpeg from PATH, keyring.
Install steps for both: documentation/runbooks/new-machine-setup.md.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

NAME = sys.platform           # also the key of [platform.<NAME>] in config.toml
MAC = NAME == "darwin"
WINDOWS = NAME == "win32"


def default_detector() -> str:
    return "vision" if MAC else "onnx"


def default_encoder() -> str:
    """NVENC is never a default: the PC's GTX 1060 shut the machine down under load on 19/10/26."""
    return "h264_videotoolbox" if MAC else "libx264"


def ffmpeg_dir() -> Path | None:
    """Folder of ffmpeg and ffprobe: SHORTS_FFMPEG_DIR on any OS, else Homebrew's keg-only
    ffmpeg-full on the Mac, else None (take them from PATH)."""
    env = os.environ.get("SHORTS_FFMPEG_DIR")
    if env:
        return Path(env).expanduser()
    return Path("/opt/homebrew/opt/ffmpeg-full/bin") if MAC else None


def exe(name: str) -> str:
    return name + ".exe" if WINDOWS else name


def secret_store() -> str:
    return "keychain" if MAC else "keyring"


def default_python() -> str:
    """Interpreter for transcreve when config.toml names none: the system Python 3 on the Mac,
    this same interpreter elsewhere (transcreve is stdlib only)."""
    return "/usr/bin/python3" if MAC else sys.executable


def cache_dir() -> Path:
    """Per-user cache outside the repo: %LOCALAPPDATA% on Windows, ~/.cache elsewhere."""
    if WINDOWS and os.environ.get("LOCALAPPDATA"):
        return Path(os.environ["LOCALAPPDATA"]) / "albatroz-shorts"
    return Path("~/.cache/albatroz-shorts").expanduser()


_HINTS = {
    "ffmpeg": ("brew install ffmpeg-full",
               "winget install --id Gyan.FFmpeg -e --scope machine, or set SHORTS_FFMPEG_DIR"),
    "whisper-cli": ("brew install whisper-cpp",
                    "unzip whisper-blas-bin-x64.zip (whisper.cpp release b5454) and put its Release folder on PATH"),
    "rclone": ("brew install rclone",
               r"winget install --id Rclone.Rclone -e --scope machine --location C:\albatroz\programs\rclone"),
    "secret": ("security add-generic-password -s {service} -a {user} -w",
               "python -m keyring set {service} {user}"),
}


def install_hint(tool: str, **fmt) -> str:
    mac, other = _HINTS[tool]
    return (mac if MAC else other).format(**fmt)
