from shorts.captions import CaptionStyle, build_screens, render_ass
from shorts.timeline import Span, TimeMap
from shorts.words import Word


def ws(text, step=0.3, t0=0.0):
    return [Word(t0 + i * step, w, 1.0) for i, w in enumerate(text.split())]


def test_render_ass_highlight_and_edl_mapping():
    w = ws("Não é óbvio? Aí você vai ter")
    tm = TimeMap([Span(0, 1.0), Span(1.5, 3.0)])
    text = render_ass(w, build_screens(w, "pt"), tm, CaptionStyle(), tm.duration)
    events = [l for l in text.splitlines() if l.startswith("Dialogue:")]
    assert events[0] == "Dialogue: 0,0:00:00.00,0:00:00.30,Cap,,0,0,0,,{\\an2\\pos(547,956)}{\\c&H00E5FF&}NÃO{\\c&HFFFFFF&} É ÓBVIO?"
    assert "Style: Cap,Anton,128,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,1,0,1,6,0,2,70,55,860,1" in text
    # "Aí" at class 0.9 is inside kept span 1 -> clip 0.9; word at class 1.2 sits in the gap -> snaps to 1.0
    assert any(",0:00:00.90," in e and "{\\c&H00E5FF&}AÍ" in e for e in events)
    assert all("0:00:01.20" not in e.split(",")[1] for e in events)


def test_word_text_cannot_break_the_ass_event():
    w = [Word(0.0, "fé\nlinha", 1.0), Word(0.3, "{\\b1}Deus\r", 1.0)]
    text = render_ass(w, build_screens(w, "pt"), TimeMap([Span(0, 1)]), CaptionStyle(), 1.0)
    body = text.split("[Events]", 1)[1].strip().splitlines()
    # every line of the events section is a Format or Dialogue line: no word text broke a line
    assert all(l.startswith(("Format:", "Dialogue:")) for l in body)
    events = [l for l in body if l.startswith("Dialogue:")]
    assert any("FÉ LINHA" in e for e in events) and any("B1DEUS" in e for e in events)
    assert all("{\\b1}" not in e for e in events)  # override tags from the text never survive


def test_two_line_positions():
    w = ws("Aí eu li isso a primeira vez,")
    tm = TimeMap([Span(0, 5)])
    ev = [l for l in render_ass(w, build_screens(w, "pt"), tm, CaptionStyle(), 5).splitlines() if l.startswith("Dialogue")]
    assert "\\pos(547,956)" in ev[0] and "\\pos(547,1060)" in ev[1]


def test_one_line_screen_sits_at_the_upper_line_height():
    # Owner, 2026-10-01: a lone line on the lower line's height makes the eye jump between heights.
    w = ws("Não é óbvio?")
    tm = TimeMap([Span(0, 5)])
    ev = [l for l in render_ass(w, build_screens(w, "pt"), tm, CaptionStyle(), 5).splitlines()
          if l.startswith("Dialogue")]
    assert ev and all("\\pos(547,956)" in e for e in ev)


def test_one_line_height_follows_the_style():
    w = ws("Não é óbvio?")
    tm = TimeMap([Span(0, 5)])
    st = CaptionStyle(baseline_y=1000, pitch=90)
    ev = [l for l in render_ass(w, build_screens(w, "pt"), tm, st, 5).splitlines()
          if l.startswith("Dialogue")]
    assert ev and all("\\pos(547,910)" in e for e in ev)
