import jsonschema
import pytest

from shorts.analyze import schemas
from shorts.analyze.prompts import load_prompt


@pytest.mark.parametrize("name", ["scan", "detail", "review_blind", "review_faithful",
                                  "class_sheet", "caption_fix"])
def test_prompts_load_with_hash(name):
    text, h = load_prompt(name)
    assert len(text) > 200 and len(h) == 64


def test_detail_prompt_has_rubric_and_rules():
    text, _ = load_prompt("detail")
    for needle in ["hook", "value", "conversation", "emotion", "STANDS ALONE",
                   "NEVER QUOTE-MINE", "who_reacts", "emphasis", "hook_id", "out_of_order",
                   "first 6 and the last 6 words"]:
        assert needle in text


def test_detail_schema_accepts_good_and_rejects_four_segments():
    seg = {"window_id": "w1", "first_words": "a b c d e f", "last_words": "g h i j k l"}
    dim = {"score": 7, "why": "x"}
    cand = {"segments": [seg], "out_of_order": False, "title": "T", "hook": "H",
            "scores": {"hook": dim, "value": dim, "conversation": dim, "emotion": dim},
            "controversy": {"level": 1, "why": "x"}, "who_reacts": "w",
            "emphasis": ["e"], "hook_id": "h1"}
    jsonschema.validate({"candidates": [cand]}, schemas.DETAIL)
    jsonschema.validate({"candidates": []}, schemas.DETAIL)
    bad = dict(cand, segments=[seg] * 4)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"candidates": [bad]}, schemas.DETAIL)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"candidates": [dict(cand, title="x" * 61)]}, schemas.DETAIL)


def test_scan_schema():
    jsonschema.validate({"windows": [{"id": "w1", "score": 80, "reason": "r"}]}, schemas.SCAN)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"windows": [{"id": "w1", "score": 101, "reason": "r"}]}, schemas.SCAN)


def test_review_schemas():
    jsonschema.validate({"results": [{"id": "c01", "stands_alone": True, "why": "ok",
                                      "suggest_earlier_start": False}]}, schemas.REVIEW_BLIND)
    jsonschema.validate({"results": [{"id": "c01", "faithful": False, "why": "drops qualifier"}]},
                        schemas.REVIEW_FAITHFUL)


def test_for_batch_pins_ids_and_count():
    s = schemas.for_batch(schemas.SCAN, "windows", ["w1", "w2"])
    ok = {"windows": [{"id": "w1", "score": 1, "reason": "r"}, {"id": "w2", "score": 2, "reason": "r"}]}
    jsonschema.validate(ok, s)
    with pytest.raises(jsonschema.ValidationError):      # one missing
        jsonschema.validate({"windows": ok["windows"][:1]}, s)
    with pytest.raises(jsonschema.ValidationError):      # invented id
        jsonschema.validate({"windows": [ok["windows"][0], dict(ok["windows"][1], id="w9")]}, s)
    # the shared constant is untouched
    assert "enum" not in schemas.SCAN["properties"]["windows"]["items"]["properties"]["id"]


def test_caption_fix_schema():
    ok = {"edits": [{"first": 1089, "last": 1091, "tokens": ["lamá", "sabactâni?"],
                     "kind": "foreign_term", "reason": "citação aramaica", "confidence": 0.9}]}
    jsonschema.validate(ok, schemas.CAPTION_FIX)
    jsonschema.validate({"edits": []}, schemas.CAPTION_FIX)
    e = ok["edits"][0]
    for bad in (dict(e, kind="style"), dict(e, confidence=1.5), {k: v for k, v in e.items() if k != "reason"}):
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate({"edits": [bad]}, schemas.CAPTION_FIX)
    # counts and lengths are the code's job (fixwords.check_edit), so a reply is not retried for them
    jsonschema.validate({"edits": [dict(e, tokens=["a"] * 13)]}, schemas.CAPTION_FIX)


def test_class_sheet_schema():
    ok = {"topic": "Salmo 22 na Septuaginta", "references": ["Salmos 22,17"],
          "terms": [{"term": "kaaru", "language": "hebraico"}],
          "variable_spellings": [{"heard": "caro", "spelling": "kaaru"}]}
    jsonschema.validate(ok, schemas.CLASS_SHEET)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({k: v for k, v in ok.items() if k != "terms"}, schemas.CLASS_SHEET)


def test_caption_prompts_state_the_rules():
    text, _ = load_prompt("caption_fix")
    for needle in ["You correct automatic captions", "paraphrase", "reorder", "register", "number word",
                   "0.5", "not a target", "read-only", '{"edits": []}', "foreign_term",
                   "split_or_joined_word", "content language", "0.6"]:
        assert needle in text, needle
    sheet, _ = load_prompt("class_sheet")
    for needle in ["You write the class sheet", "topic", "references", "terms",
                   "variable_spellings", "sheet so far"]:
        assert needle in sheet, needle
