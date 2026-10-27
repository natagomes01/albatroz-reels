"""config.toml (app-wide) and channels.toml (per channel) loading."""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from shorts import machine
from shorts.broll.model import BrollConfig
from shorts.dereverb import DEFAULT_LEVELS, DereverbConfig, parse_levels

DEFAULT_WEIGHTS = {"hook": 0.30, "value": 0.25, "conversation": 0.25, "emotion": 0.20}


class ConfigError(ValueError):
    """A bad value in config.toml; the CLI prints it as one `error:` line."""


@dataclass(frozen=True)
class ChannelConfig:
    id: str
    language: str
    brand_dir: Path | None
    glossary: str
    captions: bool = True
    color: bool = True
    sound: bool = True
    silence: bool = True
    broll: bool = True
    caption_y: int | None = None    # caption baseline row; None = CaptionStyle's (a job setting sets it)
    weights: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))


@dataclass(frozen=True)
class AppConfig:
    media_root: Path
    jobs_dir: Path
    backends: dict[str, dict]  # pass name -> {"backend": str, "model": str, ...}
    scan_threshold: int = 60
    scan_ceiling: int = 40
    backup_auto: bool = False
    backup_remote: str = "gdrive:albatroz-media-backup"
    transcreve: dict = field(default_factory=dict)  # [transcreve]: python, script
    pricing_path: Path | None = None  # pricing.toml next to config.toml; None when absent (S4)
    cost_confirm_above_usd: float = 0.0  # > 0: analyze asks before an estimate above this (S4)
    dereverb: DereverbConfig = field(default_factory=DereverbConfig)  # [dereverb] (S8 audio)
    broll: BrollConfig = field(default_factory=BrollConfig)  # [broll] (S8B)
    final_dir: Path | None = None  # where export writes the video to post; None = <media_root>/final


def _resolve(base: Path, value: str) -> Path:
    p = Path(value).expanduser()
    return p if p.is_absolute() else (base / p).resolve()


def _require_mounted(key: str, p: Path) -> Path:
    """A path on /Volumes/<share> needs the share mounted; otherwise mkdir would build a fake
    folder in /Volumes on the Mac's own disk and fill it."""
    parts = p.parts
    if len(parts) > 2 and parts[:2] == ("/", "Volumes") and not os.path.ismount(f"/Volumes/{parts[2]}"):
        raise ConfigError(f"config.toml {key}: /Volumes/{parts[2]} is not mounted "
                          f"(Finder > Cmd+K > smb://<host>/{parts[2]})")
    return p


_BROLL_POSITIVE = ("candidates", "min_fill_px", "max_still_px", "thumb_width", "pan_px_per_s",
                   "insert_max_s", "max_inserts", "upload_max_mb")


def _broll_config(d: dict) -> BrollConfig:
    defaults = BrollConfig()
    values = {}
    for name in BrollConfig.__dataclass_fields__:
        raw = d.get(name, getattr(defaults, name))
        kind = type(getattr(defaults, name))
        try:
            values[name] = kind(raw)
        except (TypeError, ValueError):
            raise ConfigError(f"config.toml [broll] {name}: {raw!r} is not a {kind.__name__}") from None
    for name in _BROLL_POSITIVE:
        if values[name] <= 0:
            raise ConfigError(f"config.toml [broll] {name} must be above 0")
    if not 0 < values["max_share"] <= 1:
        raise ConfigError("config.toml [broll] max_share must be between 0 and 1")
    if not 960 <= values["split_face_y"] <= 1920:
        raise ConfigError("config.toml [broll] split_face_y must be between 960 and 1920")
    return BrollConfig(**values)


def _platform_overlay(data: dict, platform: str) -> dict:
    """[platform.<machine.NAME>] overrides top-level keys; a table merges one level deep, so
    [platform.win32.transcreve] can change `script` and keep the rest of [transcreve]."""
    over = (data.get("platform") or {}).get(platform) or {}
    merged = {k: v for k, v in data.items() if k != "platform"}
    for key, value in over.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = {**merged[key], **value}
        else:
            merged[key] = value
    return merged


def load_config(path: Path) -> AppConfig:
    data = _platform_overlay(tomllib.loads(Path(path).read_text(encoding="utf-8")), machine.NAME)
    base = Path(path).resolve().parent
    backup = data.get("backup", {})
    d = data.get("dereverb", {})
    try:
        levels = parse_levels(d.get("levels", list(DEFAULT_LEVELS)))
    except ValueError as e:
        raise ConfigError(f"config.toml [dereverb]: {e}") from e
    dereverb = DereverbConfig(
        levels=levels,
        model=str(d.get("model", "UVR-DeEcho-DeReverb.pth")),
        model_dir=_require_mounted("[dereverb] model_dir",
                                   _resolve(base, d.get("model_dir", "~/dev/albatroz-media/models"))),
        separator=_resolve(base, d.get("separator", "~/.local/bin/audio-separator")),
        excerpt_seconds=float(d.get("excerpt_seconds", 20)),
    )
    broll = _broll_config(data.get("broll", {}))
    pricing = _resolve(base, data.get("pricing", "pricing.toml"))
    media_root = _require_mounted("media_root", _resolve(base, data["media_root"]))
    final_dir = _resolve(base, data["final_dir"]) if "final_dir" in data else media_root / "final"
    return AppConfig(
        media_root=media_root,
        final_dir=final_dir,
        jobs_dir=_resolve(base, data.get("jobs_dir", "jobs")),
        backends=dict(data.get("backends", {})),
        scan_threshold=int(data.get("scan_threshold", 60)),
        scan_ceiling=int(data.get("scan_ceiling", 40)),
        backup_auto=bool(backup.get("auto", False)),
        backup_remote=str(backup.get("remote", "gdrive:albatroz-media-backup")),
        transcreve=dict(data.get("transcreve", {})),
        pricing_path=pricing if pricing.exists() else None,
        cost_confirm_above_usd=float(data.get("cost_confirm_above_usd", 0)),
        dereverb=dereverb,
        broll=broll,
    )


def load_channels(path: Path) -> dict[str, ChannelConfig]:
    data = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    base = Path(path).resolve().parent
    out: dict[str, ChannelConfig] = {}
    for cid, c in data.get("channels", {}).items():
        weights = dict(DEFAULT_WEIGHTS)
        weights.update({k: float(v) for k, v in c.get("weights", {}).items()})
        if abs(sum(weights.values()) - 1.0) > 1e-6:
            raise ValueError(f"channel {cid}: weights must sum to 1.0, got {sum(weights.values())}")
        brand = c.get("brand_dir") or None
        out[cid] = ChannelConfig(
            id=cid,
            language=str(c["language"]),
            brand_dir=_resolve(base, brand) if brand else None,
            glossary=str(c.get("glossary", "")),
            captions=bool(c.get("captions", True)),
            color=bool(c.get("color", True)),
            sound=bool(c.get("sound", True)),
            silence=bool(c.get("silence", True)),
            broll=bool(c.get("broll", True)),
            weights=weights,
        )
    return out
