"""Caption layout (screens and lines by character count) and the ASS writer (spec section 9)."""
from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, replace

from shorts.timeline import TimeMap
from shorts.words import Word

SEGMENT_MAX = 30  # characters per screen before a segment is split into several screens
LINE_MAX = 16  # a screen up to this many characters is a single line
PAUSE_BREAK = 0.7  # seconds between word starts that closes a segment...
PAUSE_MIN_CHARS = 12  # ...but only once the segment has this many characters
COMMA_MIN_CHARS = 14  # a comma closes a segment once it has this many characters
FN_PENALTY = 6  # cost added to a line split that leaves a function word at a line end

FUNCTION_WORDS = {
    "pt": {
        "a", "o", "as", "os", "e", "de", "da", "do", "das", "dos", "na", "no", "nas", "nos",
        "em", "um", "uma", "se", "que", "ou", "mas", "por", "pra", "para", "com", "ao", "à",
        "esse", "essa", "este", "esta", "aquele", "aquela", "meu", "minha", "seu", "sua",
        "nosso", "nossa",
    },
    "en": {
        "the", "a", "an", "of", "to", "and", "or", "but", "in", "on", "at", "for", "with",
        "from", "by", "as", "is", "that", "this", "my", "your", "our", "their", "his", "her",
    },
}

_ACCENTED = set("ÁÉÍÓÚÂÊÔÃÕÀÜ")
_TALL_TOP = set("ÇQ,;")


@dataclass(frozen=True)
class Screen:
    lines: list[list[int]]  # word indices into the clip word list, 1 or 2 lines


@dataclass(frozen=True)
class CaptionStyle:
    font: str = "Anton"
    size: int = 128
    outline: int = 6
    primary: str = "&H00FFFFFF"
    highlight: str = "&H00E5FF&"
    x: int = 547
    baseline_y: int = 1060
    pitch: int = 104
    pitch_tall: int = 116



def caption_style(channel) -> CaptionStyle:
    """The style of a render: the default, with the baseline a job setting may move."""
    y = getattr(channel, "caption_y", None)
    return CaptionStyle() if y is None else replace(CaptionStyle(), baseline_y=y)


def _chars(words: list[Word], ids: list[int]) -> int:
    return sum(len(words[i].w) for i in ids) + max(len(ids) - 1, 0)


def _is_fn(word: Word, lang: str) -> bool:
    bare = word.w.lower().strip(".,;:!?…\"'”’()")
    return bare in FUNCTION_WORDS.get(lang, set())


def _segments(words: list[Word]) -> list[list[int]]:
    segs: list[list[int]] = []
    cur: list[int] = []
    for i, word in enumerate(words):
        cur.append(i)
        nxt = words[i + 1].t if i + 1 < len(words) else None
        n = _chars(words, cur)
        last = word.w.rstrip("\"'”’)")[-1:]
        if (
            nxt is None
            or (last and last in ".?!…")
            or (nxt - word.t > PAUSE_BREAK and n >= PAUSE_MIN_CHARS)
            or (last and last in ",;:" and n >= COMMA_MIN_CHARS)
        ):
            segs.append(cur)
            cur = []
    return segs


def _split_screens(words: list[Word], seg: list[int], lang: str) -> list[list[int]]:
    """Split a long segment into k screens of similar length (k = ceil(chars / 30)).

    Tries every set of split points and keeps the one with the smallest squared deviation
    from the average length; a screen ending on a function word costs FN_PENALTY squared.
    """
    total = _chars(words, seg)
    k = math.ceil(total / SEGMENT_MAX)
    if k <= 1 or len(seg) < k:
        return [seg]
    if k > 3:  # keep the exhaustive search small: optimise ~90-character pieces separately
        pieces: list[list[int]] = []
        acc: list[int] = []
        for j in seg:
            if acc and _chars(words, acc + [j]) > 3 * SEGMENT_MAX:
                pieces.append(acc)
                acc = []
            acc.append(j)
        pieces.append(acc)
        return [s for piece in pieces for s in _split_screens(words, piece, lang)]
    target = total / k
    best: tuple[float, list[list[int]]] | None = None
    for cuts in itertools.combinations(range(1, len(seg)), k - 1):
        bounds = (0, *cuts, len(seg))
        parts = [seg[bounds[i] : bounds[i + 1]] for i in range(k)]
        cost = sum((_chars(words, part) - target) ** 2 for part in parts)
        cost += sum(FN_PENALTY**2 for part in parts[:-1] if _is_fn(words[part[-1]], lang))
        if best is None or cost < best[0]:
            best = (cost, parts)
    assert best is not None
    return best[1]


def _split_lines(words: list[Word], screen: list[int], lang: str) -> list[list[int]]:
    if _chars(words, screen) <= LINE_MAX or len(screen) == 1:
        return [screen]

    def cost(k: int) -> int:
        a, b = screen[:k], screen[k:]
        penalty = FN_PENALTY if _is_fn(words[a[-1]], lang) else 0
        return abs(_chars(words, a) - _chars(words, b)) + penalty

    best = min(range(1, len(screen)), key=cost)
    return [screen[:best], screen[best:]]


def build_screens(words: list[Word], lang: str) -> list[Screen]:
    """Lay the clip's words out into screens of one or two balanced lines."""
    screens: list[Screen] = []
    for seg in _segments(words):
        for scr in _split_screens(words, seg, lang):
            screens.append(Screen(lines=_split_lines(words, scr, lang)))
    return screens


def line_pitch(top: str, bottom: str, style: CaptionStyle) -> int:
    """Baseline distance between two lines; taller when a descender sits above an accent."""
    if set(top.upper()) & _TALL_TOP and set(bottom.upper()) & _ACCENTED:
        return style.pitch_tall
    return style.pitch


def _ass_time(t: float) -> str:
    t = max(t, 0.0)
    cs = int(round(t * 100))
    h, rem = divmod(cs, 360000)
    m, rem = divmod(rem, 6000)
    s, cs = divmod(rem, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _clean(text: str) -> str:
    """Caption text is data: no ASS override braces, no backslashes, no line breaks (a word
    corrected on the review page could carry a newline that would split the event)."""
    for ch in "{}\\":
        text = text.replace(ch, "")
    return " ".join(text.split()).upper()


def _header(style: CaptionStyle) -> str:
    return (
        "[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\nWrapStyle: 2\n"
        "ScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Cap,{style.font},{style.size},{style.primary},{style.primary},&H00000000,"
        f"&H00000000,0,0,0,0,100,100,1,0,1,{style.outline},0,2,70,55,860,1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )


def render_ass(
    words: list[Word], screens: list[Screen], tm: TimeMap, style: CaptionStyle, clip_end: float
) -> str:
    """ASS file text: one event per word per line; the spoken word is highlighted."""
    reset = "&H" + style.primary[-6:] + "&"
    events: list[str] = []
    starts = [tm.snap_to_clip(words[s.lines[0][0]].t) for s in screens]
    for si, screen in enumerate(screens):
        order = [i for line in screen.lines for i in line]
        screen_end = starts[si + 1] if si + 1 < len(screens) else clip_end
        texts = [" ".join(_clean(words[i].w) for i in line) for line in screen.lines]
        pitch = line_pitch(texts[0], texts[1], style) if len(texts) == 2 else style.pitch
        for k, wi in enumerate(order):
            a = tm.snap_to_clip(words[wi].t)
            b = tm.snap_to_clip(words[order[k + 1]].t) if k + 1 < len(order) else screen_end
            if b <= a:
                continue
            n = len(screen.lines)
            for li, line in enumerate(screen.lines):
                # A one-line screen sits at the upper line's height, so the eye stays at one height
                # (owner, 2026-10-01); two lines keep the lower line on the baseline.
                y = style.baseline_y - (n - 1 - li) * pitch if n > 1 else style.baseline_y - style.pitch
                parts = [
                    f"{{\\c{style.highlight}}}{_clean(words[i].w)}{{\\c{reset}}}" if i == wi
                    else _clean(words[i].w)
                    for i in line
                ]
                events.append(
                    f"Dialogue: 0,{_ass_time(a)},{_ass_time(b)},Cap,,0,0,0,,"
                    f"{{\\an2\\pos({style.x},{y})}}{' '.join(parts)}"
                )
    return _header(style) + "\n".join(events) + "\n"
