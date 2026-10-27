"""`shorts export <job>`: one folder per rendered clip, everything the content kit needs to write
the caption, the SEO and the on-screen hook (handoff doc: documentation/features/content-kit-handoff.md).

Per clip: the video (a hard link, so no second copy of the file on disk), `clip.json` (the render's
meta: title, hook, channel, language, B-roll credits), `captions.ass`, `transcript.txt` (the words
the captions show, with the owner's fixes) and `context.md` (class topic, references, glossary).
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

from shorts import jobs
from shorts.stages import approved_clips, effective_clip_words, render_path


def _link_or_copy(src: Path, dst: Path) -> str:
    if dst.exists() or dst.is_symlink():
        dst.unlink()
    try:
        os.link(src, dst)
        return "linked"
    except OSError:
        shutil.copy2(src, dst)
        return "copied"


def transcript(job, plan) -> str:
    """The clip's words as the captions show them, one paragraph."""
    words = effective_clip_words(job, plan)
    text = [w.w for w in words if any(s.start <= w.t < s.end for s in plan.spans) and w.w]
    return " ".join(text).strip()


def context_md(job, channel, plan, meta: dict) -> str:
    sheet = (jobs.read_json(job.root / "analyze" / "class_sheet.json", {}) or {}).get("sheet") or {}
    lines = [f"# {plan.title}", "",
             f"- Channel: {channel.id} (content language: {channel.language})",
             f"- Job: {job.id}, clip {plan.id}",
             f"- Hook on screen: {plan.hook_text}",
             f"- Duration: {meta.get('duration', '?')} s",
             f"- Render version: {meta.get('render_version', '?')}", ""]
    if sheet.get("topic"):
        lines += ["## Class", "", str(sheet["topic"]), ""]
    if sheet.get("references"):
        lines += ["## References in the class", "", ", ".join(map(str, sheet["references"])), ""]
    terms = [t.get("term") for t in sheet.get("terms") or [] if isinstance(t, dict) and t.get("term")]
    if terms:
        lines += ["## Names and terms", "", ", ".join(terms), ""]
    if meta.get("credits"):
        lines += ["## Image credits (put them in the post)", "", str(meta["credits"]), ""]
    return "\n".join(lines).rstrip() + "\n"


def export_job(app, job, channel, dest: Path | None = None) -> list[dict]:
    """Export every approved clip that has a render. Returns one result per clip."""
    final = app.final_dir or Path(app.media_root).expanduser() / "final"
    base = Path(dest) if dest else final / channel.id / job.id
    out = []
    for plan in approved_clips(job):
        video = render_path(app, channel.id, job, plan.id)
        meta_path = video.with_suffix(".json")
        if not video.exists() or not meta_path.exists():
            out.append({"clip": plan.id, "skipped": "not rendered"})
            continue
        meta = jobs.read_json(meta_path)
        folder = base / plan.id
        folder.mkdir(parents=True, exist_ok=True)
        how = _link_or_copy(video, folder / f"{plan.id}.mp4")
        jobs.write_json_atomic(folder / "clip.json", meta)
        ass = job.root / "clips" / plan.id / "captions.ass"
        if ass.exists():
            shutil.copy2(ass, folder / "captions.ass")
        jobs.write_text_atomic(folder / "transcript.txt", transcript(job, plan) + "\n")
        jobs.write_text_atomic(folder / "context.md", context_md(job, channel, plan, meta))
        out.append({"clip": plan.id, "folder": str(folder), "video": how})
    index = [{"clip": r["clip"], "folder": r.get("folder")} for r in out if "folder" in r]
    if index:
        jobs.write_json_atomic(base / "index.json", {"job": job.id, "channel": channel.id, "clips": index})
    return out
