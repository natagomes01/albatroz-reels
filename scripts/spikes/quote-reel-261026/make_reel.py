"""Spike: faceless quote Reel for EP 01 (Saint Ambrose), voice from ElevenLabs, paintings from Commons.

Usage: uv run python scripts/spikes/quote-reel-261026/make_reel.py [version]
Reads the voice and its transcreve words from <media>/raw/<JOB>/, the Commons picks from
<media>/broll/<JOB>/candidates.json (made by find_images.py), and writes
<media>/renders/catholic-br/<JOB>/quote-ambrosio-v<N>.mp4 plus credits.txt.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from shorts.audio import TARGET, _last_json
from shorts.broll.sources import http_download
from shorts import captions
from shorts.captions import CaptionStyle, build_screens, render_ass
from shorts.config import load_config
from shorts.ffmpeg import FFMPEG, encoder_args, run
from shorts.render import _quote
from shorts.timeline import Span, TimeMap
from shorts.words import Word

JOB = "261026-quote-ambrosio"
REPO = Path(__file__).resolve().parents[3]
APP = load_config(REPO / "config.toml")
MEDIA = APP.media_root
RAW = MEDIA / "raw" / JOB
VOICE = "voice-eliel"   # stem of the voice file and its .palavras.json in RAW
BROLL = MEDIA / "broll" / JOB
OUT = MEDIA / "renders" / "catholic-br" / JOB
FONTS = REPO / "assets" / "fonts"
UA = APP.broll.user_agent

# The quote as it is in the series file: whisper's words keep their times, these keep the spelling.
QUOTE = (
    "Aprende aqui também que Satanás se transfigura em anjo de luz e, das próprias Escrituras divinas, "
    "muitas vezes arma um laço para os fiéis. Portanto, que o herege não te capture por poder apresentar "
    "alguns exemplos das Escrituras, nem se arrogue o título de douto por parecer instruído. Também o diabo "
    "se serve dos testemunhos das Escrituras, não para ensinar, mas para enredar e enganar."
)
CREDIT = ("SANTO AMBRÓSIO", "COMENTÁRIO AO EVANGELHO", "DE LUCAS IV,26 (C. 390)")

W, H, FPS = 1080, 1920, 30
LEAD = 0.4      # first painting before the voice starts (the title goes on in the app, v4)
TAIL = 3.2      # credit card after the voice ends
FADE = 0.35     # cross-fade between paintings
DRIFT = 0.07    # Ken Burns zoom over one painting
PUNCH = 0.10    # extra zoom on a punch word...
PUNCH_FRAMES = 7  # ...eased in over this many frames (a one-frame jump read as a skip, v3)

# A quote reads in longer lines than talk: lower, smaller, about 24 characters a line (v4).
# The baseline sits under the Reels Ads safe zone but where the catolico-reel V5 put it (1400),
# above the organic Reels caption and the right-hand buttons.
QUOTE_STYLE = CaptionStyle(size=96, outline=5, x=510, baseline_y=1430, pitch=80, pitch_tall=88)
captions.LINE_MAX = 24
captions.SEGMENT_MAX = 48
captions.COMMA_MIN_CHARS = 22
captions.PAUSE_MIN_CHARS = 20

# (group, n in candidates.json, first word of the shot, focus x, focus y, zoom in?, punch word)
SHOTS = [
    ("ambrose", 2, None, 0.50, 0.30, True, None),             # Claude Vignon, Saint Ambrose
    ("temptation", 5, "satanás", 0.70, 0.40, False, None),    # Ary Scheffer, Christ and Satan
    ("temptation", 10, "e,", 0.55, 0.40, True, None),         # Sebastiano Ricci, in the wilderness
    ("temptation", 1, "muitas", 0.55, 0.25, True, None),      # Tintoretto, San Rocco
    ("ambrose", 0, "portanto,", 0.40, 0.35, False, None),     # Giovanni di Paolo
    ("ambrose", 18, "nem", 0.50, 0.25, True, None),           # mosaic, Cappella Palatina, Palermo
    ("temptation", 3, "também", 0.65, 0.35, True, "diabo"),   # Ary Scheffer
    ("temptation", 6, "não", 0.35, 0.40, True, "enganar."),
    ("ambrose", 21, "<tail>", 0.50, 0.25, True, None),        # mosaic in Sant'Ambrogio, 5th c.
]


def load_words() -> list[Word]:
    data = json.loads((RAW / f"{VOICE}.palavras.json").read_text(encoding="utf-8"))["words"]
    spelled = QUOTE.split()
    if len(spelled) != len(data):
        raise SystemExit(f"whisper heard {len(data)} words, the quote has {len(spelled)}")
    return [Word(t=float(x["t"]) + LEAD, w=s, p=float(x["p"])) for x, s in zip(data, spelled)]


def voice_end(words: list[Word]) -> float:
    """Where the last word stops: the first silence after the last word starts, else the file end."""
    probe = run([FFMPEG, "-v", "info", "-i", str(RAW / f"{VOICE}.mp3"), "-af",
                 "silencedetect=n=-45dB:d=0.2", "-f", "null", "-"])
    log = probe.stderr.decode("utf-8", "replace")
    last = words[-1].t - LEAD
    ends = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", log) if float(x) > last]
    if not ends:
        h, m, s = re.findall(r"time=(\d+):(\d+):([\d.]+)", log)[-1]
        ends = [int(h) * 3600 + int(m) * 60 + float(s)]
    return ends[0] + LEAD


def voice_loudnorm() -> str:
    """Two-pass loudnorm to -14 LUFS: a single pass lands about 1.5 LU short on this voice."""
    probe = run([FFMPEG, "-v", "info", "-i", str(RAW / f"{VOICE}.mp3"), "-af",
                 f"loudnorm={TARGET}:print_format=json", "-f", "null", "-"])
    m = _last_json(probe.stderr.decode("utf-8", "replace"))
    return (f"loudnorm={TARGET}:measured_I={m['input_i']}:measured_TP={m['input_tp']}"
            f":measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}"
            f":offset={m['target_offset']}:linear=true,"
            # linear mode stops short when the true peak would pass -1.5 (it gave -14.9): lift, then limit
            f"volume=0.9dB,alimiter=limit=0.84:level=false,aresample=48000")


def find_word(words: list[Word], text: str, after: float) -> float:
    for w in words:
        if w.t >= after and w.w.lower() == text:
            return w.t
    raise SystemExit(f"no word {text!r} after {after:.2f}")


def fetch_images() -> tuple[list[Path], list[dict]]:
    cands = json.loads((BROLL / "candidates.json").read_text(encoding="utf-8"))
    paths, rows = [], []
    for group, n, *_ in SHOTS:
        r = cands[group][n]
        dest = BROLL / f"{r['key']}.jpg"
        if not dest.exists():
            http_download(r["download_url"], dest, {"User-Agent": UA}, 60 << 20)
        paths.append(dest)
        rows.append(r)
    return paths, rows


def shot_times(words: list[Word], end_voice: float) -> list[tuple[float, float | None]]:
    """Start of every shot and its punch time, on the video timeline."""
    out, after = [], 0.0
    for _, _, first, _, _, _, punch in SHOTS:
        if first is None:
            start = 0.0
        elif first == "<tail>":
            start = end_voice + 0.3
        else:
            start = find_word(words, first, after) - 0.12
        after = start
        out.append((start, find_word(words, punch, start) if punch else None))
    return out


def shot_filter(i: int, img: Path, length: float, punch_at: float | None, fx: float, fy: float,
                zoom_in: bool) -> str:
    frames = round(length * FPS)
    sw, sh = W * 3, H * 3                      # zoompan on a 3x image keeps the drift smooth
    z = f"(1+{DRIFT}*on/{frames})" if zoom_in else f"(1+{DRIFT}*(1-on/{frames}))"
    if punch_at is not None:
        u = f"clip((on-{round(punch_at * FPS)})/{PUNCH_FRAMES},0,1)"
        z += f"+{PUNCH}*{u}*{u}*(3-2*{u})"     # smoothstep
    return (f"[{i}:v]scale={sw}:{sh}:force_original_aspect_ratio=increase,"
            f"crop={sw}:{sh}:(iw-{sw})*{fx}:(ih-{sh})*{fy},setsar=1,"
            f"zoompan=z='{z}':x='(iw-iw/zoom)*{fx}':y='(ih-ih/zoom)*{fy}':d={frames}:s={W}x{H}:fps={FPS},"
            f"format=yuv420p,trim=end_frame={frames}[s{i}]")


def ass_text(words: list[Word], total: float, end_voice: float) -> str:
    style = QUOTE_STYLE
    tm = TimeMap([Span(0.0, total)])
    body = render_ass(words, build_screens(words, "pt"), tm, style, end_voice + 0.25)
    head, events = body.split("\n[Events]\n", 1)
    head += "Style: Credit,Anton,64,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,1,0,1,5,0,5,40,40,0,1\n"
    hi = style.highlight
    t = lambda s: f"{int(s // 3600)}:{int(s % 3600 // 60):02d}:{s % 60:05.2f}"
    c0 = end_voice + 0.45
    credit = (f"Dialogue: 1,{t(c0)},{t(total)},Credit,,0,0,0,,{{\\pos(540,1080)\\fad(300,0)\\fs140}}"
              f"{CREDIT[0]}\\N{{\\fs84\\c{hi}}}{CREDIT[1]}\\N{CREDIT[2]}\n")
    return head + "\n[Events]\n" + events + credit


def main(version: int) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    words = load_words()
    end_voice = voice_end(words)
    total = round((end_voice + TAIL) * FPS) / FPS
    images, rows = fetch_images()
    times = shot_times(words, end_voice)

    args = [FFMPEG, "-y", "-v", "error", "-stats"]
    graph = []
    for i, (img, (start, punch)) in enumerate(zip(images, times)):
        nxt = times[i + 1][0] if i + 1 < len(times) else total
        lead_in = FADE if i else 0.0
        length = nxt - start + lead_in
        args += ["-i", str(img)]
        _, _, _, fx, fy, zin, _ = SHOTS[i]
        local_punch = None if punch is None else punch - start + lead_in
        graph.append(shot_filter(i, img, length, local_punch, fx, fy, zin))
    prev = "[s0]"
    for i in range(1, len(images)):
        off = times[i][0] - FADE
        graph.append(f"{prev}[s{i}]xfade=transition=fade:duration={FADE}:offset={off:.3f}[x{i}]")
        prev = f"[x{i}]"

    ass = OUT / f"quote-ambrosio-v{version}.ass"
    ass.write_text(ass_text(words, total, end_voice), encoding="utf-8")
    graph.append(f"{prev}eq=contrast=1.06:saturation=0.92:brightness=-0.03,vignette=angle=PI/4.5,"
                 f"noise=alls=6:allf=t,subtitles=filename={_quote(ass)}:fontsdir={_quote(FONTS)},"
                 f"trim=duration={total},format=yuv420p[v]")

    a = len(images)
    args += ["-i", str(RAW / f"{VOICE}.mp3")]
    graph.append(f"[{a}:a]adelay={round(LEAD * 1000)}:all=1,{voice_loudnorm()},"
                 f"apad,atrim=duration={total}[a]")
    script = OUT / f"quote-ambrosio-v{version}.graph"
    script.write_text(";\n".join(graph), encoding="utf-8")
    out = OUT / f"quote-ambrosio-v{version}.mp4"
    run(args + ["-/filter_complex", str(script), "-map", "[v]", "-map", "[a]", "-r", str(FPS),
                *encoder_args(), "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out)])

    credits = [f"{r['title']}, {r['author']} ({r['license']}), {r['page_url']}" for r in rows]
    (OUT / "credits.txt").write_text("\n".join(dict.fromkeys(credits)) + "\n", encoding="utf-8")
    print(out, f"{total:.2f}s")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 1)
