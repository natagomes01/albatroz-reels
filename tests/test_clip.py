import json
import re
import subprocess
from pathlib import Path

import pytest

from conftest import needs_ffmpeg
from shorts.clip import make_clip
from shorts.config import AppConfig, ChannelConfig
from shorts.ffmpeg import FFMPEG, FFPROBE, probe


REPO = Path(__file__).resolve().parents[1]


def _fake_words(path: Path, seconds: float, silent: tuple[float, float]) -> Path:
    text = ("Aí eu li isso a primeira vez, eu falei. " * 10).split()
    words = [{"t": round(0.5 + i * 0.4, 2), "p": 1.0, "w": w} for i, w in enumerate(text)]
    words = [w for w in words if w["t"] < seconds and not silent[0] <= w["t"] < silent[1]]
    path.write_text(json.dumps({"version": 1, "words": words}), encoding="utf-8")
    return path


@needs_ffmpeg
def test_make_clip_end_to_end_synthetic(synth_video, tmp_path):
    pytest.importorskip("Vision")
    v = synth_video(12, silent=(4, 6))
    words = _fake_words(tmp_path / "w.palavras.json", 12, (4, 6))
    app = AppConfig(media_root=tmp_path / "media", jobs_dir=tmp_path / "jobs", backends={})
    ch = ChannelConfig(id="catholic-br", language="pt", brand_dir=None, glossary="")
    out = make_clip(v, ch, "solo-standing", 1.0, 11.0, words, app, REPO, False, tmp_path / "work")
    meta = json.loads(out.with_suffix(".json").read_text(encoding="utf-8"))
    edl_duration = sum(s["end"] - s["start"] for s in meta["edl"])
    assert out.parent == tmp_path / "media" / "renders" / "catholic-br" / "manual"
    assert probe(out).duration == pytest.approx(edl_duration, abs=0.1)
    assert edl_duration < 10.0  # the 2-second silence was shortened
    assert meta["weak_tracking"] is True  # no person in a gradient
    assert _codecs(out) == ("h264", "aac", "48000")


def _codecs(video: Path) -> tuple[str, str, str]:
    streams = json.loads(subprocess.run([FFPROBE, "-v", "error", "-show_streams", "-print_format", "json",
                                         str(video)], capture_output=True, text=True, check=True).stdout)["streams"]
    v = next(s for s in streams if s["codec_type"] == "video")
    a = next(s for s in streams if s["codec_type"] == "audio")
    return v["codec_name"], a["codec_name"], a["sample_rate"]


@needs_ffmpeg
def test_make_clip_from_mov_with_data_stream(synth_video, tmp_path):
    pytest.importorskip("Vision")
    v = synth_video(8, ext="mov", data_stream=True)
    words = _fake_words(tmp_path / "w.palavras.json", 8, (20, 20))
    app = AppConfig(media_root=tmp_path / "media", jobs_dir=tmp_path / "jobs", backends={})
    ch = ChannelConfig(id="catholic-br", language="pt", brand_dir=None, glossary="")
    out = make_clip(v, ch, "solo-seated", 1.0, 7.0, words, app, REPO, False, tmp_path / "work")
    assert _codecs(out) == ("h264", "aac", "48000")


@needs_ffmpeg
def test_missing_safe_zone_fails_before_decoding(synth_video, tmp_path, monkeypatch):
    import shorts.clip as clip

    v = synth_video(6)
    words = _fake_words(tmp_path / "w.palavras.json", 6, (10, 10))
    app = AppConfig(media_root=tmp_path / "media", jobs_dir=tmp_path / "jobs", backends={})
    ch = ChannelConfig(id="catholic-br", language="pt", brand_dir=None, glossary="")
    monkeypatch.setattr(clip, "detect_silences", lambda *a, **k: pytest.fail("decoded before the check"))
    with pytest.raises(FileNotFoundError, match="safe-zone"):
        make_clip(v, ch, "solo-standing", 1.0, 5.0, words, app, tmp_path, True, tmp_path / "work")


def _loudness(video: Path) -> float:
    err = subprocess.run([FFMPEG, "-hide_banner", "-nostats", "-i", str(video), "-vn", "-af",
                          "loudnorm=print_format=summary", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    return float(re.search(r"Input Integrated:\s*(-?[0-9.]+)", err).group(1))


@needs_ffmpeg
def test_make_clip_on_real_sample(sample, tmp_path):
    """Spec 12 end-to-end: the real 10-min excerpt through `shorts clip` (skips without SHORTS_SAMPLE)."""
    pytest.importorskip("Vision")
    words = sample.parent / f"{sample.stem}.palavras.json"
    if not words.exists():
        pytest.skip(f"{words} missing: run trs --palavras on the sample first")
    app = AppConfig(media_root=tmp_path / "media", jobs_dir=tmp_path / "jobs", backends={})
    ch = ChannelConfig(id="catholic-br", language="pt", brand_dir=None, glossary="")
    out = make_clip(sample, ch, "solo-standing", 60.0, 90.0, words, app, REPO, False, tmp_path / "work")
    info = probe(out)
    meta = json.loads(out.with_suffix(".json").read_text(encoding="utf-8"))
    edl_duration = sum(s["end"] - s["start"] for s in meta["edl"])
    assert (info.width, info.height) == (1080, 1920)
    assert info.fps == pytest.approx(30.0)
    assert info.duration == pytest.approx(edl_duration, abs=0.1)
    assert _codecs(out) == ("h264", "aac", "48000")
    assert -15.0 <= _loudness(out) <= -13.0
    assert meta["weak_tracking"] is False  # Natã is in frame the whole time


@needs_ffmpeg
def test_make_clip_rejects_bad_requests(synth_video, tmp_path):
    v = synth_video(6)
    words = _fake_words(tmp_path / "w.palavras.json", 6, (10, 10))
    app = AppConfig(media_root=tmp_path / "media", jobs_dir=tmp_path / "jobs", backends={})
    ch = ChannelConfig(id="catholic-br", language="pt", brand_dir=None, glossary="")
    args = (words, app, REPO, False, tmp_path / "work")
    with pytest.raises(ValueError, match="phase 1b"):
        make_clip(v, ch, "conversation", 1.0, 5.0, *args)
    with pytest.raises(ValueError, match="after"):
        make_clip(v, ch, "solo-standing", 5.0, 4.0, *args)
    with pytest.raises(ValueError, match="past the end"):
        make_clip(v, ch, "solo-standing", 1.0, 9.0, *args)
    with pytest.raises(ValueError, match="no transcribed words"):
        make_clip(v, ch, "solo-standing", 5.0, 6.0, _fake_words(tmp_path / "e.palavras.json", 0, (10, 10)), *args[1:])
    with pytest.raises(ValueError, match="at least"):
        make_clip(v, ch, "solo-standing", 0.0, 0.3, *args)
    with pytest.raises(ValueError, match="start at 0"):
        make_clip(v, ch, "solo-standing", -1.0, 3.0, *args)
    assert not (tmp_path / "work").exists() and not (tmp_path / "media").exists()


def test_hook_is_capped_without_punctuation():
    from shorts.clip import hook_span
    from shorts.shots import plan_shots
    from shorts.timeline import Span, TimeMap
    from shorts.words import Word, sentences

    words = [Word(100 + i * 0.5, "palavra", 1.0) for i in range(40)]  # 20 s, no sentence end
    sents = sentences(words)
    hook = hook_span(words, sents[0])
    assert hook == Span(100, 106.0)
    tm = TimeMap([Span(100, 110), Span(111, 121)])  # an EDL join at 10 s allows a cut
    kinds = [s.kind for s in plan_shots(tm, words, sents, hook, [], [])]
    assert kinds == ["close", "wide"]


@needs_ffmpeg
def test_make_clip_rejects_single_quote_workdir_up_front(synth_video, tmp_path):
    v = synth_video(6)
    words = _fake_words(tmp_path / "w.palavras.json", 6, (10, 10))
    app = AppConfig(media_root=tmp_path / "media", jobs_dir=tmp_path / "jobs", backends={})
    ch = ChannelConfig(id="catholic-br", language="pt", brand_dir=None, glossary="")
    with pytest.raises(ValueError, match="single quote"):
        make_clip(v, ch, "solo-standing", 1.0, 5.0, words, app, REPO, False, tmp_path / "d'work")
    assert not (tmp_path / "d'work").exists() and not (tmp_path / "media").exists()


@needs_ffmpeg
def test_make_clip_rejects_narrow_master(synth_video, tmp_path):
    v = synth_video(6, size="320x640")
    words = _fake_words(tmp_path / "w.palavras.json", 6, (10, 10))
    app = AppConfig(media_root=tmp_path / "media", jobs_dir=tmp_path / "jobs", backends={})
    ch = ChannelConfig(id="catholic-br", language="pt", brand_dir=None, glossary="")
    with pytest.raises(ValueError, match="narrower than 9:16"):
        make_clip(v, ch, "solo-standing", 1.0, 5.0, words, app, REPO, False, tmp_path / "work")
    assert not (tmp_path / "work").exists()


@needs_ffmpeg
def test_captions_and_meta_are_written_atomically(synth_video, tmp_path, monkeypatch):
    pytest.importorskip("Vision")
    from shorts import jobs
    written = []
    real = jobs.write_text_atomic
    monkeypatch.setattr(jobs, "write_text_atomic", lambda p, t: (written.append(Path(p).name), real(p, t))[1])
    v = synth_video(8)
    words = _fake_words(tmp_path / "w.palavras.json", 8, (99, 99))
    app = AppConfig(media_root=tmp_path / "media", jobs_dir=tmp_path / "jobs", backends={})
    ch = ChannelConfig(id="catholic-br", language="pt", brand_dir=None, glossary="")
    out = make_clip(v, ch, "solo-standing", 1.0, 7.0, words, app, REPO, False, tmp_path / "work")
    assert "captions.ass" in written and out.with_suffix(".json").name in written
    assert not list(tmp_path.rglob("*.tmp"))
