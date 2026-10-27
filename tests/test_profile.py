from pathlib import Path

import pytest

from shorts.analyze.profile import caption_channel_block, load_caption_notes, load_profile, text_digest
from shorts.config import ChannelConfig

REPO = Path(__file__).resolve().parents[1]


def _chan(brand_dir):
    return ChannelConfig(id="catholic-br", language="pt", brand_dir=brand_dir, glossary="")


def test_loads_starter_profile_relative_to_repo():
    p = load_profile(_chan(Path("profiles/catholic-br")), REPO)
    assert "sola scriptura" in p.audience
    assert p.language == "pt"
    block = p.as_prompt_block()
    assert "## ICP" in block and "## Audience" in block and "## Learned lessons" in block


def test_memory_files_sorted_and_optional(tmp_path):
    (tmp_path / "icp.md").write_text("I", encoding="utf-8")
    (tmp_path / "audience.md").write_text("A", encoding="utf-8")
    p = load_profile(_chan(tmp_path), tmp_path)
    assert p.memory == []
    (tmp_path / "memory").mkdir()
    (tmp_path / "memory" / "b.md").write_text("B", encoding="utf-8")
    (tmp_path / "memory" / "a.md").write_text("A2", encoding="utf-8")
    assert load_profile(_chan(tmp_path), tmp_path).memory == ["A2", "B"]


def test_digest_changes_when_memory_changes(tmp_path):
    (tmp_path / "icp.md").write_text("I", encoding="utf-8")
    (tmp_path / "audience.md").write_text("A", encoding="utf-8")
    d1 = load_profile(_chan(tmp_path), tmp_path).digest()
    (tmp_path / "memory").mkdir()
    (tmp_path / "memory" / "x.md").write_text("new lesson", encoding="utf-8")
    assert load_profile(_chan(tmp_path), tmp_path).digest() != d1


def test_missing_brand_dir_errors(tmp_path):
    with pytest.raises(FileNotFoundError, match="brand_dir"):
        load_profile(_chan(None), tmp_path)
    with pytest.raises(FileNotFoundError, match="icp.md"):
        load_profile(_chan(tmp_path / "nope"), tmp_path)


def test_starter_caption_notes_for_catholic_br():
    notes = load_caption_notes(_chan(Path("profiles/catholic-br")), REPO)
    for needle in ["Eloí, Eloí, lamá sabactâni", "Septuaginta", "Deuteronômio", "kaaru", "kaari",
                   "deuterocanonical", "Tobias", "paraphrase", "never rewrite"]:
        assert needle in notes, needle


def test_missing_caption_notes_are_empty(tmp_path):
    (tmp_path / "icp.md").write_text("I", encoding="utf-8")
    assert load_caption_notes(_chan(tmp_path), tmp_path) == ""
    assert load_caption_notes(_chan(None), tmp_path) == ""
    (tmp_path / "captions.md").write_text("  Write Eloí.\n\n", encoding="utf-8")
    assert load_caption_notes(_chan(tmp_path), tmp_path) == "Write Eloí."


def test_caption_channel_block_and_digest():
    ch = ChannelConfig(id="catholic-br", language="pt", brand_dir=None, glossary="Septuaginta")
    block = caption_channel_block(ch, "Write Eloí.")
    assert "Content language: pt" in block and "Glossary: Septuaginta" in block
    assert "## Caption notes\nWrite Eloí." in block
    assert "## Caption notes\n(none)" in caption_channel_block(ch, "")
    assert text_digest("a") != text_digest("b") and len(text_digest("")) == 64
