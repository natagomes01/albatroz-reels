import json
import os
from pathlib import Path

import pytest

from shorts import jobs


def test_create_and_load_job(tmp_path):
    job = jobs.create_job(tmp_path, "260927-aula", {"channel": "catholic-br"})
    assert job.id == "260927-aula"
    assert json.loads(job.job_json.read_text(encoding="utf-8"))["channel"] == "catholic-br"
    assert jobs.load_job("260927-aula", tmp_path).root == job.root
    assert jobs.load_job(str(job.root), tmp_path).root == job.root
    assert job.clip_dir("c07") == job.root / "clips" / "c07"


def test_create_job_refuses_existing(tmp_path):
    jobs.create_job(tmp_path, "x", {})
    with pytest.raises(FileExistsError):
        jobs.create_job(tmp_path, "x", {})


def test_load_job_missing(tmp_path):
    with pytest.raises(FileNotFoundError, match="no job"):
        jobs.load_job("nope", tmp_path)


def test_write_json_atomic_leaves_no_tmp(tmp_path):
    p = tmp_path / "a" / "b.json"
    jobs.write_json_atomic(p, {"é": 1})
    assert json.loads(p.read_text(encoding="utf-8")) == {"é": 1}
    assert not list(p.parent.glob("*.tmp"))


def test_stage_key_is_order_independent_and_versioned():
    a = jobs.stage_key(jobs.LLM_CACHE_VERSION, x=1, y={"b": 2, "a": 1})
    b = jobs.stage_key(jobs.LLM_CACHE_VERSION, y={"a": 1, "b": 2}, x=1)
    assert a == b
    assert jobs.stage_key("999", x=1, y={"b": 2, "a": 1}) != a


def test_llm_and_render_versions_are_independent():
    # Bumping the render version must never invalidate LLM caches (spec 4.3, Max-plan budget).
    k_llm = jobs.stage_key(jobs.LLM_CACHE_VERSION, stage="scan", x=1)
    k_render = jobs.stage_key(jobs.RENDER_VERSION + "-bumped", stage="render", x=1)
    assert k_llm == jobs.stage_key(jobs.LLM_CACHE_VERSION, stage="scan", x=1)
    assert k_llm != k_render


def test_is_fresh(tmp_path):
    p = tmp_path / "scan.json"
    assert not jobs.is_fresh(p, "k1")
    jobs.write_json_atomic(p, {})
    assert not jobs.is_fresh(p, "k1")
    jobs.write_key(p, "k1")
    assert jobs.is_fresh(p, "k1")
    assert not jobs.is_fresh(p, "k2")


def test_quick_hash_changes_with_content(tmp_path):
    p = tmp_path / "m.bin"
    p.write_bytes(b"a" * 10)
    h1 = jobs.quick_hash(p)
    p.write_bytes(b"a" * 9 + b"b")
    assert jobs.quick_hash(p) != h1


def test_log_event_appends_lines(tmp_path):
    job = jobs.create_job(tmp_path, "j", {})
    jobs.log_event(job, kind="llm", tokens=3)
    jobs.log_event(job, kind="ffmpeg")
    lines = job.log_path.read_text(encoding="utf-8").splitlines()
    assert [json.loads(l)["kind"] for l in lines] == ["llm", "ffmpeg"]
    assert "ts" in json.loads(lines[0])


def test_caption_pass_paths(tmp_path):
    job = jobs.create_job(tmp_path, "j", {})
    assert job.corrections_json == job.root / "analyze" / "corrections.json"
    assert job.class_sheet_json == job.root / "analyze" / "class_sheet.json"
