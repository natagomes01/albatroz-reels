# tests/test_review_state.py
import json

from shorts import jobs
from shorts.review.state import apply_decision, apply_edit, load_state


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


def test_load_state_shapes(tmp_path):
    s = load_state(make_job(tmp_path))
    assert s["job"] == "j" and s["words"][1] == [0.5, "w1."]
    assert s["candidates"][0]["estimated_duration"] > 0
    assert s["review"] == {"decisions": {}}


def test_two_edits_both_survive(tmp_path):
    job = make_job(tmp_path)
    apply_edit(job, "c01", {"title": "Novo"})
    apply_edit(job, "c01", {"segments": [[1.0, 35.0]]})
    apply_decision(job, "c01", "approved")
    d = json.loads(job.review_json.read_text(encoding="utf-8"))["decisions"]["c01"]
    assert d == {"title": "Novo", "segments": [[1.0, 35.0]], "status": "approved"}


def test_word_fix_merges(tmp_path):
    job = make_job(tmp_path)
    apply_edit(job, "c01", {"word_fixes": {"3": "Denzinger"}})
    apply_edit(job, "c01", {"word_fixes": {"5": "Agostinho"}})
    d = json.loads(job.review_json.read_text(encoding="utf-8"))["decisions"]["c01"]
    assert d["word_fixes"] == {"3": "Denzinger", "5": "Agostinho"}


def test_bad_status_rejected(tmp_path):
    import pytest
    job = make_job(tmp_path)
    with pytest.raises(ValueError):
        apply_decision(job, "c01", "maybe")
    with pytest.raises(ValueError, match="unknown clip"):
        apply_decision(job, "c99", "approved")


def test_malformed_edits_are_value_errors(tmp_path):
    import pytest
    job = make_job(tmp_path)
    for bad in ["not a dict", {"segments": "0-40"}, {"segments": [[0, 40, 50]]},
                {"segments": [[10, 5]]}, {"segments": [[0, 30], [20, 50]]},
                {"segments": [[0, 10], [20, 30], [40, 50], [60, 70]]}, {"segments": [[0, 5000]]},
                {"word_fixes": {"9999": "x"}}, {"word_fixes": {"abc": "x"}},
                {"word_fixes": {"3": "  "}}, {"title": 7}, {"nope": 1}]:
        with pytest.raises(ValueError):
            apply_edit(job, "c01", bad)
    assert not job.review_json.exists()          # nothing half-written


def test_word_fix_is_cleaned_of_ass_and_newlines(tmp_path):
    job = make_job(tmp_path)
    apply_edit(job, "c01", {"word_fixes": {"3": "Agos{\\c&H0000FF&}ti\nnho\r"}})
    fixed = json.loads(job.review_json.read_text(encoding="utf-8"))["decisions"]["c01"]["word_fixes"]["3"]
    assert fixed == "Agosc&H0000FF&ti nho"
    assert "{" not in fixed and "}" not in fixed and "\\" not in fixed and "\n" not in fixed


def test_nonfinite_bool_segments_and_nonstring_fix_rejected(tmp_path):
    import pytest
    job = make_job(tmp_path)
    for bad in [{"segments": [[float("nan"), float("nan")]]}, {"segments": [[float("nan"), 5]]},
                {"segments": [[True, 5]]}, {"segments": [[0, float("inf")]]},
                {"segments": [[float("-inf"), 5]]},
                {"word_fixes": {"3": 7}}]:
        with pytest.raises(ValueError):
            apply_edit(job, "c01", bad)
    assert not job.review_json.exists()


def test_corrupt_review_json_names_the_file(tmp_path):
    import pytest
    job = make_job(tmp_path)
    job.review_json.write_text('<<<<<<< HEAD\n{"decisions": {}}\n=======\n>>>>>>> other\n', encoding="utf-8")
    with pytest.raises(ValueError, match="review.json is not valid JSON") as e:
        load_state(job)
    assert str(job.review_json) in str(e.value)
    with pytest.raises(ValueError, match="not valid JSON"):
        apply_decision(job, "c01", "approved")


def test_empty_title_or_hook_and_long_title_are_rejected(tmp_path):
    import pytest
    job = make_job(tmp_path)
    for edit in ({"title": "   "}, {"hook": ""}, {"title": "x" * 61}):
        with pytest.raises(ValueError):
            apply_edit(job, "c01", edit)
    assert not job.review_json.exists()
    apply_edit(job, "c01", {"title": "x" * 60, "hook": "ok"})
    assert json.loads(job.review_json.read_text(encoding="utf-8"))["decisions"]["c01"]["title"] == "x" * 60


def test_empty_word_fix_drops_a_slot_and_range_replace_round_trips(tmp_path):
    from shorts.wordfix import effective_words
    from shorts.words import load_words
    job = make_job(tmp_path)
    apply_edit(job, "c01", {"word_fixes": {"3": "lamá sabactâni?", "4": "", "5": ""}})
    d = json.loads(job.review_json.read_text(encoding="utf-8"))["decisions"]["c01"]
    assert d["word_fixes"] == {"3": "lamá sabactâni?", "4": "", "5": ""}
    out = effective_words(load_words(job.words_json), [], d["word_fixes"])
    assert [w.w for w in out[2:5]] == ["w2.", "lamá sabactâni?", "w6."]
    assert out[3].t == 1.5 and out[4].t == 3.0          # no word moved; slots 4-5 were absorbed


def test_whitespace_only_word_fix_is_still_rejected(tmp_path):
    import pytest
    job = make_job(tmp_path)
    for bad in ({"word_fixes": {"3": "  "}}, {"word_fixes": {"3": "\n"}}):
        with pytest.raises(ValueError, match="cannot be empty"):
            apply_edit(job, "c01", bad)
    assert not job.review_json.exists()


def _write_edits(job, edits):
    jobs.write_json_atomic(job.corrections_json, {
        "version": 1, "words_hash": jobs.file_hash(job.words_json),
        "edits": [e.to_dict() for e in edits]})


def test_load_state_marks_automatic_fixes_with_their_range_and_reason(tmp_path):
    from shorts.wordfix import Edit
    job = make_job(tmp_path)
    _write_edits(job, [Edit(3, 5, ("lamá", "sabactâni?"), "foreign_term", "aramaico", 0.9)])
    s = load_state(job)
    assert s["auto_edits"] == [{"first": 3, "last": 5, "tokens": ["lamá", "sabactâni?"],
                                "kind": "foreign_term", "reason": "aramaico", "confidence": 0.9,
                                "original": "w3. w4. w5."}]
    assert s["auto_slots"] == {"3": {"text": "lamá", "edit": 0}, "4": {"text": "sabactâni?", "edit": 0},
                               "5": {"text": "", "edit": 0}}
    assert s["words"][3] == [1.5, "w3."]                    # the raw words stay raw


def test_load_state_without_corrections(tmp_path):
    s = load_state(make_job(tmp_path))
    assert s["auto_edits"] == [] and s["auto_slots"] == {}


def test_use_auto_is_stored_sorted_and_an_empty_list_removes_it(tmp_path):
    job = make_job(tmp_path)
    apply_edit(job, "c01", {"use_auto": [9, 3, 9]})
    assert json.loads(job.review_json.read_text(encoding="utf-8"))["decisions"]["c01"] == {"use_auto": [3, 9]}
    apply_edit(job, "c01", {"use_auto": []})
    assert json.loads(job.review_json.read_text(encoding="utf-8"))["decisions"]["c01"] == {}


def test_bad_use_auto_is_rejected(tmp_path):
    import pytest
    job = make_job(tmp_path)
    for bad in ("3", [True], [-1], [1.5], ["3"], {"3": 1}, [None]):
        with pytest.raises(ValueError, match="use_auto must be"):
            apply_edit(job, "c01", {"use_auto": bad})
    assert not job.review_json.exists()


def test_fix_and_choice_in_one_edit_are_one_entry(tmp_path):
    job = make_job(tmp_path)
    apply_edit(job, "c01", {"use_auto": [3]})
    apply_edit(job, "c01", {"word_fixes": {"3": "lamá", "4": ""}, "use_auto": []})
    assert json.loads(job.review_json.read_text(encoding="utf-8"))["decisions"]["c01"] == {
        "word_fixes": {"3": "lamá", "4": ""}}


def test_null_erases_the_owner_fix_of_a_slot(tmp_path):
    job = make_job(tmp_path)
    apply_edit(job, "c01", {"word_fixes": {"3": "", "5": "Agostinho"}})
    apply_edit(job, "c01", {"word_fixes": {"3": None}})
    assert json.loads(job.review_json.read_text(encoding="utf-8"))["decisions"]["c01"] == {
        "word_fixes": {"5": "Agostinho"}}
    apply_edit(job, "c01", {"word_fixes": {"5": None, "7": None}})    # 7 had no fix: nothing to erase
    assert json.loads(job.review_json.read_text(encoding="utf-8"))["decisions"]["c01"] == {}


def test_overlapping_automatic_fixes_show_only_the_one_the_render_applies(tmp_path):
    from shorts.wordfix import Edit
    job = make_job(tmp_path)
    _write_edits(job, [Edit(3, 5, ("a",), "mishearing", "", 0.9),
                       Edit(4, 6, ("b",), "mishearing", "", 0.9)])
    s = load_state(job)
    assert [e["first"] for e in s["auto_edits"]] == [3]
    assert sorted(s["auto_slots"], key=int) == ["3", "4", "5"]


import pytest

from shorts.review.state import UNDO_LIMIT, NothingToUndo, history_counts, redo, undo


def _saved(job):
    return json.loads(job.review_json.read_text(encoding="utf-8"))["decisions"]


def test_each_change_is_one_step_and_a_no_op_is_none(tmp_path):
    job = make_job(tmp_path)
    r = apply_edit(job, "c01", {"title": "A"})
    assert (r["undo"], r["redo"]) == (1, 0) and r["title"] == "A"
    r = apply_edit(job, "c01", {"title": "A"})                  # same value: no new step
    assert r["undo"] == 1
    r = apply_decision(job, "c01", "approved")
    assert (r["undo"], r["status"]) == (2, "approved")
    apply_edit(job, "c01", {"word_fixes": {"3": "x", "4": "", "5": ""}})   # a range replace is one step
    assert history_counts(job, "c01") == {"undo": 3, "redo": 0}


def test_a_rejected_edit_pushes_no_step(tmp_path):
    job = make_job(tmp_path)
    apply_edit(job, "c01", {"title": "A"})
    with pytest.raises(ValueError):
        apply_edit(job, "c01", {"segments": [[0, 30], [20, 50]]})
    with pytest.raises(ValueError):
        apply_decision(job, "c01", "maybe")
    assert history_counts(job, "c01") == {"undo": 1, "redo": 0}


def test_undo_then_redo_round_trips_every_field(tmp_path):
    job = make_job(tmp_path)
    apply_edit(job, "c01", {"title": "Novo", "hook": "Gancho", "segments": [[1.0, 35.0]],
                            "word_fixes": {"3": "Denzinger"}, "use_auto": [7]})
    apply_decision(job, "c01", "approved")
    full = _saved(job)["c01"]
    r = undo(job, "c01")
    assert _saved(job)["c01"] == {k: v for k, v in full.items() if k != "status"}
    assert "status" not in r and (r["undo"], r["redo"]) == (1, 1)
    r = undo(job, "c01")
    assert "c01" not in _saved(job) and (r["undo"], r["redo"]) == (0, 2)
    assert "title" not in r and r["estimated_duration"] > 0     # the candidate's own segments
    redo(job, "c01")
    r = redo(job, "c01")
    assert _saved(job)["c01"] == full and (r["undo"], r["redo"]) == (2, 0)
    assert r["segments"] == [[1.0, 35.0]] and r["use_auto"] == [7]


def test_a_new_change_clears_redo(tmp_path):
    job = make_job(tmp_path)
    apply_edit(job, "c01", {"title": "A"})
    apply_edit(job, "c01", {"title": "B"})
    undo(job, "c01")
    r = apply_edit(job, "c01", {"title": "C"})
    assert (r["undo"], r["redo"]) == (2, 0)
    with pytest.raises(NothingToUndo, match="nothing to redo"):
        redo(job, "c01")


def test_history_keeps_the_last_100_steps(tmp_path):
    job = make_job(tmp_path)
    for n in range(UNDO_LIMIT + 5):
        apply_edit(job, "c01", {"title": f"t{n}"})
    assert history_counts(job, "c01")["undo"] == UNDO_LIMIT
    for _ in range(UNDO_LIMIT):
        r = undo(job, "c01")
    assert r["title"] == "t4"                                   # the five oldest steps were dropped
    with pytest.raises(NothingToUndo):
        undo(job, "c01")


def test_empty_stacks_raise_and_leave_the_file_alone(tmp_path):
    job = make_job(tmp_path)
    with pytest.raises(NothingToUndo, match="nothing to undo"):
        undo(job, "c01")
    assert not job.review_json.exists()
    apply_edit(job, "c01", {"title": "A"})
    before = job.review_json.read_bytes()
    with pytest.raises(NothingToUndo, match="nothing to redo"):
        redo(job, "c01")
    assert job.review_json.read_bytes() == before
    with pytest.raises(ValueError, match="unknown clip"):
        undo(job, "c99")


def test_two_clips_keep_separate_stacks(tmp_path):
    job = make_job(tmp_path)
    data = json.loads(job.candidates_json.read_text(encoding="utf-8"))
    data["candidates"].append({**data["candidates"][0], "id": "c02"})
    jobs.write_json_atomic(job.candidates_json, data)
    apply_edit(job, "c01", {"title": "A"})
    apply_edit(job, "c02", {"title": "B"})
    apply_edit(job, "c02", {"title": "C"})
    undo(job, "c01")
    assert _saved(job) == {"c02": {"title": "C"}}
    assert history_counts(job, "c02") == {"undo": 2, "redo": 0}


def test_load_state_reports_the_history_counts(tmp_path):
    job = make_job(tmp_path)
    assert load_state(job)["candidates"][0]["undo"] == 0
    apply_edit(job, "c01", {"title": "A"})
    undo(job, "c01")
    c = load_state(job)["candidates"][0]
    assert (c["undo"], c["redo"]) == (0, 1)


def test_load_state_names_the_clip_changed_last_so_a_reload_keeps_the_keys_working(tmp_path):
    job = make_job(tmp_path)
    assert load_state(job)["last_clip"] is None
    apply_edit(job, "c01", {"title": "A"})
    assert load_state(job)["last_clip"] == "c01"
    undo(job, "c01")
    assert load_state(job)["last_clip"] == "c01"
    redo(job, "c01")
    undo(job, "c01")
    undo_empty = load_state(job)
    assert undo_empty["last_clip"] == "c01"          # the clip stays the target; its buttons say 0 or 1


from shorts.review.state import set_class_strength


def test_clip_override_is_an_edit_with_undo(tmp_path):
    job = make_job(tmp_path)
    apply_edit(job, "c01", {"dereverb": 30})
    assert json.loads(job.review_json.read_text(encoding="utf-8"))["decisions"]["c01"] == {"dereverb": 30}
    apply_edit(job, "c01", {"dereverb": None})                 # back to the class strength
    assert "dereverb" not in json.loads(job.review_json.read_text(encoding="utf-8"))["decisions"]["c01"]
    undo(job, "c01")
    assert json.loads(job.review_json.read_text(encoding="utf-8"))["decisions"]["c01"] == {"dereverb": 30}
    redo(job, "c01")      # back to an empty entry, which redo removes from the file
    assert "dereverb" not in json.loads(job.review_json.read_text(encoding="utf-8"))["decisions"].get("c01", {})


def test_clip_override_must_be_a_level(tmp_path):
    job = make_job(tmp_path)
    for bad in (15, "20", True, 20.5):
        with pytest.raises(ValueError, match="dereverb must be one of"):
            apply_edit(job, "c01", {"dereverb": bad})
    apply_edit(job, "c01", {"dereverb": 40}, levels=(0, 20, 40))


def test_class_strength_is_top_level_and_keeps_decisions(tmp_path):
    job = make_job(tmp_path)
    apply_decision(job, "c01", "approved")
    assert set_class_strength(job, 20, (0, 10, 20, 30)) == {"dereverb": 20}
    data = json.loads(job.review_json.read_text(encoding="utf-8"))
    assert data["dereverb"] == 20 and data["decisions"]["c01"]["status"] == "approved"
    with pytest.raises(ValueError):
        set_class_strength(job, 25, (0, 10, 20, 30))
    assert load_state(job)["review"]["dereverb"] == 20
