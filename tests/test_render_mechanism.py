"""Spike (kept as a regression test): drive per-frame crop windows from a list.

Decision: two fixed-size crops (wide, close) whose x/y change per frame through `sendcmd`,
each scaled to 1080x1920, joined by `overlay=enable=...`. Crop w/h never change mid-stream,
so no filter reinitialises. See docs/decisions/0001-per-frame-crop-mechanism.md.
"""
from pathlib import Path

from conftest import needs_ffmpeg
from shorts.ffmpeg import FFMPEG, encoder_args, run
from shorts.render import _quote


def _pixel(video: Path, frame: int, x: int, y: int):
    return tuple(run([FFMPEG, "-v", "error", "-i", str(video), "-vf",
                      f"select='eq(n,{frame})',format=rgb24,crop=1:1:{x}:{y}",
                      "-frames:v", "1", "-f", "rawvideo", "-"], capture_stdout=True).stdout)


@needs_ffmpeg
def test_sendcmd_moves_fixed_size_crops(synth_video, tmp_path):
    src = synth_video(4)
    cmds = tmp_path / "crop.cmd"
    # frame i fires at i/30 - 0.0005: sendcmd acts when the frame time is at or past the command
    # time, so a time rounded UP (frame 2 -> 0.0667 > 0.06667) would land one frame late
    cmds.write_text("".join(f"{max(i / 30 - 0.0005, 0):.4f} crop@wide x {i * 10}, crop@wide y 0;\n"
                            for i in range(60))
                    + "1.9995 crop@close x 400, crop@close y 100;\n", encoding="utf-8")
    graph = tmp_path / "graph.txt"
    graph.write_text(
        f"[0:v:0]fps=30,sendcmd=f={_quote(cmds)},split=2[a][b];\n"
        "[a]crop@wide=w=404:h=720:x=0:y=0,scale=1080:1920,setsar=1[w];\n"
        "[b]crop@close=w=290:h=514:x=0:y=0,scale=1080:1920,setsar=1[c];\n"
        "[w][c]overlay=enable='gte(t,1.9995)'[v]\n"
    , encoding="utf-8")
    out = tmp_path / "m.mp4"
    run([FFMPEG, "-y", "-v", "error", "-i", str(src), "-/filter_complex", str(graph), "-map", "[v]",
         "-frames:v", "90", *encoder_args(), str(out)])
    # red = source x / 5 at the output centre, i.e. (crop x + 202) / 5 while wide
    for frame in (10, 40):
        assert abs(_pixel(out, frame, 540, 300)[0] - (frame * 10 + 202) / 5) <= 10
    assert abs(_pixel(out, 70, 540, 300)[0] - (400 + 145) / 5) <= 6  # close-up from t=2 s
