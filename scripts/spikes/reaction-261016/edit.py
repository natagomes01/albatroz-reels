"""Spike: reaction edit for 261016-stedfast. Throwaway; lessons go to the spec.

Run from the repo: uv run --with numpy python scripts/spikes/reaction-261016/edit.py (DRY=1 writes plan.json only)
"""
import json
import re
import subprocess
from dataclasses import replace
from pathlib import Path

import shorts.captions as C
from shorts.captions import CaptionStyle, build_screens, render_ass
from shorts.silence import detect_silences
from shorts.timeline import Span, TimeMap, build_edl
from shorts.words import Word, load_words, sentences

FF = "/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg"
FPS = 30
D = Path.home() / "dev/albatroz-media/reactions/261016-stedfast"
W = D / "spike"
P = W / "pieces3"
P.mkdir(parents=True, exist_ok=True)
FONTS = Path.home() / "dev/albatroz-shorts/assets/fonts"
REAC, ORIG = D / "reaction.mov", W / "original_blur.mp4"
OFF = 0.98  # original t=0 sits at reaction t=0.98 (audio cross-correlation)

HOOK = (7.6, 10.6, 9.55)  # original span and the instant the tight crop cuts in
SPLIT_SPANS = [Span(3.88, 6.98), Span(12.25, 20.5), Span(22.7, 30.1), Span(36.4, 53.95)]  # reaction spans in the split
SEGMENTS = [Span(54.9, 153.3), Span(167.25, 181.2)]  # reaction spans kept in the full phase

# crops (x, y, w, h)
O_WIDE = (180, 330, 646, 1150)
O_TIGHT = (545, 560, 430, 765)
O_TOP = (0, 380, 1080, 956)
R_BOTTOM = (0, 230, 1080, 956)
R_FRAMING = {"wide": None, "close": (125, 130, 830, 1476), "tight": (203, 230, 675, 1200)}

PUNCH = [(113.5, 115.4), (123.0, 125.9), (139.4, 141.3), (149.8, 153.3), (178.9, 181.2)]
CUTAWAY = [  # reaction span, original start, crop
    (63.4, 65.5, 9.0, O_WIDE),
    (107.9, 110.0, 35.3, (434, 320, 646, 1150)),
    (121.5, 123.2, 25.0, (434, 320, 646, 1150)),
    (144.1, 146.4, 37.9, (300, 330, 646, 1150)),
]
CARDS = [  # reaction span, reference, text
    (74.2, 82.4, "ÊX 25,18", "“Farás dois querubins de ouro”"),
    (83.7, 88.3, "CL 1,15", "“Ele é a imagem do Deus invisível”"),
    (96.6, 105.6, "1COR 10,20", "“O que os pagãos sacrificam,\\Nsacrificam aos demônios”"),
    (131.2, 136.5, "GN 3,15", "“Porei inimizade entre ti e a mulher”"),
    (136.5, 139.2, "AP 12,13", "“O dragão perseguiu a mulher”"),
]
KEYWORDS = [(64.85, 65.5, "ÓDIO"), (112.9, 115.4, "EUCARISTIA"), (125.1, 126.0, "SATÂNICO")]
ORIG_PT = [  # original span, translation
    (0.2, 1.9, "Então, é o seguinte."),
    (2.9, 6.0, "A Bíblia diz: não farás para ti imagem esculpida."),
    (6.1, 8.8, "Então, pode bater."),
    (14.1, 15.7, "Vou dar algumas opções, tá?"),
    (15.7, 19.5, "Temos uma Maria pra todos os católicos, tá?"),
    (21.2, 25.1, "Temos outra coisa de anjo..."),
    (25.1, 27.4, "...demônio, se quiser chamar assim."),
    (27.6, 31.3, "E outra esquisita, que já perdeu umas asas,"),
    (31.3, 33.3, "mas precisa perder mais."),
    (33.4, 35.4, "Então, escolha o que quiser."),
    (35.5, 36.8, "Beleza, a Maria vai cair."),
    (36.8, 39.2, "Católicos, sinto muito."),
    (39.5, 41.0, "PÁ!"),
]
WORD_FIX = {162: "visível.", 177: "aqueles"}  # 162: Whisper heard "invisível"; the owner said "visível"
BR = W / "br"  # paintings downloaded from Wikimedia Commons
BROLL = [  # reaction span, painting (Wikimedia Commons, public domain), layout, pan window and path
    # the window (w, h) is in source pixels with the layout's aspect; the pan moves along ONE axis
    # (owner, 2026-10-16: a diagonal pan reads as a nudge sideways and a nudge up)
    (84.1, 87.6, "christ.jpg", "split", (801, 709), "v", 0, (80, 420)),
    (112.5, 115.5, "supper.jpg", "full", (757, 1346), "h", 0, (480, 700)),
    (131.3, 136.45, "immaculate.jpg", "split", (1920, 1700), "v", 0, (300, 1500)),
    (136.5, 139.1, "woman.jpg", "full", (1393, 2477), "h", 0, (100, 427)),
    (139.1, 142.5, "satan.jpg", "split", (800, 708), "h", 330, (700, 560)),  # Cabanel, The Fallen Angel: the eye
]

V_ENC = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "16", "-pix_fmt", "yuv420p", "-r", str(FPS)]
A_ENC = ["-c:a", "pcm_s16le", "-ar", "48000", "-ac", "2"]


def g(t):
    return round(t * FPS) / FPS


def crop(c):
    return "" if c is None else f"crop={c[2]}:{c[3]}:{c[0]}:{c[1]},"


import os
DRY = os.environ.get("DRY") == "1"


def run(args):
    if DRY:
        return
    subprocess.run([FF, "-v", "error", "-y", *args], check=True)


def mean_db(path, ss, t):
    out = subprocess.run([FF, "-ss", str(ss), "-t", str(t), "-i", str(path), "-map", "0:a:0", "-af",
                          "volumedetect", "-f", "null", "-"], stderr=subprocess.PIPE, text=True).stderr
    return float(re.search(r"mean_volume: (-?[\d.]+) dB", out).group(1))


pieces = []  # (path, duration)


def piece(args, dur):
    """One piece as two files: video cut to a whole number of frames, audio padded to the same length.

    One output with both streams lets ffmpeg end the audio a few ms early or the video a frame
    late; each drift is small but they add up across 40 pieces and push the voice off the lips.
    """
    n = round(dur * FPS)
    dur = n / FPS
    i = len(pieces)
    vpath, apath = P / f"{i:03d}.mov", P / f"{i:03d}.wav"
    m = [k for k, x in enumerate(args) if x == "-map"]
    base, vmap, amap = args[:m[0]], args[m[0] + 1], args[m[1] + 1]
    af = [] if amap.startswith("[") else ["-af", f"apad=whole_dur={dur:.6f}"]
    run([*base, "-map", vmap, *V_ENC, "-frames:v", str(n), str(vpath),
         "-map", amap, *af, *A_ENC, "-t", f"{dur:.6f}", str(apath)])
    pieces.append((vpath, apath, dur))


# 1. hook: the boy's blow, wide then tight, original sound
h0, h1, hc = HOOK
hook_dur = h1 - h0
piece(["-ss", str(h0), "-t", str(hook_dur), "-i", str(ORIG), "-filter_complex",
       f"[0:v]split[a][b];[a]trim=0:{hc - h0},setpts=PTS-STARTPTS,{crop(O_WIDE)}scale=1080:1920,setsar=1[a1];"
       f"[b]trim={hc - h0}:{hook_dur},setpts=PTS-STARTPTS,{crop(O_TIGHT)}scale=1080:1920,setsar=1[b1];"
       f"[a1][b1]concat=n=2:v=1:a=0[v]", "-map", "[v]", "-map", "0:a:0"], hook_dur)

# 2. split screen, shortened: the original moments that carry the story, every moment he speaks,
# his pauses cut; after the original ends the top shows slow-motion replays
words = load_words(D / "reaction.palavras.json")
words = [replace(w, w=WORD_FIX.get(i, w.w)) for i, w in enumerate(words)]
ORIG_END_R = g(OFF + 41.92)
sil_b = detect_silences(REAC, Span(ORIG_END_R, SPLIT_SPANS[-1].end), noise_db=-40.0, min_dur=0.3)
split_edl = build_edl(SPLIT_SPANS, sil_b, words, trigger=0.6, keep=0.3, keep_after_question=0.5, fps=FPS)
split_parts = []
for s in split_edl:
    a, b = g(s.start), g(s.end)
    if a < ORIG_END_R < b:
        split_parts += [(a, ORIG_END_R), (ORIG_END_R, b)]
    elif b - a >= 1 / FPS:
        split_parts.append((a, b))
top = f"{crop(O_TOP)}scale=1080:956,setsar=1"
replay = W / "replay.mov"  # top panel only: the girl's blow, then the boy's, both at half speed
run(["-ss", "37.6", "-t", "3.0", "-i", str(ORIG), "-ss", "8.9", "-t", "3.5", "-i", str(ORIG), "-filter_complex",
     f"[0:v]setpts=2*PTS,{top},fps={FPS}[a];[1:v]setpts=2*PTS,{top},fps={FPS}[b];[a][b]concat=n=2:v=1:a=0[v]",
     "-map", "[v]", "-an", *V_ENC, str(replay)])
o_db, r_db = mean_db(D / "original.mp4", 0, 41.9), mean_db(REAC, 12, 40)
o_gain = (r_db - 4) - o_db  # original sits 4 dB under his voice before ducking
bottom = f"{crop(R_BOTTOM)}scale=1080:956,setsar=1"
line = f"color=c=0xE5C76B:s=1080x8:r={FPS}[line]"
replay_pos = 0.0
for a, b in split_parts:
    d = round((b - a) * FPS) / FPS
    if b <= ORIG_END_R:  # original in sync, ducked under his voice
        piece(["-ss", f"{a:.4f}", "-t", f"{d:.4f}", "-i", str(REAC),
               "-ss", f"{a - OFF:.4f}", "-t", f"{d:.4f}", "-i", str(ORIG), "-filter_complex",
               f"[1:v]{top},fps={FPS}[top];[0:v]{bottom}[bot];{line};"
               f"[top][line][bot]vstack=inputs=3,trim=0:{d}[v];"
               f"[1:a]volume={o_gain:.1f}dB,apad=whole_dur={d}[oa];[0:a]asplit[r1][r2];"
               f"[oa][r1]sidechaincompress=threshold=0.03:ratio=8:attack=15:release=400[od];"
               f"[r2][od]amix=inputs=2:normalize=0:duration=first,apad=whole_dur={d}[a]",
               "-map", "[v]", "-map", "[a]"], d)
    else:  # replay on top, his voice only
        piece(["-ss", f"{a:.4f}", "-t", f"{d:.4f}", "-i", str(REAC),
               "-ss", f"{replay_pos:.4f}", "-t", f"{d:.4f}", "-i", str(replay), "-filter_complex",
               f"[1:v]setsar=1[top];[0:v]{bottom}[bot];{line};[top][line][bot]vstack=inputs=3,trim=0:{d}[v];"
               f"[0:a]apad=whole_dur={d}[a]", "-map", "[v]", "-map", "[a]"], d)
        replay_pos += d
tm_split = TimeMap([Span(a, b) for a, b in split_parts])
split_dur = sum(d for _, _, d in pieces[1:])

# 3. full phase: silence-cut, framing per sentence, punches, cutaways and B-roll paintings
sil = [s for seg in SEGMENTS for s in detect_silences(REAC, seg, noise_db=-40.0, min_dur=0.3)]
edl = build_edl(SEGMENTS, sil, words, trigger=0.6, keep=0.3, keep_after_question=0.5, fps=FPS)
edl = [Span(g(s.start), g(s.end)) for s in edl]
edl = [s for s in edl if s.end - s.start >= 1 / FPS]
sent_starts = [words[s.first].t - 0.12 for s in sentences(words)]
cuts = sorted({g(t) for t in sent_starts}
              | {g(t) for a, b in PUNCH for t in (a, b)}
              | {g(t) for a, b, _, _ in CUTAWAY for t in (a, b)}
              | {g(t) for x in BROLL for t in x[:2]})
MIN_SHOT = 0.7  # a framing change shorter than this reads as a glitch


def mode(t):
    for a, b, o0, c in CUTAWAY:
        if a <= t < b:
            return ("cut", a)
    for x in BROLL:
        a, b = x[:2]
        if a <= t < b:
            return ("broll", a)
    for a, b in PUNCH:
        if a <= t < b:
            return ("tight",)
    k = sum(1 for s in sent_starts if s <= t)
    return ("wide",) if k % 2 else ("close",)


def merge(seq):
    out = []
    for a, b, m in seq:
        if out and out[-1][2] == m and abs(out[-1][1] - a) < 1e-6:
            out[-1] = (out[-1][0], b, m)
        else:
            out.append((a, b, m))
    return out


raw = []
for span in edl:
    pts = [span.start] + [c for c in cuts if span.start < c < span.end] + [span.end]
    raw += [(a, b, mode(a)) for a, b in zip(pts, pts[1:])]
subs = merge(raw)
FRAMING = {"wide", "close", "tight"}
for i in range(1, len(subs)):  # a short framing shot takes the look of the shot it touches
    a, b, m = subs[i]
    pa, pb, pm = subs[i - 1]
    if m[0] in FRAMING and b - a < MIN_SHOT and abs(pb - a) < 1e-6:
        subs[i] = (a, b, pm)
for i in range(len(subs) - 2, -1, -1):
    a, b, m = subs[i]
    na, nb, nm = subs[i + 1]
    if m[0] in FRAMING and b - a < MIN_SHOT and abs(b - na) < 1e-6:
        subs[i] = (a, b, nm)
subs = merge(subs)

if DRY:
    json.dump({"split": split_parts, "full": [(a, b, m[0]) for a, b, m in subs]}, open(W / "plan.json", "w"))
    raise SystemExit

elapsed = {}
for a, b, m in subs:
    dur = round((b - a) * FPS) / FPS
    if m[0] == "cut":
        ca = next(c for c in CUTAWAY if c[0] == m[1])
        o_start = ca[2] + elapsed.get(ca[0], 0.0)
        elapsed[ca[0]] = elapsed.get(ca[0], 0.0) + dur
        piece(["-ss", f"{a:.4f}", "-t", f"{dur:.4f}", "-i", str(REAC),
               "-ss", f"{o_start:.4f}", "-t", f"{dur:.4f}", "-i", str(ORIG),
               "-filter_complex", f"[1:v]{crop(ca[3])}scale=1080:1920,setsar=1,fps={FPS}[v]",
               "-map", "[v]", "-map", "0:a:0"], dur)
    elif m[0] == "broll":
        br = next(x for x in BROLL if x[0] == m[1])
        r0, r1, name, layout, (cw, ch), axis, fixed, (p0, p1) = br
        e0 = elapsed.get(r0, 0.0)
        elapsed[r0] = e0 + dur
        tw, th = (1080, 1920) if layout == "full" else (1080, 956)
        k = tw / cw
        pos = f"({p0}+({p1 - p0})*({e0:.4f}+t)/{r1 - r0:.4f})*{k:.5f}"
        x, y = (pos, f"{fixed * k:.1f}") if axis == "h" else (f"{fixed * k:.1f}", pos)
        pan = f"scale=w='ceil(iw*{k:.6f}/2)*2':h=-2:out_range=tv,crop={tw}:{th}:x='{x}':y='{y}',setsar=1,format=yuv420p"
        img_in = ["-loop", "1", "-framerate", str(FPS), "-t", f"{dur:.4f}", "-i", str(BR / name)]
        if layout == "full":
            graph = f"[1:v]{pan}[v]"
        else:  # Natã on top (the caption band falls on the painting), painting below
            graph = (f"[0:v]{crop(R_BOTTOM)}scale=1080:956,setsar=1,fps={FPS},format=yuv420p[me];[1:v]{pan}[art];{line};"
                     f"[me][line][art]vstack=inputs=3[v]")
        piece(["-ss", f"{a:.4f}", "-t", f"{dur:.4f}", "-i", str(REAC), *img_in,
               "-filter_complex", graph, "-map", "[v]", "-map", "0:a:0"], dur)
    else:
        piece(["-ss", f"{a:.4f}", "-t", f"{dur:.4f}", "-i", str(REAC),
               "-vf", f"{crop(R_FRAMING[m[0]])}scale=1080:1920,setsar=1,fps={FPS}",
               "-map", "0:v:0", "-map", "0:a:0"], dur)

# timeline maps
full_start = hook_dur + split_dur
tm_full = TimeMap([Span(a, b) for a, b, _ in subs])
total = full_start + sum(round((b - a) * FPS) / FPS for a, b, _ in subs)


def out_split(r):
    v = tm_split.to_clip(r)
    return None if v is None else hook_dur + v


def out_full(r):
    v = tm_full.to_clip(r)
    return None if v is None else full_start + v


C.SEGMENT_MAX = C.LINE_MAX  # one line per screen: the eye never reads ahead of the voice
# captions: Natã in the split (on the divider) and in the full phase (lower band)
split_words = [Word(out_split(w.t), w.w, w.p) for w in words if out_split(w.t) is not None]
full_words = [Word(out_full(w.t), w.w, w.p) for w in words if out_full(w.t) is not None]
ident = TimeMap([Span(0, total)])
s_split = replace(CaptionStyle(), size=92, outline=5, baseline_y=1010, pitch=78, pitch_tall=88)
s_full = replace(CaptionStyle(), baseline_y=1330)
(W / "cap_split.ass").write_text(render_ass(split_words, build_screens(split_words, "pt"), ident, s_split, full_start))
(W / "cap_full.ass").write_text(render_ass(full_words, build_screens(full_words, "pt"), ident, s_full, total))


def at(t):
    t = max(t, 0)
    return f"{int(t // 3600)}:{int(t % 3600 // 60):02d}:{t % 60:05.2f}"


POP = r"\fad(120,120)\fscx70\fscy70\t(0,160,\fscx100\fscy100)"
ev = []
ev.append(f"Dialogue: 2,{at(0)},{at(hook_dur)},Title,,0,0,0,,{{\\an8\\pos(540,230){POP}}}"
          "PASTOR ENSINA CRIANÇAS\\NA QUEBRAR {\\c&H00E5FF&}NOSSA SENHORA")
for a, b, text in ORIG_PT:
    s, e = max(a - h0, 0), min(b - h0, hook_dur)  # hook window
    if e > s:
        ev.append(f"Dialogue: 1,{at(s)},{at(e)},Orig,,0,0,0,,{{\\an2\\pos(540,1560)}}{text}")
    for pa, pb in split_parts:  # split window: every kept part the line overlaps
        ra, rb = max(a + OFF, pa), min(b + OFF, pb, ORIG_END_R)
        if rb - ra > 0.25:
            ev.append(f"Dialogue: 1,{at(out_split(ra))},{at(out_split(ra) + rb - ra)},Orig,,0,0,0,,"
                      f"{{\\an8\\pos(540,150)}}{text}")
for a, b, ref, text in CARDS:
    s, e = out_full(a) or tm_full.snap_to_clip(a) + full_start, out_full(b) or tm_full.snap_to_clip(b) + full_start
    ev.append(f"Dialogue: 2,{at(s)},{at(e)},Card,,0,0,0,,{{\\an8\\pos(540,170){POP}}}"
              f"{{\\fnAnton\\fs84\\c&H00E5FF&}}{ref}\\N{{\\fnRaleway\\b1\\fs52\\c&HFFFFFF&}}{text}")
for a, b, text in KEYWORDS:
    s, e = tm_full.snap_to_clip(a) + full_start, tm_full.snap_to_clip(b) + full_start
    ev.append(f"Dialogue: 3,{at(s)},{at(e)},Key,,0,0,0,,{{\\an5\\pos(540,300){POP}}}{text}")
head = (
    "[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\nWrapStyle: 2\nScaledBorderAndShadow: yes\n\n"
    "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
    "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, "
    "MarginL, MarginR, MarginV, Encoding\n"
    "Style: Title,Anton,96,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,1,0,1,7,0,8,40,40,0,1\n"
    "Style: Orig,Raleway,50,&H00FFFFFF,&H00FFFFFF,&H60000000,&H00000000,1,1,0,0,100,100,0,0,3,14,0,2,60,60,0,1\n"
    "Style: Card,Raleway,52,&H00FFFFFF,&H00FFFFFF,&H50101010,&H00000000,1,0,0,0,100,100,0,0,3,22,0,8,70,70,0,1\n"
    "Style: Key,Anton,170,&H0000E5FF,&H0000E5FF,&H00000000,&H00000000,0,0,0,0,100,100,2,0,1,9,0,5,40,40,0,1\n\n"
    "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
)
(W / "overlay.ass").write_text(head + "\n".join(ev) + "\n")

# sound effects, generated (no library yet)
run(["-f", "lavfi", "-i", "aevalsrc='0.9*sin(2*PI*52*t)*exp(-7*t)+0.35*(random(0)*2-1)*exp(-30*t)':s=48000:d=0.7",
     "-ac", "2", str(W / "hit.wav")])
run(["-f", "lavfi", "-i", "anoisesrc=d=0.45:c=pink:a=0.5:r=48000", "-af",
     "highpass=f=400,lowpass=f=5000,afade=t=in:d=0.3:curve=exp,afade=t=out:st=0.3:d=0.15",
     "-ac", "2", str(W / "whoosh.wav")])
sfx = [("hit", hc - h0 + 0.12), ("whoosh", hook_dur - 0.3)]
sfx += [("whoosh", tm_full.snap_to_clip(a) + full_start - 0.25) for a, _, _, _ in CUTAWAY]
sfx += [("hit", tm_full.snap_to_clip(a) + full_start) for a, _, t in KEYWORDS]
sfx += [("whoosh", tm_full.snap_to_clip(x[0]) + full_start - 0.25) for x in BROLL]

# 4. join and finish: captions burned, sfx mixed, loudness to -14 LUFS
vl, al = W / "pieces_v.txt", W / "pieces_a.txt"
vl.write_text("".join(f"file '{v}'\n" for v, _, _ in pieces))
al.write_text("".join(f"file '{a}'\n" for _, a, _ in pieces))
run(["-f", "concat", "-safe", "0", "-i", str(vl), "-f", "concat", "-safe", "0", "-i", str(al),
     "-map", "0:v:0", "-map", "1:a:0", "-c", "copy", str(W / "body.mov")])
# the sfx are summed in numpy: an ffmpeg amix of a dozen delayed inputs dropped about 40 s of
# the voice in v2 (packets missing, holes of 3 to 7 s)
import numpy as np


def read_f32(path):
    raw = subprocess.run([FF, "-v", "error", "-i", str(path), "-map", "0:a:0", "-ac", "2", "-ar", "48000",
                          "-f", "f32le", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.float32).reshape(-1, 2).copy()


voice = read_f32(W / "body.mov")
for name, t in sfx:
    clip = read_f32(W / f"{name}.wav") * 10 ** ((-9 if name == "hit" else -16) / 20)
    i0 = int(round(t * 48000))
    i1 = min(len(voice), i0 + len(clip))
    if 0 <= i0 < len(voice):
        voice[i0:i1] += clip[: i1 - i0]
np.clip(voice, -1, 1).astype(np.float32).tofile(W / "mix.f32")
run(["-f", "f32le", "-ar", "48000", "-ac", "2", "-i", str(W / "mix.f32"), "-af",
     "loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000", "-c:a", "pcm_s16le", str(W / "mix.wav")])
fd = str(FONTS)
graph = (f"[0:v]subtitles={W / 'cap_split.ass'}:fontsdir={fd},subtitles={W / 'cap_full.ass'}:fontsdir={fd},"
         f"subtitles={W / 'overlay.ass'}:fontsdir={fd}[v]")
out = W / "reacao-stedfast-v3.mp4"
run(["-i", str(W / "body.mov"), "-i", str(W / "mix.wav"), "-filter_complex", graph, "-map", "[v]", "-map", "1:a:0",
     "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
     "-movflags", "+faststart", str(out)])
json.dump({"pieces": len(pieces), "total_s": round(total, 2), "hook": hook_dur, "split": split_dur,
           "full": round(total - full_start, 2), "orig_gain_db": round(o_gain, 1)},
          open(W / "edit_summary.json", "w"), indent=1)
print(open(W / "edit_summary.json").read())
