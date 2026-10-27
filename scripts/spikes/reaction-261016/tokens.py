import json, sys
P = {"in": 4.00, "out": 20.00, "w5": 5.00, "w1h": 8.00, "read": 0.20}  # opus-5-5, pricing.toml
path = sys.argv[1]
marks = {"facebook.com/share": "link", "IMG_9887": "recording", "Estou assistindo aqui": "v2", "o áudio parou aos 39": "v3", "agora ficou perfeito": "docs"}
seen, phase, tot = set(), "brainstorm", {}
for line in open(path):
    try:
        e = json.loads(line)
    except Exception:
        continue
    if e.get("type") == "user":
        c = e.get("message", {}).get("content")
        txt = c if isinstance(c, str) else " ".join(x.get("text", "") for x in c if isinstance(x, dict) and x.get("type") == "text") if isinstance(c, list) else ""
        for k, v in marks.items():
            if k in txt:
                phase = v
    if e.get("type") != "assistant":
        continue
    m = e["message"]; mid = m.get("id")
    if mid in seen:
        continue
    seen.add(mid)
    u = m.get("usage") or {}
    cc = u.get("cache_creation") or {}
    w1h = cc.get("ephemeral_1h_input_tokens", 0); w5 = cc.get("ephemeral_5m_input_tokens", u.get("cache_creation_input_tokens", 0) - w1h)
    d = tot.setdefault(phase, {"calls": 0, "in": 0, "w5": 0, "w1h": 0, "read": 0, "out": 0})
    d["calls"] += 1; d["in"] += u.get("input_tokens", 0); d["w5"] += w5; d["w1h"] += w1h
    d["read"] += u.get("cache_read_input_tokens", 0); d["out"] += u.get("output_tokens", 0)
grand = 0
for ph, d in tot.items():
    usd = sum(d[k] * P[k] for k in P) / 1e6; grand += usd
    print(ph, d, f"USD {usd:.2f}")
print(f"total USD {grand:.2f}")
