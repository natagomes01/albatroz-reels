"""Effective words: raw transcript + the owner's word fixes + automatic caption edits.

Caption spec (docs/superpowers/specs/2026-09-29-caption-context-pass-design.md) sections 3, 4.5
and 5. Indices are always RAW slot indices of words.json. A slot has no end time: a word is shown
until the next word's start (captions.render_ass), so dropping a slot hands its time to the
previous word without moving any other word.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

from shorts import jobs
from shorts.words import Word

LAST_SLOT = 0.5  # duration of the class's last slot (textutil.word_end also uses +0.5 s)
CORRECTIONS_VERSION = 1


@dataclass(frozen=True)
class Edit:
    first: int                   # first raw slot replaced (inclusive)
    last: int                    # last raw slot replaced (inclusive)
    tokens: tuple[str, ...]      # 1 to 12 words that replace slots first..last
    kind: str = "mishearing"     # foreign_term | proper_name | scripture | mishearing |
                                 # split_or_joined_word | punctuation
    reason: str = ""             # the model's reason, in the channel language
    confidence: float = 1.0

    def to_dict(self) -> dict:
        return {"first": self.first, "last": self.last, "tokens": list(self.tokens),
                "kind": self.kind, "reason": self.reason, "confidence": self.confidence}

    @classmethod
    def from_dict(cls, d: dict) -> Edit:
        return cls(int(d["first"]), int(d["last"]), tuple(str(t) for t in d["tokens"]),
                   str(d.get("kind", "mishearing")), str(d.get("reason", "")),
                   float(d.get("confidence", 1.0)))


def anchors(edit: Edit) -> dict[int, list[str]]:
    """Raw slot -> tokens anchored to it: token m goes to slot first + floor(m * n / k)."""
    n, k = edit.last - edit.first + 1, len(edit.tokens)
    out: dict[int, list[str]] = {}
    for m, tok in enumerate(edit.tokens):
        out.setdefault(edit.first + (m * n) // k, []).append(tok)
    return out


def _slots(manual: dict[str, str] | None, n_raw: int) -> dict[int, str]:
    out: dict[int, str] = {}
    for key, text in (manual or {}).items():
        try:
            i = int(key)
        except (TypeError, ValueError):
            continue
        if 0 <= i < n_raw:
            out[i] = text
    return out


def active_edits(n_raw: int, auto_edits: list[Edit], manual: dict[str, str] | None,
                 prefer_auto: frozenset[int] | set[int] = frozenset()) -> list[Edit]:
    """The automatic edits that apply: in range, not overlapping an earlier one, and not touching
    any slot the owner fixed (the owner's word wins over the whole automatic edit), unless the
    owner chose the suggestion for that range: its `first` is in `prefer_auto` (review spec 4.4)."""
    touched = set(_slots(manual, n_raw))
    out: list[Edit] = []
    end = -1
    for e in sorted(auto_edits, key=lambda e: (e.first, e.last)):
        if not e.tokens or not 0 <= e.first <= e.last < n_raw or e.first <= end:
            continue
        end = e.last  # an owner-overridden edit still claims its range for the overlap test
        if e.first not in prefer_auto and any(e.first <= s <= e.last for s in touched):
            continue
        out.append(e)
    return out


def _edit_words(raw: list[Word], edit: Edit) -> list[Word]:
    out: list[Word] = []
    for s, toks in sorted(anchors(edit).items()):
        start = raw[s].t
        dur = raw[s + 1].t - start if s + 1 < len(raw) else LAST_SLOT
        total = sum(len(t) for t in toks)
        before = 0
        for tok in toks:
            out.append(Word(round(start + dur * before / total, 6), tok, raw[s].p))
            before += len(tok)
    return out


def effective_words(raw: list[Word], auto_edits: list[Edit], manual: dict[str, str] | None,
                    prefer_auto: frozenset[int] | set[int] = frozenset()) -> list[Word]:
    """Raw words, then the owner's fixes ("" drops a slot), then the automatic edits that the owner
    did not touch or chose (`prefer_auto`), placed with the timing rule of spec 4.5. An applied
    edit covers its whole range, so owner fixes inside it are skipped, not lost."""
    texts = [w.w for w in raw]
    for i, text in _slots(manual, len(raw)).items():
        texts[i] = text
    starts = {e.first: e for e in active_edits(len(raw), auto_edits, manual, prefer_auto)}
    out: list[Word] = []
    i = 0
    while i < len(raw):
        edit = starts.get(i)
        if edit is not None:
            out.extend(_edit_words(raw, edit))
            i = edit.last + 1
            continue
        if texts[i] != "":
            out.append(Word(raw[i].t, texts[i], raw[i].p))
        i += 1
    return out


def read_edits(job) -> list[Edit]:
    """The automatic edits of analyze/corrections.json. Ignored (empty) when words.json changed
    since they were made: they point at raw indices of the old transcript."""
    data = jobs.read_json(job.corrections_json)
    if not data or not job.words_json.exists():
        return []
    try:
        if data.get("words_hash") != jobs.file_hash(job.words_json):
            return []
        return [Edit.from_dict(d) for d in data.get("edits", [])]
    except (AttributeError, KeyError, TypeError, ValueError):
        return []                        # malformed file: same as no corrections


def edits_touching(edits: list[Edit], raw: list[Word], spans, pad: float = 2.0) -> list[Edit]:
    """The edits whose time range meets a segment extended by `pad` seconds (caption spec 8)."""
    out = []
    for e in edits:
        if not 0 <= e.first <= e.last < len(raw):
            continue
        a = raw[e.first].t
        b = raw[e.last + 1].t if e.last + 1 < len(raw) else raw[e.last].t + LAST_SLOT
        if any(a < s.end + pad and b > s.start - pad for s in spans):
            out.append(e)
    return out


def edits_digest(edits: list[Edit], raw: list[Word], spans, pad: float = 2.0) -> str:
    touching = [e.to_dict() for e in edits_touching(edits, raw, spans, pad)]
    return hashlib.sha256(jobs.canonical(touching).encode("utf-8")).hexdigest()
