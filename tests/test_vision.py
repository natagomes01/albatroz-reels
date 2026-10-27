from pathlib import Path

import pytest

from conftest import needs_ffmpeg
from shorts.ffmpeg import FFMPEG, FFmpegError, VideoInfo, probe, run
from shorts.timeline import Span

Vision = pytest.importorskip("Vision")
import shorts.vision as vision  # noqa: E402
from shorts.vision import detect, sample_command, sample_frames  # noqa: E402


def test_sample_command_maps_first_video_and_tone_maps_hdr():
    sdr = VideoInfo(1920, 1080, 30.0, 60.0, "bt709", True)
    cmd, w, h = sample_command(Path("m.mov"), Span(10.0, 20.0), sdr)
    vf = cmd[cmd.index("-vf") + 1]
    assert (w, h) == (640, 360) and "0:v:0" in cmd and "tonemap=" not in vf
    hdr = VideoInfo(3840, 2160, 30.0, 60.0, "arib-std-b67", True)
    vf_hdr = sample_command(Path("m.mov"), Span(10.0, 20.0), hdr)[0]
    assert "tonemap=" in vf_hdr[vf_hdr.index("-vf") + 1]
    portrait = VideoInfo(1080, 1920, 30.0, 60.0, "bt709", True, rotation=90)
    assert sample_command(Path("m.mov"), Span(0, 1), portrait)[1:] == (640, 1138)


@needs_ffmpeg
def test_sample_frames_raises_when_ffmpeg_fails(tmp_path, monkeypatch, synth_video):
    v = synth_video(2)
    monkeypatch.setattr(vision, "FFMPEG", "/usr/bin/false")
    with pytest.raises(FFmpegError):
        list(sample_frames(v, Span(0.0, 2.0)))


@needs_ffmpeg
def test_sample_frames_early_stop_is_not_an_error(synth_video):
    frames = sample_frames(synth_video(4), Span(0.0, 4.0))
    next(frames)
    frames.close()  # consumer stops: ffmpeg gets SIGPIPE, no exception


@needs_ffmpeg
def test_sample_frames_rate_size_and_blank_detection(tmp_path):
    blank = tmp_path / "blank.mp4"
    run([FFMPEG, "-y", "-v", "error", "-f", "lavfi", "-i", "color=white:s=1280x720:d=2:r=30",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(blank)])
    frames = list(sample_frames(blank, Span(0.0, 2.0)))
    assert len(frames) == 6
    t, bgra, w, h = frames[-1]
    assert (w, h) == (640, 360) and len(bgra) == 640 * 360 * 4
    assert t == pytest.approx(5 / 3)
    bodies, faces = detect(bgra, w, h, False, (1280, 720))
    assert bodies == [] and faces == []


def test_finds_the_speaker_in_the_real_sample(sample):
    info = probe(sample)  # 1920x1080 HEVC .mov on Natã's machine
    hits = total = 0
    for _, bgra, w, h in sample_frames(sample, Span(60.0, 90.0)):
        bodies, _ = detect(bgra, w, h, False, (info.width, info.height))
        total += 1
        hits += bool(bodies)
    assert total in (89, 90, 91)
    assert hits / total >= 0.7
