from pathlib import Path

import pytest

from conftest import needs_ffmpeg
from shorts.audio import audio_filter, loudnorm_measure, select_expr
from shorts.color import (NEUTRAL, Grade, frames_command, grade_filter, grade_from_stats,
                          interpolate_grade, measure_points)
from shorts.timeline import Span


def test_grade_warm_dim_frame():
    values = [20 + int(130 * (k / 100) ** 2) for k in range(101)]  # mostly dark
    px = [(min(255, int(v * 1.15)), v, int(v * 0.8)) for v in values] * 10
    g = grade_from_stats(px)
    assert g.rimax > g.gimax > g.bimax  # warm cast: less gain on red, more on blue
    assert g.gamma > 1.0  # dim: brighten mid-tones
    f = grade_filter(g)
    assert f.startswith("scale=in_color_matrix=bt709") and "colorlevels=rimin=" in f
    assert "out_color_matrix=bt709" in f and f.endswith(":saturation=1.05")


def test_frames_command_tone_maps_hdr_and_maps_first_video():
    sdr = frames_command(Path("m.mov"), 12.0, hdr=False)
    hdr = frames_command(Path("m.mov"), 12.0, hdr=True)
    assert "0:v:0" in sdr and "tonemap=" not in sdr[sdr.index("-vf") + 1]
    vf = hdr[hdr.index("-vf") + 1]
    assert vf.index("tonemap=") < vf.index("scale=64:36")


def test_interpolate_grade():
    a, b = Grade(0, 0, 0, 1, 1, 1, 1.0), Grade(0.1, 0.1, 0.1, 0.8, 0.8, 0.8, 1.2)
    mid = interpolate_grade([(0, a), (600, b)], 300)
    assert mid.rimin == pytest.approx(0.05) and mid.gamma == pytest.approx(1.1)
    assert interpolate_grade([(0, a), (600, b)], 900) == b
    assert interpolate_grade([], 5) == NEUTRAL


def test_select_expr_is_half_open():
    assert select_expr([Span(10, 12), Span(13, 15)], 10) == "gte(t,0.000)*lt(t,2.000)+gte(t,3.000)*lt(t,5.000)"


def test_audio_filter():
    assert audio_filter(None) == "highpass=f=70,afftdn=nr=6:nf=-45,loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000"
    m = {"input_i": "-21.8", "input_tp": "-3.4", "input_lra": "4.2", "input_thresh": "-32.1", "target_offset": "0.3"}
    assert "measured_I=-21.8:measured_TP=-3.4:measured_LRA=4.2:measured_thresh=-32.1:offset=0.3:linear=true" in audio_filter(m)


@needs_ffmpeg
def test_color_points_and_loudnorm(synth_video):
    v = synth_video(6)
    points = measure_points(v, 6.0)
    assert len(points) == 1 and points[0][0] == 0.0
    m = loudnorm_measure(v, [Span(0.5, 2.5), Span(3.5, 5.5)])
    assert float(m["input_i"]) < -10


@needs_ffmpeg
def test_measure_points_tone_maps_hdr_first(synth_video):
    """The same gradient tagged HLG must measure differently from its SDR twin: proof the
    measurement looks at the tone-mapped image, not the raw HLG code values."""
    sdr = measure_points(synth_video(4), 4.0)[0][1]
    hdr = measure_points(synth_video(4, ext="mov", data_stream=True, hlg=True), 4.0)[0][1]
    assert abs(hdr.gamma - sdr.gamma) > 0.02 or abs(hdr.rimax - sdr.rimax) > 0.02
