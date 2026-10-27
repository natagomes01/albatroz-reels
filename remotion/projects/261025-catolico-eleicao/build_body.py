"""Body overlays -> src/body.json (body-clip frames), from the clip's edl.json, meta.json and captions.ass.

Usage: python3 -I build_body.py <clips/e220a01 dir> <body.mp4 duration in seconds>
Master times are the job master's (masters/261025-catolico-eleicao.mp4). The long-cut-reel skill has the flow.
"""
import json, math, re, sys
from pathlib import Path

clip = Path(sys.argv[1])
dur = float(sys.argv[2])
FPS = 30
edl = json.load(open(clip / "edl.json"))["edl"]
meta = json.load(open(clip / "meta.json"))


def clip_t(t):
    acc = 0.0
    for s in edl:
        if s["start"] <= t < s["end"]:
            return acc + t - s["start"]
        if t < s["start"]:
            return acc            # inside a cut: snap to the next kept span
        acc += s["end"] - s["start"]
    return acc


def fr(master_t):
    return round(clip_t(master_t) * FPS)


def window(clip_s, clip_e):
    # same frames the pipeline's gte(t,a)*lt(t,b) enables
    return math.ceil(clip_s * FPS - 1e-6), math.ceil(clip_e * FPS - 1e-6)


INSERTS = [  # master start, master end, file, object position
    (10.35, 12.08, "filho-prodigo-rembrandt.jpg", "50% 45%"),  # "padre, eu pequei, quero confessar"
    (17.70, 22.85, "caim-abel-ticiano.jpg", "50% 45%"),        # "e desejar o mal do seu irmão ... por algum motivo"
    (58.30, 65.95, "sermao-montanha-bloch.jpg", "55% 40%"),    # "O evangelho de hoje ... deixa isso muito claro"
    (84.45, 88.85, "belsazar-rembrandt.jpg", "45% 40%"),       # "e eles vão gastar bilhões naquela bonança toda lá em Brasília"
]
TAGS = [  # master start, master end, text, colour, top row (safe zone: y 252 to 1080, the tag is about 150 tall)
    (12.80, 17.65, "CATECISMO §2113", None, 300),   # idolatria: over the Poussin split, top half
    (58.45, 65.90, "MT 22,34-40", "lightGold", 300), # today's Gospel, over the Bloch insert
]

verse = next(b for b in meta["broll"] if b["title"].startswith("Placa"))
vf, vt = window(verse["start"], verse["end"])


def ts(x):
    h, m, s = x.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


screens = {}
for line in open(clip / "captions.ass"):
    if not line.startswith("Dialogue:"):
        continue
    f = line.rstrip("\n").split(",", 9)
    s, e, txt = ts(f[1]), ts(f[2]), f[9]
    y = int(re.search(r"\\pos\(\d+,(\d+)\)", txt).group(1))
    rest = re.sub(r"^\{[^}]*\}", "", txt)
    parts, hl = [], False
    for tok in re.split(r"(\{[^}]*\})", rest):
        if not tok:
            continue
        if tok.startswith("{"):
            hl = "00E5FF" in tok  # the yellow current-word override
            continue
        parts.append({"t": tok, "hl": hl})
    screens.setdefault((s, e), []).append((y, parts))
captions = []
for (s, e), lines in sorted(screens.items()):
    lines.sort(key=lambda l: l[0])
    for i, (_, parts) in enumerate(lines):
        captions.append({"from": round(s * FPS), "to": round(e * FPS), "line": i, "lines": len(lines), "parts": parts})

words = json.load(open(clip.parent.parent / "words.json"))["words"]
def word_t(text, after):
    return next(w["t"] for w in words if w["w"] == text and w["t"] > after)
pode = word_t("Pode", 97.0)
out = {
    "bodyFrames": round(dur * FPS),
    "inserts": [{"from": fr(a), "to": fr(b), "file": f, "origin": o} for a, b, f, o in INSERTS],
    "verse": {"from": vf, "to": vt},
    # split moments: the captions sit on the split line there, above the face
    "splits": [dict(zip(("from", "to"), window(b["start"], b["end"]))) for b in meta["broll"] if b["layout"] == "split"],
    "tags": [dict({"from": fr(a), "to": fr(b), "text": t, "y": y}, **({"color": c} if c else {})) for a, b, t, c, y in TAGS],
    "captions": captions,
    # whisper runs about 3 frames late: pull each pop a little earlier
    "cta": {"from": fr(pode - 0.15), "melhor": fr(word_t("é", pode) - 0.1), "perfil": fr(word_t("vida", pode) - 0.1)},
}
json.dump(out, open(Path(__file__).parent / "src" / "body.json", "w"), ensure_ascii=False)
print({k: v for k, v in out.items() if k != "captions"}, len(captions), "caption lines")
