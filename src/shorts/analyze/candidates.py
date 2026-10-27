"""Candidates: weighted total, duplicates at 80%, hook groups (spec 6.3, 6.6)."""
from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field

from shorts.timeline import Span

DIMENSIONS = ("hook", "value", "conversation", "emotion")


@dataclass(frozen=True)
class SegmentRef:
    window_id: str
    first_words: str
    last_words: str
    proposed: Span
    snapped: Span


@dataclass
class Candidate:
    id: str
    window_id: str
    segments: list[SegmentRef]
    title: str
    hook: str
    scores: dict[str, dict]
    controversy: int
    controversy_why: str
    who_reacts: str
    emphasis: list[str]
    hook_id: str
    out_of_order: bool
    too_long: bool = False
    too_short: bool = False
    llm_hook_id: str = ""
    blind: dict | None = None
    faithful: dict | None = None
    verdict: str = "review"
    warnings: list[str] = field(default_factory=list)
    total: float = 0.0

    def spans(self) -> list[Span]:
        return [s.snapped for s in self.segments]

    def duration(self) -> float:
        return sum(s.duration for s in self.spans())

    def to_dict(self) -> dict:
        d = asdict(self)
        d["segments"] = [{"window_id": s.window_id, "first_words": s.first_words,
                          "last_words": s.last_words,
                          "proposed": [s.proposed.start, s.proposed.end],
                          "snapped": [s.snapped.start, s.snapped.end]} for s in self.segments]
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Candidate":
        d = dict(d)
        d["segments"] = [SegmentRef(s["window_id"], s["first_words"], s["last_words"],
                                    Span(*s["proposed"]), Span(*s["snapped"])) for s in d["segments"]]
        return cls(**d)


def total(c: Candidate, weights: dict[str, float]) -> float:
    return round(sum(c.scores[k]["score"] * 10 * weights[k] for k in DIMENSIONS), 1)


def _inter(a: Span, b: Span) -> float:
    return max(0.0, min(a.end, b.end) - max(a.start, b.start))


def overlap(a: Candidate, b: Candidate) -> float:
    return sum(_inter(x, y) for x in a.spans() for y in b.spans())


def dedupe(cands: list[Candidate], ratio: float = 0.8) -> list[Candidate]:
    """Run after the reviews: a dropped candidate never hides a surviving near-copy."""
    kept: list[Candidate] = []
    for c in sorted(cands, key=lambda c: (c.verdict != "drop", c.total), reverse=True):
        if all(overlap(c, k) < ratio * min(c.duration(), k.duration()) for k in kept):
            kept.append(c)
    return kept


def group_by_hook(cands: list[Candidate], tol: float = 1.0) -> dict[str, list[str]]:
    """Union of two signals: the model's namespaced hook id, and first segments starting
    within `tol` seconds (the model only sees one window per call, so the start catches
    the same hook found from two windows)."""
    order = sorted(cands, key=lambda c: c.total, reverse=True)
    parent = list(range(len(order)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, a in enumerate(order):
        for j in range(i):
            b = order[j]
            same_llm = bool(a.llm_hook_id) and a.llm_hook_id == b.llm_hook_id
            same_start = abs(a.spans()[0].start - b.spans()[0].start) <= tol
            if same_llm or same_start:
                parent[find(i)] = find(j)
    groups: dict[int, list[Candidate]] = {}
    for i, c in enumerate(order):
        groups.setdefault(find(i), []).append(c)
    out: dict[str, list[str]] = {}
    for members in groups.values():
        gid = "h-" + members[0].id           # best member's stable id: stable across reruns
        for c in members:
            c.hook_id = gid
        out[gid] = [c.id for c in members]
    return out


def stable_id(c: Candidate) -> str:
    key = ";".join(f"{s.start:.1f}-{s.end:.1f}" for s in c.spans())
    return "c" + hashlib.sha1(key.encode()).hexdigest()[:6]


def assign_ids(cands: list[Candidate]) -> None:
    """Content-derived ids (review C1): a rerun that finds the same clip gives it the same id,
    so a decision in review.json can never move to a different clip."""
    seen: dict[str, int] = {}
    for c in cands:
        base = stable_id(c)
        seen[base] = seen.get(base, 0) + 1
        c.id = base if seen[base] == 1 else f"{base}-{seen[base]}"
