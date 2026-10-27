"""Spike: search Wikimedia Commons for the EP 01 paintings and build a contact sheet to pick from.

Usage: uv run python scripts/spikes/quote-reel-261026/find_images.py <out_dir>
Writes <out_dir>/candidates.json, thumbs/<key>.jpg and contact-<group>.jpg (numbered tiles).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from shorts.broll.sources import SourceError, commons_search, http_download, http_fetch
from shorts.config import load_config
from shorts.ffmpeg import FFMPEG, run

UA = load_config(Path(__file__).resolve().parents[3] / "config.toml").broll.user_agent
TERMS = {
    "ambrose": ["Saint Ambrose painting", "Ambrosius von Mailand Gemälde", "Sant'Ambrogio dipinto",
                "Saint Ambrose mosaic Milan"],
    "temptation": ["Temptation of Christ pinnacle temple painting", "Temptation of Christ painting",
                   "Tentazioni di Cristo Botticelli", "Tissot pinnacle of the temple"],
    "scripture": ["illuminated manuscript Gospel Vulgate", "Codex Gospel book medieval",
                  "Saint Ambrose writing manuscript"],
}


def main(out: Path) -> None:
    thumbs = out / "thumbs"
    thumbs.mkdir(parents=True, exist_ok=True)
    found: dict[str, list[dict]] = {}
    for group, terms in TERMS.items():
        seen, rows = set(), []
        for term in terms:
            try:
                cands = commons_search(term, http_fetch, UA, 4096, 320)
            except SourceError as e:
                print("skip", term, e)
                continue
            for c in cands:
                if c.key in seen or min(c.w, c.h) < 900:
                    continue
                seen.add(c.key)
                rows.append(c.to_dict())
        rows = rows[:30]
        for i, r in enumerate(rows):
            r["n"] = i
            dest = thumbs / f"{r['key']}.jpg"
            if not dest.exists():
                try:
                    http_download(r["thumb_url"], dest, {"User-Agent": UA}, 5 << 20)
                except SourceError as e:
                    print("thumb failed", r["key"], e)
        found[group] = rows
        _sheet(out / f"contact-{group}.jpg", [thumbs / f"{r['key']}.jpg" for r in rows])
    (out / "candidates.json").write_text(json.dumps(found, ensure_ascii=False, indent=1), encoding="utf-8")


def _sheet(dest: Path, files: list[Path]) -> None:
    files = [f for f in files if f.exists()]
    if not files:
        return
    args = [FFMPEG, "-y", "-v", "error"]
    for f in files:
        args += ["-i", str(f)]
    tiles = [f"[{i}:v]scale=240:240:force_original_aspect_ratio=decrease,pad=240:240:(ow-iw)/2:(oh-ih)/2,"
             f"drawtext=fontfile='C\\:/Windows/Fonts/arial.ttf':text='{i}':x=6:y=6:fontsize=28:fontcolor=yellow:box=1:boxcolor=black[t{i}]"
             for i in range(len(files))]
    cols = 6
    layout = "|".join(f"{(i % cols) * 240}_{(i // cols) * 240}" for i in range(len(files)))
    graph = ";".join(tiles) + ";" + "".join(f"[t{i}]" for i in range(len(files)))
    graph += f"xstack=inputs={len(files)}:layout={layout}:fill=black" if len(files) > 1 else "null"
    run(args + ["-filter_complex", graph, "-frames:v", "1", str(dest)])


if __name__ == "__main__":
    main(Path(sys.argv[1]))
