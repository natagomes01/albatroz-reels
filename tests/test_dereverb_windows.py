from dataclasses import replace

import pytest

from conftest import needs_ffmpeg
from shorts.dereverb import (UVR_ATTEMPTS, DereverbError, audio_duration, cache_key, dereverb_windows,
                             run_separator)
from shorts.timeline import Span


def calls_of(calls):
    return calls.read_text(encoding="utf-8").splitlines() if calls.exists() else []


@needs_ffmpeg
def test_one_wav_per_window_with_the_window_length(synth_video, fake_uvr, tmp_path):
    cfg, calls = fake_uvr
    master = synth_video(8)
    wins = [Span(2.0, 4.5), Span(5.0, 6.0)]
    out = dereverb_windows(master, wins, 20, cfg, tmp_path / "cache", "m1", 8.0)
    assert len(out) == 2 and all(p.parent == tmp_path / "cache" for p in out)
    assert [round(audio_duration(p), 2) for p in out] == [2.5, 1.0]
    assert [line.split()[0] for line in calls_of(calls)] == ["20", "20"]


@needs_ffmpeg
def test_cache_is_reused_per_strength(synth_video, fake_uvr, tmp_path):
    cfg, calls = fake_uvr
    master = synth_video(6)
    w = [Span(1.0, 3.0)]
    a = dereverb_windows(master, w, 20, cfg, tmp_path / "cache", "m1", 6.0)
    b = dereverb_windows(master, w, 20, cfg, tmp_path / "cache", "m1", 6.0)
    c = dereverb_windows(master, w, 30, cfg, tmp_path / "cache", "m1", 6.0)
    assert a == b and a != c
    assert len(calls_of(calls)) == 2


@needs_ffmpeg
@pytest.mark.parametrize("mode", ["abort", "mutex", "segv", "complete"])
def test_uvr_that_aborts_once_is_retried(mode, synth_video, fake_uvr, tmp_path, monkeypatch):
    cfg, calls = fake_uvr
    master = synth_video(4)
    monkeypatch.setenv("FAKE_UVR_FAIL_FIRST", "1")
    monkeypatch.setenv("FAKE_UVR_MODE", mode)
    [out] = dereverb_windows(master, [Span(1.0, 2.0)], 20, cfg, tmp_path / "cache", "m1", 4.0)
    assert out.exists() and len(calls_of(calls)) == 2


@needs_ffmpeg
def test_uvr_that_always_aborts_gives_up_after_three_calls(synth_video, fake_uvr, tmp_path, monkeypatch):
    cfg, calls = fake_uvr
    master = synth_video(4)
    monkeypatch.setenv("FAKE_UVR_FAIL_FIRST", "9")
    monkeypatch.setenv("FAKE_UVR_MODE", "abort")
    with pytest.raises(DereverbError, match=r"exit -6, 3 attempts"):
        dereverb_windows(master, [Span(1.0, 2.0)], 20, cfg, tmp_path / "cache", "m1", 4.0)
    assert len(calls_of(calls)) == 3 == UVR_ATTEMPTS
    assert list((tmp_path / "cache").iterdir()) == []


@needs_ffmpeg
def test_plain_failure_is_not_retried(synth_video, fake_uvr, tmp_path, monkeypatch):
    cfg, calls = fake_uvr
    master = synth_video(4)
    monkeypatch.setenv("FAKE_UVR_FAIL_FIRST", "9")          # exit 3, no known message
    with pytest.raises(DereverbError, match="exit 3") as e:
        dereverb_windows(master, [Span(1.0, 2.0)], 20, cfg, tmp_path / "cache", "m1", 4.0)
    assert "attempts" not in str(e.value) and len(calls_of(calls)) == 1


@needs_ffmpeg
def test_window_in_the_first_second_clamps_the_padding(synth_video, fake_uvr, tmp_path):
    # Review Focus 1: the pad before a window at 0.4 s is 0.4 s, not 1 s
    import re
    from shorts.ffmpeg import FFMPEG, run
    cfg, _ = fake_uvr
    master = synth_video(4, silent=(0.4, 0.7))   # the window opens on 0.3 s of silence
    [p] = dereverb_windows(master, [Span(0.4, 2.4)], 20, cfg, tmp_path / "cache", "m1", 4.0)
    assert abs(audio_duration(p) - 2.0) <= 0.05

    def mean_db(start, length):
        err = run([FFMPEG, "-hide_banner", "-ss", str(start), "-t", str(length), "-i", str(p),
                   "-af", "volumedetect", "-f", "null", "-"]).stderr.decode()
        m = re.search(r"mean_volume: (-?[\d.]+|-inf) dB", err)
        return float("-inf") if m.group(1) == "-inf" else float(m.group(1))
    # a trim offset of 0 (tone from 0.0 s) or of a fixed 1 s (tone from 1.0 s) would put tone here
    assert mean_db(0.02, 0.2) < -60
    assert mean_db(0.5, 0.3) > -40          # and the tone is back after the silence


@needs_ffmpeg
def test_failed_uvr_leaves_no_file_in_the_cache(synth_video, fake_uvr, tmp_path, monkeypatch):
    # Review Focus 2
    cfg, calls = fake_uvr
    master = synth_video(4)
    monkeypatch.setenv("FAKE_UVR_FAIL", "1")
    with pytest.raises(DereverbError, match="exit 3"):
        dereverb_windows(master, [Span(1.0, 2.0)], 20, cfg, tmp_path / "cache", "m1", 4.0)
    assert list((tmp_path / "cache").iterdir()) == []
    monkeypatch.delenv("FAKE_UVR_FAIL")
    dereverb_windows(master, [Span(1.0, 2.0)], 20, cfg, tmp_path / "cache", "m1", 4.0)
    assert len(calls_of(calls)) == 2


@needs_ffmpeg
def test_wrong_length_output_is_an_error(synth_video, fake_uvr, tmp_path, monkeypatch):
    cfg, _ = fake_uvr
    monkeypatch.setenv("FAKE_UVR_SHORT", "1")
    with pytest.raises(DereverbError, match="input|window"):
        dereverb_windows(synth_video(6), [Span(1.0, 4.0)], 20, cfg, tmp_path / "cache", "m1", 6.0)


def test_missing_program_or_model_names_the_runbook(fake_uvr, tmp_path):
    cfg, _ = fake_uvr
    src = tmp_path / "in.wav"
    src.write_bytes(b"")
    with pytest.raises(DereverbError, match="new-machine-setup"):
        run_separator(replace(cfg, separator=tmp_path / "nope"), src, tmp_path / "o", 20)
    with pytest.raises(DereverbError, match="new-machine-setup"):
        run_separator(replace(cfg, model="missing.pth"), src, tmp_path / "o", 20)


@needs_ffmpeg
def test_command_uses_the_local_model_folder(synth_video, fake_uvr, tmp_path):
    # Review Focus 5: UVR must find the model in the configured folder (offline runs)
    cfg, calls = fake_uvr
    dereverb_windows(synth_video(4), [Span(1.0, 2.0)], 10, cfg, tmp_path / "cache", "m1", 4.0)
    line = calls_of(calls)[0]
    assert f"--model_file_dir {cfg.model_dir}" in line
    assert "--model_filename UVR-DeEcho-DeReverb.pth" in line and "--single_stem No Reverb" in line


def test_cache_key_changes_with_every_input():
    base = cache_key("m1", Span(1.0, 2.0), 20, "a.pth")
    assert base == cache_key("m1", Span(1.0, 2.0), 20, "a.pth")
    for other in (cache_key("m2", Span(1.0, 2.0), 20, "a.pth"), cache_key("m1", Span(1.0, 2.5), 20, "a.pth"),
                  cache_key("m1", Span(1.0, 2.0), 30, "a.pth"), cache_key("m1", Span(1.0, 2.0), 20, "b.pth")):
        assert other != base


@needs_ffmpeg
def test_audio_shorter_than_the_container_duration_is_not_an_error(synth_video, fake_uvr, tmp_path):
    # live bug: the container is ~150 ms longer than its audio, so the pad asks for sound that
    # does not exist; UVR's output is checked against the extracted input, not the nominal window
    import re
    from shorts.ffmpeg import FFMPEG, run
    cfg, _ = fake_uvr
    master = synth_video(6, silent=(4.0, 4.3))
    [p] = dereverb_windows(master, [Span(4.0, 6.1)], 20, cfg, tmp_path / "cache", "m1", 6.2)
    assert 1.9 <= audio_duration(p) <= 2.1

    def mean_db(start, length):
        err = run([FFMPEG, "-hide_banner", "-ss", str(start), "-t", str(length), "-i", str(p),
                   "-af", "volumedetect", "-f", "null", "-"]).stderr.decode()
        m = re.search(r"mean_volume: (-?[\d.]+|-inf) dB", err)
        return float("-inf") if m.group(1) == "-inf" else float(m.group(1))
    assert mean_db(0.02, 0.2) < -60 and mean_db(0.4, 0.3) > -40     # starts exactly at the window
