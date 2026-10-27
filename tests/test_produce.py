import json

import pytest

from shorts import clip
from shorts.clip import ClipRequest, produce
from shorts.config import ChannelConfig
from shorts.ffmpeg import VideoInfo
from shorts.timeline import Span
from shorts.vision import Box
from shorts.words import Word

INFO = VideoInfo(width=1280, height=720, fps=30.0, duration=600.0, color_transfer="bt709", has_audio=True)
CH = ChannelConfig(id="catholic-br", language="pt", brand_dir=None, glossary="", color=False, sound=False)
A, B = Span(100.0, 112.0), Span(300.0, 312.0)


def _words(start: float, end: float, tag: str) -> list[Word]:
    out, t, i = [], start + 0.2, 0
    while t < end - 0.3:
        out.append(Word(round(t, 2), f"{tag}{i}" + ("." if i % 8 == 7 else ""), 1.0))
        t, i = t + 0.45, i + 1
    return out


WORDS = _words(100.0, 112.0, "a") + _words(300.0, 312.0, "b")


def fake_track(master, seg, src_w, src_h, upper_body_only):
    cx = 300 if seg.start < 200 else 1000     # the speaker stands far apart in the two segments
    samples = [(seg.start + k / 3, Box(cx - 75, 100, 150, 500)) for k in range(int(seg.duration * 3))]
    faces = [(t, Box(b.cx - 40, 110, 80, 90)) for t, b in samples]
    return samples, faces


@pytest.fixture
def fakes(monkeypatch):
    calls = {"track": 0, "render": [], "preview": []}
    monkeypatch.setattr(clip, "probe", lambda path: INFO)
    monkeypatch.setattr(clip, "detect_silences", lambda master, span: [])

    def track(*args):
        calls["track"] += 1
        return fake_track(*args)

    def render(inp, workdir):
        calls["render"].append(inp)
        return inp.out

    def preview(master, info, edl, segments, crops, bodies, out, fps=30):
        calls["preview"].append((crops, bodies))
        return out

    monkeypatch.setattr(clip, "_track_segment", track)
    monkeypatch.setattr(clip, "render_clip", render)
    monkeypatch.setattr(clip, "track_preview", preview)
    return calls


def req(tmp_path, segments, **kw) -> ClipRequest:
    base = dict(master=tmp_path / "m.mp4", segments=segments, words=WORDS, channel=CH,
                fmt="solo-standing", out_path=tmp_path / "out" / "c01.mp4", work_dir=tmp_path / "work")
    base.update(kw)
    return ClipRequest(**base)


def test_two_segments_make_one_edl_and_switch_shot_at_the_join(tmp_path, fakes):
    res = produce(req(tmp_path, [A, B], stop_after="captions"))
    assert res.edl == [A, B] and res.duration == pytest.approx(24.0)
    shots = json.loads((tmp_path / "work" / "shots.json").read_text(encoding="utf-8"))["shots"]
    assert not [s for s in shots if s["start"] < 12.0 - 1e-6 and s["end"] > 12.0 + 1e-6]
    before = next(s for s in shots if abs(s["end"] - 12.0) < 1e-6)
    after = next(s for s in shots if abs(s["start"] - 12.0) < 1e-6)
    assert before["kind"] != after["kind"]
    assert fakes["render"] == []


def test_out_of_order_segments_play_in_request_order(tmp_path, fakes):
    res = produce(req(tmp_path, [B, A], stop_after="captions"))
    assert res.edl == [B, A]
    ass = (tmp_path / "work" / "captions.ass").read_text(encoding="utf-8")
    first_line = next(line for line in ass.splitlines() if line.startswith("Dialogue:"))
    assert "B0" in first_line and "A0" not in first_line


def test_stop_after_track_writes_track_files_only(tmp_path, fakes):
    res = produce(req(tmp_path, [A], stop_after="track"))
    work = tmp_path / "work"
    assert res.out_path is None
    assert (work / "edl.json").exists() and (work / "track.json").exists() and (work / "shots.json").exists()
    assert not (work / "captions.ass").exists() and fakes["render"] == []


def test_reuse_track_skips_vision(tmp_path, fakes, monkeypatch):
    produce(req(tmp_path, [A], stop_after="track"))
    assert fakes["track"] == 1
    monkeypatch.setattr(clip, "_track_segment", lambda *a: pytest.fail("Vision ran again"))
    produce(req(tmp_path, [A], stop_after="captions", reuse_track=True))


def test_reuse_track_is_ignored_when_segments_changed(tmp_path, fakes):
    produce(req(tmp_path, [A], stop_after="track"))
    produce(req(tmp_path, [Span(101.0, 112.0)], stop_after="track", reuse_track=True))
    assert fakes["track"] == 2


def test_word_fix_reaches_the_captions(tmp_path, fakes):
    words = [Word(w.t, "Denzinger", w.p) if w.w == "a3" else w for w in WORDS]
    produce(req(tmp_path, [A], stop_after="captions", words=words))
    assert "DENZINGER" in (tmp_path / "work" / "captions.ass").read_text(encoding="utf-8")


def test_render_gets_segments_and_output_path(tmp_path, fakes):
    res = produce(req(tmp_path, [B, A]))
    inp = fakes["render"][0]
    assert inp.segments == [B, A] and inp.out == tmp_path / "out" / "c01.mp4"
    assert inp.safe_zone is None and len(inp.crops) == 720
    assert res.out_path == inp.out and res.shots


def test_missing_safe_zone_template_fails_before_any_work(tmp_path, fakes):
    with pytest.raises(FileNotFoundError, match="safe-zone"):
        produce(req(tmp_path, [A], safe_zone=True, repo_root=tmp_path))
    assert fakes["track"] == 0


def test_preview_gets_one_body_per_output_frame(tmp_path, fakes):
    res = produce(req(tmp_path, [A], stop_after="track", preview=True))
    crops, bodies = fakes["preview"][0]
    assert len(crops) == len(bodies) == 360 and bodies[0] is not None
    assert res.preview_path == tmp_path / "work" / "track-preview.mp4"


def test_job_color_points_are_used_instead_of_measuring(tmp_path, fakes, monkeypatch):
    from dataclasses import replace
    from shorts.color import Grade
    monkeypatch.setattr(clip, "measure_points", lambda *a: pytest.fail("measured the master again"))
    monkeypatch.setattr(clip, "loudnorm_measure", lambda *a: None)
    g = Grade(0.01, 0.01, 0.01, 0.9, 0.9, 0.8, 1.05)
    produce(req(tmp_path, [A], channel=replace(CH, color=True), color_points=((0.0, g),)))
    assert fakes["render"][0].grade == g


def test_rejects_bad_requests(tmp_path, fakes):
    with pytest.raises(ValueError, match="1 to 3"):
        produce(req(tmp_path, [A, B, Span(400.0, 410.0), Span(500.0, 510.0)]))
    with pytest.raises(ValueError, match="overlap"):
        produce(req(tmp_path, [A, Span(105.0, 115.0)]))
    with pytest.raises(ValueError, match="phase 1b"):
        produce(req(tmp_path, [A], fmt="conversation"))
    with pytest.raises(ValueError, match="stop_after"):
        produce(req(tmp_path, [A], stop_after="upload"))


def test_dereverb_feeds_the_loudness_pass_and_the_render(tmp_path, fakes, monkeypatch):
    from dataclasses import replace
    from shorts.dereverb import DereverbConfig
    seen = {}

    def windows(master, wins, strength, cfg, cache_dir, master_id, duration):
        seen.update(wins=wins, strength=strength, cache=cache_dir, master_id=master_id)
        return [tmp_path / f"w{i}.wav" for i in range(len(wins))]

    monkeypatch.setattr(clip, "dereverb_windows", windows)
    monkeypatch.setattr(clip, "loudnorm_measure",
                        lambda master, edl, segs, files=None: seen.setdefault("measured_from", files) and {})
    produce(req(tmp_path, [B, A], channel=replace(CH, sound=True), dereverb=20,
                dereverb_cfg=DereverbConfig(), audio_cache=tmp_path / "cache", master_id="mh"))
    inp = fakes["render"][0]
    assert seen["strength"] == 20 and seen["cache"] == tmp_path / "cache" and seen["master_id"] == "mh"
    assert len(seen["wins"]) == 2 and seen["wins"][0].start >= B.start - 1e-6   # playback order
    assert inp.audio_files == [tmp_path / "w0.wav", tmp_path / "w1.wav"]
    assert seen["measured_from"] == inp.audio_files


def test_strength_zero_or_untreated_sound_never_calls_uvr(tmp_path, fakes, monkeypatch):
    from dataclasses import replace
    monkeypatch.setattr(clip, "dereverb_windows", lambda *a: pytest.fail("UVR must not run"))
    monkeypatch.setattr(clip, "loudnorm_measure", lambda *a, **k: {})
    produce(req(tmp_path, [A], channel=replace(CH, sound=True), dereverb=0))
    produce(req(tmp_path, [A], channel=CH, dereverb=20))          # CH has sound=False
    assert all(inp.audio_files is None for inp in fakes["render"])
def test_picked_broll_reaches_the_render_with_clip_times(tmp_path, fakes):
    from shorts.broll.files import BrollFileMissing
    from shorts.broll.inserts import BrollPlan, split_top
    img = tmp_path / "a.jpg"
    img.write_bytes(b"x")
    plan = BrollPlan("s1", 104.0, 108.0, "image", img, "split", "cover", "still", (0.5, 0.5), 4000, 2000, {})
    produce(req(tmp_path, [A], broll=(plan,)))
    inp = fakes["render"][0]
    ins = inp.broll[0]
    assert (ins.start, ins.end) == pytest.approx((4.0, 8.0)) and inp.pan_px_per_s == 40.0
    expected = split_top(Box(260, 110, 80, 90), Box(225, 100, 150, 500), inp.crops[180], 1250)
    assert ins.split_top == expected
    img.unlink()
    with pytest.raises(BrollFileMissing, match="a.jpg"):
        produce(req(tmp_path, [A], broll=(plan,)))
