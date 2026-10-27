import json

from shorts import jobs
from shorts.export import _link_or_copy, context_md
from shorts.metrics import build, write


def _job(tmp_path, events):
    root = tmp_path / "j1"
    root.mkdir()
    (root / "job.json").write_text(json.dumps({"id": "j1", "channel": "c", "duration": 600.0, "width": 1920, "height": 1080}), encoding="utf-8")
    (root / "log.jsonl").write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")
    return jobs.Job(root)


def test_metrics_report_lists_runs_passes_and_clip_stages(tmp_path):
    ev = [{"ts": 1.0, "kind": "transcreve", "returncode": 0, "wall_s": 90.0},
          {"ts": 2.0, "kind": "run_start", "run": "r1", "command": "analyze"},
          {"ts": 3.0, "kind": "llm", "run": "r1", "pass": "scan", "model": "claude-haiku-4-5", "ok": True,
           "input_tokens": 10, "output_tokens": 20, "cost_usd": 0.5, "duration_ms": 4000},
          {"ts": 4.0, "kind": "run_end", "run": "r1", "exit_code": 0, "wall_s": 12.5},
          {"ts": 5.0, "kind": "clip_stage", "clip": "a1", "stage": "render", "duration": 40.0, "wall_s": 22.0,
           "reused_track": False}]
    job = _job(tmp_path, ev)
    text = build(job)
    assert "Class length: 600.0 min" not in text and "10.0 min" in text
    assert "| analyze |" in text and "12.5" in text
    assert "transcribe (transcreve)" in text and "90.0" in text
    assert "| scan | claude-haiku-4-5 | 1 |" in text and "0.5000" in text
    assert "| a1 | render | 22.0 | 40.0 |" in text
    write(job)
    assert (job.root / "metrics.md").read_text(encoding="utf-8") == text


def test_export_links_without_a_second_copy(tmp_path):
    src, dst = tmp_path / "a.mp4", tmp_path / "out.mp4"
    src.write_bytes(b"video")
    dst.write_bytes(b"old")
    assert _link_or_copy(src, dst) == "linked"
    assert dst.read_bytes() == b"video" and src.stat().st_ino == dst.stat().st_ino


def test_context_md_has_class_topic_and_credits(tmp_path):
    job = _job(tmp_path, [])
    (job.root / "analyze").mkdir()
    (job.root / "analyze" / "class_sheet.json").write_text(json.dumps(
        {"sheet": {"topic": "A Bíblia grega", "references": ["Salmo 22"], "terms": [{"term": "Ezequias"}]}}), encoding="utf-8")

    class P:
        title, id, hook_text = "Título", "a1", "Gancho"

    class C:
        id, language = "catholic-br", "pt-BR"
    text = context_md(job, C, P, {"duration": 54.4, "render_version": "4.01", "credits": "Foto: Ana (CC BY)"})
    assert "A Bíblia grega" in text and "Salmo 22" in text and "Ezequias" in text
    assert "Foto: Ana (CC BY)" in text and "catholic-br" in text and "Gancho" in text
