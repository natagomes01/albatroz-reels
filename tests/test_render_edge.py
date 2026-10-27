import json
from dataclasses import replace
from pathlib import Path

import pytest

from conftest import needs_ffmpeg
from shorts.captions import CaptionStyle, build_screens, render_ass
from shorts.color import NEUTRAL
from shorts.ffmpeg import FFMPEG, FFPROBE, VideoInfo, probe, run
from shorts.render import RenderInputs, _quote, build_render, render_clip
from shorts.shots import Crop
from shorts.timeline import Span, TimeMap
from shorts.words import Word
from test_render import pixel

REPO = Path(__file__).resolve().parents[1]


def test_quote_rejects_single_quote():
    with pytest.raises(ValueError, match="single quote"):
        _quote(Path("/tmp/it's.ass"))


@needs_ffmpeg
def test_paths_with_spaces(synth_video, tmp_path):
    v = synth_video(3)
    work = tmp_path / "job with space"
    work.mkdir()
    words = [Word(0.2 + i * 0.4, w, 1.0) for i, w in enumerate("Não é óbvio?".split())]
    tm = TimeMap([Span(0.0, 3.0)])
    ass = work / "captions file.ass"
    ass.write_text(render_ass(words, build_screens(words, "pt"), tm, CaptionStyle(), 3.0), encoding="utf-8")
    out = render_clip(RenderInputs(master=v, info=probe(v), edl=[Span(0.0, 3.0)], crops=[Crop(438, 0, 404, 720)] * 90,
                                   ass_path=ass, fonts_dir=REPO / "assets" / "fonts", grade=None, audio_measured=None,
                                   sound=False, safe_zone=None, out=work / "out clip.mp4"), work)
    assert probe(out).duration == pytest.approx(3.0, abs=0.05)


def _inputs(master, info, out, crops, grade=None):
    return RenderInputs(master=master, info=info, edl=[Span(0.0, len(crops) / 30)], crops=crops,
                        ass_path=None, fonts_dir=REPO / "assets" / "fonts", grade=grade, audio_measured=None,
                        sound=False, safe_zone=None, out=out)


def _mean_luma(video: Path, frame: int) -> float:
    raw = run([FFMPEG, "-v", "error", "-i", str(video), "-vf", f"select='eq(n,{frame})',format=gray",
               "-frames:v", "1", "-f", "rawvideo", "-"], capture_stdout=True).stdout
    return sum(raw) / len(raw)


def _hlg(tmp_path: Path) -> Path:
    hdr = tmp_path / "hdr.mov"
    run([FFMPEG, "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=1280x720:r=30:d=2",
         "-vf", "setparams=color_primaries=bt2020:color_trc=arib-std-b67:colorspace=bt2020nc",
         "-c:v", "libx265", "-pix_fmt", "yuv420p10le", "-color_primaries", "bt2020",
         "-color_trc", "arib-std-b67", "-colorspace", "bt2020nc", "-tag:v", "hvc1", str(hdr)])
    return hdr


def test_hdr_render_command_tone_maps(tmp_path):
    """Review C2: the output flags force bt709 tags either way, so check the graph itself."""
    crops = [Crop(438, 0, 404, 720)] * 30
    sdr = VideoInfo(1280, 720, 30.0, 2.0, "bt709", False)
    build_render(_inputs(Path("m.mov"), sdr, tmp_path / "a.mp4", crops), tmp_path / "a")
    assert "tonemap=" not in (tmp_path / "a" / "graph.txt").read_text(encoding="utf-8")
    build_render(_inputs(Path("m.mov"), replace(sdr, color_transfer="arib-std-b67"), tmp_path / "b.mp4", crops),
                 tmp_path / "b")
    graph = (tmp_path / "b" / "graph.txt").read_text(encoding="utf-8")
    # tone-map after the crop (per branch), never before select: review M1
    assert "tonemap=" in graph and graph.index("select=") < graph.index("crop@wide") < graph.index("tonemap=")
    assert "[0:v:0]" in graph and "[0:v]" not in graph


@needs_ffmpeg
def test_hdr_branch_changes_pixels(tmp_path):
    """The same HLG source rendered with and without the HDR branch must differ visibly:
    deleting the is_hdr branch makes this test fail."""
    hdr = _hlg(tmp_path)
    info = probe(hdr)
    assert info.is_hdr
    crops = [Crop(438, 0, 404, 720)] * 60
    mapped = render_clip(_inputs(hdr, info, tmp_path / "mapped.mp4", crops), tmp_path / "w1")
    raw = render_clip(_inputs(hdr, replace(info, color_transfer="bt709"), tmp_path / "raw.mp4", crops), tmp_path / "w2")
    stream = json.loads(run([FFPROBE, "-v", "error", "-show_streams", "-print_format", "json", str(mapped)],
                            capture_stdout=True).stdout)["streams"][0]
    assert stream["color_transfer"] == "bt709" and stream["pix_fmt"] == "yuv420p"
    assert abs(_mean_luma(mapped, 30) - _mean_luma(raw, 30)) > 3


@needs_ffmpeg
def test_mov_with_data_stream_renders(synth_video, tmp_path):
    """iPhone masters carry extra data streams: only 0:v:0 and 0:a:0 may be mapped."""
    v = synth_video(3, ext="mov", data_stream=True)
    out = render_clip(_inputs(v, probe(v), tmp_path / "mov.mp4", [Crop(438, 0, 404, 720)] * 90), tmp_path / "w")
    types = {s["codec_type"] for s in json.loads(run(
        [FFPROBE, "-v", "error", "-show_streams", "-print_format", "json", str(out)], capture_stdout=True).stdout)["streams"]}
    assert types == {"video", "audio"}


@needs_ffmpeg
def test_neutral_grade_keeps_colors(tmp_path):
    """The RGB<->YUV conversions around colorlevels are explicit bt709: a neutral grade must not
    shift saturated colors (a bt601/bt709 mix-up moves them by 10+ levels)."""
    bars = tmp_path / "bars.mp4"
    run([FFMPEG, "-y", "-v", "error", "-f", "lavfi", "-i", "smptehdbars=s=1280x720:r=30:d=1",
         "-vf", "setparams=colorspace=bt709:color_primaries=bt709:color_trc=bt709",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-colorspace", "bt709", "-color_primaries", "bt709",
         "-color_trc", "bt709", str(bars)])
    crops = [Crop(438, 0, 404, 720)] * 30
    plain = render_clip(_inputs(bars, probe(bars), tmp_path / "plain.mp4", crops), tmp_path / "w1")
    graded = render_clip(_inputs(bars, probe(bars), tmp_path / "graded.mp4", crops, grade=NEUTRAL), tmp_path / "w2")
    for x in (100, 400, 700, 1000):
        a, b = pixel(plain, 15, x, 500), pixel(graded, 15, x, 500)
        # saturation=1.05 in the grade moves colors a little; a matrix error moves them a lot
        assert max(abs(i - j) for i, j in zip(a, b)) <= 12, (x, a, b)


def test_temp_render_removed_on_interrupt(tmp_path, monkeypatch):
    import shorts.render as render

    def boom(cmd):
        Path(cmd[-1]).write_bytes(b"partial")
        raise KeyboardInterrupt

    monkeypatch.setattr(render, "run", boom)
    out = tmp_path / "x.mp4"
    with pytest.raises(KeyboardInterrupt):
        render_clip(_inputs(Path("m.mov"), VideoInfo(1280, 720, 30.0, 1.0, "bt709", False), out,
                            [Crop(438, 0, 404, 720)] * 30), tmp_path / "w")
    assert not Path(str(out) + ".tmp.mp4").exists() and not out.exists()
