"""`shorts clean`: delete renders of REJECTED clips only (spec 4.1, 4.4). Drive is untouched.

Pending and never-reviewed clips are kept: a clip set back to pending is Natã thinking it over,
not a rejection (review M11).
"""
from __future__ import annotations

import shutil
from pathlib import Path

from shorts import jobs
from shorts.broll.paths import thumbs_dir


def _check_segment(value: str, what: str) -> None:
    if not value or value in (".", "..") or "/" in value or "\\" in value:
        raise ValueError(f"unsafe {what}: {value!r}")


def run_clean(job, app, channel_id: str) -> list[Path]:
    """Delete renders of rejected clips and the job's B-roll thumbnail cache.

    Renders (.mp4, .json, .key, including `<id>.tmp.mp4` leftovers) of rejected clips.

    Returns the deleted files except `.key` files. Only touches real files directly inside
    `<media_root>/renders/<channel>/<job>/`; masters can never be reached (ValueError on an unsafe
    channel or job id, nothing deleted when the folder resolves outside renders/, symlinks skipped).
    """
    _check_segment(channel_id, "channel id")
    _check_segment(job.id, "job id")
    removed: list[Path] = []
    thumbs = thumbs_dir(app, job)
    cache_root = (Path(app.media_root).expanduser() / "cache").resolve()
    if thumbs.is_dir() and not thumbs.is_symlink() and thumbs.resolve().is_relative_to(cache_root):
        shutil.rmtree(thumbs)                # S8B spec 6: thumbnails are regenerable
        removed.append(thumbs)
    decisions = jobs.read_json(job.review_json, {"decisions": {}})["decisions"]
    rejected = {cid for cid, d in decisions.items() if d.get("status") == "rejected"}
    renders = (Path(app.media_root).expanduser() / "renders").resolve()
    folder = renders / channel_id / job.id
    if not folder.is_dir() or not folder.resolve().is_relative_to(renders):
        return removed
    folder = folder.resolve()
    for p in sorted(folder.iterdir()):
        if p.is_symlink() or not p.is_file():
            continue
        if p.suffix in (".mp4", ".json", ".key") and p.name.split(".")[0] in rejected:
            p.unlink()
            removed.append(p)
    return [p for p in removed if p.suffix != ".key"]
