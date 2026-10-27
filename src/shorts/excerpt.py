"""The listening excerpt of a class at every dereverb strength (S8 audio spec 5)."""
from __future__ import annotations

from pathlib import Path

from shorts import jobs
from shorts.audio import loudnorm_measure, render_audio
from shorts.dereverb import audio_cache_dir, dereverb_windows
from shorts.ffmpeg import probe
from shorts.silence import detect_silences
from shorts.timeline import Span, build_edl, group_edl
from shorts.words import load_words

FPS = 30


def excerpt_path(app, job, level: int) -> Path:
    return audio_cache_dir(app, job) / f"excerpt-{level}.m4a"


def excerpt_ready(app, job) -> bool:
    return all(excerpt_path(app, job, lv).is_file() for lv in app.dereverb.levels)


def first_candidate(job) -> dict:
    """The candidate that starts earliest in the class (spec 5.2)."""
    cands = jobs.read_json(job.candidates_json, {"candidates": []})["candidates"]
    if not cands:
        raise ValueError("no candidates: nothing to take the audio excerpt from")
    return min(cands, key=lambda c: c["segments"][0]["snapped"][0])


def trim_edl(edl: list[Span], seconds: float) -> list[Span]:
    out: list[Span] = []
    left = seconds
    for s in edl:
        if left <= 1e-6:
            break
        take = min(s.duration, left)
        out.append(Span(s.start, s.start + take))
        left -= take
    return out


def make_excerpts(job, app, channel, detect=detect_silences) -> list[Path]:
    """One .m4a per level: the first `excerpt_seconds` of the first candidate's sound, silence
    cuts applied as in the render, dereverbed (except level 0), cleaned and normalised."""
    meta = jobs.read_json(job.job_json)
    master = Path(meta["master"])
    info = probe(master)
    if not info.has_audio:
        raise ValueError(f"{master} has no audio stream")
    segments = [Span(*s["snapped"]) for s in first_candidate(job)["segments"]]
    silences: list[Span] = []
    if channel.silence:
        for seg in segments:
            silences += detect(master, seg)
    edl = trim_edl(build_edl(segments, silences, load_words(job.words_json), fps=FPS),
                   app.dereverb.excerpt_seconds)
    windows = [w for w, _ in group_edl(edl, segments)]
    cache = audio_cache_dir(app, job)
    master_id = meta.get("master_hash") or jobs.quick_hash(master)
    out: list[Path] = []
    for level in app.dereverb.levels:
        files = (dereverb_windows(master, windows, level, app.dereverb, cache, master_id, info.duration)
                 if level > 0 else None)
        measured = loudnorm_measure(master, edl, segments, files)
        out.append(render_audio(master, edl, segments, files, measured, excerpt_path(app, job, level)))
    return out
