"""Master-time lettering -> body-clip frames, through the clip's EDL (kept spans in master time)."""
import json, sys
edl = json.load(open(sys.argv[1]))["edl"]
dur = float(sys.argv[3])
def clip_t(t):
    acc = 0.0
    for s in edl:
        if s["start"] <= t < s["end"]:
            return acc + t - s["start"]
        if t < s["start"]:
            return acc            # inside a cut: snap to the next kept span
        acc += s["end"] - s["start"]
    return acc
ITEMS = [  # master start, master end, text, colour, top padding
    (45.75, 50.0, "76 VERSÍCULOS", None, 300),
    (51.0, 56.6, "1Cr 28,19", "yellow", 300),
    (57.6, 61.1, "22 SÓ EM ÊXODO", None, 300),
    (93.49, 97.0, "COMENTE IMAGENS", None, 300),
]
fps = 30
out = {"bodyFrames": round(dur * fps), "items": []}
for a, b, text, color, y in ITEMS:
    it = {"from": round(clip_t(a) * fps), "to": round(clip_t(b) * fps), "text": text, "y": y}
    if color: it["color"] = color
    out["items"].append(it)
json.dump(out, open(sys.argv[2], "w"), ensure_ascii=False, indent=1)
print(json.dumps(out, ensure_ascii=False))
