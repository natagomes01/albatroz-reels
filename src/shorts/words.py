"""Word-level transcript: loading, sentence grouping, normalized phrase search."""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

_SENTENCE_END = ".?!…"


@dataclass(frozen=True)
class Word:
    t: float  # start time in seconds, class timeline (DTW-shifted)
    w: str  # text as transcribed, punctuation attached
    p: float  # confidence 0..1


@dataclass(frozen=True)
class Sentence:
    first: int  # index of first word in the words list
    last: int  # index of last word (inclusive)


def load_words(path: Path) -> list[Word]:
    """Read a transcreve `.palavras.json` file (spec section 5)."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if data.get("version") != 1:
            raise ValueError(f"{path}: unsupported words file version {data.get('version')!r}")
        words = [Word(t=float(x["t"]), w=str(x["w"]), p=float(x["p"])) for x in data["words"]]
    except (KeyError, TypeError, AttributeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{path}: malformed words file") from exc
    for a, b in zip(words, words[1:]):
        if b.t < a.t:
            raise ValueError(f"{path}: word times go backwards at {a.w!r} -> {b.w!r}")
    return words


def _ends_sentence(text: str) -> bool:
    stripped = text.rstrip("\"'”’)]")
    return bool(stripped) and stripped[-1] in _SENTENCE_END


def sentences(words: list[Word]) -> list[Sentence]:
    """Group words into sentences closing on . ? ! or …; a trailing fragment is a sentence too."""
    out: list[Sentence] = []
    first = 0
    for i, word in enumerate(words):
        if _ends_sentence(word.w):
            out.append(Sentence(first, i))
            first = i + 1
    if first < len(words):
        out.append(Sentence(first, len(words) - 1))
    return out


def normalize(text: str) -> str:
    """Lowercase, strip accents and punctuation, collapse spaces."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    no_accents = "".join(c for c in decomposed if not unicodedata.combining(c))
    no_punct = re.sub(r"[^\w\s]", " ", no_accents)
    return " ".join(no_punct.split())


def _token_stream(words: list[Word]) -> list[tuple[str, int, bool, bool]]:
    """(token, word index, is first token of its word, is last token of its word)."""
    stream: list[tuple[str, int, bool, bool]] = []
    for idx, word in enumerate(words):
        toks = normalize(word.w).split()
        for k, tok in enumerate(toks):
            stream.append((tok, idx, k == 0, k == len(toks) - 1))
    return stream


def find_phrase_span(
    words: list[Word], phrase: str, start_at: int = 0, end_before: int | None = None
) -> tuple[int, int] | None:
    """(first, last) word indices of the first normalized match of `phrase`.

    The match starts at a word's first token and ends at a word's last token, its first word is
    at or after `start_at`, and its last word is before `end_before` (exclusive) when given.
    """
    target = normalize(phrase).split()
    if not target:
        return None
    stream = _token_stream(words)
    n = len(target)
    for i in range(len(stream) - n + 1):
        tok, first_idx, is_first, _ = stream[i]
        if first_idx < start_at or not is_first or tok != target[0]:
            continue
        window = stream[i : i + n]
        if [t for t, _, _, _ in window] != target or not window[-1][3]:
            continue
        last_idx = window[-1][1]
        if end_before is not None and last_idx >= end_before:
            return None  # later matches only end further right
        return first_idx, last_idx
    return None


def find_phrase(words: list[Word], phrase: str, start_at: int = 0) -> int | None:
    """Index of the first word of the first normalized match of `phrase` at or after start_at."""
    span = find_phrase_span(words, phrase, start_at)
    return span[0] if span else None
