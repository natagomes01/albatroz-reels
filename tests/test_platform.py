"""The Windows port: detector and encoder choice, keys that keep the Mac's caches, filter-graph
paths with a drive letter, the config overlay and the keyring store."""
from pathlib import Path, PureWindowsPath

import pytest

from shorts import config, ffmpeg, keychain, machine, vision
from shorts.render import _quote


def on(monkeypatch, name: str) -> None:
    """Pretend shorts runs on `name` ("darwin" or "win32")."""
    monkeypatch.setattr(machine, "NAME", name)
    monkeypatch.setattr(machine, "MAC", name == "darwin")
    monkeypatch.setattr(machine, "WINDOWS", name == "win32")


def test_detector_defaults_by_platform_and_env_overrides(monkeypatch):
    monkeypatch.delenv("SHORTS_DETECTOR", raising=False)
    on(monkeypatch, "darwin")
    assert vision.detector_name() == "vision"
    on(monkeypatch, "win32")
    assert vision.detector_name() == "onnx"
    monkeypatch.setenv("SHORTS_DETECTOR", "vision")
    assert vision.detector_name() == "vision"
    monkeypatch.setenv("SHORTS_DETECTOR", "yolo")
    with pytest.raises(ValueError, match="SHORTS_DETECTOR"):
        vision.detector_name()


def test_detect_dispatches_to_onnx(monkeypatch):
    from shorts import detect_onnx
    monkeypatch.setenv("SHORTS_DETECTOR", "onnx")
    seen = []
    monkeypatch.setattr(detect_onnx, "detect", lambda *a: seen.append(a) or ([], []))
    assert vision.detect(b"\0" * 16, 2, 2, False, (4, 4)) == ([], [])
    assert seen and seen[0][4] == (4, 4)


def test_encoder_defaults_and_nvenc_only_when_asked(monkeypatch):
    monkeypatch.delenv("SHORTS_ENCODER", raising=False)
    on(monkeypatch, "darwin")
    assert ffmpeg.video_encoder() == "h264_videotoolbox"
    on(monkeypatch, "win32")
    assert ffmpeg.video_encoder() == "libx264"
    monkeypatch.setenv("SHORTS_ENCODER", "h264_nvenc")
    assert ffmpeg.video_encoder() == "h264_nvenc"
    monkeypatch.setenv("SHORTS_ENCODER", "x265")
    with pytest.raises(ValueError):
        ffmpeg.video_encoder()


def test_encoder_args_keep_the_mac_render_and_use_crf_on_x264():
    assert ffmpeg.encoder_args(encoder="h264_videotoolbox") == [
        "-c:v", "h264_videotoolbox", "-b:v", "10M", "-maxrate", "14M", "-bufsize", "20M"]
    assert ffmpeg.encoder_args(preview=True, encoder="h264_videotoolbox") == ["-c:v", "h264_videotoolbox", "-b:v", "2M"]
    x264 = ffmpeg.encoder_args(encoder="libx264")
    assert x264[:2] == ["-c:v", "libx264"] and x264[x264.index("-crf") + 1] == "19"
    assert ffmpeg.encoder_args(encoder="h264_nvenc")[:2] == ["-c:v", "h264_nvenc"]


def test_quote_escapes_the_drive_colon_and_uses_forward_slashes():
    assert _quote(PureWindowsPath(r"C:\albatroz\dev\jobs\a b\captions.ass")) == r"'C\:/albatroz/dev/jobs/a b/captions.ass'"
    assert _quote(Path("/Users/n/jobs/captions.ass")) == "'/Users/n/jobs/captions.ass'"
    with pytest.raises(ValueError):
        _quote(Path("d'aula.ass"))


def test_platform_overlay_merges_tables_one_level():
    data = {"media_root": "~/m", "transcreve": {"python": "/usr/bin/python3", "script": "~/t.py"},
            "platform": {"win32": {"media_root": "E:/m", "transcreve": {"script": "E:/t.py"}}}}
    win = config._platform_overlay(data, "win32")
    assert win["media_root"] == "E:/m" and win["transcreve"] == {"python": "/usr/bin/python3", "script": "E:/t.py"}
    mac = config._platform_overlay(data, "darwin")
    assert mac["media_root"] == "~/m" and "platform" not in mac


def test_repo_config_keeps_the_mac_paths_on_the_mac(monkeypatch):
    repo = Path(__file__).resolve().parents[1]
    on(monkeypatch, "darwin")
    mac = config.load_config(repo / "config.toml")
    assert mac.transcreve["python"] == "/usr/bin/python3"
    on(monkeypatch, "win32")
    win = config.load_config(repo / "config.toml")
    assert win.transcreve == {"python": "python", "script": "C:/albatroz/dev/transcreve/transcreve.py"}
    assert win.final_dir.as_posix().endswith("C:/albatroz/media/final")   # not the Mac's ~/dev


def test_keyring_store_off_the_mac(monkeypatch):
    keyring = pytest.importorskip("keyring")
    store = {("anthropic-api", "u"): " sk-1 "}
    on(monkeypatch, "win32")
    monkeypatch.setattr(keychain.getpass, "getuser", lambda: "u")
    monkeypatch.setattr(keyring, "get_password", lambda s, u: store.get((s, u)))
    assert keychain.get_secret("anthropic-api") == "sk-1"
    assert keychain.has_secret("anthropic-api") and not keychain.has_secret("pixabay-api")
    with pytest.raises(keychain.MissingSecret, match="python -m keyring set pixabay-api u"):
        keychain.get_secret("pixabay-api")


def test_switching_detector_or_encoder_invalidates_the_track_and_render_keys(tmp_path, monkeypatch):
    from test_broll_stages import CH, RENDER_CHANNEL_FIELDS, _keys, approved_clips, jobs, load_words, make_job

    job = make_job(tmp_path, {})
    plan = approved_clips(job)[0]
    words = load_words(job.words_json)
    rc = {k: getattr(CH, k) for k in RENDER_CHANNEL_FIELDS}
    meta = jobs.read_json(job.job_json)

    def keys(det, enc):
        monkeypatch.setenv("SHORTS_DETECTOR", det)
        monkeypatch.setenv("SHORTS_ENCODER", enc)
        return _keys(meta, plan, words, "solo-standing", rc, False, "", 0)

    mac_track, mac_render = keys("vision", "h264_videotoolbox")
    pc_track, pc_render = keys("onnx", "libx264")
    assert pc_track != mac_track and pc_render != mac_render
    assert keys("vision", "libx264")[0] == mac_track     # the encoder never re-tracks


def test_onnx_detector_on_a_blank_frame_finds_nothing():
    pytest.importorskip("cv2")
    pytest.importorskip("onnxruntime")
    from shorts import detect_onnx
    if not all((detect_onnx.models_dir() / m.file).exists() for m in (detect_onnx.YUNET, detect_onnx.YOLOX_S)):
        pytest.skip("ONNX models not in the cache yet (the first real track downloads them)")
    blank = b"\xff" * (640 * 360 * 4)
    assert detect_onnx.detect(blank, 640, 360, False, (1920, 1080)) == ([], [])


def test_a_corrupt_model_file_is_an_error_not_a_redownload(tmp_path):
    from shorts import detect_onnx
    (tmp_path / detect_onnx.YUNET.file).write_bytes(b"not a model")
    with pytest.raises(RuntimeError, match="sha256"):
        detect_onnx.ensure_model(detect_onnx.YUNET, tmp_path)


def test_only_machine_reads_the_platform():
    src = Path(__file__).resolve().parents[1] / "src" / "shorts"
    readers = [p.name for p in src.rglob("*.py")
               if "sys.platform" in p.read_text(encoding="utf-8") and p.name != "machine.py"]
    assert readers == []


def test_machine_defaults_per_os(monkeypatch):
    monkeypatch.delenv("SHORTS_FFMPEG_DIR", raising=False)
    on(monkeypatch, "darwin")
    assert (machine.default_detector(), machine.default_encoder(), machine.secret_store()) ==         ("vision", "h264_videotoolbox", "keychain")
    assert machine.ffmpeg_dir() == Path("/opt/homebrew/opt/ffmpeg-full/bin") and machine.exe("ffmpeg") == "ffmpeg"
    assert machine.default_python() == "/usr/bin/python3"
    on(monkeypatch, "win32")
    assert (machine.default_detector(), machine.default_encoder(), machine.secret_store()) ==         ("onnx", "libx264", "keyring")
    assert machine.ffmpeg_dir() is None and machine.exe("ffmpeg") == "ffmpeg.exe"
    monkeypatch.setenv("SHORTS_FFMPEG_DIR", "/opt/ff")
    assert machine.ffmpeg_dir() == Path("/opt/ff")
    assert "winget" in machine.install_hint("ffmpeg")
    assert machine.install_hint("rclone").endswith("--location C:\\albatroz\\programs\\rclone")


def test_doctor_checks_the_detector_this_machine_uses(monkeypatch):
    from shorts.doctor import check_detector
    monkeypatch.setenv("SHORTS_DETECTOR", "onnx")
    assert [c.name for c in check_detector()] == ["detector: YuNet + YOLOX-S (ONNX)", "detector models"]
    monkeypatch.setenv("SHORTS_DETECTOR", "vision")
    assert [c.name for c in check_detector()] == ["detector: Apple Vision"]
