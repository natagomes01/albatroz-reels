from pathlib import Path

from conftest import needs_ffmpeg
from shorts.ffmpeg import FFMPEG, probe, run
from shorts.preview import track_preview
from shorts.shots import Crop
from shorts.timeline import Span
from shorts.vision import Box


def pixel(video: Path, frame: int, x: int, y: int) -> tuple[int, int, int]:
    out = run([FFMPEG, "-v", "error", "-i", str(video), "-vf",
               f"select='eq(n,{frame})',format=rgb24,crop=1:1:{x}:{y}",
               "-frames:v", "1", "-f", "rawvideo", "-"], capture_stdout=True).stdout
    return tuple(out)


@needs_ffmpeg
def test_preview_draws_crop_window_and_body_box(synth_video, tmp_path):
    v = synth_video(3)
    edl = [Span(0.0, 3.0)]
    crops = [Crop(438, 0, 404, 720)] * 90
    bodies = [Box(600, 100, 150, 500)] * 45 + [None] * 45
    out = track_preview(v, probe(v), edl, list(edl), crops, bodies, tmp_path / "p.mp4")
    assert probe(out).width == 640
    crop_edge = pixel(out, 30, 221, 180)       # source x 438..448 -> preview 219..224
    body_edge = pixel(out, 30, 302, 150)       # source x 600..610 -> preview 300..305
    assert crop_edge[1] > 180 and crop_edge[0] < 110, crop_edge   # lime
    assert body_edge[0] > 180 and body_edge[1] < 110, body_edge   # red
    gone = pixel(out, 75, 302, 150)            # body lost: no red box drawn
    assert gone[0] < 180, gone


def test_preview_rejects_empty_crops(tmp_path):
    import pytest
    from shorts.ffmpeg import VideoInfo
    info = VideoInfo(width=1280, height=720, fps=30.0, duration=3.0, color_transfer="bt709", has_audio=False)
    with pytest.raises(ValueError, match="at least one"):
        track_preview(tmp_path / "m.mp4", info, [Span(0.0, 3.0)], None, [], [], tmp_path / "p.mp4")


@needs_ffmpeg
def test_preview_is_atomic(synth_video, tmp_path, monkeypatch):
    import pytest
    from shorts import preview
    from shorts.ffmpeg import FFmpegError
    v = synth_video(1)
    edl = [Span(0.0, 1.0)]
    crops = [Crop(438, 0, 404, 720)] * 30
    bodies = [None] * 30
    out = tmp_path / "p.mp4"

    def failing(cmd):
        Path(cmd[-1]).write_bytes(b"partial")
        raise FFmpegError(cmd, "boom")

    monkeypatch.setattr(preview, "run", failing)
    with pytest.raises(FFmpegError):
        track_preview(v, probe(v), edl, None, crops, bodies, out)
    assert not out.exists() and not Path(str(out) + ".tmp.mp4").exists()
    monkeypatch.undo()
    track_preview(v, probe(v), edl, None, crops, bodies, out)
    assert out.exists() and not Path(str(out) + ".tmp.mp4").exists()
