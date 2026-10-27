"""Clip time for B-roll moments (S8B spec 4): the clip's EDL, read from clips/<id>/edl.json when it
was made for the same segments, else made here with the same calls `clip.produce()` uses."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path

from shorts import jobs
from shorts.silence import detect_silences
from shorts.timeline import Span, TimeMap, build_edl
from shorts.words import Word

FPS = 30            # clip.FPS; not imported, to keep clip.py out of the review server's imports


def clip_map(job, clip_id: str, channel, spans: list[Span], words: list[Word], master: Path,
             detect=detect_silences, has_audio: Callable[[], bool] | None = None) -> TimeMap:
    path = job.clip_dir(clip_id) / "edl.json"
    seg = [[s.start, s.end] for s in spans]
    try:
        data = jobs.read_json(path)
    except ValueError:
        data = None
    if isinstance(data, dict) and data.get("segments") == seg and data.get("edl"):
        return TimeMap([Span(d["start"], d["end"]) for d in data["edl"]])
    silences: list[Span] = []
    if channel.silence:
        if has_audio is None:
            from shorts.ffmpeg import probe
            has_audio = lambda: probe(master).has_audio      # noqa: E731
        if has_audio():
            for s in spans:
                silences += detect(master, s)
    edl = build_edl(spans, silences, words, fps=FPS)
    jobs.write_json_atomic(path, {"segments": seg, "edl": [asdict(s) for s in edl]})
    return TimeMap(edl)
