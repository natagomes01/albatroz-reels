import json
from pathlib import Path

from shorts.analyze.detail import detail_user, run_detail
from shorts.analyze.profile import ChannelProfile
from shorts.analyze.scan import ScanResult
from shorts.analyze.windows import build_windows
from shorts.words import Word, sentences

FIX = Path(__file__).parent / "fixtures" / "llm"
PROFILE = ChannelProfile("catholic-br", "pt", "icp", "aud")
WEIGHTS = {"hook": .30, "value": .25, "conversation": .25, "emotion": .20}


def cls():
    ws, t = [], 0.0
    for s in range(60):
        for k in range(10):
            ws.append(Word(round(t, 3), f"p{s}q{k}" + ("." if k == 9 else ""), 1.0))
            t += 0.5
        t += 0.5
    return ws


WS = cls()
SENTS = sentences(WS)
WINS = build_windows(WS, SENTS)
DUR = WS[-1].t + 1.0


class Stub:
    model = "stub"

    def __init__(self, replies):
        self.replies, self.users = list(replies), []

    def complete(self, system, user, schema):
        self.users.append(user)
        return self.replies.pop(0)


def test_user_message_marks_target_and_lists_companions():
    sel = [ScanResult("w1", 90, "r1"), ScanResult("w3", 80, "r3")]
    msg = detail_user(WINS[0], sel, {w.id: w for w in WINS}, WS, PROFILE)
    assert "<<<TARGET w1>>>" in msg and "<<<END TARGET>>>" in msg
    assert "[w3]" in msg and "r3" in msg
    assert "Companion window [w3]" in msg


def test_run_detail_snaps_scores_and_drops_unmatched():
    logs = []
    stub = Stub([json.loads((FIX / "detail_w1.json").read_text(encoding="utf-8"))])
    cands = run_detail([ScanResult("w1", 90, "r")], WINS, WS, SENTS, PROFILE, stub, WEIGHTS,
                       DUR, log=logs.append)
    assert len(cands) == 1
    c = cands[0]
    assert c.id == "w1-1" and c.total == round((8 * .30 + 7 * .25 + 9 * .25 + 6 * .20) * 10, 1)
    assert 30 <= c.duration() <= 60
    assert c.controversy == 1 and c.who_reacts.startswith("Protestant")
    assert c.llm_hook_id == "w1:moses" and not c.too_long and not c.too_short
    assert any(e["kind"] == "candidate_dropped" and "first_words" in e["reason"] for e in logs)


def test_detail_cache():
    store = {}
    stub = Stub([json.loads((FIX / "detail_w1.json").read_text(encoding="utf-8"))])
    run_detail([ScanResult("w1", 90, "r")], WINS, WS, SENTS, PROFILE, stub, WEIGHTS, DUR,
               cache=store.get, store=store.__setitem__)
    stub2 = Stub([])
    again = run_detail([ScanResult("w1", 90, "r")], WINS, WS, SENTS, PROFILE, stub2, WEIGHTS, DUR,
                       cache=store.get, store=store.__setitem__)
    assert len(again) == 1 and stub2.users == []
