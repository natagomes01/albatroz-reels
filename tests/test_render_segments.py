from pathlib import Path

import pytest

from conftest import needs_ffmpeg
from shorts.audio import loudnorm_measure
from shorts.ffmpeg import FFMPEG, probe, run
from shorts.render import RenderInputs, render_clip
from shorts.shots import Crop
from shorts.timeline import Span, group_edl

REPO = Path(__file__).resolve().parents[1]


def pixel(video: Path, frame: int, x: int, y: int) -> tuple[int, int, int]:
    out = run([FFMPEG, "-v", "error", "-i", str(video), "-vf",
               f"select='eq(n,{frame})',format=rgb24,crop=1:1:{x}:{y}",
               "-frames:v", "1", "-f", "rawvideo", "-"], capture_stdout=True).stdout
    return tuple(out)


def clock_video(tmp_path: Path) -> Path:
    """Blue channel = 20 x seconds, so each output frame tells which class time it came from."""
    out = tmp_path / "clock.mp4"
    run([FFMPEG, "-y", "-v", "error",
         "-f", "lavfi", "-i", "nullsrc=s=1280x720:r=30:d=10,geq=r='X/5':g='Y/3':b='T*20'",
         "-f", "lavfi", "-i", "sine=f=300:d=10:sample_rate=44100",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(out)])
    return out


def test_group_edl_follows_segments_in_playback_order():
    edl = [Span(6.0, 7.0), Span(7.5, 8.0), Span(1.0, 3.0)]
    groups = group_edl(edl, [Span(6.0, 8.0), Span(1.0, 3.0)])
    assert groups == [(Span(6.0, 8.0), edl[:2]), (Span(1.0, 3.0), edl[2:])]
    assert group_edl(edl[:2]) == [(Span(6.0, 8.0), edl[:2])]
    with pytest.raises(ValueError, match="outside"):
        group_edl(edl, [Span(6.0, 8.0)])
    # build_edl snaps a segment's end to its frame grid, up to half a frame past the raw end
    snapped = [Span(1.0, 3.016667)]
    assert group_edl(snapped, [Span(1.0, 3.01)]) == [(Span(1.0, 3.016667), snapped)]


@needs_ffmpeg
def test_out_of_order_segments_render_in_playback_order(tmp_path):
    v = clock_video(tmp_path)
    segs = [Span(6.0, 8.0), Span(1.0, 3.0)]
    out = render_clip(
        RenderInputs(master=v, info=probe(v), edl=list(segs), crops=[Crop(438, 0, 404, 720)] * 120,
                     ass_path=None, fonts_dir=REPO / "assets" / "fonts", grade=None, audio_measured=None,
                     sound=False, safe_zone=None, out=tmp_path / "o.mp4", segments=segs),
        tmp_path / "w",
    )
    assert probe(out).duration == pytest.approx(4.0, abs=0.05)
    first, late = pixel(out, 5, 540, 900)[2], pixel(out, 90, 540, 900)[2]
    assert abs(first - 6.2 * 20) <= 12, first     # frame 5 comes from class time ~6.2 s
    assert abs(late - 2.0 * 20) <= 12, late       # frame 90 comes from class time ~2.0 s


@needs_ffmpeg
def test_loudnorm_measure_reads_each_segment(tmp_path):
    v = clock_video(tmp_path)
    segs = [Span(6.0, 8.0), Span(1.0, 3.0)]
    measured = loudnorm_measure(v, list(segs), segs)
    assert float(measured["input_i"]) < 0
