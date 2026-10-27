"""Body captions (clips/<id>/captions.ass) inside the ebook windows -> JSON the Remotion ebook pass redraws.

Usage: python3 ebook_captions.py <captions.ass> <out.json> <start>-<end> [<start>-<end> ...]   (clip seconds)
"""
import json, re, sys

def ts(x):
    h, m, s = x.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)

ass, out_path = sys.argv[1], sys.argv[2]
windows = [tuple(float(v) for v in w.split("-")) for w in sys.argv[3:]]
events = []
for line in open(ass):
    if not line.startswith("Dialogue:"):
        continue
    f = line.rstrip("\n").split(",", 9)
    s, e, txt = ts(f[1]), ts(f[2]), f[9]
    if not any(s < b and e > a for a, b in windows):
        continue
    y = int(re.search(r"\\pos\(\d+,(\d+)\)", txt).group(1))
    body = re.sub(r"^\{[^}]*\}", "", txt)
    parts, hl = [], False
    for tok in re.split(r"(\{[^}]*\})", body):
        if not tok:
            continue
        if tok.startswith("{"):
            hl = "00E5FF" in tok  # the yellow current-word override
            continue
        parts.append({"t": tok, "hl": hl})
    events.append({"s": round(s, 3), "e": round(e, 3), "y": y, "parts": parts})
json.dump({"windows": windows, "events": events}, open(out_path, "w"), ensure_ascii=False)
print(len(events), "events")
