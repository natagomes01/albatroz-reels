"""JSON schemas for every LLM pass (spec 6.7)."""
import copy

_DIM = {"type": "object", "required": ["score", "why"], "additionalProperties": False,
        "properties": {"score": {"type": "integer", "minimum": 0, "maximum": 10},
                       "why": {"type": "string"}}}

SCAN = {
    "type": "object", "required": ["windows"], "additionalProperties": False,
    "properties": {"windows": {"type": "array", "items": {
        "type": "object", "required": ["id", "score", "reason"], "additionalProperties": False,
        "properties": {"id": {"type": "string"},
                       "score": {"type": "integer", "minimum": 0, "maximum": 100},
                       "reason": {"type": "string"}}}}},
}

_SEGMENT = {"type": "object", "required": ["window_id", "first_words", "last_words"],
            "additionalProperties": False,
            "properties": {"window_id": {"type": "string"},
                           "first_words": {"type": "string", "minLength": 1},
                           "last_words": {"type": "string", "minLength": 1}}}

DETAIL = {
    "type": "object", "required": ["candidates"], "additionalProperties": False,
    "properties": {"candidates": {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "required": ["segments", "out_of_order", "title", "hook", "scores", "controversy",
                     "who_reacts", "emphasis", "hook_id"],
        "properties": {
            "segments": {"type": "array", "minItems": 1, "maxItems": 3, "items": _SEGMENT},
            "out_of_order": {"type": "boolean"},
            "title": {"type": "string", "minLength": 1, "maxLength": 60},
            "hook": {"type": "string"},
            "scores": {"type": "object", "additionalProperties": False,
                       "required": ["hook", "value", "conversation", "emotion"],
                       "properties": {k: _DIM for k in ("hook", "value", "conversation", "emotion")}},
            "controversy": {"type": "object", "required": ["level", "why"], "additionalProperties": False,
                            "properties": {"level": {"type": "integer", "enum": [0, 1, 2]},
                                           "why": {"type": "string"}}},
            "who_reacts": {"type": "string"},
            "emphasis": {"type": "array", "minItems": 1, "maxItems": 3, "items": {"type": "string"}},
            "hook_id": {"type": "string"},
        }}}},
}

REVIEW_BLIND = {
    "type": "object", "required": ["results"], "additionalProperties": False,
    "properties": {"results": {"type": "array", "items": {
        "type": "object", "required": ["id", "stands_alone", "why", "suggest_earlier_start"],
        "additionalProperties": False,
        "properties": {"id": {"type": "string"}, "stands_alone": {"type": "boolean"},
                       "why": {"type": "string"}, "suggest_earlier_start": {"type": "boolean"}}}}},
}

REVIEW_FAITHFUL = {
    "type": "object", "required": ["results"], "additionalProperties": False,
    "properties": {"results": {"type": "array", "items": {
        "type": "object", "required": ["id", "faithful", "why"], "additionalProperties": False,
        "properties": {"id": {"type": "string"}, "faithful": {"type": "boolean"},
                       "why": {"type": "string"}}}}},
}

FIX_KINDS = ("foreign_term", "proper_name", "scripture", "mishearing", "split_or_joined_word",
             "punctuation")

# Caption-fix pass (caption spec 4.3). Only types here: slot and token counts, token length and
# the 0.6 confidence floor are checked in code, so a bad edit is dropped, not retried.
CAPTION_FIX = {
    "type": "object", "required": ["edits"], "additionalProperties": False,
    "properties": {"edits": {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "required": ["first", "last", "tokens", "kind", "reason", "confidence"],
        "properties": {"first": {"type": "integer"}, "last": {"type": "integer"},
                       "tokens": {"type": "array", "items": {"type": "string"}},
                       "kind": {"type": "string", "enum": list(FIX_KINDS)},
                       "reason": {"type": "string"},
                       "confidence": {"type": "number", "minimum": 0, "maximum": 1}}}}},
}

CLASS_SHEET = {
    "type": "object", "additionalProperties": False,
    "required": ["topic", "references", "terms", "variable_spellings"],
    "properties": {
        "topic": {"type": "string"},
        "references": {"type": "array", "items": {"type": "string"}},
        "terms": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["term", "language"],
            "properties": {"term": {"type": "string"}, "language": {"type": "string"}}}},
        "variable_spellings": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["heard", "spelling"],
            "properties": {"heard": {"type": "string"}, "spelling": {"type": "string"}}}},
    },
}

BROLL_KINDS = ("painting", "photo", "video", "own")
BROLL = {
    "type": "object", "required": ["moments"], "additionalProperties": False,
    "properties": {"moments": {"type": "array", "maxItems": 6, "items": {
        "type": "object", "additionalProperties": False,
        "required": ["first", "last", "layout", "kind", "terms", "note"],
        "properties": {"first": {"type": "integer"}, "last": {"type": "integer"},
                       "layout": {"type": "string", "enum": ["full", "split"]},
                       "kind": {"type": "string", "enum": list(BROLL_KINDS)},
                       "terms": {"type": "array", "maxItems": 3, "items": {"type": "string"}},
                       "note": {"type": "string"}}}}},
}


def for_batch(schema: dict, list_key: str, ids: list[str]) -> dict:
    """Pin a list-shaped schema to one batch: every id exactly once, nothing invented.
    Uniqueness is implied by enum + count only if ids repeat nowhere, so uniqueItems is not
    enough on objects; the caller also checks for duplicates after validation."""
    s = copy.deepcopy(schema)
    arr = s["properties"][list_key]
    arr["minItems"] = len(ids)
    arr["maxItems"] = len(ids)
    arr["items"]["properties"]["id"] = {"type": "string", "enum": list(ids)}
    return s
