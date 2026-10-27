import json

import pytest

from shorts import jobs
from shorts.review.state import apply_edit, merge_suggestion, redo, set_pick, undo


def make_job(tmp_path):
    job = jobs.create_job(tmp_path, "j", {"channel": "catholic-br", "format": "solo-standing",
                                          "master": "/m.mp4", "warnings": []})
    jobs.write_json_atomic(job.words_json, {"version": 1, "words": [{"t": i * 0.5, "w": f"w{i}.", "p": 1}
                                                                   for i in range(200)]})
    cand = {"id": "c01", "window_id": "w1", "title": "T", "hook": "H", "total": 70.0,
            "segments": [{"window_id": "w1", "first_words": "", "last_words": "",
                          "proposed": [0, 40], "snapped": [0, 40]}],
            "scores": {}, "controversy": 1, "controversy_why": "", "who_reacts": "",
            "emphasis": [], "hook_id": "h01", "out_of_order": False, "too_long": False,
            "blind": None, "faithful": None, "verdict": "publish", "warnings": []}
    jobs.write_json_atomic(job.candidates_json, {"candidates": [cand], "groups": {"h01": ["c01"]}})
    return job


def moment(mid, first, last, origin="llm", **kw):
    return {"id": mid, "origin": origin, "first": first, "last": last, "layout": "full", "fit": "cover",
            "pan": "still", "focus": [0.5, 0.5], "terms": ["altar"], "note": "", "pick": None, **kw}


PICK = {"source": "commons", "id": "1", "kind": "image", "file": "commons-1.jpg", "download_url": "u",
        "w": 4000, "h": 2000, "duration": None, "title": "T", "author": "A", "license": "CC BY 4.0",
        "license_url": "", "page_url": "p"}


def saved(job):
    return json.loads(job.review_json.read_text(encoding="utf-8"))["decisions"]["c01"]


def test_broll_edit_validates_and_saves(tmp_path):
    job = make_job(tmp_path)
    res = apply_edit(job, "c01", {"broll": [moment("s1", 10, 15)]})
    assert res["broll"][0]["id"] == "s1" and saved(job)["broll"][0]["terms"] == ["altar"]
    with pytest.raises(ValueError):
        apply_edit(job, "c01", {"broll": [moment("s1", 10, 500)]})
    assert saved(job)["broll"][0]["last"] == 15                      # nothing written on error


def test_an_empty_list_removes_the_key(tmp_path):
    job = make_job(tmp_path)
    apply_edit(job, "c01", {"broll": [moment("s1", 10, 15)]})
    apply_edit(job, "c01", {"broll": []})
    assert "broll" not in saved(job)


def test_broll_edits_undo_and_redo(tmp_path):
    job = make_job(tmp_path)
    apply_edit(job, "c01", {"broll": [moment("s1", 10, 15)]})
    apply_edit(job, "c01", {"broll": [moment("s1", 10, 15, layout="split")]})
    assert undo(job, "c01")["broll"][0]["layout"] == "full"
    assert redo(job, "c01")["broll"][0]["layout"] == "split"


def test_cut_change_drops_moments_and_one_undo_restores_both(tmp_path):
    job = make_job(tmp_path)
    apply_edit(job, "c01", {"broll": [moment("s1", 10, 15), moment("o1", 60, 65, origin="owner")]})
    res = apply_edit(job, "c01", {"segments": [[0.0, 20.0]]})
    assert [m["id"] for m in res["broll"]] == ["s1"] and res["broll_dropped"] == ["o1"]
    back = undo(job, "c01")
    assert "segments" not in back and [m["id"] for m in back["broll"]] == ["s1", "o1"]
    assert "broll_dropped" not in apply_edit(job, "c01", {"title": "Novo"})


def test_a_cut_that_drops_every_moment_removes_the_key(tmp_path):
    job = make_job(tmp_path)
    apply_edit(job, "c01", {"broll": [moment("s1", 60, 65)]})
    apply_edit(job, "c01", {"segments": [[0.0, 20.0]]})
    assert "broll" not in saved(job)


def test_merge_keeps_owner_moments_and_replaces_old_suggestions(tmp_path):
    job = make_job(tmp_path)
    apply_edit(job, "c01", {"broll": [moment("s1", 10, 15), moment("o1", 60, 65, origin="owner")]})
    res = merge_suggestion(job, "c01", [moment("s1", 30, 35), moment("s2", 40, 45)])
    assert [(m["id"], m["first"]) for m in res["broll"]] == [("o1", 60), ("s1", 30), ("s2", 40)]
    assert undo(job, "c01")["broll"][0]["first"] == 10              # one step
    res = merge_suggestion(job, "c01", [])
    assert [m["id"] for m in res["broll"]] == ["o1"]


def test_merge_never_exceeds_six_moments(tmp_path):
    job = make_job(tmp_path)
    owners = [moment(f"o{i}", 10 * i, 10 * i + 3, origin="owner") for i in range(1, 6)]
    apply_edit(job, "c01", {"broll": owners})
    res = merge_suggestion(job, "c01", [moment("s1", 2, 4), moment("s2", 5, 7)])
    assert len(res["broll"]) == 6 and res["broll"][-1]["id"] == "s1"


def test_set_pick_applies_the_defaults(tmp_path):
    job = make_job(tmp_path)
    apply_edit(job, "c01", {"broll": [moment("s1", 10, 15)]})
    res = set_pick(job, "c01", "s1", PICK)
    m = res["broll"][0]
    assert m["pick"]["file"] == "commons-1.jpg" and (m["fit"], m["pan"]) == ("cover", "ltr")
    small = {**PICK, "source": "pixabay", "w": 1280, "h": 853}
    m = set_pick(job, "c01", "s1", small)["broll"][0]
    assert (m["fit"], m["pan"]) == ("whole", "still")
    assert undo(job, "c01")["broll"][0]["pick"]["w"] == 4000
    with pytest.raises(ValueError, match="unknown moment"):
        set_pick(job, "c01", "s9", PICK)
    with pytest.raises(ValueError):
        set_pick(job, "c01", "s1", {**PICK, "file": "../x.jpg"})


def test_merge_after_the_cut_was_trimmed_drops_the_out_of_clip_moment(tmp_path):
    job = make_job(tmp_path)
    apply_edit(job, "c01", {"segments": [[0.0, 20.0]]})
    res = merge_suggestion(job, "c01", [moment("s1", 60, 65), moment("s2", 10, 15)])
    assert [m["id"] for m in res["broll"]] == ["s2"] and res["broll_dropped"] == ["s1"]
    assert "broll" not in undo(job, "c01")                           # one undo step


def test_a_direct_broll_edit_drops_moments_outside_the_clip(tmp_path):
    job = make_job(tmp_path)
    res = apply_edit(job, "c01", {"broll": [moment("s1", 10, 15), moment("o1", 100, 105, origin="owner")]})
    assert [m["id"] for m in res["broll"]] == ["s1"] and res["broll_dropped"] == ["o1"]
    assert [m["id"] for m in saved(job)["broll"]] == ["s1"]
    assert "broll_dropped" not in apply_edit(job, "c01", {"broll": [moment("s1", 10, 15)]})
