"""Dereverb with UVR (S8 audio spec): the per-class strength, its gate, and the UVR runs."""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from shorts import jobs
from shorts.ffmpeg import FFMPEG, FFPROBE, run
from shorts.timeline import Span

DEFAULT_LEVELS = (0, 10, 20, 30)
GATE_MESSAGE = "choose the audio strength on the review page first"
SETUP_DOC = "documentation/runbooks/new-machine-setup.md, section 'Dereverb (UVR)'"


class StrengthNotChosen(ValueError):
    """Rendering a class whose dereverb strength the owner has not chosen yet (spec 3)."""


@dataclass(frozen=True)
class DereverbConfig:
    levels: tuple[int, ...] = DEFAULT_LEVELS
    model: str = "UVR-DeEcho-DeReverb.pth"
    model_dir: Path = Path("~/dev/albatroz-media/models").expanduser()
    separator: Path = Path("~/.local/bin/audio-separator").expanduser()
    excerpt_seconds: float = 20.0


def _is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def parse_levels(values) -> tuple[int, ...]:
    """`[dereverb] levels`: integers 0..100 (UVR aggression), no repeats, 0 (off) included."""
    if not isinstance(values, (list, tuple)) or not values:
        raise ValueError("[dereverb] levels must be a non-empty list of integers")
    for v in values:
        if not _is_int(v) or not 0 <= v <= 100:
            raise ValueError(f"[dereverb] level {v!r} must be an integer from 0 to 100")
    if 0 not in values:
        raise ValueError("[dereverb] levels must include 0 (off)")
    if len(set(values)) != len(values):
        raise ValueError("[dereverb] levels must not repeat")
    return tuple(sorted(values))


def check_level(value, levels) -> int:
    if not _is_int(value) or value not in levels:
        raise ValueError(f"dereverb must be one of {list(levels)}")
    return value


def class_strength(review: dict) -> int | None:
    """The class strength in review.json; anything but an integer counts as not chosen."""
    v = review.get("dereverb")
    return v if _is_int(v) else None


def effective_strength(review: dict, decision: dict) -> int | None:
    """The clip's override when it has one, else the class strength (spec 3)."""
    v = decision.get("dereverb")
    return v if _is_int(v) else class_strength(review)


def gate(channel, review: dict, has_audio: Callable[[], bool] = lambda: True) -> None:
    """Refuse to render a class with treated sound whose strength is not chosen (spec 3)."""
    if channel.sound and class_strength(review) is None and has_audio():
        raise StrengthNotChosen(GATE_MESSAGE)


PAD = 1.0                   # seconds of context on each side of a window (spec 4.1)
UVR_ATTEMPTS = 3            # audio-separator sometimes aborts at exit (exit -6); try up to 3 times
DURATION_TOLERANCE = 0.05   # seconds; a longer or shorter UVR output is an error (spec 4.6)
CACHE_VERSION = "1"


class DereverbError(RuntimeError):
    """UVR missing, failed, or returned audio of the wrong length; the clip is not rendered."""


def audio_cache_dir(app, job) -> Path:
    return Path(app.media_root).expanduser() / "cache" / job.id / "audio"


def audio_duration(path: Path) -> float:
    proc = run([FFPROBE, "-v", "error", "-show_entries", "format=duration",
                "-of", "default=nw=1:nk=1", str(path)], capture_stdout=True)
    return float(proc.stdout.decode().strip())


def cache_key(master_id: str, window: Span, strength: int, model: str) -> str:
    return jobs.stage_key(CACHE_VERSION, stage="dereverb", master=master_id,
                          window=[round(window.start, 3), round(window.end, 3)],
                          strength=strength, model=model)[:32]


def run_separator(cfg: DereverbConfig, src: Path, out_dir: Path, strength: int) -> Path:
    """One UVR run on `src`; returns the single 'No Reverb' WAV it wrote into `out_dir`."""
    exe = Path(cfg.separator).expanduser()
    if not exe.exists():
        raise DereverbError(f"UVR not installed: {exe} not found; see {SETUP_DOC}")
    model_dir = Path(cfg.model_dir).expanduser()
    if not (model_dir / cfg.model).exists():
        raise DereverbError(f"UVR model missing: {model_dir / cfg.model}; see {SETUP_DOC}")
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [str(exe), str(src), "--model_filename", cfg.model, "--model_file_dir", str(model_dir),
           "--output_dir", str(out_dir), "--output_format", "WAV",
           "--vr_aggression", str(strength), "--single_stem", "No Reverb"]
    for n in range(1, UVR_ATTEMPTS + 1):
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if proc.returncode == 0:
            break
        text = proc.stdout + proc.stderr
        tail = " | ".join(text.strip().splitlines()[-3:])
        # only the known exit-time crashes are worth a retry (SIGABRT, SIGSEGV, or a crash after
        # "Separation complete"); anything else is a real failure
        if (proc.returncode not in (-6, -11) and "recursive_mutex" not in text
                and "Separation complete" not in text):
            raise DereverbError(f"UVR failed (exit {proc.returncode}): {tail}")
        if n == UVR_ATTEMPTS:
            raise DereverbError(f"UVR failed (exit {proc.returncode}, {n} attempts): {tail}")
        # never keep output from a run that exited non-zero
        for f in out_dir.iterdir():
            if f.is_dir():
                shutil.rmtree(f)
            else:
                f.unlink()
    outs = sorted(out_dir.glob("*.wav"))
    if len(outs) != 1:
        raise DereverbError(f"UVR wrote {len(outs)} WAV files to {out_dir}, expected 1")
    return outs[0]


def dereverb_windows(master: Path, windows: list[Span], strength: int, cfg: DereverbConfig,
                     cache_dir: Path, master_id: str, duration: float) -> list[Path]:
    """One dereverbed WAV per window, each starting exactly at its window's start (spec 4).
    Cached by (master, window, strength, model); a cached file is never recomputed."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    out: list[Path] = []
    for w in windows:
        dest = cache_dir / f"{cache_key(master_id, w, strength, cfg.model)}.wav"
        if not dest.exists():
            _dereverb_window(master, w, strength, cfg, dest, duration)
        out.append(dest)
    return out


def _dereverb_window(master: Path, w: Span, strength: int, cfg: DereverbConfig, dest: Path,
                     duration: float) -> None:
    a = max(0.0, w.start - PAD)
    b = w.end + PAD if duration <= 0 else min(duration, w.end + PAD)
    # the temporary folder sits next to the cache, so os.replace never crosses a volume, and a
    # crash leaves only this folder behind, never a partial WAV under the cache name
    with tempfile.TemporaryDirectory(prefix=".dereverb-", dir=dest.parent) as tmp_name:
        tmp = Path(tmp_name)
        src = tmp / "in.wav"
        run([FFMPEG, "-y", "-hide_banner", "-nostats", "-ss", f"{a:.3f}", "-to", f"{b:.3f}",
             "-i", str(master), "-map", "0:a:0", "-ac", "2", "-ar", "44100", "-c:a", "pcm_s16le",
             str(src)])
        # the container can outlast its audio stream (~150 ms on the iPhone masters), so the
        # real input length is measured, not assumed from the window
        real_in = audio_duration(src)
        sep = run_separator(cfg, src, tmp / "out", strength)
        # spec 4.6 checks UVR's own output against its input: one shorter by less than the pad
        # would still trim to the window length, with the sound shifted against the picture
        got = audio_duration(sep)
        if abs(got - real_in) > DURATION_TOLERANCE:
            raise DereverbError(f"UVR output is {got:.3f} s for a {real_in:.3f} s input")
        offset = w.start - a
        expected = min(w.duration, real_in - offset)
        part = tmp / "trim.wav"
        run([FFMPEG, "-y", "-hide_banner", "-nostats", "-i", str(sep),
             "-af", f"atrim=start={offset:.3f}:duration={w.duration:.3f},asetpts=N/SR/TB",
             "-c:a", "pcm_s16le", str(part)])
        got = audio_duration(part)
        if abs(got - expected) > DURATION_TOLERANCE:
            raise DereverbError(f"UVR output is {got:.3f} s for a {expected:.3f} s window")
        os.replace(part, dest)
