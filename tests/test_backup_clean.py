import subprocess
from pathlib import Path

from shorts import jobs, machine
from shorts.backup import build_cmds, rclone_remote_ok, run_backup
from shorts.clean import run_clean
from shorts.config import AppConfig


def app(tmp_path):
    return AppConfig(media_root=tmp_path / "media", jobs_dir=tmp_path / "jobs", backends={},
                     backup_remote="gdrive:albatroz-media-backup")


def test_backup_uses_copy_never_sync(tmp_path):
    job = jobs.Job(tmp_path / "jobs" / "260927-a")
    for cmds in [build_cmds(app(tmp_path)),
                 build_cmds(app(tmp_path), job=job, channel_id="catholic-br", masters=True, dry_run=True)]:
        for c in cmds:
            assert c[:2] == ["rclone", "copy"]
            assert "sync" not in " ".join(c)
    one = build_cmds(app(tmp_path), job=job, channel_id="catholic-br")
    assert Path(one[0][2]).as_posix().endswith("media/renders/catholic-br/260927-a")
    assert one[0][3] == "gdrive:albatroz-media-backup/renders/catholic-br/260927-a"
    assert "--dry-run" in build_cmds(app(tmp_path), dry_run=True)[0]
    assert build_cmds(app(tmp_path), masters=True)[-1][3].endswith("/masters")
    # leftovers of an interrupted render and cache keys never reach Drive (they would stay forever)
    c = one[0]
    excluded = {c[i + 1] for i, x in enumerate(c) if x == "--exclude"}
    assert {"*.tmp.mp4", "*.tmp", "*.key"} <= excluded


def test_run_backup_reports_codes(tmp_path):
    seen = []
    runner = lambda c, **k: (seen.append(c), subprocess.CompletedProcess(c, 0))[1]
    assert run_backup(app(tmp_path), runner=runner) == [0]
    assert seen[0][1] == "copy"


def test_remote_check(tmp_path):
    ok = lambda c, **k: subprocess.CompletedProcess(c, 0, stdout="gdrive:\nother:\n", stderr="")
    assert rclone_remote_ok("gdrive:albatroz-media-backup", runner=ok)[0]
    missing = lambda c, **k: subprocess.CompletedProcess(c, 0, stdout="other:\n", stderr="")
    good, why = rclone_remote_ok("gdrive:x", runner=missing)
    assert not good and "rclone config" in why


def test_clean_removes_rejected_renders_only(tmp_path):
    a = app(tmp_path)
    job = jobs.create_job(a.jobs_dir, "260927-a", {"channel": "catholic-br"})
    jobs.write_json_atomic(job.review_json, {"decisions": {"c01": {"status": "approved"},
                                                           "c02": {"status": "rejected"},
                                                           "c04": {"status": "pending"}}})
    d = a.media_root / "renders" / "catholic-br" / "260927-a"
    d.mkdir(parents=True)
    for n in ("c01", "c02", "c03", "c04"):
        (d / f"{n}.mp4").write_bytes(b"x")
        (d / f"{n}.json").write_text("{}", encoding="utf-8")
        (d / f"{n}.mp4.key").write_text("k", encoding="utf-8")
    removed = run_clean(job, a, "catholic-br")
    assert sorted(p.name for p in removed) == ["c02.json", "c02.mp4"]
    assert not (d / "c02.mp4.key").exists()
    # approved, pending (Natã is thinking it over) and never-reviewed renders are all kept
    for n in ("c01", "c03", "c04"):
        assert (d / f"{n}.mp4").exists()


def test_clean_never_touches_masters(tmp_path):
    a = app(tmp_path)
    job = jobs.create_job(a.jobs_dir, "260927-a", {"channel": "catholic-br"})
    jobs.write_json_atomic(job.review_json, {"decisions": {"c02": {"status": "rejected"}}})
    master = a.media_root / "masters" / "260927-a.mov"
    master.parent.mkdir(parents=True)
    master.write_bytes(b"m")
    run_clean(job, a, "catholic-br")
    assert master.exists()


def test_absent_rclone_is_reported_not_raised(tmp_path):
    def gone(c, **k):
        raise FileNotFoundError("rclone")
    ok, why = rclone_remote_ok("gdrive:x", runner=gone)
    assert not ok and machine.install_hint("rclone") in why


def _rejected_job(a, jid="260927-a"):
    job = jobs.create_job(a.jobs_dir, jid, {"channel": "catholic-br"})
    jobs.write_json_atomic(job.review_json, {"decisions": {"c02": {"status": "rejected"}}})
    master = a.media_root / "masters" / f"{jid}.mov"
    master.parent.mkdir(parents=True, exist_ok=True)
    master.write_bytes(b"m")
    return job, master


def test_clean_rejects_unsafe_ids_and_keeps_masters(tmp_path):
    import pytest
    a = app(tmp_path)
    job, master = _rejected_job(a)
    (a.media_root / "masters" / "c02.mp4").write_bytes(b"x")
    for bad in ("..", ".", "../../masters", "a/b", ""):
        with pytest.raises(ValueError):
            run_clean(job, a, bad)
    bad_job = jobs.Job(tmp_path / "jobs" / "..")
    with pytest.raises(ValueError):
        run_clean(bad_job, a, "catholic-br")
    assert master.exists() and (a.media_root / "masters" / "c02.mp4").exists()


def test_clean_symlinked_folder_outside_renders_deletes_nothing(tmp_path):
    a = app(tmp_path)
    job, master = _rejected_job(a)
    outside = a.media_root / "masters"
    (outside / "c02.mp4").write_bytes(b"x")
    ch = a.media_root / "renders" / "catholic-br"
    ch.mkdir(parents=True)
    (ch / "260927-a").symlink_to(outside, target_is_directory=True)
    assert run_clean(job, a, "catholic-br") == []
    assert master.exists() and (outside / "c02.mp4").exists()


def test_clean_skips_symlinked_files(tmp_path):
    a = app(tmp_path)
    job, master = _rejected_job(a)
    d = a.media_root / "renders" / "catholic-br" / "260927-a"
    d.mkdir(parents=True)
    (d / "c02.mp4").symlink_to(master)
    assert run_clean(job, a, "catholic-br") == []
    assert master.exists() and (d / "c02.mp4").is_symlink()


def test_clean_handles_interrupted_render_leftovers(tmp_path):
    a = app(tmp_path)
    job, master = _rejected_job(a)
    d = a.media_root / "renders" / "catholic-br" / "260927-a"
    d.mkdir(parents=True)
    (d / "c02.tmp.mp4").write_bytes(b"x")
    (d / "c01.tmp.mp4").write_bytes(b"x")
    removed = run_clean(job, a, "catholic-br")
    assert [p.name for p in removed] == ["c02.tmp.mp4"]
    assert (d / "c01.tmp.mp4").exists() and master.exists()


def test_clean_also_removes_the_broll_thumbnails(tmp_path):
    from shorts import jobs
    from shorts.broll.paths import thumbs_dir
    from shorts.config import AppConfig
    a = AppConfig(media_root=tmp_path / "media", jobs_dir=tmp_path / "jobs", backends={})
    job = jobs.create_job(tmp_path / "jobs", "260927-a", {"channel": "catholic-br"})
    jobs.write_json_atomic(job.review_json, {"decisions": {}})
    thumbs = thumbs_dir(a, job)
    thumbs.mkdir(parents=True)
    (thumbs / "commons-1.jpg").write_bytes(b"x")
    picked = tmp_path / "media" / "broll" / "260927-a" / "commons-1.jpg"
    picked.parent.mkdir(parents=True)
    picked.write_bytes(b"x")
    assert run_clean(job, a, "catholic-br") == [thumbs]
    assert not thumbs.exists() and picked.exists()          # chosen files stay
