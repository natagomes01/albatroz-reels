import pytest

from shorts.analyze.class_sheet import (EMPTY_SHEET, LIMITS, run_class_sheet, sheet_block,
                                        sheet_digest)
from shorts.llm.base import LLMError
from shorts.words import Word, sentences

SHEET = {"topic": "Salmo 22 na Septuaginta", "references": ["Salmos 22,17"],
         "terms": [{"term": "kaaru", "language": "hebraico"}],
         "variable_spellings": [{"heard": "caro", "spelling": "kaaru"}]}


def words_of(n):
    return [Word(i * 0.5, f"w{i}" + ("." if i % 10 == 9 else ""), 0.9) for i in range(n)]


class SheetStub:
    model = "stub"

    def __init__(self, fail=None, refs=None):
        self.users, self.fail, self.refs = [], fail, refs

    def complete(self, system, user, schema):
        assert "You write the class sheet" in system
        self.users.append(user)
        if self.fail:
            raise self.fail
        out = dict(SHEET, topic=f"{SHEET['topic']} ({len(self.users)})")
        if self.refs is not None:
            out["references"] = self.refs
        return out


def dict_cache():
    store = {}
    return store.get, store.__setitem__


def test_one_call_for_a_short_class_and_the_cache_is_reused():
    w = words_of(1587)
    get, put = dict_cache()
    b = SheetStub()
    s1 = run_class_sheet(w, sentences(w), "# Channel", "Salmo 22", b, cache=get, store=put)
    assert len(b.users) == 1 and s1["topic"] == "Salmo 22 na Septuaginta (1)"
    b2 = SheetStub()
    assert run_class_sheet(w, sentences(w), "# Channel", "Salmo 22", b2, cache=get, store=put) == s1
    assert b2.users == []


def test_long_class_is_read_in_parts_that_carry_the_sheet_so_far():
    w = words_of(13000)
    b = SheetStub()
    run_class_sheet(w, sentences(w), "# Channel", "", b)
    assert len(b.users) == 3
    assert "Transcript part 2 of 3" in b.users[1]
    assert "Salmo 22 na Septuaginta (1)" in b.users[1]           # the first reply is the sheet so far


def test_topic_and_channel_block_reach_the_request_and_change_the_key():
    w = words_of(100)
    get, put = dict_cache()
    b = SheetStub()
    run_class_sheet(w, sentences(w), "# Channel X\nNOTES", "tópico A", b, cache=get, store=put)
    assert "tópico A" in b.users[0] and "NOTES" in b.users[0]
    b2 = SheetStub()
    run_class_sheet(w, sentences(w), "# Channel X\nNOTES", "tópico B", b2, cache=get, store=put)
    assert len(b2.users) == 1


def test_schema_failure_keeps_the_sheet_so_far_and_logs():
    w = words_of(100)
    events = []
    s = run_class_sheet(w, sentences(w), "#", "", SheetStub(fail=LLMError("bad shape", "schema")),
                        log=events.append)
    assert s == EMPTY_SHEET and events[0]["kind"] == "class_sheet_failed"


def test_usage_limit_propagates():
    w = words_of(100)
    with pytest.raises(LLMError) as e:
        run_class_sheet(w, sentences(w), "#", "", SheetStub(fail=LLMError("hit your limit", "limit")))
    assert e.value.kind == "limit"


def test_empty_transcript_makes_no_call():
    b = SheetStub()
    assert run_class_sheet([], [], "#", "", b) == EMPTY_SHEET and b.users == []


def test_long_lists_are_trimmed():
    w = words_of(100)
    s = run_class_sheet(w, sentences(w), "#", "", SheetStub(refs=[f"Salmos {i}" for i in range(100)]))
    assert len(s["references"]) == LIMITS["references"] == 40


def test_sheet_block_and_digest():
    block = sheet_block(SHEET)
    assert "Class topic: Salmo 22 na Septuaginta" in block and "Salmos 22,17" in block
    assert "kaaru (hebraico)" in block and "caro -> kaaru" in block
    assert "(none)" in sheet_block(EMPTY_SHEET)
    assert sheet_digest(SHEET) != sheet_digest(EMPTY_SHEET) and len(sheet_digest(SHEET)) == 64
