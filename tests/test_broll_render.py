import subprocess
from pathlib import Path

import pytest

from conftest import needs_ffmpeg
from shorts.broll.graph import BrollInsert, cover_size, input_args, layer_chain, overlay_graph, pan_path
from shorts.ffmpeg import FFMPEG, probe, run
from shorts.render import RenderInputs, _quote, build_render, render_clip
from shorts.shots import Crop
from shorts.timeline import Span

REPO = Path(__file__).resolve().parents[1]


def ins(**kw):
    base = dict(start=1.0, end=4.0, kind="image", file=Path("/x/a.jpg"), layout="full", fit="cover",
                pan="ltr", focus=(0.5, 0.5), w=1600, h=900)
    base.update(kw)
    return BrollInsert(**base)


def test_cover_size_is_even_and_covers():
    assert cover_size(1600, 900, 1080, 1920) == (3414, 1920)
    assert cover_size(900, 1600, 1080, 960) == (1080, 1920)


def test_pan_path_is_centred_on_the_focus_and_clamped():
    assert pan_path(ins(), 40) == pytest.approx((1107.0, 1227.0, 0.0, 0.0))
    assert pan_path(ins(pan="rtl"), 40) == pytest.approx((1227.0, 1107.0, 0.0, 0.0))
    assert pan_path(ins(focus=(0.0, 0.5)), 40) == pytest.approx((0.0, 120.0, 0.0, 0.0))
    assert pan_path(ins(focus=(1.0, 0.5)), 40) == pytest.approx((2214.0, 2334.0, 0.0, 0.0))
    assert pan_path(ins(pan="still"), 40) == pytest.approx((1167.0, 1167.0, 0.0, 0.0))
    assert pan_path(ins(kind="video"), 40)[0] == pan_path(ins(kind="video"), 40)[1]
    tall = ins(w=900, h=1600, layout="split", pan="ttb")      # 1080x1920 scaled, 960 overflow
    assert pan_path(tall, 40) == pytest.approx((0.0, 0.0, 420.0, 540.0))
    assert pan_path(ins(pan="ltr"), 4000)[:2] == pytest.approx((0.0, 2334.0))   # path never leaves the image


def test_layer_chains():
    cover = layer_chain(ins(), 5, 0, 30, 40)
    assert len(cover) == 1 and cover[0].startswith("[5:v:0]scale=3414:1920:flags=lanczos,format=rgb24,crop=1080:1920:")
    assert "x='1107.00+40.0000*t'" in cover[0] and cover[0].endswith("setpts=PTS-STARTPTS+1.0000/TB[b0]")
    whole = layer_chain(ins(fit="whole", layout="split"), 6, 1, 30, 40)
    assert whole[0] == "[6:v:0]split=2[bg1][fg1]" and "gblur=sigma=40" in whole[1]
    assert "force_original_aspect_ratio=decrease" in whole[2] and whole[3].endswith("[b1]")
    assert input_args(ins(), 30) == ["-loop", "1", "-framerate", "30", "-t", "3.000", "-i", str(Path("/x/a.jpg"))]
    assert input_args(ins(kind="video"), 30) == ["-t", "3.000", "-an", "-i", str(Path("/x/a.jpg"))]


def test_overlay_graph_full_and_split():
    lines, tail = overlay_graph([ins(), ins(start=5.0, end=7.0, layout="split", split_top=250)], 4, "[vb]", 30, 40)
    assert tail == "[o1]"
    assert "[vb][b0]overlay=x=0:y=0:enable='gte(t,0.9995)*lt(t,3.9995)':eof_action=pass[o0]" in lines
    assert "[o0]split=2[m1][s1]" in lines and "[s1]crop=1080:960:0:250[sp1]" in lines
    assert "[m1][sp1]overlay=x=0:y=960:enable='gte(t,4.9995)*lt(t,6.9995)'[mm1]" in lines
    assert lines[-1] == "[mm1][b1]overlay=x=0:y=0:enable='gte(t,4.9995)*lt(t,6.9995)':eof_action=pass[o1]"


def make_inputs(v, tmp_path, broll=(), name="o.mp4", ass=None, pan=40.0):
    crops = [Crop(438, 0, 404, 720)] * 120
    return RenderInputs(master=v, info=probe(v), edl=[Span(0.0, 4.0)], crops=crops, ass_path=ass,
                        fonts_dir=REPO / "assets" / "fonts", grade=None, audio_measured=None,
                        sound=False, safe_zone=None, out=tmp_path / name, broll=tuple(broll),
                        pan_px_per_s=pan)


def test_an_empty_broll_keeps_the_graph_and_command(tmp_path):
    v = tmp_path / "v.mp4"
    v.write_bytes(b"")
    from shorts.ffmpeg import VideoInfo
    info = VideoInfo(1280, 720, 30.0, 6.0, "bt709", False)
    base = dict(master=v, info=info, edl=[Span(0.0, 4.0)], crops=[Crop(438, 0, 404, 720)] * 120,
                ass_path=None, fonts_dir=REPO / "assets" / "fonts", grade=None, audio_measured=None,
                sound=False, safe_zone=None, out=tmp_path / "o.mp4")
    a = build_render(RenderInputs(**base), tmp_path / "w1")
    g1 = (tmp_path / "w1" / "graph.txt").read_text(encoding="utf-8")
    b = build_render(RenderInputs(**base, broll=()), tmp_path / "w2")
    assert [x.replace(str(tmp_path / "w1"), str(tmp_path / "w2")) for x in a] == b
    g2 = (tmp_path / "w2" / "graph.txt").read_text(encoding="utf-8")
    assert g1.replace(_quote(tmp_path / "w1")[1:-1], _quote(tmp_path / "w2")[1:-1]) == g2


def still(tmp_path, name, expr_or_color, size):
    out = tmp_path / name
    src = (f"color={expr_or_color}:s={size}:d=1" if "=" not in expr_or_color
           else f"nullsrc=s={size}:d=1,{expr_or_color}")
    subprocess.run([FFMPEG, "-v", "error", "-f", "lavfi", "-i", src, "-frames:v", "1", str(out)], check=True)
    return out


def pixel(video: Path, frame: int, x: int, y: int):
    return tuple(run([FFMPEG, "-v", "error", "-i", str(video), "-vf",
                      f"select='eq(n,{frame})',format=rgb24,crop=1:1:{x}:{y}",
                      "-frames:v", "1", "-f", "rawvideo", "-"], capture_stdout=True).stdout)


def near(a, b, tol=12):
    return all(abs(x - y) <= tol for x, y in zip(a, b))


@needs_ffmpeg
def test_a_full_screen_still_covers_only_its_moment(synth_video, tmp_path):
    v = synth_video(6)
    red = still(tmp_path, "red.png", "red", "1600x900")
    out = render_clip(make_inputs(v, tmp_path, [ins(start=1.0, end=2.0, file=red, pan="still")]), tmp_path / "w")
    assert near(pixel(out, 45, 540, 300), (255, 0, 0))
    assert not near(pixel(out, 15, 540, 300), (255, 0, 0)) and not near(pixel(out, 75, 540, 300), (255, 0, 0))
    graph = (tmp_path / "w" / "graph.txt").read_text(encoding="utf-8")
    assert graph.index("eof_action=pass[o0]") < graph.index("format=yuv420p[v]")


@needs_ffmpeg
def test_captions_are_burned_over_the_broll(synth_video, tmp_path):
    v = synth_video(6)
    red = still(tmp_path, "red.png", "red", "1600x900")
    ass = tmp_path / "c.ass"
    ass.write_text("[Script Info]\n", encoding="utf-8")          # only the graph is checked here
    build_render(make_inputs(v, tmp_path, [ins(start=1.0, end=2.0, file=red, pan="still")], ass=ass), tmp_path / "w")
    graph = (tmp_path / "w" / "graph.txt").read_text(encoding="utf-8")
    assert graph.index("eof_action=pass[o0]") < graph.index("[o0]subtitles=")


@needs_ffmpeg
def test_split_puts_the_image_on_top_and_the_speaker_below(synth_video, tmp_path):
    v = synth_video(6)
    red = still(tmp_path, "red.png", "red", "1600x900")
    plain = render_clip(make_inputs(v, tmp_path, name="plain.mp4"), tmp_path / "w0")
    out = render_clip(make_inputs(v, tmp_path, [ins(start=1.0, end=2.0, file=red, layout="split",
                                                   pan="still", split_top=300)]), tmp_path / "w")
    assert near(pixel(out, 45, 540, 400), (255, 0, 0))
    assert near(pixel(out, 45, 540, 1500), pixel(plain, 45, 540, 1500 - 960 + 300))
    assert near(pixel(out, 75, 540, 1500), pixel(plain, 75, 540, 1500))      # after the moment


@needs_ffmpeg
def test_a_still_pans_at_the_set_speed(synth_video, tmp_path):
    v = synth_video(6)
    ramp = still(tmp_path, "ramp.png", "geq=r='X*255/1600':g=0:b=0", "1600x900")
    i = ins(start=0.5, end=3.5, file=ramp, pan="ltr")
    out = render_clip(make_inputs(v, tmp_path, [i], pan=400.0), tmp_path / "w")
    x0, x1, _, _ = pan_path(i, 400.0)
    s = cover_size(1600, 900, 1080, 1920)[0] / 1600

    def expected(local):
        return (x0 + (x1 - x0) * local / 3.0 + 540) / s * 255 / 1600
    for frame in (18, 102):
        assert abs(pixel(out, frame, 540, 960)[0] - expected(frame / 30 - 0.5)) <= 8


@needs_ffmpeg
def test_whole_shows_the_image_on_a_darker_blurred_band(synth_video, tmp_path):
    v = synth_video(6)
    green = still(tmp_path, "g.png", "green", "1200x1200")
    out = render_clip(make_inputs(v, tmp_path, [ins(start=1.0, end=2.0, file=green, fit="whole",
                                                   pan="still", w=1200, h=1200)]), tmp_path / "w")
    centre, band = pixel(out, 45, 540, 960), pixel(out, 45, 540, 150)
    assert centre[1] > 100 and band[1] > 60 and centre[1] - band[1] >= 8


@needs_ffmpeg
def test_a_video_insert_ends_with_its_moment(synth_video, tmp_path):
    v = synth_video(6)
    blue = tmp_path / "blue.mp4"
    subprocess.run([FFMPEG, "-v", "error", "-f", "lavfi", "-i", "color=blue:s=1920x1080:d=3:r=30",
                    "-pix_fmt", "yuv420p", str(blue)], check=True)
    out = render_clip(make_inputs(v, tmp_path, [ins(start=1.0, end=2.0, file=blue, kind="video",
                                                   pan="still", w=1920, h=1080)]), tmp_path / "w")
    assert near(pixel(out, 45, 540, 300), (0, 0, 255), tol=30)
    assert not near(pixel(out, 70, 540, 300), (0, 0, 255), tol=30)
    assert probe(out).duration == pytest.approx(4.0, abs=0.05)
