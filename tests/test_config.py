from pathlib import Path

import pytest

from shorts import machine
from shorts.cli import parse_time
from shorts.config import ConfigError, load_channels, load_config


def test_config_and_channels(tmp_path):
    (tmp_path / "config.toml").write_text('media_root = "~/dev/albatroz-media"\n[backends.scan]\nbackend = "claude-cli"\nmodel = "claude-haiku-4-5"\n', encoding="utf-8")
    app = load_config(tmp_path / "config.toml")
    assert app.media_root == Path("~/dev/albatroz-media").expanduser()
    assert app.jobs_dir == tmp_path / "jobs" and app.scan_threshold == 60
    (tmp_path / "channels.toml").write_text('[channels.catholic-br]\nlanguage = "pt"\nglossary = "Agostinho"\n[channels.ai-en]\nlanguage = "en"\nsound = false\n', encoding="utf-8")
    ch = load_channels(tmp_path / "channels.toml")
    assert ch["catholic-br"].weights["hook"] == 0.30 and ch["catholic-br"].brand_dir is None
    assert ch["ai-en"].sound is False


def test_channel_weights_must_sum_to_one(tmp_path):
    (tmp_path / "c.toml").write_text('[channels.x]\nlanguage = "pt"\n[channels.x.weights]\nhook = 0.9\n', encoding="utf-8")
    with pytest.raises(ValueError, match="sum to 1.0"):
        load_channels(tmp_path / "c.toml")


def test_parse_time():
    assert parse_time("41:10") == 2470.0
    assert parse_time("1:02:03.5") == 3723.5
    assert parse_time("90") == 90.0


def test_repo_config_has_the_caption_pass_backends():
    from shorts.llm.base import get_backend
    from shorts.llm.claude_cli import ClaudeCliBackend
    app = load_config(Path(__file__).resolve().parents[1] / "config.toml")
    assert app.backends["caption_fix"] == {"backend": "claude-cli", "model": "claude-sonnet-5"}
    assert app.backends["class_sheet"] == {"backend": "claude-cli", "model": "claude-haiku-4-5"}
    for name, model in (("caption_fix", "claude-sonnet-5"), ("class_sheet", "claude-haiku-4-5")):
        b = get_backend(name, app)
        assert isinstance(b, ClaudeCliBackend) and b.model == model


def test_dereverb_section(tmp_path):
    from shorts.config import load_config
    p = tmp_path / "config.toml"
    p.write_text('media_root = "media"\n[dereverb]\nlevels = [0, 20, 40]\n'
                 'model_dir = "models"\nseparator = "bin/sep"\nexcerpt_seconds = 15\n', encoding="utf-8")
    d = load_config(p).dereverb
    assert d.levels == (0, 20, 40) and d.excerpt_seconds == 15.0
    assert d.model == "UVR-DeEcho-DeReverb.pth"
    assert d.model_dir == (tmp_path / "models").resolve()
    assert d.separator == (tmp_path / "bin" / "sep").resolve()


def test_dereverb_defaults_when_absent(tmp_path):
    from shorts.config import load_config
    p = tmp_path / "config.toml"
    p.write_text('media_root = "media"\n', encoding="utf-8")
    d = load_config(p).dereverb
    assert d.levels == (0, 10, 20, 30) and d.separator.name == "audio-separator"


def test_broll_section_and_channel_toggle(tmp_path):
    from shorts.broll.model import BrollConfig
    from shorts.config import ConfigError, load_channels, load_config
    cfg = tmp_path / "config.toml"
    cfg.write_text('media_root = "m"\n[broll]\nuser_agent = "x (a@b)"\npan_px_per_s = 30\n', encoding="utf-8")
    app = load_config(cfg)
    assert app.broll.user_agent == "x (a@b)" and app.broll.pan_px_per_s == 30.0
    assert app.broll.candidates == BrollConfig().candidates
    cfg.write_text('media_root = "m"\n[broll]\ncandidates = 0\n', encoding="utf-8")
    with pytest.raises(ConfigError, match=r"\[broll\] candidates"):
        load_config(cfg)
    cfg.write_text('media_root = "m"\n[broll]\nmax_share = 1.5\n', encoding="utf-8")
    with pytest.raises(ConfigError, match="max_share"):
        load_config(cfg)
    ch = tmp_path / "channels.toml"
    ch.write_text('[channels.a]\nlanguage = "pt"\n[channels.b]\nlanguage = "en"\nbroll = false\n', encoding="utf-8")
    chans = load_channels(ch)
    assert chans["a"].broll is True and chans["b"].broll is False


def test_repo_config_has_the_broll_pass():
    from shorts.config import load_config
    app = load_config(Path(__file__).resolve().parents[1] / "config.toml")
    assert app.backends["broll"] == {"backend": "claude-cli", "model": "claude-haiku-4-5"}
    assert app.broll.split_face_y == 1250 and app.broll.max_still_px == 4096


@pytest.mark.skipif(not machine.MAC, reason="the SMB share lives in /Volumes on the Mac only")
def test_media_root_on_unmounted_volume_is_refused(tmp_path):
    # An unmounted SMB share would make mkdir fill a fake folder in /Volumes on the Mac's own disk.
    cfg = tmp_path / "config.toml"
    cfg.write_text('media_root = "/Volumes/no-such-share-xyz/albatroz-media"\n')
    with pytest.raises(ConfigError, match="not mounted"):
        load_config(cfg)


def test_final_dir_defaults_under_media_root_and_can_point_elsewhere(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text('media_root = "m"\n')
    assert load_config(cfg).final_dir == tmp_path / "m" / "final"
    cfg.write_text('media_root = "m"\nfinal_dir = "local/final"\n')
    assert load_config(cfg).final_dir == tmp_path / "local" / "final"
