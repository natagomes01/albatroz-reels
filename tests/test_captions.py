from shorts.captions import CaptionStyle, build_screens, line_pitch, render_ass
from shorts.timeline import Span, TimeMap
from shorts.words import Word


def ws(text, step=0.3, t0=0.0):
    return [Word(t0 + i * step, w, 1.0) for i, w in enumerate(text.split())]


def lines(words, lang):
    return [[" ".join(words[i].w.upper() for i in ln) for ln in s.lines] for s in build_screens(words, lang)]


def test_golden_pt_moses():
    w = ws("Aí eu li isso a primeira vez, eu falei, ué, mas se foi Moisés que escreveu esse livro, esse pedacinho aqui foi outra pessoa. Não é óbvio?")
    assert lines(w, "pt") == [
        ["AÍ EU LI ISSO", "A PRIMEIRA VEZ,"],
        ["EU FALEI, UÉ,", "MAS SE FOI"],
        ["MOISÉS QUE ESCREVEU", "ESSE LIVRO,"],
        ["ESSE PEDACINHO", "AQUI"],
        ["FOI OUTRA", "PESSOA."],
        ["NÃO É ÓBVIO?"],
    ]


def test_golden_pt_criticism():
    w = ws("Aí você vai ter uma corrente acadêmica surgida no século XVIII, que é a crítica textual, que virou moda, explodiu no meio protestante")
    assert lines(w, "pt") == [
        ["AÍ VOCÊ VAI TER"],
        ["UMA CORRENTE", "ACADÊMICA"],
        ["SURGIDA", "NO SÉCULO XVIII,"],
        ["QUE É A CRÍTICA", "TEXTUAL,"],
        ["QUE VIROU MODA,"],
        ["EXPLODIU NO MEIO", "PROTESTANTE"],
    ]


def test_golden_en():
    w = ws("So the thing is, the Bible was never a single book, it was a library of seventy three books.")
    assert lines(w, "en") == [
        ["SO THE THING IS,"],
        ["THE BIBLE", "WAS NEVER"],
        ["A SINGLE BOOK,"],
        ["IT WAS A LIBRARY"],
        ["OF SEVENTY", "THREE BOOKS."],
    ]


def test_long_unpunctuated_segment_is_fast_and_bounded():
    w = [Word(i * 0.3, "palavra", 1.0) for i in range(200)]
    screens = build_screens(w, "pt")
    assert all(1 <= len(s.lines) <= 2 for s in screens)
    assert sum(len(ln) for s in screens for ln in s.lines) == 200


def test_line_pitch():
    st = CaptionStyle()
    assert line_pitch("MOISÉS QUE ESCREVEU,", "É ÓBVIO", st) == 116
    assert line_pitch("AÍ EU LI", "ÓBVIO", st) == 104
    assert line_pitch("TEXTUAL,", "QUE VIROU MODA", st) == 104


def test_blank_word_does_not_close_a_segment():
    w = [Word(0.0, "eu", 1.0), Word(0.3, "", 1.0), Word(0.6, "falei", 1.0)]
    assert len(build_screens(w, "pt")) == 1


def test_caption_style_follows_the_channel_baseline():
    from dataclasses import replace
    from shorts.captions import CaptionStyle, caption_style
    from shorts.config import ChannelConfig
    ch = ChannelConfig(id="x", language="pt", brand_dir=None, glossary="")
    assert caption_style(ch) == CaptionStyle()
    assert caption_style(replace(ch, caption_y=1300)).baseline_y == 1300
