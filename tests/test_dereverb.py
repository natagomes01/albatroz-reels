import pytest

from shorts.config import ChannelConfig
from shorts.dereverb import (GATE_MESSAGE, StrengthNotChosen, check_level, class_strength,
                             effective_strength, gate, parse_levels)

CH = ChannelConfig(id="catholic-br", language="pt", brand_dir=None, glossary="")


def test_parse_levels_sorts_and_needs_off():
    assert parse_levels([20, 0, 10, 30]) == (0, 10, 20, 30)
    for bad in ([], [10, 20], [0, 0, 10], [0, 101], [0, True], [0, 2.5], "0,10"):
        with pytest.raises(ValueError):
            parse_levels(bad)


def test_check_level():
    assert check_level(20, (0, 10, 20, 30)) == 20
    for bad in (15, "20", True, None, 20.0):
        with pytest.raises(ValueError):
            check_level(bad, (0, 10, 20, 30))


def test_class_strength_ignores_hand_edited_non_integers():
    assert class_strength({"dereverb": 20}) == 20
    assert class_strength({"dereverb": 0}) == 0
    for bad in ({}, {"dereverb": "20"}, {"dereverb": True}, {"dereverb": None}, {"dereverb": 2.0}):
        assert class_strength(bad) is None


def test_effective_strength_prefers_the_clip_override():
    review = {"dereverb": 20}
    assert effective_strength(review, {}) == 20
    assert effective_strength(review, {"dereverb": 30}) == 30
    assert effective_strength(review, {"dereverb": 0}) == 0
    assert effective_strength(review, {"dereverb": "30"}) == 20
    assert effective_strength({}, {}) is None
    assert effective_strength({}, {"dereverb": 10}) == 10


def test_gate():
    with pytest.raises(StrengthNotChosen, match=GATE_MESSAGE):
        gate(CH, {"decisions": {}})
    gate(CH, {"decisions": {}, "dereverb": 0})                       # off is a choice
    gate(ChannelConfig(id="x", language="pt", brand_dir=None, glossary="", sound=False), {})
    gate(CH, {}, has_audio=lambda: False)                              # a silent master
    assert GATE_MESSAGE == "choose the audio strength on the review page first"
