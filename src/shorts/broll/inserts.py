"""Picked moments on the clip (S8B spec 8.4, 8.7, 8.9): class time to clip time, the rows of the
speaker in a split, the render-key digest, the meta entries and the credit text."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from shorts import jobs
from shorts.broll.files import file_digest
from shorts.broll.graph import SPLIT_Y, BrollInsert
from shorts.broll.model import BrollConfig, in_clip, moment_span
from shorts.timeline import Span, TimeMap
from shorts.words import Word

OUT_H = 1920
FALLBACK_TOP = 300
CREDIT_TEMPLATES = {"pt": "Imagem: {title}, de {author}, {license} ({url})",
                    "en": "Image: {title} by {author}, {license} ({url})"}


@dataclass(frozen=True)
class BrollPlan:
    id: str
    start: float                    # class time
    end: float
    kind: str
    file: Path
    layout: str
    fit: str
    pan: str
    focus: tuple[float, float]
    w: int
    h: int
    pick: dict = field(compare=False, hash=False, repr=False)


def picked_plans(decision: dict, raw: list[Word], spans: list[Span], dest_dir: Path) -> list[BrollPlan]:
    out = []
    for m in decision.get("broll") or []:
        pick = m.get("pick")
        if not pick or not in_clip(raw, m, spans):
            continue
        sp = moment_span(raw, m)
        out.append(BrollPlan(m["id"], sp.start, sp.end, pick["kind"], dest_dir / pick["file"], m["layout"],
                             m["fit"], m["pan"], (float(m["focus"][0]), float(m["focus"][1])),
                             int(pick["w"]), int(pick["h"]), pick))
    return sorted(out, key=lambda p: p.start)


def broll_digest(plans: list[BrollPlan], cfg) -> str:
    """Spec 8.7: what changes the B-roll pixels; "" for a clip without picks (its key stays as it was)."""
    if not plans:
        return ""
    items = [[p.start, p.end, p.kind, p.layout, p.fit, p.pan, list(p.focus),
              file_digest(p.file) if p.file.exists() else f"missing:{p.file.name}"] for p in plans]
    return jobs.stage_key("1", items=items, tunables=[cfg.pan_px_per_s, cfg.split_face_y])


def split_top(face, body, crop, face_y: int) -> int:
    """First row of the framed video shown in the lower half of a split: the face centre lands on
    output row `face_y` (spec 8.4); without a face, the body top lands 5% below the seam."""
    scale = OUT_H / crop.h
    if face is not None:
        y0 = (face.y + face.h / 2 - crop.y) * scale - (face_y - SPLIT_Y)
    elif body is not None:
        y0 = (body.y - crop.y) * scale - 0.05 * SPLIT_Y
    else:
        return FALLBACK_TOP
    return int(round(min(max(y0, 0.0), float(SPLIT_Y))))


def make_inserts(plans, tm: TimeMap, crops, face_at, body_at, cfg: BrollConfig,
                 fps: int = 30) -> tuple[BrollInsert, ...]:
    out = []
    for p in plans:
        a = tm.snap_to_clip(p.start)
        b = min(tm.snap_to_clip(p.end), tm.duration)
        if b - a < 1 / fps:
            continue                 # its words fell inside a silence cut
        top = FALLBACK_TOP
        if p.layout == "split":
            mid = (a + b) / 2
            t = tm.to_class(mid)
            top = split_top(face_at(t), body_at(t), crops[min(int(mid * fps), len(crops) - 1)], cfg.split_face_y)
        out.append(BrollInsert(a, b, p.kind, p.file, p.layout, p.fit, p.pan, p.focus, p.w, p.h, top))
    return tuple(out)


def credits(picks: list[dict], language: str) -> str:
    """Spec 8.9: one line per CC BY pick, in the channel's language; nothing for the others."""
    template = CREDIT_TEMPLATES.get(language, CREDIT_TEMPLATES["en"])
    return "\n".join(template.format(title=p["title"], author=p["author"], license=p["license"],
                                     url=p["page_url"])
                     for p in picks if str(p.get("license", "")).startswith("CC BY"))


def on_screen(plans: list[BrollPlan], tm: TimeMap, fps: int = 30) -> list[BrollPlan]:
    """The plans `make_inserts` keeps: those whose words survive the silence cuts."""
    return [p for p in plans if min(tm.snap_to_clip(p.end), tm.duration) - tm.snap_to_clip(p.start) >= 1 / fps]


def meta_entries(plans: list[BrollPlan], tm: TimeMap) -> list[dict]:
    plans = on_screen(plans, tm)
    return [{"start": round(tm.snap_to_clip(p.start), 2), "end": round(min(tm.snap_to_clip(p.end), tm.duration), 2),
             "layout": p.layout, "source": p.pick.get("source"), "kind": p.kind,
             "title": p.pick.get("title", ""), "author": p.pick.get("author", ""),
             "license": p.pick.get("license", ""), "page_url": p.pick.get("page_url", "")} for p in plans]
