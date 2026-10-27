import argparse
import json

import pytest

from shorts import jobs
from shorts.broll import timing
from shorts.broll.model import BrollConfig
from shorts.broll.paths import result_path, thumbs_dir
from shorts.broll.sources import SourceError
from shorts.broll.suggest import build_request, clip_lines, read_result, suggest_clip
from shorts.config import AppConfig, ChannelConfig
from shorts.llm.base import LLMError
from shorts.llm.context import current_context
from shorts.stages import approved_clips
from shorts.timeline import Span, TimeMap
from shorts.words import Word

CH = ChannelConfig(id="catholic-br", language="pt", brand_dir=None, glossary="")
SPAN = Span(9.65, 50.45)


def make_job(tmp_path, decision=None):
    job = jobs.create_job(tmp_path / "jobs", "260927-a", {
        "channel": "catholic-br", "format": "solo-standing", "master": str(tmp_path / "m.mp4"),
        "topic": "Salmo 22"})
    words = [{"t": i * 0.5, "w": f"w{i}" + ("." if i % 10 == 9 else ""), "p": 1} for i in range(400)]
    jobs.write_json_atomic(job.words_json, {"version": 1, "words": words})
    cand = {"id": "c01", "window_id": "w1", "title": "T", "hook": "H", "total": 80.0,
            "segments": [{"window_id": "w1", "first_words": "", "last_words": "",
                          "proposed": [10.0, 50.0], "snapped": [SPAN.start, SPAN.end]}],
            "scores": {}, "controversy": 1, "controversy_why": "", "who_reacts": "P",
            "emphasis": [], "hook_id": "h01", "out_of_order": False, "too_long": False,
            "blind": None, "faithful": None, "verdict": "publish", "warnings": []}
    jobs.write_json_atomic(job.candidates_json, {"candidates": [cand], "groups": {"h01": ["c01"]}})
    jobs.write_json_atomic(job.review_json, {"decisions": {"c01": {"status": "approved", **(decision or {})}}})
    return job


def app(tmp_path):
    return AppConfig(media_root=tmp_path / "media", jobs_dir=tmp_path / "jobs", backends={},
                     broll=BrollConfig(user_agent="ua"))


class Stub:
    model = "claude-haiku-4-5"

    def __init__(self, replies):
        self.replies, self.users, self.passes = list(replies), [], []

    def complete(self, system, user, schema):
        self.users.append(user)
        self.passes.append(current_context()["pass"])
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def moment(first, last, kind="painting", layout="full", terms=("Last Supper painting",), note="why"):
    return {"first": first, "last": last, "layout": layout, "kind": kind, "terms": list(terms), "note": note}


REPLY = {"moments": [moment(26, 31), moment(30, 33), moment(20, 23), moment(60, 65, kind="own", terms=()),
                     moment(5, 8)]}
COMMONS = {"query": {"pages": {"1": {"pageid": 1, "index": 1, "title": "File:Ceia.jpg", "imageinfo": [{
    "width": 4000, "height": 3000, "mime": "image/jpeg", "descriptionurl": "https://c/File:Ceia.jpg",
    "extmetadata": {"LicenseShortName": {"value": "Public domain"}, "Artist": {"value": "Leonardo"},
                    "ObjectName": {"value": "Ceia"}}}]}}}}


def fetch(url, headers):
    if url.startswith("https://commons.wikimedia.org/w/api.php"):
        return json.dumps(COMMONS).encode()
    if url.startswith("https://commons.wikimedia.org/wiki/Special:FilePath/"):
        return b"jpg"
    raise SourceError(f"no route for {url}")


def plain_map(job, clip_id, channel, spans, words, master):
    return TimeMap(list(spans))


def run(tmp_path, job, stub, **kw):
    plan = approved_clips(job)[0]
    return suggest_clip(job, app(tmp_path), CH, plan, stub, {}, fetch=fetch, clip_map_fn=plain_map,
                        now=0, **kw)


def test_rules_drop_moments_and_kept_ones_are_renumbered(tmp_path):
    job = make_job(tmp_path)
    res = run(tmp_path, job, Stub([REPLY]))
    assert [(m["id"], m["first"], m["last"]) for m in res["moments"]] == [("s1", 26, 31), ("s2", 60, 65)]
    assert res["kinds"] == {"s1": "painting", "s2": "own"}
    assert all(m["origin"] == "llm" and m["pan"] == "still" and m["pick"] is None for m in res["moments"])
    log = [json.loads(line) for line in job.log_path.read_text(encoding="utf-8").splitlines()]
    dropped = {e["moment"]: e["reason"] for e in log if e["kind"] == "broll_dropped"}
    assert dropped == {"p2": "overlaps p1", "p3": "starts in the first 3 s",
                       "p5": "word index outside the clip"}
    assert read_result(job, "c01") == res and result_path(job, "c01").exists()


def test_own_moments_get_no_search_and_paintings_get_candidates(tmp_path):
    job = make_job(tmp_path)
    res = run(tmp_path, job, Stub([REPLY]))
    own = res["moments"][1]
    assert own["fit"] == "whole" and own["terms"] == [] and "s2" not in res["candidates"]
    assert [c["key"] for c in res["candidates"]["s1"]] == ["commons-1"]
    assert (thumbs_dir(app(tmp_path), job) / "commons-1.jpg").exists()


def test_the_pass_is_named_cached_and_force_asks_again(tmp_path):
    job = make_job(tmp_path)
    stub = Stub([REPLY, REPLY])
    run(tmp_path, job, stub)
    assert stub.passes == ["broll"]
    run(tmp_path, job, stub)
    assert len(stub.users) == 1                                 # cache hit
    run(tmp_path, job, stub, force=True)
    assert len(stub.users) == 2


def test_a_bad_reply_shape_is_an_error_and_is_not_cached(tmp_path):
    job = make_job(tmp_path)
    stub = Stub([LLMError("bad shape", "schema"), REPLY])
    res = run(tmp_path, job, stub)
    assert res["moments"] == [] and res["errors"] == ["the model's reply had the wrong shape; Try again"]
    res = run(tmp_path, job, stub)
    assert len(res["moments"]) == 2


def test_a_usage_limit_is_raised(tmp_path):
    job = make_job(tmp_path)
    with pytest.raises(LLMError):
        run(tmp_path, job, Stub([LLMError("limit", "limit")]))
    assert read_result(job, "c01") is None


def test_request_carries_owner_fixes_topic_and_rules(tmp_path):
    job = make_job(tmp_path, {"word_fixes": {"30": "Ceia", "31": ""}})
    jobs.write_json_atomic(job.class_sheet_json, {"sheet": {"topic": "A Última Ceia"}})
    stub = Stub([REPLY])
    run(tmp_path, job, stub)
    user = stub.users[0]
    assert "\n30|5.3|Ceia\n" in user and "|w31" not in user          # fix applied, dropped word gone
    assert "Class topic: A Última Ceia" in user and "content language: pt" in user
    assert "at most 10 s" in user and "together at most 50% of the clip (40.8 s long)" in user
    assert "no moment starts before 3 s or ends after 38.8 s" in user


def test_clip_lines_map_to_clip_time():
    raw = [Word(i * 0.5, f"w{i}", 1.0) for i in range(20)]
    tm = TimeMap([Span(2.0, 4.0), Span(5.0, 8.0)])
    lines = clip_lines(raw, {"5": "X", "11": ""}, [Span(2.0, 4.0), Span(5.0, 8.0)], tm)
    assert lines[:2] == [(4, 0.0, "w4"), (5, 0.5, "X")]
    assert (8, 2.0, "w8") not in lines and (10, 2.0, "w10") in lines and all(i != 11 for i, _, _ in lines)


def test_build_request_without_topic():
    text = build_request([(1, 0.0, "a")], "", CH, BrollConfig(), 20.0)
    assert "Class topic: (not given)" in text and "\n1|0.0|a\n" in text


def test_clip_map_reuses_the_edl_or_makes_and_writes_it(tmp_path):
    job = make_job(tmp_path)
    words = [Word(i * 0.5, f"w{i}", 1.0) for i in range(100)]
    calls = []

    def detect(master, seg):
        calls.append(seg)
        return [Span(20.0, 22.0)]

    tm = timing.clip_map(job, "c01", CH, [SPAN], words, tmp_path / "m.mp4", detect=detect,
                         has_audio=lambda: True)
    assert len(calls) == 1 and tm.duration < SPAN.duration
    saved = json.loads((job.clip_dir("c01") / "edl.json").read_text(encoding="utf-8"))
    assert saved["segments"] == [[SPAN.start, SPAN.end]]
    tm2 = timing.clip_map(job, "c01", CH, [SPAN], words, tmp_path / "m.mp4", detect=detect,
                          has_audio=lambda: True)
    assert len(calls) == 1 and tm2.duration == pytest.approx(tm.duration)
    from dataclasses import replace
    tm3 = timing.clip_map(job, "c01", replace(CH, silence=False), [Span(9.65, 40.0)], words,
                          tmp_path / "m.mp4", detect=detect, has_audio=lambda: True)
    assert len(calls) == 1 and tm3.duration == pytest.approx(40.0 - 9.65, abs=0.05)


def test_cli_registers_broll():
    from shorts.cli_jobs import register
    parser = argparse.ArgumentParser()
    register(parser.add_subparsers())
    args = parser.parse_args(["broll", "j", "--clip", "c01", "--clip", "c02", "--force"])
    assert args.job == "j" and args.clip == ["c01", "c02"] and args.force


def test_repo_prompt_names_every_kind_and_the_schema_matches():
    from shorts.analyze.prompts import load_prompt
    from shorts.analyze.schemas import BROLL, BROLL_KINDS
    text, _ = load_prompt("broll")
    assert all(f'"{k}"' in text for k in BROLL_KINDS) and "English" in text
    item = BROLL["properties"]["moments"]["items"]
    assert set(item["required"]) == {"first", "last", "layout", "kind", "terms", "note"}


def test_topic_whitespace_is_collapsed(tmp_path):
    from shorts.broll.suggest import _topic
    job = make_job(tmp_path)
    jobs.write_json_atomic(job.class_sheet_json, {"sheet": {"topic": "  A Última\n\nCeia \t do  Senhor "}})
    assert _topic(job) == "A Última Ceia do Senhor"
