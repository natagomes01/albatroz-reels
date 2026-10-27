"""`shorts ingest`: place the master in the media root and transcribe it (spec 4.1, 4.4, 5)."""
from __future__ import annotations

import os
import re
import subprocess
import sys
import time
import unicodedata
from datetime import date
from pathlib import Path

from shorts import jobs, machine
from shorts.ffmpeg import probe

FORMATS = ("solo-standing", "solo-seated")
MAX_TOPIC = 300


def clean_topic(text) -> str:
    """The owner's topic line for the caption pass (caption spec 4.2): one line, at most 300 chars."""
    return " ".join(str(text or "").split())[:MAX_TOPIC]


def _stderr(msg: str) -> None:
    print(msg, file=sys.stderr)


def check_format(fmt: str) -> None:
    if fmt == "conversation":
        raise ValueError("format 'conversation' arrives in phase 1b")
    if fmt not in FORMATS:
        raise ValueError(f"unknown format '{fmt}' (use one of {', '.join(FORMATS)})")


def _masters(media_root: Path) -> Path:
    return Path(media_root).expanduser() / "masters"


def make_job_id(video: Path, media_root: Path, today: date | None = None) -> str:
    video = Path(video).expanduser().resolve()
    if video.parent == _masters(media_root).resolve():
        return video.stem                          # already placed: its name IS the job id
    today = today or date.today()
    stem = unicodedata.normalize("NFKD", video.stem).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", stem.lower()).strip("-") or "class"
    return f"{today:%y%m%d}-{slug}"


def place_master(video: Path, media_root: Path, job_id: str) -> Path:
    video = Path(video).expanduser().resolve()
    masters = _masters(media_root)
    masters.mkdir(parents=True, exist_ok=True)
    if video.parent == masters.resolve():
        return video
    dst = masters / f"{job_id}{video.suffix.lower()}"
    if dst.exists():
        raise FileExistsError(f"{dst} already exists")
    if video.stat().st_dev != masters.stat().st_dev:
        raise RuntimeError(f"{video} is on another volume; move it into {masters} yourself "
                           f"(the pipeline never copies masters)")
    video.rename(dst)
    return dst


def input_warnings(info) -> list[str]:
    out = []
    if info.height < 1080:
        out.append("input_below_1080p")
    if getattr(info, "is_hdr", False):
        out.append("hdr_input")
    return out


_WARN_TEXT = {
    "input_below_1080p": "warning: input is below 1080p; close-ups will be soft (use the camera master)",
    "hdr_input": "warning: input is HDR; the render converts it to SDR bt709 before grading",
}


def ingest(video: Path, channel, fmt: str, app, runner=subprocess.run,
           today: date | None = None, warn=_stderr, topic: str = "") -> jobs.Job:
    check_format(fmt)
    job_id = make_job_id(video, app.media_root, today)
    job_root = Path(app.jobs_dir) / job_id
    if (job_root / "job.json").exists():
        job = jobs.Job(job_root)
        if job.words_json.exists():
            raise FileExistsError(f"job {job_id} is already ingested ({job.words_json})")
        meta = jobs.read_json(job.job_json)
        if topic:
            meta = {**meta, "topic": clean_topic(topic)}
            jobs.write_json_atomic(job.job_json, meta)
        master = Path(meta["master"])
    else:
        master = place_master(video, app.media_root, job_id)
        info = probe(master)
        warnings = input_warnings(info)
        job = jobs.create_job(app.jobs_dir, job_id, {
            "channel": channel.id, "format": fmt, "master": str(master),
            "master_hash": jobs.quick_hash(master), "duration": info.duration,
            "width": info.width, "height": info.height, "warnings": warnings,
            "topic": clean_topic(topic)})
        for w in warnings:
            warn(_WARN_TEXT[w])
    tr = app.transcreve
    cmd = [tr.get("python") or machine.default_python(), str(Path(tr["script"]).expanduser()),
           str(master), "--palavras", "--idioma", channel.language, "--saida", str(job.root)]
    if channel.glossary:
        cmd += ["--prompt", channel.glossary]
    started = time.monotonic()
    r = runner(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    jobs.log_event(job, kind="transcreve", cmd=cmd, returncode=r.returncode, stderr=r.stderr[-2000:],
                   wall_s=round(time.monotonic() - started, 3))
    if r.returncode != 0:
        raise RuntimeError(f"transcreve failed (exit {r.returncode}); fix it and run the same "
                           f"`shorts ingest` again on {master} (it resumes). Log: {job.log_path}")
    out = job.root / f"{master.stem}.palavras.json"
    if not out.exists():
        raise RuntimeError(f"transcreve finished but {out} is missing (is it the --palavras version?)")
    os.replace(out, job.words_json)
    return job
