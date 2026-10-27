"""Where B-roll files live (S8B spec 6): media in the media root, never in Git."""
from __future__ import annotations

from pathlib import Path


def broll_dir(app, job) -> Path:
    return Path(app.media_root).expanduser() / "broll" / job.id


def cache_dir(app, job) -> Path:
    return Path(app.media_root).expanduser() / "cache" / job.id / "broll"


def thumbs_dir(app, job) -> Path:
    return cache_dir(app, job) / "thumbs"


def search_dir(app, job) -> Path:
    return cache_dir(app, job) / "search"


def result_path(job, clip_id: str) -> Path:
    return job.root / "broll" / f"{clip_id}.json"
