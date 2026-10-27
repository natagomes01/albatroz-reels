import json
from pathlib import Path

import pytest

from conftest import needs_ffmpeg
from shorts.audio import loudnorm_measure
from shorts.ffmpeg import FFMPEG, FFPROBE, probe, run
from shorts.render import RenderInputs, render_clip
from shorts.shots import Crop
from shorts.timeline import Span, TimeMap


REPO = Path(__file__).resolve().parents[1]


def pixel(video: Path, frame: int, x: int, y: int) -> tuple[int, int, int]:
    out = run([FFMPEG, "-v", "error", "-i", str(video), "-vf",
               f"select='eq(n,{frame})',format=rgb24,crop=1:1:{x}:{y}",
               "-frames:v", "1", "-f", "rawvideo", "-"], capture_stdout=True).stdout
    return tuple(out)


@needs_ffmpeg
def test_crop_mechanism_sendcmd_and_overlay(synth_video, tmp_path):
    """Spike turned regression test: per-frame x via sendcmd on two fixed-size crops."""
    v = synth_video(6)
    edl = [Span(0.5, 2.5), Span(3.5, 5.5)]
    crops = [Crop(int(i * 800 / 59), 0, 404, 720) for i in range(60)] + [Crop(400, 100, 290, 514)] * 60
    out = render_clip(
        RenderInputs(master=v, info=probe(v), edl=edl, crops=crops, ass_path=None,
                     fonts_dir=REPO / "assets" / "fonts", grade=None, audio_measured=None,
                     sound=False, safe_zone=None, out=tmp_path / "c.mp4"),
        tmp_path / "work",
    )
    info = probe(out)
    assert (info.width, info.height) == (1080, 1920)
    assert info.duration == pytest.approx(4.0, abs=0.05)
    # red channel encodes source x / 5 at the centre of the output: it must follow the crop
    red = [pixel(out, f, 540, 300)[0] for f in (5, 30, 55)]
    expected = [(crops[f].x + 202) / 5 for f in (5, 30, 55)]
    assert all(abs(r - e) <= 10 for r, e in zip(red, expected)), (red, expected)
    # frame 90 is the close-up: source x 400..690 -> centre 545 -> red ~109
    assert abs(pixel(out, 90, 540, 300)[0] - 109) <= 6


@needs_ffmpeg
def test_first_frame_of_second_close_up_is_exact(synth_video, tmp_path):
    """Review C3: frame 62 (t = 2.0667 s) starts a close-up at a new x. With sendcmd times
    rounded up, frame 62 would still show the first close-up's window (red ~49)."""
    v = synth_video(4)
    close_a, wide, close_b = Crop(100, 100, 290, 514), Crop(438, 0, 404, 720), Crop(700, 100, 290, 514)
    crops = [close_a] * 31 + [wide] * 31 + [close_b] * 30
    out = render_clip(
        RenderInputs(master=v, info=probe(v), edl=[Span(0.0, 92 / 30)], crops=crops, ass_path=None,
                     fonts_dir=REPO / "assets" / "fonts", grade=None, audio_measured=None,
                     sound=False, safe_zone=None, out=tmp_path / "cc.mp4"),
        tmp_path / "work",
    )
    assert abs(pixel(out, 62, 540, 300)[0] - (700 + 145) / 5) <= 6  # ~169, not ~49
    assert abs(pixel(out, 61, 540, 300)[0] - (438 + 202) / 5) <= 10  # still wide one frame before


@needs_ffmpeg
def test_render_with_captions_sound_and_safe_zone(synth_video, tmp_path):
    from shorts.captions import CaptionStyle, build_screens, render_ass
    from shorts.words import Word

    v = synth_video(6)
    edl = [Span(0.5, 5.5)]
    tm = TimeMap(edl)
    words = [Word(0.6 + i * 0.4, w, 1.0) for i, w in enumerate("Não é óbvio? Aí você vai ter uma corrente".split())]
    ass = tmp_path / "c.ass"
    ass.write_text(render_ass(words, build_screens(words, "pt"), tm, CaptionStyle(), tm.duration), encoding="utf-8")
    zone = tmp_path / "zone.png"
    run([FFMPEG, "-y", "-v", "error", "-f", "lavfi", "-i", "color=0xFFAD80:s=1080x1920",
         "-vf", "drawbox=x=70:y=250:w=955:h=832:color=white:t=fill", "-frames:v", "1", str(zone)])
    crops = [Crop(438, 0, 404, 720)] * 150
    out = render_clip(
        RenderInputs(master=v, info=probe(v), edl=edl, crops=crops, ass_path=ass,
                     fonts_dir=REPO / "assets" / "fonts", grade=None,
                     audio_measured=loudnorm_measure(v, edl), sound=True, safe_zone=zone,
                     out=tmp_path / "z.mp4"),
        tmp_path / "work",
    )
    streams = json.loads(run([FFPROBE, "-v", "error", "-show_streams",
                              "-print_format", "json", str(out)], capture_stdout=True).stdout)["streams"]
    audio = next(s for s in streams if s["codec_type"] == "audio")
    video = next(s for s in streams if s["codec_type"] == "video")
    assert audio["sample_rate"] == "48000" and video["codec_name"] == "h264" and video["pix_fmt"] == "yuv420p"
    # green encodes source y/3: y=100 -> ~12 untouched; the orange overlay (G=173, 50%) lifts it
    top, inside = pixel(out, 10, 540, 100), pixel(out, 10, 540, 600)
    assert top[1] > 60, top
    assert abs(inside[1] - 75) <= 15, inside  # y=600 -> source y 225 -> green 75, not covered
