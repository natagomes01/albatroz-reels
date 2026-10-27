import pytest

from shorts.llm.base import LLMBackend, LLMError, parse_json_payload

SCHEMA = {"type": "object", "required": ["n"], "properties": {"n": {"type": "integer"}},
          "additionalProperties": False}


class Fake(LLMBackend):
    name = "fake"

    def __init__(self, replies, **kw):
        super().__init__("m", **kw)
        self.replies = list(replies)
        self.users = []

    def _call(self, system, user, schema):
        self.users.append(user)
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return r, {"input_tokens": 10, "output_tokens": 2}


def test_valid_reply_returns_dict_and_logs():
    logged = []
    b = Fake([{"n": 1}], log=logged.append)
    assert b.complete("s", "u", SCHEMA) == {"n": 1}
    assert logged[0]["backend"] == "fake" and logged[0]["input_tokens"] == 10 and logged[0]["ok"]


def test_string_payload_with_fences_is_parsed():
    assert parse_json_payload('```json\n{"n": 2}\n```') == {"n": 2}


def test_schema_failure_retries_twice_then_raises():
    b = Fake([{"n": "x"}, {"n": "y"}, {"n": "z"}])
    with pytest.raises(LLMError) as e:
        b.complete("s", "u", SCHEMA)
    assert e.value.kind == "schema"
    assert len(b.users) == 3
    assert "did not match the schema" in b.users[1]


def test_schema_failure_then_success():
    b = Fake([{"n": "x"}, {"n": 3}])
    assert b.complete("s", "u", SCHEMA) == {"n": 3}


def test_transient_error_backs_off_then_succeeds():
    slept = []
    b = Fake([LLMError("overloaded", "transient"), {"n": 4}], sleep=slept.append)
    assert b.complete("s", "u", SCHEMA) == {"n": 4}
    assert slept == [2]


def test_transient_exhausted_raises():
    b = Fake([LLMError("x", "transient")] * 4, sleep=lambda s: None)
    with pytest.raises(LLMError) as e:
        b.complete("s", "u", SCHEMA)
    assert e.value.kind == "transient"


def test_limit_error_is_not_retried():
    b = Fake([LLMError("usage limit reached", "limit"), {"n": 1}], sleep=lambda s: None)
    with pytest.raises(LLMError) as e:
        b.complete("s", "u", SCHEMA)
    assert e.value.kind == "limit"
    assert len(b.users) == 1


def test_unparseable_string_counts_as_schema_failure():
    b = Fake(["not json", {"n": 1}])
    assert b.complete("s", "u", SCHEMA) == {"n": 1}
