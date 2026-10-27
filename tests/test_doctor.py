from pathlib import Path

from shorts.config import AppConfig
from shorts.doctor import check_assets, check_ffmpeg, check_media_root, disk_check
from shorts.ffmpeg import video_encoder

REPO = Path(__file__).resolve().parents[1]


def test_media_root_created_and_writable(tmp_path):
    app = AppConfig(media_root=tmp_path / "media", jobs_dir=tmp_path / "jobs", backends={})
    checks = {c.name: c for c in check_media_root(app)}
    assert checks["media root writable"].ok
    assert (tmp_path / "media" / "renders").is_dir()


def test_disk_check_thresholds():
    assert disk_check(15.0).ok
    warn = disk_check(8.0)
    assert not warn.ok and not warn.required
    fail = disk_check(2.0)
    assert not fail.ok and fail.required


def test_assets_check_flags_missing_font(tmp_path):
    checks = {c.name: c for c in check_assets(tmp_path)}
    assert not checks["Anton font"].ok and checks["Anton font"].required
    assert not checks["safe-zone template"].required


def test_ffmpeg_full_has_libass_and_the_encoder_of_this_machine():
    checks = {c.name: c for c in check_ffmpeg()}
    if not checks["ffmpeg-full"].ok:
        return  # machine without ffmpeg-full: the check itself reports it
    assert checks["libass (subtitles filter)"].ok
    assert checks[video_encoder()].ok


def test_doctor_cli_exit_code(tmp_path, capsys):
    from shorts.cli import main

    cfg = tmp_path / "config.toml"
    cfg.write_text(f'media_root = "{(tmp_path / "media").as_posix()}"\n', encoding="utf-8")
    code = main(["--config", str(cfg), "doctor"])
    out = capsys.readouterr().out
    assert code in (0, 1) and "[ok  ] media root writable" in out
