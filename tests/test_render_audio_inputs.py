from pathlib import Path

from shorts import audio
from shorts.ffmpeg import VideoInfo
from shorts.render import RenderInputs, build_render
from shorts.shots import Crop
from shorts.timeline import Span

INFO = VideoInfo(width=1280, height=720, fps=30.0, duration=60.0, color_transfer="bt709", has_audio=True)
REPO = Path(__file__).resolve().parents[1]


def inputs(tmp_path, audio_files, segments=None, safe_zone=None):
    return RenderInputs(master=tmp_path / "m.mp4", info=INFO, edl=[Span(10.0, 12.0), Span(20.0, 21.0)],
                        crops=[Crop(0, 0, 404, 720)] * 90, ass_path=None, fonts_dir=REPO / "assets" / "fonts",
                        grade=None, audio_measured=None, sound=True, safe_zone=safe_zone,
                        out=tmp_path / "o.mp4", segments=segments, audio_files=audio_files)


def test_without_audio_files_the_master_feeds_the_sound(tmp_path):
    cmd = build_render(inputs(tmp_path, None), tmp_path / "w")
    graph = (tmp_path / "w" / "graph.txt").read_text(encoding="utf-8")
    assert "[0:a:0]aselect" in graph and cmd.count("-i") == 1


def test_audio_files_follow_the_video_inputs(tmp_path):
    segs = [Span(10.0, 12.0), Span(20.0, 21.0)]
    wavs = [tmp_path / "a.wav", tmp_path / "b.wav"]
    cmd = build_render(inputs(tmp_path, wavs, segments=segs), tmp_path / "w")
    graph = (tmp_path / "w" / "graph.txt").read_text(encoding="utf-8")
    assert "[2:a:0]aselect" in graph and "[3:a:0]aselect" in graph and "[0:a:0]" not in graph
    i = cmd.index(str(wavs[0]))
    assert cmd[i - 1] == "-i" and cmd[i + 2] == str(wavs[1])


def test_audio_files_come_after_the_safe_zone_input(tmp_path):
    zone = tmp_path / "zone.png"
    cmd = build_render(inputs(tmp_path, [tmp_path / "a.wav"], safe_zone=zone), tmp_path / "w")
    graph = (tmp_path / "w" / "graph.txt").read_text(encoding="utf-8")
    assert "[2:a:0]aselect" in graph and "[1:v]" in graph
    assert cmd.index(str(zone)) < cmd.index(str(tmp_path / "a.wav"))


def test_wrong_number_of_audio_files_is_refused(tmp_path):
    import pytest
    with pytest.raises(ValueError, match="audio file"):
        build_render(inputs(tmp_path, [tmp_path / "a.wav", tmp_path / "b.wav"]), tmp_path / "w")


def test_loudness_pass_reads_the_audio_files(tmp_path, monkeypatch):
    seen = {}

    class Done:
        stderr = b'{"input_i": "-20", "input_tp": "-3", "input_lra": "5", "input_thresh": "-30", "target_offset": "0"}'

    monkeypatch.setattr(audio, "run", lambda cmd: seen.setdefault("cmd", cmd) and Done())
    wav = tmp_path / "a.wav"
    audio.loudnorm_measure(tmp_path / "m.mp4", [Span(10.0, 12.0)], None, [wav])
    cmd = seen["cmd"]
    assert cmd[cmd.index(str(wav)) - 1] == "-i" and str(tmp_path / "m.mp4") not in cmd
    assert "-ss" not in cmd
