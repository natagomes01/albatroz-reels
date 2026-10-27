from __future__ import annotations

import hashlib
from pathlib import Path

PROMPTS_DIR = Path(__file__).resolve().parents[3] / "prompts"


def load_prompt(name: str) -> tuple[str, str]:
    text = (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")
    return text, hashlib.sha256(text.encode("utf-8")).hexdigest()
