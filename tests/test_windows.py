# tests/test_windows.py
from shorts.analyze.windows import build_windows
from shorts.words import Word, sentences


def make_class(n_sentences=40, words_per=10, step=0.5):
    words, t = [], 0.0
    for s in range(n_sentences):
        for k in range(words_per):
            txt = f"s{s}w{k}" + ("." if k == words_per - 1 else "")
            words.append(Word(t=round(t, 3), w=txt, p=1.0))
            t += step
    return words


def test_windows_cover_class_and_end_on_sentences():
    ws = make_class()                         # 40 sentences x 5 s = 200 s
    wins = build_windows(ws, sentences(ws), length=60, overlap=15)
    assert wins[0].first == 0
    assert wins[-1].last == len(ws) - 1
    for w in wins:
        assert ws[w.last].w.endswith(".")
        assert w.end - w.start >= 55 or w is wins[-1]
    ids = [w.id for w in wins]
    assert ids == [f"w{i + 1}" for i in range(len(wins))]


def test_consecutive_windows_overlap_about_overlap_seconds():
    ws = make_class()
    wins = build_windows(ws, sentences(ws), length=60, overlap=15)
    for a, b in zip(wins, wins[1:]):
        assert a.start < b.start < a.end
        assert 10 <= a.end - b.start <= 20


def test_short_class_gives_one_window():
    ws = make_class(n_sentences=3)
    wins = build_windows(ws, sentences(ws))
    assert len(wins) == 1 and wins[0].text.startswith("s0w0")
    assert wins[0].label().startswith("[w1] 00:00-")


def _sent_words(spans):
    """One sentence per (start, end): two words, the second ending the sentence."""
    ws = []
    for a, b in spans:
        ws += [Word(t=float(a), w="x", p=1.0), Word(t=float(b) - 1.0, w="y.", p=1.0)]
    return ws


def test_empty_word_list_gives_no_windows():
    assert build_windows([], []) == []


def test_single_sentence_longer_than_length_is_one_window():
    ws = _sent_words([(0, 200)])
    wins = build_windows(ws, sentences(ws), length=120)
    assert len(wins) == 1 and wins[0].first == 0 and wins[0].last == 1


def test_no_window_is_a_subset_of_the_previous_one():
    ws = _sent_words([(0, 50), (50, 100), (100, 230), (230, 260)])
    wins = build_windows(ws, sentences(ws), length=120, overlap=30)
    lasts = [w.last for w in wins]
    assert len(lasts) == len(set(lasts))
    for a, b in zip(wins, wins[1:]):
        assert b.last > a.last
    assert wins[-1].last == len(ws) - 1


from shorts.analyze.windows import Chunk, build_chunks  # noqa: E402


def _ten_word_sentences(n_words):
    return [Word(i * 0.5, f"w{i}" + ("." if i % 10 == 9 else ""), 1.0) for i in range(n_words)]


def test_chunks_of_the_10_minute_sample_shape():
    w = _ten_word_sentences(1587)                    # the sample has 1,587 words (spec 10)
    chunks = build_chunks(sentences(w))
    assert [(c.first, c.last) for c in chunks] == [(0, 499), (400, 899), (800, 1299), (1200, 1586)]
    assert [c.id for c in chunks] == [0, 1, 2, 3]
    for a, b in zip(chunks, chunks[1:]):
        assert a.last - b.first + 1 == 100           # 100 words of overlap
    assert all(w[c.last].w.endswith(".") for c in chunks[:-1])   # cut at sentence ends
    assert chunks[-1].last == 1586                    # the trailing fragment is kept


def test_unpunctuated_transcript_still_gives_500_word_chunks():
    w = [Word(i * 0.5, f"w{i}", 1.0) for i in range(1200)]      # no period anywhere
    chunks = build_chunks(sentences(w))
    assert all(c.last - c.first + 1 <= 500 for c in chunks)
    assert chunks[0].first == 0 and chunks[-1].last == 1199
    covered = set()
    for c in chunks:
        covered.update(range(c.first, c.last + 1))
    assert covered == set(range(1200))


def test_chunks_without_overlap_and_empty():
    w = _ten_word_sentences(13000)
    assert [(c.first, c.last) for c in build_chunks(sentences(w), 6000, 0)] == [
        (0, 5999), (6000, 11999), (12000, 12999)]
    assert build_chunks([]) == []
