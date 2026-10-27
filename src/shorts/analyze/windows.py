"""120 s scan windows with 30 s overlap, cut at sentence ends (spec 6.2)."""
from __future__ import annotations

from dataclasses import dataclass

from shorts.analyze.textutil import fmt_ts, text_of, word_end
from shorts.words import Sentence, Word


@dataclass(frozen=True)
class Window:
    id: str
    first: int
    last: int
    start: float
    end: float
    text: str

    def label(self) -> str:
        return f"[{self.id}] {fmt_ts(self.start)}-{fmt_ts(self.end)}"


def build_windows(words: list[Word], sents: list[Sentence], length: float = 120.0,
                  overlap: float = 30.0) -> list[Window]:
    if not sents:
        return []
    s_start = [words[s.first].t for s in sents]
    s_end = [word_end(words, s.last) for s in sents]
    wins: list[Window] = []
    i = 0
    while i < len(sents):
        j = i
        while j + 1 < len(sents) and s_end[j] - s_start[i] < length:
            j += 1
        first, last = sents[i].first, sents[j].last
        if not wins or last != wins[-1].last:      # same end as the previous window = a subset
            wins.append(Window(id=f"w{len(wins) + 1}", first=first, last=last,
                               start=s_start[i], end=s_end[j], text=text_of(words, first, last)))
        if j == len(sents) - 1:
            break
        nxt = j
        while nxt > i + 1 and s_start[nxt] > s_end[j] - overlap:
            nxt -= 1
        i = max(nxt, i + 1)
    return wins


@dataclass(frozen=True)
class Chunk:
    id: int
    first: int      # word index, inclusive
    last: int       # word index, inclusive


def _pieces(sents: list[Sentence], size: int) -> list[Sentence]:
    """A 'sentence' longer than `size` words (a transcript without periods) is cut into pieces."""
    out: list[Sentence] = []
    for s in sents:
        a = s.first
        while s.last - a + 1 > size:
            out.append(Sentence(a, a + size - 1))
            a += size
        out.append(Sentence(a, s.last))
    return out


def build_chunks(sents: list[Sentence], size: int = 500, overlap: int = 100) -> list[Chunk]:
    """Word chunks of at most `size` words, cut at sentence ends, the next one starting at the
    earliest sentence that keeps the overlap within `overlap` words (caption spec 4.2)."""
    sents = _pieces(sents, size)
    out: list[Chunk] = []
    i = 0
    while i < len(sents):
        j = i
        while j + 1 < len(sents) and sents[j + 1].last - sents[i].first + 1 <= size:
            j += 1
        first, last = sents[i].first, sents[j].last
        out.append(Chunk(len(out), first, last))
        if j == len(sents) - 1:
            break
        nxt = j + 1
        while nxt - 1 > i and last - sents[nxt - 1].first + 1 <= overlap:
            nxt -= 1
        i = nxt
    return out
