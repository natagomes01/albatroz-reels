import pytest

from conftest import needs_ffmpeg
from shorts.ffmpeg import parse_probe, probe


def test_parse_probe_hdr():
    data = {"streams": [{"codec_type": "video", "width": 3840, "height": 2160, "avg_frame_rate": "30000/1001",
                         "color_transfer": "arib-std-b67"}, {"codec_type": "audio"}], "format": {"duration": "12.5"}}
    info = parse_probe(data)
    assert info.is_hdr and info.has_audio and info.fps == pytest.approx(29.97, abs=0.01)


def test_parse_probe_iphone_mov_with_data_streams():
    # Shape of the real master (ffprobe of 260927-catequese-permanente-1.mov, trimmed).
    data = {"streams": [
        {"index": 0, "codec_type": "video", "codec_name": "hevc", "width": 1920, "height": 1080,
         "color_transfer": "bt709", "r_frame_rate": "30/1", "avg_frame_rate": "27253350/908537"},
        {"index": 1, "codec_type": "audio", "codec_name": "aac", "sample_rate": "48000", "channels": 1},
        {"index": 2, "codec_type": "data"}, {"index": 3, "codec_type": "data"},
        {"index": 4, "codec_type": "data"}, {"index": 5, "codec_type": "data"},
    ], "format": {"duration": "6056.913333"}}
    info = parse_probe(data)
    assert (info.width, info.height, info.is_hdr, info.has_audio, info.rotation) == (1920, 1080, False, True, 0)
    assert info.fps == pytest.approx(29.997, abs=0.001)


def test_parse_probe_rotation_swaps_size():
    side = {"streams": [{"codec_type": "video", "width": 1920, "height": 1080, "avg_frame_rate": "30/1",
                         "side_data_list": [{"side_data_type": "Display Matrix", "rotation": -90}]}],
            "format": {"duration": "5"}}
    info = parse_probe(side)
    assert (info.width, info.height, info.rotation) == (1080, 1920, -90)
    tag = {"streams": [{"codec_type": "video", "width": 1920, "height": 1080, "avg_frame_rate": "30/1",
                        "tags": {"rotate": "90"}}], "format": {"duration": "5"}}
    assert (parse_probe(tag).width, parse_probe(tag).height) == (1080, 1920)
    flipped = {"streams": [{"codec_type": "video", "width": 1920, "height": 1080, "avg_frame_rate": "30/1",
                            "side_data_list": [{"rotation": 180}]}], "format": {"duration": "5"}}
    assert (parse_probe(flipped).width, parse_probe(flipped).height) == (1920, 1080)


def test_parse_probe_without_video_raises():
    with pytest.raises(ValueError, match="no video stream"):
        parse_probe({"streams": [{"codec_type": "audio"}], "format": {"duration": "1"}})


@needs_ffmpeg
def test_probe_synthetic(synth_video):
    info = probe(synth_video(2))
    assert (info.width, info.height, info.has_audio, info.is_hdr) == (1280, 720, True, False)
    assert info.fps == pytest.approx(30.0) and info.duration == pytest.approx(2.0, abs=0.05)


@needs_ffmpeg
def test_probe_mov_with_data_stream_and_hlg(synth_video):
    info = probe(synth_video(2, ext="mov", data_stream=True, hlg=True))
    assert (info.width, info.height, info.has_audio, info.is_hdr) == (1280, 720, True, True)


@needs_ffmpeg
def test_probe_rotated_mov_reports_displayed_size(synth_video, tmp_path):
    from shorts.ffmpeg import FFMPEG, run

    src = synth_video(2, ext="mov")
    rotated = tmp_path / "rotated.mov"
    run([FFMPEG, "-y", "-loglevel", "error", "-display_rotation", "90", "-i", str(src),
         "-map", "0:v:0", "-map", "0:a:0", "-c", "copy", str(rotated)])
    info = probe(rotated)
    assert (info.width, info.height) == (720, 1280) and abs(info.rotation) == 90
