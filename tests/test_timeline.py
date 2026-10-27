import pytest

from conftest import needs_ffmpeg
from shorts.silence import detect_silences, parse_silencedetect
from shorts.timeline import Span, TimeMap, build_edl
from shorts.words import Word


def test_edl_rules():
    words = [Word(104.0, "óbvio?", 1), Word(109.0, "x", 1)]
    assert build_edl([Span(100, 120)], [Span(105.0, 106.5), Span(110, 110.5)], words) == [Span(100, 105.4), Span(106.1, 120)]
    assert build_edl([Span(100, 120)], [Span(107, 109)], words) == [Span(100, 107.4), Span(108.6, 120)]
    # 111.25 and 112.75 are not on the 1/30 s grid: they snap to the nearest frame
    assert build_edl([Span(100, 120)], [Span(111, 113)], words) == [
        Span(100, round(100 + 338 / 30, 6)), Span(round(100 + 383 / 30, 6), 120)]
    assert build_edl([Span(100, 105), Span(200, 203)], [], words) == [Span(100, 105), Span(200, 203)]


def test_edl_boundaries_sit_on_the_frame_grid():
    words = [Word(0.5, "a", 1)]
    seg = Span(10.013, 40.0)
    sil = [Span(12.111, 13.777), Span(20.2049, 22.0), Span(30.0, 31.3333)]
    for span in build_edl([seg], sil, words):
        for edge in (span.start, span.end):
            frames = (edge - seg.start) * 30
            assert abs(frames - round(frames)) < 1e-4


def test_timemap():
    tm = TimeMap([Span(100, 107.4), Span(108.6, 120)])
    assert tm.duration == pytest.approx(18.8)
    assert tm.cut_points() == [pytest.approx(7.4)]
    assert tm.to_clip(108) is None
    assert tm.to_clip(110) == pytest.approx(8.8)
    assert tm.to_class(7.5) == pytest.approx(108.7)
    assert tm.snap_to_clip(108) == pytest.approx(7.4)


def test_silencedetect_parse():
    err = "[silencedetect] silence_start: 1.5\n[silencedetect] silence_end: 2.7 | silence_duration: 1.2\n[silencedetect] silence_start: 9.0\n"
    assert parse_silencedetect(err, 100.0, end=110.0) == [Span(101.5, 102.7), Span(109.0, 110.0)]


@needs_ffmpeg
def test_detect_silences_on_synthetic(synth_video):
    v = synth_video(12, silent=(4, 6))
    sil = detect_silences(v, Span(1.0, 11.0))
    assert len(sil) == 1
    assert sil[0].start == pytest.approx(4.0, abs=0.1) and sil[0].end == pytest.approx(6.0, abs=0.1)


def test_blank_word_before_silence_is_not_a_question():
    words = [Word(104.0, "", 1), Word(109.0, "x", 1)]
    assert build_edl([Span(100, 120)], [Span(105.0, 106.5)], words) == [Span(100, 105.266667), Span(106.266667, 120.0)]
