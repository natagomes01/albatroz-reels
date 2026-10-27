"""B-roll layers in the render graph (S8B spec 8): one input and one overlay per picked moment,
between the framed video [vb] and the captions. Strings only; no frame goes through Python."""
from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

from shorts.broll.model import target_size

OUT_W = 1080
SPLIT_Y = 960
SUPERSAMPLE = 1     # 2 = pan on a twice-larger image and scale down (spec 8.6 fallback for judder)


@dataclass(frozen=True)
class BrollInsert:
    start: float                # clip time
    end: float
    kind: str                   # "image" | "video"
    file: Path
    layout: str                 # "full" | "split"
    fit: str                    # "cover" | "whole"
    pan: str                    # "ltr" | "rtl" | "ttb" | "btt" | "still"
    focus: tuple[float, float]  # fraction of the overflow: 0 = left or top edge, 1 = right or bottom
    w: int                      # the file's size
    h: int
    split_top: int = 300        # first row of the framed video shown in the lower half (split)


def _even_up(v: float) -> int:
    n = math.ceil(v - 1e-6)
    return n + (n % 2)


def cover_size(w: int, h: int, tw: int, th: int) -> tuple[int, int]:
    s = max(tw / w, th / h)
    return max(tw, _even_up(w * s)), max(th, _even_up(h * s))


def _path(c: float, overflow: float, dist: float) -> tuple[float, float]:
    a = min(max(c - dist / 2, 0.0), overflow - dist)
    return a, a + dist


def pan_path(ins: BrollInsert, speed: float) -> tuple[float, float, float, float]:
    """Crop origin at the insert's start and end (scaled px): centred on the focus, clamped to the
    image, `speed` px per second along the pan axis, shorter when the image overflows less."""
    tw, th = target_size(ins.layout)
    sw, sh = cover_size(ins.w, ins.h, tw, th)
    ox, oy = sw - tw, sh - th
    # focus = fraction of the overflow, the same rule as CSS background-position on the page's
    # preview, so what the owner drags is what renders (Fable plan review)
    cx, cy = ins.focus[0] * ox, ins.focus[1] * oy
    dur = ins.end - ins.start
    if ins.kind == "video" or ins.fit != "cover" or ins.pan == "still":
        return cx, cx, cy, cy
    if ins.pan in ("ltr", "rtl"):
        a, b = _path(cx, ox, min(speed * dur, ox))
        return (a, b, cy, cy) if ins.pan == "ltr" else (b, a, cy, cy)
    a, b = _path(cy, oy, min(speed * dur, oy))
    return (cx, cx, a, b) if ins.pan == "ttb" else (cx, cx, b, a)


def layer_chain(ins: BrollInsert, idx: int, k: int, fps: int, speed: float) -> list[str]:
    """Filter lines turning input `idx` into the layer `[b{k}]`: the target size, 30 fps, and its
    timestamps moved to the insert's start, so the overlay picks it up at the right frame."""
    tw, th = target_size(ins.layout)
    tail = f"fps={fps},scale=out_color_matrix=bt709,format=yuv420p,setsar=1,setpts=PTS-STARTPTS+{ins.start:.4f}/TB[b{k}]"
    if ins.fit == "whole":
        return [f"[{idx}:v:0]split=2[bg{k}][fg{k}]",
                f"[bg{k}]scale={tw}:{th}:force_original_aspect_ratio=increase,crop={tw}:{th},"
                f"gblur=sigma=40,eq=brightness=-0.08[bgb{k}]",
                f"[fg{k}]scale={tw}:{th}:force_original_aspect_ratio=decrease:flags=lanczos[fgs{k}]",
                f"[bgb{k}][fgs{k}]overlay=x=(W-w)/2:y=(H-h)/2,{tail}"]
    f = SUPERSAMPLE
    sw, sh = cover_size(ins.w, ins.h, tw, th)
    x0, x1, y0, y1 = pan_path(ins, speed)
    dur = ins.end - ins.start
    # rgb24 before the crop: a yuv420p crop moves in 2 px steps, which shows as judder on a slow pan
    chain = (f"[{idx}:v:0]scale={sw * f}:{sh * f}:flags=lanczos,format=rgb24,crop={tw * f}:{th * f}:"
             f"x='{x0 * f:.2f}+{(x1 - x0) * f / dur:.4f}*t':y='{y0 * f:.2f}+{(y1 - y0) * f / dur:.4f}*t',")
    if f > 1:
        chain += f"scale={tw}:{th}:flags=lanczos,"
    return [chain + tail]


def input_args(ins: BrollInsert, fps: int) -> list[str]:
    dur = f"{ins.end - ins.start:.3f}"
    if ins.kind == "image":
        return ["-loop", "1", "-framerate", str(fps), "-t", dur, "-i", str(ins.file)]
    return ["-t", dur, "-an", "-i", str(ins.file)]    # muted: its sound is never decoded


def overlay_graph(inserts, first_input: int, tail: str, fps: int, speed: float) -> tuple[list[str], str]:
    """Layers and overlays after the framed video `tail`; returns the lines and the new tail.
    A split insert first moves rows split_top..split_top+960 of the framed video to the lower half."""
    lines: list[str] = []
    for k, ins in enumerate(inserts):
        lines += layer_chain(ins, first_input + k, k, fps, speed)
        # at or past the frame time: same rounding rule as the crop commands (docs/decisions/0001)
        en = f"gte(t,{ins.start - 0.0005:.4f})*lt(t,{ins.end - 0.0005:.4f})"
        src = tail
        if ins.layout == "split":
            lines.append(f"{tail}split=2[m{k}][s{k}]")
            lines.append(f"[s{k}]crop={OUT_W}:{SPLIT_Y}:0:{ins.split_top}[sp{k}]")
            lines.append(f"[m{k}][sp{k}]overlay=x=0:y={SPLIT_Y}:enable='{en}'[mm{k}]")
            src = f"[mm{k}]"
        lines.append(f"{src}[b{k}]overlay=x=0:y=0:enable='{en}':eof_action=pass[o{k}]")
        tail = f"[o{k}]"
    return lines, tail
