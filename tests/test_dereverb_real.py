"""The real UVR on 5 s of the sample (S8 audio spec 8); skipped without UVR or the sample."""
from pathlib import Path

import pytest

from conftest import needs_ffmpeg
from shorts.config import load_config
from shorts.dereverb import audio_duration, dereverb_windows
from shorts.ffmpeg import FFMPEG, probe, run
from shorts.timeline import Span

REPO = Path(__file__).resolve().parents[1]


@needs_ffmpeg
def test_uvr_changes_the_sound_and_keeps_its_length(sample, tmp_path):
    cfg = load_config(REPO / "config.toml").dereverb
    if not cfg.separator.exists() or not (cfg.model_dir / cfg.model).exists():
        pytest.skip("UVR not installed (documentation/runbooks/new-machine-setup.md)")
    w = Span(430.0, 435.0)
    [out] = dereverb_windows(sample, [w], 20, cfg, tmp_path / "cache", "sample", probe(sample).duration)
    assert abs(audio_duration(out) - 5.0) <= 0.05
    raw = tmp_path / "raw.wav"
    run([FFMPEG, "-y", "-v", "error", "-ss", "430", "-to", "435", "-i", str(sample), "-map", "0:a:0",
         "-ac", "2", "-ar", "44100", "-c:a", "pcm_s16le", str(raw)])
    assert out.read_bytes() != raw.read_bytes()
