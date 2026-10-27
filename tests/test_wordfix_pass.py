from shorts.analyze.fixwords import (build_request, chunk_key, chunk_lines, chunk_span,
                                     neighbor_context, select_chunks)
from shorts.analyze.textutil import text_of
from shorts.analyze.windows import Chunk, build_chunks
from shorts.words import Word, sentences


def words_of(n):
    return [Word(i * 0.5, f"w{i}" + ("." if i % 10 == 9 else ""), 0.95) for i in range(n)]


def test_chunk_lines_are_index_word_confidence():
    w = [Word(393.43, "la", 0.414), Word(393.89, "massa", 0.38)]
    assert chunk_lines(w, Chunk(0, 0, 1)) == "0|la|0.41\n1|massa|0.38"


def test_request_carries_every_layer_and_read_only_context():
    w = words_of(60)
    s = sentences(w)
    user = build_request(w, s, Chunk(1, 20, 39), "# Channel: catholic-br\nCAPTION NOTES HERE",
                         "Salmo 22", "Class topic: SHEET TOPIC\n")
    assert "CAPTION NOTES HERE" in user and "Topic from the owner: Salmo 22" in user
    assert "SHEET TOPIC" in user
    assert text_of(w, 10, 19) in user and text_of(w, 40, 49) in user       # neighbor sentences
    assert "\n20|w20|0.95\n" in user and "\n39|w39.|0.95\n" in user
    assert "|w19.|" not in user and "|w40|" not in user                    # context is not editable
    assert "indices 20 to 39" in user


def test_class_edges_are_marked():
    w = words_of(20)
    s = sentences(w)
    assert neighbor_context(w, s, Chunk(0, 0, 19)) == ("", "")
    user = build_request(w, s, Chunk(0, 0, 19), "#", "", "")
    assert "(start of the class)" in user and "(end of the class)" in user
    assert "Topic from the owner: (not given)" in user


def test_neighbor_context_is_capped_in_an_unpunctuated_transcript():
    w = [Word(i * 0.5, f"w{i}", 0.9) for i in range(1000)]
    before, after = neighbor_context(w, sentences(w), Chunk(1, 400, 599))
    assert before == text_of(w, 340, 399) and after == text_of(w, 600, 659)


def test_scope_default_and_all():
    w = words_of(600)
    chunks = build_chunks(sentences(w))
    assert [(c.first, c.last) for c in chunks] == [(0, 499), (400, 599)]
    assert chunk_span(w, chunks[0]) == (0.0, 250.0)
    assert select_chunks(chunks, w, [(10.0, 50.0)]) == chunks[:1]
    assert select_chunks(chunks, w, [(10.0, 50.0)], all_chunks=True) == chunks
    assert select_chunks(chunks, w, [(255.0, 270.0)]) == chunks      # the 60 s pad reaches chunk 0
    assert select_chunks(chunks, w, []) == []


def test_chunk_key_changes_with_each_input():
    base = dict(lines="0|a|1.00", context="x", prompt_hash="p", model="m", glossary_digest="g",
                notes_digest="n", sheet_digest="s", topic="t")
    k = chunk_key(**base)
    assert chunk_key(**base) == k
    for field in base:
        assert chunk_key(**{**base, field: base[field] + "2"}) != k, field


# ---- validation, overlap and storage (Task 8) ----
import json

import pytest

from shorts import jobs
from shorts.analyze.fixwords import ChunkRejected, check_chunk, resolve, write_corrections
from shorts.wordfix import Edit, read_edits

W100 = [Word(i * 0.5, f"w{i}", 0.9) for i in range(100)]
C100 = Chunk(0, 0, 99)


def raw_edit(first, last, tokens, confidence=0.9, kind="mishearing"):
    return {"first": first, "last": last, "tokens": tokens, "kind": kind, "reason": "r",
            "confidence": confidence}


@pytest.mark.parametrize("raw,reason", [
    (raw_edit(-1, 0, ["x"]), "range"),
    (raw_edit(5, 4, ["x"]), "range"),
    (raw_edit(99, 100, ["x"]), "range"),
    ({"first": "3", "last": 3, "tokens": ["x"], "confidence": 0.9}, "range"),
    (raw_edit(0, 12, ["x"]), "too_many_slots"),
    (raw_edit(1, 1, []), "tokens"),
    (raw_edit(1, 1, ["a"] * 13), "tokens"),
    (raw_edit(1, 1, [""]), "tokens"),
    (raw_edit(1, 1, ["x" * 41]), "tokens"),
    (raw_edit(1, 1, ["{\\an8}x"]), "tokens"),
    (raw_edit(1, 1, ["a\\Nb"]), "tokens"),
    (raw_edit(1, 1, ["a b"]), "tokens"),
    (raw_edit(1, 1, ["x"], confidence=0.59), "low_confidence"),
    (raw_edit(1, 1, ["x"], confidence=float("nan")), "low_confidence"),
    (raw_edit(1, 1, ["w1"]), "no_change"),
    ("not an object", "shape"),
])
def test_each_bad_edit_is_dropped_with_its_reason(raw, reason):
    edits, drops = check_chunk({"edits": [raw]}, W100, C100)
    assert edits == [] and [d["reason"] for d in drops] == [reason]
    assert drops[0]["kind"] == "fixword_dropped" and drops[0]["chunk"] == 0


def test_a_good_edit_is_kept():
    edits, drops = check_chunk({"edits": [raw_edit(3, 5, ["lamá", "sabactâni?"])]}, W100, C100)
    assert edits == [Edit(3, 5, ("lamá", "sabactâni?"), "mishearing", "r", 0.9)] and drops == []


def test_indices_outside_this_chunk_are_out_of_range():
    _, drops = check_chunk({"edits": [raw_edit(10, 10, ["x"])]}, W100, Chunk(1, 20, 99))
    assert drops[0]["reason"] == "range"


def test_more_than_15_percent_edited_rejects_the_chunk():
    many = [raw_edit(i, i, [f"x{i}"]) for i in range(16)]
    with pytest.raises(ChunkRejected, match="more than 15%"):
        check_chunk({"edits": many}, W100, C100)
    edits, _ = check_chunk({"edits": many[:15]}, W100, C100)          # exactly 15% is allowed
    assert len(edits) == 15


def test_overlap_keeps_the_higher_confidence_and_duplicates_count_once():
    a = Edit(1, 2, ("a",), confidence=0.7)
    b = Edit(2, 3, ("b",), confidence=0.9)
    c = Edit(8, 8, ("c",), confidence=0.8)
    c2 = Edit(8, 8, ("c",), confidence=0.95)                         # same edit from the next chunk
    kept, drops = resolve([a, b, c, c2])
    assert kept == [b, c2]
    assert [d["reason"] for d in drops] == ["overlap"] and drops[0]["first"] == 1


def test_corrections_round_trip_and_stale_words_are_ignored(tmp_path):
    job = jobs.create_job(tmp_path, "j", {})
    jobs.write_json_atomic(job.words_json, {"version": 1, "words": [{"t": 0.0, "w": "a.", "p": 1.0}]})
    e = Edit(0, 0, ("A.",), "punctuation", "r", 0.8)
    write_corrections(job, [e], model="stub")
    data = json.loads(job.corrections_json.read_text(encoding="utf-8"))
    assert data["version"] == 1 and data["model"] == "stub" and data["edits"] == [e.to_dict()]
    assert data["words_hash"] == jobs.file_hash(job.words_json)
    assert read_edits(job) == [e]
    jobs.write_json_atomic(job.words_json, {"version": 1, "words": [{"t": 0.0, "w": "b.", "p": 1.0}]})
    assert read_edits(job) == []                                     # re-transcribed: stale
    job.corrections_json.unlink()
    assert read_edits(job) == []


@pytest.mark.parametrize("payload", [
    ["not", "a", "dict"],
    {"words_hash": "x"},
    {"edits": None},
    {"edits": [{"first": 0}]},
    {"edits": ["nope"]},
])
def test_malformed_corrections_read_as_no_edits(tmp_path, payload):
    job = jobs.create_job(tmp_path, "j", {})
    jobs.write_json_atomic(job.words_json, {"version": 1, "words": [{"t": 0.0, "w": "a.", "p": 1.0}]})
    if isinstance(payload, dict):
        payload = {"words_hash": jobs.file_hash(job.words_json), **payload}
    jobs.write_json_atomic(job.corrections_json, payload)
    assert read_edits(job) == []


# ---- run_fixwords (Task 9) ----
from shorts.analyze.fixwords import run_fixwords
from shorts.config import AppConfig, ChannelConfig
from shorts.llm.base import LLMError

ARAMAIC_SLOTS = {37: "la", 38: "massa", 39: "bactamia."}


def make_job(tmp_path, n=600, candidates=None, topic="", decisions=None):
    words = [{"t": i * 0.5, "w": ARAMAIC_SLOTS.get(i, f"w{i}" + ("." if i % 10 == 9 else "")),
              "p": 0.4 if i in ARAMAIC_SLOTS else 0.95} for i in range(n)]
    job = jobs.create_job(tmp_path / "jobs", "260927-a", {
        "channel": "catholic-br", "format": "solo-standing", "duration": n * 0.5, "topic": topic})
    jobs.write_json_atomic(job.words_json, {"version": 1, "words": words})
    if candidates is None:
        candidates = [{"id": "c01", "segments": [{"snapped": [10.0, 50.0]}]}]
    jobs.write_json_atomic(job.candidates_json, {"candidates": candidates, "groups": {}})
    if decisions is not None:
        jobs.write_json_atomic(job.review_json, {"decisions": decisions})
    return job


def channel(tmp_path, notes="Write `Eloí, Eloí, lamá sabactâni` as in Marcos 15,34."):
    brand = tmp_path / "brand"
    brand.mkdir(exist_ok=True)
    if notes is not None:
        (brand / "captions.md").write_text(notes, encoding="utf-8")
    return ChannelConfig(id="catholic-br", language="pt", brand_dir=brand, glossary="Septuaginta")


def app(tmp_path):
    return AppConfig(media_root=tmp_path / "media", jobs_dir=tmp_path / "jobs", backends={})


def aramaic(user):
    if "\n37|la|0.40\n" in user:
        return {"edits": [{"first": 37, "last": 39, "tokens": ["lamá", "sabactâni?"],
                           "kind": "foreign_term", "reason": "citação aramaica (Marcos 15,34)",
                           "confidence": 0.93}]}
    return {"edits": []}


class FixStub:
    model = "stub"
    name = "stub-backend"

    def __init__(self, reply=None, limit_on_fix=None, schema_error=False):
        self.reply = reply or (lambda user: {"edits": []})
        self.limit_on_fix, self.schema_error = limit_on_fix, schema_error
        self.kinds, self.fix_users, self.sheet_users = [], [], []

    def complete(self, system, user, schema):
        if "You write the class sheet" in system:
            self.kinds.append("sheet")
            self.sheet_users.append(user)
            return {"topic": "Salmo 22 e a Septuaginta", "references": ["Salmos 22,17"],
                    "terms": [{"term": "kaaru", "language": "hebraico"}], "variable_spellings": []}
        assert "You correct automatic captions" in system
        self.kinds.append("fix")
        self.fix_users.append(user)
        if self.limit_on_fix is not None and self.kinds.count("fix") == self.limit_on_fix:
            raise LLMError("You've hit your limit", "limit")
        if self.schema_error:
            raise LLMError("response did not match the schema after 3 attempts", "schema")
        return self.reply(user)


def run(tmp_path, job, b, **kw):
    return run_fixwords(job, app(tmp_path), channel(tmp_path), tmp_path,
                        backends={"class_sheet": b, "caption_fix": b}, **kw)


def events_of(job):
    return [json.loads(line) for line in job.log_path.read_text(encoding="utf-8").splitlines()]


def test_writes_corrections_and_class_sheet_and_never_touches_words(tmp_path):
    job = make_job(tmp_path)
    before = jobs.file_hash(job.words_json)
    b = FixStub(aramaic)
    res = run(tmp_path, job, b)
    assert res == {"edits": 1, "dropped": 0, "chunks": 1, "total_chunks": 2, "rejected": 0}
    assert b.kinds == ["sheet", "fix"]
    data = json.loads(job.corrections_json.read_text(encoding="utf-8"))
    assert data["edits"] == [{"first": 37, "last": 39, "tokens": ["lamá", "sabactâni?"],
                              "kind": "foreign_term", "reason": "citação aramaica (Marcos 15,34)",
                              "confidence": 0.93}]
    assert [(c["first_word"], c["last_word"]) for c in data["chunks"]] == [(0, 499)]
    assert data["model"] == "stub" and data["words_hash"] == before
    assert json.loads(job.class_sheet_json.read_text(encoding="utf-8"))["sheet"]["topic"] == "Salmo 22 e a Septuaginta"
    assert jobs.file_hash(job.words_json) == before
    assert read_edits(job) == [Edit(37, 39, ("lamá", "sabactâni?"), "foreign_term",
                                    "citação aramaica (Marcos 15,34)", 0.93)]


def test_all_runs_every_chunk(tmp_path):
    b = FixStub()
    res = run(tmp_path, make_job(tmp_path), b, all_chunks=True)
    assert b.kinds.count("fix") == 2 and res["chunks"] == 2


def test_scope_follows_edited_segments_on_the_review_page(tmp_path):
    job = make_job(tmp_path, decisions={"c01": {"status": "approved", "segments": [[200.0, 230.0]]}})
    b = FixStub()
    run(tmp_path, job, b)
    assert b.kinds.count("fix") == 2


def test_no_chunk_in_scope_needs_no_backend(tmp_path):
    job = make_job(tmp_path, candidates=[])
    res = run_fixwords(job, app(tmp_path), channel(tmp_path), tmp_path)   # no [backends.*] at all
    assert res["chunks"] == 0 and json.loads(job.corrections_json.read_text(encoding="utf-8"))["edits"] == []


def test_limit_then_rerun_makes_only_the_missing_call(tmp_path):
    job = make_job(tmp_path)
    b1 = FixStub(aramaic, limit_on_fix=2)
    with pytest.raises(LLMError) as e:
        run(tmp_path, job, b1, all_chunks=True)
    assert e.value.kind == "limit" and not job.corrections_json.exists()
    b2 = FixStub(aramaic)
    res = run(tmp_path, job, b2, all_chunks=True)
    assert b2.kinds == ["fix"] and res["edits"] == 1       # sheet and chunk 0 come from the cache
    b3 = FixStub(aramaic)
    run(tmp_path, job, b3, all_chunks=True, force=True)
    assert b3.kinds == ["sheet", "fix", "fix"]             # --force ignores the cache


def test_empty_answer_is_fine(tmp_path):
    job = make_job(tmp_path)
    res = run(tmp_path, job, FixStub())
    assert res["edits"] == 0 and json.loads(job.corrections_json.read_text(encoding="utf-8"))["edits"] == []


def test_bad_reply_shape_is_dropped_chunk_by_chunk(tmp_path):
    job = make_job(tmp_path)
    res = run(tmp_path, job, FixStub(schema_error=True), all_chunks=True)
    assert res["edits"] == 0 and res["dropped"] == 2
    assert [e["reason"] for e in events_of(job) if e["kind"] == "fixword_dropped"] == [
        "reply_shape", "reply_shape"]


def test_rewrite_guard_rejects_only_that_chunk_and_caches_nothing_for_it(tmp_path):
    def rewrite(user):
        if "\n37|la|0.40\n" in user:
            return {"edits": [{"first": i, "last": i, "tokens": [f"x{i}"], "kind": "mishearing",
                               "reason": "r", "confidence": 0.9} for i in range(100)]}
        return {"edits": [{"first": 550, "last": 550, "tokens": ["Tobias"], "kind": "proper_name",
                           "reason": "livro", "confidence": 0.9}]}
    job = make_job(tmp_path)
    res = run(tmp_path, job, FixStub(rewrite), all_chunks=True)
    assert res["rejected"] == 1 and res["edits"] == 1
    assert json.loads(job.corrections_json.read_text(encoding="utf-8"))["edits"][0]["tokens"] == ["Tobias"]
    assert len(list((job.analyze_dir / "cache" / "wordfix").glob("*.json"))) == 1
    assert any(e["kind"] == "fixword_chunk_rejected" and "more than 15%" in e["error"]
               for e in events_of(job))


def test_an_edit_found_by_two_overlapping_chunks_counts_once(tmp_path):
    def both(user):
        if "\n450|w450|0.95\n" in user:
            return {"edits": [{"first": 450, "last": 450, "tokens": ["Deuteronômio"],
                               "kind": "proper_name", "reason": "livro", "confidence": 0.9}]}
        return {"edits": []}
    res = run(tmp_path, make_job(tmp_path), FixStub(both), all_chunks=True)
    assert res["edits"] == 1 and res["dropped"] == 0


def test_each_dropped_edit_is_logged_with_its_reason(tmp_path):
    def weak(user):
        if "\n37|la|0.40\n" in user:
            return {"edits": [{"first": 37, "last": 37, "tokens": ["lá"], "kind": "mishearing",
                               "reason": "?", "confidence": 0.4}]}
        return {"edits": []}
    job = make_job(tmp_path)
    res = run(tmp_path, job, FixStub(weak))
    assert res["dropped"] == 1
    assert [e["reason"] for e in events_of(job) if e["kind"] == "fixword_dropped"] == ["low_confidence"]


def test_topic_from_ingest_and_the_override(tmp_path):
    job = make_job(tmp_path, topic="Salmo 22 na Septuaginta")
    b = FixStub()
    run(tmp_path, job, b)
    assert "Topic from the owner: Salmo 22 na Septuaginta" in b.fix_users[0]
    assert "Topic from the owner: Salmo 22 na Septuaginta" in b.sheet_users[0]
    b2 = FixStub()
    run(tmp_path, job, b2, topic="Crítica textual")
    assert "Topic from the owner: Crítica textual" in b2.fix_users[0]
    assert "Salmo 22 na Septuaginta" not in b2.fix_users[0]
    assert b2.kinds == ["sheet", "fix"]                      # a new topic is a new cache key


def test_request_carries_notes_glossary_topic_sheet_and_neighbor_context(tmp_path):
    job = make_job(tmp_path, topic="Salmo 22")
    b = FixStub()
    run(tmp_path, job, b, all_chunks=True)
    second = b.fix_users[1]                                  # words 400-599
    assert "Eloí, Eloí, lamá sabactâni" in second and "Glossary: Septuaginta" in second
    assert "Topic from the owner: Salmo 22" in second and "Salmo 22 e a Septuaginta" in second
    assert "w390 w391" in second and "\n400|w400|0.95\n" in second and "|w399.|" not in second


def test_missing_caption_notes_are_allowed(tmp_path):
    job = make_job(tmp_path)
    b = FixStub()
    run_fixwords(job, app(tmp_path), channel(tmp_path, notes=None), tmp_path,
                 backends={"class_sheet": b, "caption_fix": b})
    assert "## Caption notes\n(none)" in b.fix_users[0]


def test_missing_candidates_without_all_is_a_readable_error(tmp_path):
    job = make_job(tmp_path)
    job.candidates_json.unlink()
    with pytest.raises(FileNotFoundError, match="--all"):
        run(tmp_path, job, FixStub())
    assert run(tmp_path, job, FixStub(), all_chunks=True)["chunks"] == 2


def test_allowed_while_review_holds_decisions_and_never_touches_candidates(tmp_path):
    job = make_job(tmp_path, decisions={"c01": {"status": "approved"}})
    before = job.candidates_json.read_text(encoding="utf-8")
    run(tmp_path, job, FixStub(aramaic))
    assert job.candidates_json.read_text(encoding="utf-8") == before and job.review_json.exists()


# ---- S4 cost accounting hooks (merge of S3 and S4) ----
def test_fixwords_passes_are_named_and_cache_hits_keep_their_cost(tmp_path):
    from shorts.llm.context import current_context

    class Costed(FixStub):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            self.seen, self.last_cost_usd = [], None

        def complete(self, system, user, schema):
            self.seen.append(current_context()["pass"])
            self.last_cost_usd = 0.25 if "You write the class sheet" in system else 0.5
            return super().complete(system, user, schema)

    job = make_job(tmp_path)
    b = Costed(aramaic)
    run(tmp_path, job, b)
    assert b.seen == ["class_sheet", "caption_fix"]
    run(tmp_path, job, Costed(aramaic))                   # second run: everything from the cache
    hits = [(e["pass"], e["saved_usd"]) for e in events_of(job) if e["kind"] == "llm_cache_hit"]
    assert hits == [("class_sheet", 0.25), ("caption_fix", 0.5)]
