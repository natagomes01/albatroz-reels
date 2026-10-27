import pytest
from pathlib import Path

from conftest import needs_ffmpeg
from shorts.cli import main


def test_cli_rejects_conversation(tmp_path, capsys):
    cfg = tmp_path / "config.toml"
    cfg.write_text(f'media_root = "{(tmp_path / "media").as_posix()}"\n', encoding="utf-8")
    code = main(["--config", str(cfg), "clip", "x.mp4", "--channel", "catholic-br",
                 "--format", "conversation", "--from", "0:10", "--to", "0:40"])
    assert code == 2 and "phase 1b" in capsys.readouterr().err


def test_cli_missing_words_file(tmp_path, capsys):
    cfg = tmp_path / "config.toml"
    cfg.write_text(f'media_root = "{(tmp_path / "media").as_posix()}"\n', encoding="utf-8")
    chans = tmp_path / "channels.toml"
    chans.write_text('[channels.catholic-br]\nlanguage = "pt"\n', encoding="utf-8")
    code = main(["--config", str(cfg), "--channels", str(chans), "clip", str(tmp_path / "aula.mp4"),
                 "--channel", "catholic-br", "--format", "solo-standing", "--from", "0:10", "--to", "0:40"])
    assert code == 2 and "aula.palavras.json" in capsys.readouterr().err


def test_cli_unknown_channel(tmp_path, capsys):
    cfg = tmp_path / "config.toml"
    cfg.write_text(f'media_root = "{(tmp_path / "media").as_posix()}"\n', encoding="utf-8")
    chans = tmp_path / "channels.toml"
    chans.write_text('[channels.catholic-br]\nlanguage = "pt"\n', encoding="utf-8")
    code = main(["--config", str(cfg), "--channels", str(chans), "clip", "a.mp4",
                 "--channel", "nope", "--format", "solo-standing", "--from", "0:10", "--to", "0:40"])
    assert code == 2 and "unknown channel" in capsys.readouterr().err


def _setup(tmp_path, name="aula.mp4", from_="0:10", to="0:40"):
    cfg = tmp_path / "config.toml"
    cfg.write_text(f'media_root = "{(tmp_path / "media").as_posix()}"\njobs_dir = "{(tmp_path / "jobs").as_posix()}"\n', encoding="utf-8")
    chans = tmp_path / "channels.toml"
    chans.write_text('[channels.catholic-br]\nlanguage = "pt"\n', encoding="utf-8")
    video = tmp_path / name
    video.write_bytes(b"not a video")
    (tmp_path / f"{Path(name).stem}.palavras.json").write_text('{"version": 1, "words": []}', encoding="utf-8")
    return ["--config", str(cfg), "--channels", str(chans), "clip", str(video), "--channel", "catholic-br",
            "--format", "solo-standing", "--from", from_, "--to", to]


def _nothing_written(tmp_path):
    return not (tmp_path / "media" / "renders").exists() and not (tmp_path / "jobs").exists()


def test_cli_negative_from_rejected(tmp_path, capsys):
    argv = _setup(tmp_path)
    argv[argv.index("--from") + 1] = "-5"
    with pytest.raises(SystemExit) as exc:
        main(argv)
    assert exc.value.code == 2 and "bad time" in capsys.readouterr().err
    assert _nothing_written(tmp_path)


@pytest.mark.parametrize("bad", ["nan", "inf"])
def test_cli_nonfinite_time_rejected(tmp_path, capsys, bad):
    with pytest.raises(SystemExit) as exc:
        main(_setup(tmp_path, to=bad))
    assert exc.value.code == 2 and "bad time" in capsys.readouterr().err


def test_cli_to_before_from(tmp_path, capsys):
    code = main(_setup(tmp_path, from_="0:40", to="0:10"))
    assert code == 2 and "--to must be after --from" in capsys.readouterr().err
    assert _nothing_written(tmp_path)


def test_cli_missing_video(tmp_path, capsys):
    argv = _setup(tmp_path)
    (tmp_path / "aula.mp4").unlink()
    assert main(argv) == 2 and "not found" in capsys.readouterr().err
    assert _nothing_written(tmp_path)


def test_cli_clip_too_short(tmp_path, capsys):
    assert main(_setup(tmp_path, from_="0:10", to="0:10.5")) == 2
    assert "at least" in capsys.readouterr().err
    assert _nothing_written(tmp_path)


@needs_ffmpeg
def test_cli_single_quote_in_video_name(tmp_path, capsys, synth_video):
    argv = _setup(tmp_path, name="d'aula.mp4", from_="0:01", to="0:05")
    Path(argv[argv.index("clip") + 1]).write_bytes(synth_video(6).read_bytes())
    # the quote is sanitized out of the workdir name, so the request fails on its own merits (no words)
    assert main(argv) == 2 and "no transcribed words" in capsys.readouterr().err
    assert _nothing_written(tmp_path)


@needs_ffmpeg
def test_cli_to_past_the_end(tmp_path, capsys, synth_video):
    argv = _setup(tmp_path, from_="0:01", to="0:30")
    Path(argv[argv.index("clip") + 1]).write_bytes(synth_video(6).read_bytes())
    assert main(argv) == 2 and "past the end" in capsys.readouterr().err
    assert _nothing_written(tmp_path)


def test_cli_ffmpeg_error_exits_1_with_stderr_tail(tmp_path, capsys, monkeypatch):
    import shorts.clip
    from shorts.ffmpeg import FFmpegError

    def boom(*a, **k):
        raise FFmpegError(["ffmpeg", "-i", "x"], "line1\nlibass missing")
    monkeypatch.setattr(shorts.clip, "make_clip", boom)
    assert main(_setup(tmp_path)) == 1
    assert "libass missing" in capsys.readouterr().err


def test_dereverb_must_be_a_configured_level(tmp_path, capsys):
    from shorts.cli import main
    video = tmp_path / "v.mov"
    video.write_bytes(b"x")
    (tmp_path / "v.palavras.json").write_text('{"version": 1, "words": []}', encoding="utf-8")
    code = main(["clip", str(video), "--channel", "catholic-br", "--format", "solo-standing",
                 "--from", "0", "--to", "5", "--dereverb", "15"])
    assert code == 2 and "dereverb must be one of" in capsys.readouterr().err


def test_dereverb_on_a_channel_without_sound_is_rejected(tmp_path, capsys):
    argv = _setup(tmp_path)
    (tmp_path / "channels.toml").write_text('[channels.catholic-br]\nlanguage = "pt"\nsound = false\n', encoding="utf-8")
    code = main(argv + ["--dereverb", "20"])
    assert code == 2
    assert "error: channel catholic-br does not treat sound; --dereverb has no effect" in capsys.readouterr().err


def test_bad_dereverb_config_is_one_error_line(tmp_path, capsys):
    cfg = tmp_path / "config.toml"
    cfg.write_text(f'media_root = "{(tmp_path / "media").as_posix()}"\n[dereverb]\nlevels = [10, 20]\n', encoding="utf-8")
    code = main(["--config", str(cfg), "doctor"])
    err = capsys.readouterr().err
    assert code == 2 and err.startswith("error: config.toml [dereverb]: ") and "Traceback" not in err
