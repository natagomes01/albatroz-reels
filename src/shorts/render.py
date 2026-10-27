"""One ffmpeg pass per clip: EDL, color, per-frame crop windows, captions, sound, H.264."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from shorts.audio import audio_filter, select_expr
from shorts.broll.graph import input_args, overlay_graph
from shorts.color import Grade, grade_filter
from shorts.ffmpeg import FFMPEG, HDR_TO_SDR, VideoInfo, encoder_args, run
from shorts.shots import Crop
from shorts.timeline import Span, group_edl

OUT_W, OUT_H = 1080, 1920
# Keeps only the orange (covered) area of the safe-zone template, half transparent.
SAFE_ZONE_KEY = (
    "format=rgba,geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)'"
    ":a='if(gt(r(X,Y),200)*lt(b(X,Y),170)*gt(g(X,Y),140),128,0)'"
)


@dataclass(frozen=True)
class RenderInputs:
    master: Path
    info: VideoInfo
    edl: list[Span]
    crops: list[Crop]  # one per output frame
    ass_path: Path | None
    fonts_dir: Path
    grade: Grade | None
    audio_measured: dict | None
    sound: bool
    safe_zone: Path | None
    out: Path
    fps: int = 30
    segments: list[Span] | None = None  # 1-3 class segments in playback order; None = one stretch
    audio_files: list[Path] | None = None  # dereverbed sound, one WAV per segment group (S8 audio)
    broll: tuple = ()           # S8B: BrollInsert per picked moment (clip time), in moment order
    pan_px_per_s: float = 40.0


def _quote(path: Path) -> str:
    """A path as a filter-graph option value. The quotes protect it from the graph parser; the
    option parser then reads it again, so ':' (the drive in E:/...) still needs a backslash.
    Forward slashes on Windows, because a backslash is that second parser's escape."""
    text = str(path)
    if "'" in text:
        raise ValueError(f"path with a single quote is not supported in a filter graph: {text}")
    return "'" + path.as_posix().replace(":", r"\:") + "'"


def _sizes(crops: list[Crop]) -> tuple[tuple[int, int], tuple[int, int] | None]:
    sizes = sorted({(c.w, c.h) for c in crops}, key=lambda s: -s[0] * s[1])
    if len(sizes) > 2:
        raise ValueError(f"expected at most two crop sizes (wide, close), got {sizes}")
    return sizes[0], (sizes[1] if len(sizes) == 2 else None)


def _sendcmd(crops: list[Crop], wide: tuple[int, int], fps: int) -> str:
    """Per-frame crop positions as sendcmd lines, emitted only when a value changes."""
    lines: list[str] = []
    last: dict[str, tuple[int, int]] = {}
    for i, c in enumerate(crops):
        name = "wide" if (c.w, c.h) == wide else "close"
        if last.get(name) == (c.x, c.y):
            continue
        last[name] = (c.x, c.y)
        # at or past the command time fires it: never round a frame time up (docs/decisions/0001)
        lines.append(f"{max(i / fps - 0.0005, 0):.4f} crop@{name} x {c.x}, crop@{name} y {c.y};")
    return "\n".join(lines) + "\n"


def _close_enable(crops: list[Crop], wide: tuple[int, int], fps: int) -> str:
    runs: list[tuple[int, int]] = []
    start = None
    for i, c in enumerate(crops + [None]):  # type: ignore[list-item]
        is_close = c is not None and (c.w, c.h) != wide
        if is_close and start is None:
            start = i
        if not is_close and start is not None:
            runs.append((start, i))
            start = None
    if not runs:
        return "0"
    return "+".join(f"gte(t,{a / fps - 0.0005:.4f})*lt(t,{b / fps - 0.0005:.4f})" for a, b in runs)


def build_render(inp: RenderInputs, workdir: Path) -> list[str]:
    """Write the filter graph and sendcmd files into `workdir`; return the ffmpeg command.

    One input per segment (seeking straight to it), each trimmed by its EDL spans, then
    concatenated in playback order; crop windows, captions and the safe-zone overlay run on
    the joined clip, whose timeline is the clip timeline the crops and captions use.
    """
    workdir.mkdir(parents=True, exist_ok=True)
    groups = group_edl(inp.edl, inp.segments)
    if inp.audio_files is not None and len(inp.audio_files) != len(groups):
        raise ValueError(f"{len(inp.audio_files)} audio files for {len(groups)} segment groups")
    # inputs: one video per group, then the safe-zone image, then the dereverbed WAVs
    audio_base = len(groups) + (1 if inp.safe_zone is not None else 0)
    has_audio = inp.info.has_audio
    wide, close = _sizes(inp.crops)
    first = {("wide" if (c.w, c.h) == wide else "close"): c for c in reversed(inp.crops)}
    cmds = workdir / "crop.cmd"
    cmds.write_text(_sendcmd(inp.crops, wide, inp.fps), encoding="utf-8")

    # Plan 1's order: cheap first (fps, EDL select), then per crop branch the HDR tone-mapping
    # and the grade, so they touch only kept frames and only the cropped area.
    post = ""
    if inp.info.is_hdr:
        post += f",{HDR_TO_SDR}"
    if inp.grade is not None:
        post += f",{grade_filter(inp.grade)}"

    graph: list[str] = []
    for i, (window, spans) in enumerate(groups):
        expr = select_expr(spans, window.start)
        # explicit :v:0 / :a:0: iPhone .mov masters carry extra QuickTime data streams
        graph.append(f"[{i}:v:0]fps={inp.fps},select='{expr}',setpts=N/FRAME_RATE/TB[v{i}]")
        if has_audio:
            src = f"{audio_base + i}:a:0" if inp.audio_files is not None else f"{i}:a:0"
            graph.append(f"[{src}]aselect='{expr}',asetpts=N/SR/TB[a{i}]")
    if len(groups) == 1:
        vsrc, asrc = "[v0]", "[a0]"
    else:
        pads = "".join(f"[v{i}]" + (f"[a{i}]" if has_audio else "") for i in range(len(groups)))
        outs = "[vcat][acat]" if has_audio else "[vcat]"
        graph.append(f"{pads}concat=n={len(groups)}:v=1:a={1 if has_audio else 0}{outs}")
        vsrc, asrc = "[vcat]", "[acat]"

    w0 = first["wide"] if "wide" in first else inp.crops[0]
    graph.append(f"{vsrc}sendcmd=f={_quote(cmds)},split=2[sw][sc]")
    graph.append(
        f"[sw]crop@wide=w={wide[0]}:h={wide[1]}:x={w0.x}:y={w0.y}{post},"
        f"scale={OUT_W}:{OUT_H}:flags=lanczos,setsar=1[vw]"
    )
    if close is not None:
        c0 = first["close"]
        graph.append(
            f"[sc]crop@close=w={close[0]}:h={close[1]}:x={c0.x}:y={c0.y}{post},"
            f"scale={OUT_W}:{OUT_H}:flags=lanczos,setsar=1[vc]"
        )
        graph.append(f"[vw][vc]overlay=enable='{_close_enable(inp.crops, wide, inp.fps)}'[vb]")
    else:
        graph.append("[sc]nullsink")
        graph.append("[vw]null[vb]")
    tail = "[vb]"
    if inp.broll:   # S8B spec 8.3: B-roll sits on the framed video, under the captions
        first = len(groups) + (1 if inp.safe_zone is not None else 0) + len(inp.audio_files or [])
        extra, tail = overlay_graph(list(inp.broll), first, tail, inp.fps, inp.pan_px_per_s)
        graph += extra
    if inp.ass_path is not None:
        graph.append(
            f"{tail}subtitles=filename={_quote(inp.ass_path)}:fontsdir={_quote(inp.fonts_dir)}[vs]"
        )
        tail = "[vs]"
    zone_input = len(groups)
    if inp.safe_zone is not None:
        graph.append(f"[{zone_input}:v]{SAFE_ZONE_KEY}[sz]")
        graph.append(f"{tail}[sz]overlay=0:0:shortest=1[vz]")
        tail = "[vz]"
    graph.append(f"{tail}format=yuv420p[v]")

    if has_audio:
        af = audio_filter(inp.audio_measured) if inp.sound else "aresample=48000"
        graph.append(f"{asrc}{af}[a]")

    graph_file = workdir / "graph.txt"
    graph_file.write_text(";\n".join(graph) + "\n", encoding="utf-8")

    cmd = [FFMPEG, "-y", "-hide_banner", "-nostats"]
    for window, _ in groups:
        cmd += ["-ss", f"{window.start:.3f}", "-to", f"{window.end:.3f}", "-i", str(inp.master)]
    if inp.safe_zone is not None:
        cmd += ["-loop", "1", "-i", str(inp.safe_zone)]
    for wav in inp.audio_files or []:
        cmd += ["-i", str(wav)]
    for ins in inp.broll:
        cmd += input_args(ins, inp.fps)
    cmd += ["-/filter_complex", str(graph_file), "-map", "[v]"]
    if has_audio:
        cmd += ["-map", "[a]", "-c:a", "aac", "-b:a", "160k", "-ar", "48000"]
    cmd += [
        *encoder_args(), "-profile:v", "high", "-pix_fmt", "yuv420p",
        "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709",
        "-r", str(inp.fps), "-frames:v", str(len(inp.crops)),
        "-movflags", "+faststart", str(inp.out) + ".tmp.mp4",
    ]
    return cmd


def render_clip(inp: RenderInputs, workdir: Path) -> Path:
    """Render atomically: write <out>.tmp.mp4, then replace <out> only on success."""
    cmd = build_render(inp, workdir)
    inp.out.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(str(inp.out) + ".tmp.mp4")
    try:
        run(cmd)
        os.replace(tmp, inp.out)
    finally:
        tmp.unlink(missing_ok=True)  # also on Ctrl-C (KeyboardInterrupt is not an Exception)
    return inp.out
