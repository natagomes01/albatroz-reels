from dataclasses import replace

import pytest

from conftest import needs_ffmpeg
from shorts import jobs
from shorts.config import AppConfig, ChannelConfig
from shorts.dereverb import audio_duration
from shorts.excerpt import excerpt_path, excerpt_ready, first_candidate, make_excerpts, trim_edl
from shorts.timeline import Span

CH = ChannelConfig(id="catholic-br", language="pt", brand_dir=None, glossary="", silence=False)


def make_job(tmp_path, master):
    job = jobs.create_job(tmp_path / "jobs", "j", {"channel": "catholic-br", "format": "solo-standing",
                                                   "master": str(master), "master_hash": "mh"})
    jobs.write_json_atomic(job.words_json, {"version": 1, "words": [
        {"t": i * 0.5, "w": f"w{i}.", "p": 1} for i in range(24)]})

    def cand(cid, a, b):
        return {"id": cid, "segments": [{"snapped": [a, b]}]}
    jobs.write_json_atomic(job.candidates_json, {"candidates": [cand("c02", 6.0, 11.0),
                                                                cand("c01", 1.0, 9.0)]})
    return job


def test_trim_edl_cuts_at_the_length():
    edl = [Span(1.0, 3.0), Span(4.0, 10.0)]
    assert trim_edl(edl, 5.0) == [Span(1.0, 3.0), Span(4.0, 7.0)]
    assert trim_edl(edl, 1.0) == [Span(1.0, 2.0)]


def test_first_candidate_is_the_earliest_in_the_class(tmp_path):
    job = make_job(tmp_path, tmp_path / "m.mp4")
    assert first_candidate(job)["id"] == "c01"


@needs_ffmpeg
def test_four_files_of_the_excerpt_length(synth_video, fake_uvr, tmp_path):
    cfg, calls = fake_uvr
    master = synth_video(12)
    job = make_job(tmp_path, master)
    app = AppConfig(media_root=tmp_path / "media", jobs_dir=tmp_path / "jobs", backends={},
                    dereverb=replace(cfg, excerpt_seconds=5.0))
    assert not excerpt_ready(app, job)
    out = make_excerpts(job, app, CH)
    assert out == [excerpt_path(app, job, lv) for lv in (0, 10, 20, 30)]
    assert all(abs(audio_duration(p) - 5.0) <= 0.1 for p in out)
    assert [line.split()[0] for line in calls.read_text(encoding="utf-8").splitlines()] == ["10", "20", "30"]
    assert excerpt_ready(app, job)
    assert out[0].parent == tmp_path / "media" / "cache" / "j" / "audio"


def test_no_candidates_is_a_clear_error(tmp_path):
    job = make_job(tmp_path, tmp_path / "m.mp4")
    jobs.write_json_atomic(job.candidates_json, {"candidates": []})
    with pytest.raises(ValueError, match="no candidates"):
        first_candidate(job)
