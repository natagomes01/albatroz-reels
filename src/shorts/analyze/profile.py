"""Channel profile: ICP, audience/anti-audience, learned lessons (spec 4.5), and the channel's
caption notes for the caption-fix pass (caption spec 4.2)."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

CAPTION_NOTES = "captions.md"


@dataclass(frozen=True)
class ChannelProfile:
    channel_id: str
    language: str
    icp: str
    audience: str
    memory: list[str] = field(default_factory=list)

    def as_prompt_block(self) -> str:
        lessons = "\n\n".join(self.memory) if self.memory else "(none yet)"
        return (f"# Channel profile: {self.channel_id}\n"
                f"Content language: {self.language}\n\n"
                f"## ICP\n{self.icp.strip()}\n\n"
                f"## Audience\n{self.audience.strip()}\n\n"
                f"## Learned lessons\n{lessons.strip()}\n")

    def digest(self) -> str:
        return hashlib.sha256(self.as_prompt_block().encode("utf-8")).hexdigest()


def _brand_base(channel, repo_root: Path) -> Path:
    base = Path(channel.brand_dir).expanduser()
    return base if base.is_absolute() else Path(repo_root) / base


def load_profile(channel, repo_root: Path) -> ChannelProfile:
    if channel.brand_dir is None:
        raise FileNotFoundError(f"channel '{channel.id}' has no brand_dir in channels.toml")
    base = _brand_base(channel, repo_root)
    for name in ("icp.md", "audience.md"):
        if not (base / name).exists():
            raise FileNotFoundError(f"channel '{channel.id}': missing {base / name}")
    mem_dir = base / "memory"
    memory = [p.read_text(encoding="utf-8") for p in sorted(mem_dir.glob("*.md"))] if mem_dir.is_dir() else []
    return ChannelProfile(channel_id=channel.id, language=channel.language,
                          icp=(base / "icp.md").read_text(encoding="utf-8"),
                          audience=(base / "audience.md").read_text(encoding="utf-8"),
                          memory=memory)


def load_caption_notes(channel, repo_root: Path) -> str:
    """profiles/<channel>/captions.md: canon, spellings and recurring terms for the caption-fix
    pass. Optional: no brand_dir or no file gives empty notes."""
    if channel.brand_dir is None:
        return ""
    path = _brand_base(channel, repo_root) / CAPTION_NOTES
    return path.read_text(encoding="utf-8").strip() if path.is_file() else ""


def caption_channel_block(channel, notes: str) -> str:
    """The static channel layer of the class-sheet and caption-fix requests."""
    return (f"# Channel: {channel.id}\n"
            f"Content language: {channel.language}\n"
            f"Glossary: {channel.glossary or '(none)'}\n\n"
            f"## Caption notes\n{notes or '(none)'}\n")


def text_digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
