"""Spike: blur the children's faces in the original. Writes original_blur.mp4."""
import json
import subprocess
import sys
from pathlib import Path

FF = "/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg"
D = Path.home() / "dev/albatroz-media/reactions/261016-stedfast"
faces = json.load(open(D / "spike/faces.json"))


def lerp_expr(keys):
    """Piecewise-linear expression of t through (t, v) keys, held at both ends."""
    keys = sorted(keys)
    e = f"{keys[-1][1]:.1f}"
    for (t0, v0), (t1, v1) in reversed(list(zip(keys, keys[1:]))):
        e = f"if(lt(t,{t1:.3f}),{v0:.1f}+({v1 - v0:.1f})*(t-{t0:.3f})/{t1 - t0:.3f},{e})"
    return f"if(lt(t,{keys[0][0]:.3f}),{keys[0][1]:.1f},{e})"


tracks = []  # (start, end, size_w, size_h, [(t, cx, cy)])

# boy, close shot: Vision faces below the pastor's head (y > 700), every 0.2 s, then the crouch by hand
boy = []
for f in faces:
    if f["t"] > 13.5:
        break
    if round(f["t"] * 10) % 2:
        continue
    if 9.35 < f["t"] < 10.65:
        continue
    for x, y, w, h in f["faces"]:
        if y > 700 and y < 1000:
            boy.append((f["t"], x + w / 2, y + h / 2))
boy += [(9.5, 780, 900), (9.65, 840, 1010), (9.8, 870, 1100), (10.1, 860, 1060),
        (10.4, 850, 940), (10.6, 860, 900)]
tracks.append((0, 13.7, 200, 220, sorted(boy)))

# girl, wide shot: keyframes read off a 1 s contact sheet (head centre, source pixels)
girl = [(13.6, 400, 712), (14, 381, 722), (15, 426, 712), (16, 342, 712), (17, 335, 709),
        (18, 348, 709), (19, 351, 709), (20, 353, 709), (21, 357, 709), (22, 352, 709),
        (23, 361, 709), (24, 364, 709), (25, 368, 716), (26, 360, 716), (27, 372, 716),
        (28, 374, 716), (29, 368, 716), (30, 360, 716), (31, 372, 716), (32, 374, 716),
        (33, 379, 712), (34, 468, 712), (35, 578, 712), (36, 591, 800), (36.5, 595, 880), (37, 590, 940),
        (37.7, 600, 930), (38.0, 590, 800), (38.3, 588, 780), (38.67, 585, 910), (39.0, 600, 940),
        (39.33, 575, 880), (39.67, 580, 760), (40, 580, 731), (41, 498, 718), (41.92, 480, 718)]
tracks.append((13.5, 41.92, 190, 230, girl))

# second boy at the left edge of the wide shot
tracks.append((23.3, 33.8, 150, 180, [(23.3, 30, 737), (26, 45, 737), (30, 56, 737), (33.8, 22, 737)]))

# audience faces turned to the camera (Vision, y > 1000)
aud = []
for f in faces:
    for x, y, w, h in f["faces"]:
        if y > 1000:
            aud.append((f["t"], x + w / 2, y + h / 2, w))
spans = []
for t, cx, cy, w in aud:
    if spans and t - spans[-1][-1][0] <= 0.35:
        spans[-1].append((t, cx, cy, w))
    else:
        spans.append([(t, cx, cy, w)])
for sp in spans:
    size = max(p[3] for p in sp) * 1.8
    tracks.append((sp[0][0] - 0.2, sp[-1][0] + 0.2, size, size * 1.1, [(t, cx, cy) for t, cx, cy, _ in sp]))

parts = [f"[0:v]split={len(tracks) + 1}[base]" + "".join(f"[s{i}]" for i in range(len(tracks)))]
prev = "base"
for i, (a, b, bw, bh, keys) in enumerate(tracks):
    xk = [(t, cx - bw / 2) for t, cx, cy in keys]
    yk = [(t, cy - bh / 2) for t, cx, cy in keys]
    xe, ye = lerp_expr(xk), lerp_expr(yk)
    parts.append(
        f"[s{i}]crop=w={bw:.0f}:h={bh:.0f}:x='max(0,min(iw-ow,{xe}))':y='max(0,min(ih-oh,{ye}))',"
        f"gblur=sigma=22:steps=3[b{i}]"
    )
    parts.append(
        f"[{prev}][b{i}]overlay=x='max(0,min(W-w,{xe}))':y='max(0,min(H-h,{ye}))':"
        f"enable='gte(t,{a:.3f})*lt(t,{b:.3f})'[o{i}]"
    )
    prev = f"o{i}"
graph = ";\n".join(parts)
gpath = D / "spike/blur.graph"
gpath.write_text(graph)
print(len(tracks), "tracks")
subprocess.run([FF, "-v", "error", "-y", "-i", str(D / "original.mp4"), "-/filter_complex", str(gpath),
                "-map", f"[{prev}]", "-map", "0:a:0", "-c:v", "libx264", "-preset", "fast", "-crf", "14",
                "-pix_fmt", "yuv420p", "-c:a", "copy", str(D / "spike/original_blur.mp4")], check=True)
