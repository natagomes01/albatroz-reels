import json

import pytest

from shorts.words import Word, find_phrase, find_phrase_span, load_words, normalize, sentences


def ws(text, step=0.3, t0=0.0):
    return [Word(t0 + i * step, w, 1.0) for i, w in enumerate(text.split())]


def test_words_roundtrip(tmp_path):
    p = tmp_path / "a.palavras.json"
    p.write_text(json.dumps({"version": 1, "words": [{"t": 1.0, "p": 0.9, "w": "Olá,"}, {"t": 1.4, "p": 1.0, "w": "mundo."}]}), encoding="utf-8")
    assert load_words(p) == [Word(1.0, "Olá,", 0.9), Word(1.4, "mundo.", 1.0)]


def test_words_backwards_rejected(tmp_path):
    p = tmp_path / "a.json"
    p.write_text(json.dumps({"version": 1, "words": [{"t": 2.0, "p": 1, "w": "a"}, {"t": 1.0, "p": 1, "w": "b"}]}), encoding="utf-8")
    with pytest.raises(ValueError, match="backwards"):
        load_words(p)


def test_sentences_and_find():
    w = ws("Não é óbvio? Aí você vai ter uma corrente. Fim")
    assert sentences(w) == [s for s in sentences(w)]
    assert [(s.first, s.last) for s in sentences(w)] == [(0, 2), (3, 8), (9, 9)]
    assert normalize("Não é ÓBVIO?!") == "nao e obvio"
    assert find_phrase(w, "aí VOCÊ vai") == 3
    assert find_phrase(w, "você vai", start_at=5) is None


def test_find_span_hyphen_and_contractions():
    w = ws("Ele chama-se Pedro. I don't know, it's fine")
    assert find_phrase_span(w, "chama-se Pedro") == (1, 2)
    assert find_phrase_span(w, "CHAMA SE pedro") == (1, 2)
    assert find_phrase_span(w, "don't know") == (4, 5)
    assert find_phrase_span(w, "it's fine") == (6, 7)
    # a match may not start or end in the middle of a word
    assert find_phrase_span(w, "se Pedro") is None
    assert find_phrase_span(w, "Ele chama") is None


def test_find_span_skips_words_without_letters():
    w = ws("Deus — é ... amor.")
    assert find_phrase_span(w, "Deus é amor") == (0, 4)
    assert find_phrase(w, "é amor") == 2


def test_find_span_bounds_for_repeated_phrases():
    w = ws("a b c a b c")
    assert find_phrase_span(w, "a b") == (0, 1)
    assert find_phrase_span(w, "a b", start_at=1) == (3, 4)
    assert find_phrase_span(w, "a b", start_at=1, end_before=4) is None
    assert find_phrase_span(w, "a b", end_before=2) == (0, 1)
    assert find_phrase_span(w, "") is None


def test_load_words_malformed(tmp_path):
    import pytest
    from shorts.words import load_words
    for body in ('{"version": 1, "words": [{"t": 1}]}', '{"version": 1', '[1]'):
        p = tmp_path / "w.json"
        p.write_text(body, encoding="utf-8")
        with pytest.raises(ValueError, match="malformed words file"):
            load_words(p)
