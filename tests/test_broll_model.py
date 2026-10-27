import pytest

from shorts.broll.model import (BrollConfig, check_name, clip_range, fill_ok, in_clip, keep_valid,
                                moment_span, next_owner_id, pick_defaults, rule_problems,
                                target_size, validate_moments)
from shorts.timeline import Span, TimeMap
from shorts.words import Word

CFG = BrollConfig()
WORDS = [Word(i * 0.5, f"w{i}", 1.0) for i in range(200)]


def moment(**kw):
    m = {"id": "s1", "origin": "llm", "first": 10, "last": 15, "layout": "full", "fit": "cover",
         "pan": "still", "focus": [0.5, 0.5], "terms": ["Last Supper painting"], "note": "",
         "pick": None}
    m.update(kw)
    return m


PICK = {"source": "commons", "id": "123", "kind": "image", "file": "commons-123.jpg",
        "download_url": "https://x/y.jpg", "w": 4000, "h": 2000, "duration": None,
        "title": "The Last Supper", "author": "Leonardo", "license": "Public domain",
        "license_url": "", "page_url": "https://commons.wikimedia.org/wiki/File:X.jpg"}


def test_validate_moments_accepts_a_full_moment_and_cleans_terms():
    out = validate_moments([moment(terms=["  Last   Supper ", "altar"], pick=PICK)], len(WORDS))
    assert out[0]["terms"] == ["Last Supper", "altar"] and out[0]["pick"]["w"] == 4000


@pytest.mark.parametrize("bad", [
    {"first": 16, "last": 15}, {"first": -1}, {"last": 200}, {"first": True},
    {"layout": "pip"}, {"fit": "zoom"}, {"pan": "zoom"}, {"origin": "x"},
    {"focus": [1.2, 0.5]}, {"focus": [0.5]}, {"focus": ["a", 0.5]},
    {"terms": ["a", "b", "c", "d"]}, {"terms": ["x" * 81]}, {"terms": "Last Supper"},
    {"note": "x" * 201}, {"id": ""}, {"id": "a/b"},
    {"pick": {**PICK, "file": "../x.jpg"}}, {"pick": {**PICK, "source": "unsplash"}},
    {"pick": {**PICK, "kind": "audio"}}, {"pick": {**PICK, "w": 0}}, {"pick": {**PICK, "w": "4000"}},
    {"pick": {**PICK, "duration": -1}}, {"pick": {**PICK, "title": 3}}, {"pick": "x"},
])
def test_validate_moments_rejects_bad_fields(bad):
    with pytest.raises(ValueError):
        validate_moments([moment(**bad)], len(WORDS))


def test_validate_moments_rejects_duplicates_and_too_many():
    with pytest.raises(ValueError, match="unique"):
        validate_moments([moment(), moment()], len(WORDS))
    with pytest.raises(ValueError, match="at most 6"):
        validate_moments([moment(id=f"s{i}") for i in range(7)], len(WORDS))
    with pytest.raises(ValueError, match="list"):
        validate_moments({"id": "s1"}, len(WORDS))


def test_check_name_allows_plain_names_only():
    assert check_name("pexels-123.jpg") == "pexels-123.jpg"
    for bad in ["", ".", "..", "../a.jpg", "a/b.jpg", ".hidden", "a\\b.jpg", "x" * 200, 3]:
        with pytest.raises(ValueError):
            check_name(bad)


def test_target_size_and_fill_rule():
    assert target_size("full") == (1080, 1920) and target_size("split") == (1080, 960)
    # landscape still in full-screen cover: the height limits the fill
    assert fill_ok(4000, 2000, "full", "cover", 1080) and not fill_ok(1280, 853, "full", "cover", 1080)
    # the same 1280 px still is fine as "whole" (long side)
    assert fill_ok(1280, 853, "full", "whole", 1080)
    # portrait in split cover (1080x960): the width limits the fill
    assert fill_ok(1080, 1600, "split", "cover", 1080) and not fill_ok(900, 1600, "split", "cover", 1080)


def test_pick_defaults_set_fit_and_pan_from_the_image():
    # a wide painting in full screen overflows sideways: reading direction
    assert pick_defaults(moment(), PICK, CFG) == ("cover", "ltr")
    # a tall image in split overflows vertically
    tall = {**PICK, "w": 2000, "h": 6000}
    assert pick_defaults(moment(layout="split"), tall, CFG) == ("cover", "ttb")
    # a 1280 px Pixabay still passes only the "whole" minimum in full screen: whole, no motion
    small = {**PICK, "source": "pixabay", "w": 1280, "h": 853}
    assert pick_defaults(moment(), small, CFG) == ("whole", "still")
    # videos never pan; an own moment keeps "whole"
    video = {**PICK, "kind": "video", "duration": 8.0}
    assert pick_defaults(moment(), video, CFG) == ("cover", "still")
    assert pick_defaults(moment(fit="whole"), PICK, CFG) == ("whole", "still")
    assert pick_defaults(moment(), {**PICK, "w": 1080, "h": 1920}, CFG) == ("cover", "still")


def test_moment_span_and_clip_mapping():
    m = moment(first=10, last=15)
    assert moment_span(WORDS, m) == Span(5.0, 8.0)          # word 15 ends at word 16's start
    assert in_clip(WORDS, m, [Span(4.0, 20.0)]) and not in_clip(WORDS, m, [Span(6.0, 20.0)])
    tm = TimeMap([Span(4.0, 6.0), Span(7.0, 20.0)])           # 1 s cut out at 6..7
    assert clip_range(WORDS, m, tm) == pytest.approx((1.0, 3.0))


def test_rule_problems_name_each_rule():
    p = rule_problems({"a": (1.0, 2.5), "b": (2.0, 13.0), "c": (10.0, 14.0), "d": (20.0, 23.0),
                       "e": (27.0, 29.5)}, 30.0, CFG)
    assert "starts in the first 3 s" in p["a"]
    assert "overlaps a" in p["b"] and not any("longer" in x for x in p["b"])   # by hand, no cap
    assert "ends in the last 2 s" in p["e"]
    assert any("more than 3 moments" in x for x in p["d"] + p["e"])
    assert all(any("over 50% of the clip" in x for x in v) for v in p.values())
    assert rule_problems({"a": (5.0, 8.0)}, 30.0, CFG) == {"a": []}


def test_keep_valid_is_greedy_in_start_order():
    kept, dropped = keep_valid({"a": (4.0, 8.0), "b": (7.0, 10.0), "c": (12.0, 16.0),
                                "d": (1.0, 4.0), "e": (20.0, 24.0), "f": (40.0, 44.0)}, 60.0, CFG)
    assert kept == ["a", "c", "e"]
    assert dropped == {"b": "overlaps a", "d": "starts in the first 3 s",
                       "f": "more than 3 moments"}
    kept, dropped = keep_valid({"a": (4.0, 10.0), "b": (11.0, 16.0)}, 20.0, CFG)
    assert kept == ["a"] and dropped == {"b": "together over 50% of the clip"}
    assert keep_valid({"a": (4.0, 15.0)}, 40.0, CFG)[1] == {"a": "longer than 10 s"}   # suggestions are capped


def test_next_owner_id():
    assert next_owner_id([]) == "o1"
    assert next_owner_id([moment(id="s1"), moment(id="o1"), moment(id="o3")]) == "o4"
