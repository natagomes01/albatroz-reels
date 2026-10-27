"""One finished Short from 1-3 class segments. `shorts clip` and the job stages share `produce()`."""
from __future__ import annotations

import bisect
import json
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from shorts import jobs
from shorts.audio import loudnorm_measure
from shorts.broll.files import BrollFileMissing
from shorts.broll.inserts import make_inserts
from shorts.broll.model import BrollConfig
from shorts.captions import build_screens, caption_style, render_ass
from shorts.color import Grade, interpolate_grade, measure_points
from shorts.config import AppConfig, ChannelConfig
from shorts.dereverb import DereverbConfig, dereverb_windows
from shorts.ffmpeg import VideoInfo, probe
from shorts.preview import track_preview
from shorts.render import RenderInputs, _quote, render_clip
from shorts.shots import MIN_FRAGMENT, Shot, assert_in_bounds, crop_windows, plan_shots, settle_shots
from shorts.silence import detect_silences
from shorts.timeline import Span, TimeMap, build_edl, group_edl
from shorts.tracking import CameraParams, pick_subject, smooth_path
from shorts.vision import Box, detect, sample_frames
from shorts.words import Sentence, Word, load_words, sentences

REPO_ROOT = Path(__file__).resolve().parents[2]
FORMATS = {
    "solo-standing": {"dead_zone": 0.25, "upper_body_only": False},
    "solo-seated": {"dead_zone": 0.15, "upper_body_only": True},
}
FPS = 30
JUMP_FRACTION = 0.25  # body moved more than this share of the crop width across a cut
WEAK_TRACKING = 0.30
MIN_SHOT = 4.0
MIN_CLIP = 1.0  # seconds
HOOK_MAX = 6.0  # seconds; caps the hook when the transcript has no punctuation
STOPS = ("track", "captions", "render")


@dataclass(frozen=True)
class ClipRequest:
    master: Path
    segments: list[Span]            # class timeline, playback order
    words: list[Word]               # full class word list (review word fixes already applied)
    channel: ChannelConfig
    fmt: str                        # "solo-standing" | "solo-seated"
    out_path: Path                  # final .mp4 path
    work_dir: Path                  # edl.json, track.json, shots.json, captions.ass go here
    hook: Span | None = None        # class timeline; None = first sentence of the clip
    emphasis: tuple[Span, ...] = ()
    reuse_track: bool = False       # True: read work_dir/track.json instead of running Vision
    stop_after: str = "render"      # "track" | "captions" | "render"
    safe_zone: bool = False
    preview: bool = False           # with stop_after="track": also write work_dir/track-preview.mp4
    repo_root: Path = REPO_ROOT     # where assets/fonts and assets/safe-zone.png live
    color_points: tuple | None = None   # job's color.json points (spec 10.3); None = measure here
    dereverb: int = 0               # UVR aggression for this clip; 0 = off (S8 audio spec 4)
    dereverb_cfg: DereverbConfig | None = None   # None = the defaults of DereverbConfig
    audio_cache: Path | None = None  # where dereverbed windows are kept; None = work_dir / "audio"
    master_id: str = ""             # cache identity of the master; "" = its quick hash
    broll: tuple = ()               # S8B: BrollPlan per picked moment (class time)
    broll_cfg: BrollConfig | None = None   # None = the defaults of BrollConfig
    close_zoom: float | None = None # None = the format's CLOSE_ZOOM (a job setting may soften it)
    burn_captions: bool = True      # False: captions.ass is still written, the render leaves it out


@dataclass(frozen=True)
class ClipResult:
    out_path: Path | None           # None when stop_after != "render"
    duration: float                 # clip duration after EDL
    edl: list[Span]
    weak_tracking: bool
    shots: list[Shot] = field(default_factory=list)
    grade: Grade | None = None
    preview_path: Path | None = None


def hook_span(clip_words: list[Word], first: Sentence) -> Span:
    """The opening close-up: the first sentence plus 0.5 s, capped when nothing ends it."""
    start = clip_words[first.first].t
    return Span(start, min(clip_words[first.last].t + 0.5, start + HOOK_MAX))


def _even(v: float) -> int:
    return int(round(v / 2)) * 2


def _validate(req: ClipRequest, info: VideoInfo) -> None:
    if req.fmt not in FORMATS:
        raise ValueError(f"format {req.fmt!r} arrives in phase 1b" if req.fmt == "conversation"
                         else f"unknown format {req.fmt!r}")
    if req.stop_after not in STOPS:
        raise ValueError(f"stop_after must be one of {STOPS}")
    if not 1 <= len(req.segments) <= 3:
        raise ValueError("a clip has 1 to 3 segments")
    for seg in req.segments:
        if seg.end <= seg.start:
            raise ValueError(f"segment {seg.start:.2f}-{seg.end:.2f}: end must be after start")
        if seg.end > info.duration + 0.01:
            raise ValueError(f"segment ends at {seg.end:.2f}s, past the end of the video ({info.duration:.2f}s)")
    crop_w = _even(info.height * 9 / 16)
    if info.width < crop_w:
        raise ValueError(f"input is narrower than 9:16 ({info.width}x{info.height}); "
                         "vertical masters are not supported in S1")
    ordered = sorted(req.segments, key=lambda s: s.start)
    if any(b.start < a.end for a, b in zip(ordered, ordered[1:])):
        raise ValueError("clip segments overlap")


def _seg_index(segments: list[Span], t: float) -> int:
    return next((k for k, s in enumerate(segments) if s.start - 1e-6 <= t <= s.end + 1e-6), 0)


def _track_segment(master: Path, seg: Span, src_w: int, src_h: int, upper_body_only: bool):
    """Vision on one segment: [(t, subject box or None)], [(t, face box)], class timeline."""
    samples: list[tuple[float, Box | None]] = []
    faces: list[tuple[float, Box]] = []
    prev: float | None = None
    for t, bgra, w, h in sample_frames(master, seg):
        bodies, found = detect(bgra, w, h, upper_body_only, (src_w, src_h))
        subject = pick_subject(bodies, prev)
        samples.append((t, subject))
        if subject is None:
            continue
        prev = subject.cx
        inside = [f for f in found if subject.x <= f.cx <= subject.x + subject.w]
        if inside:
            faces.append((t, min(inside, key=lambda f: f.y)))
    return samples, faces


def _box_json(box: Box | None) -> list[float] | None:
    return None if box is None else [box.x, box.y, box.w, box.h]


def _save_track(path: Path, segments: list[Span], samples, faces) -> None:
    jobs.write_json_atomic(path, {
        "segments": [[s.start, s.end] for s in segments],
        "samples": [{"t": t, "box": _box_json(b)} for t, b in samples],
        "faces": [{"t": t, "box": _box_json(b)} for t, b in faces],
    })


def _load_track(path: Path, segments: list[Span]):
    """Saved samples and faces, or None when they were tracked for other segments."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("segments") != [[s.start, s.end] for s in segments]:
        return None
    samples = [(d["t"], None if d["box"] is None else Box(*d["box"])) for d in data["samples"]]
    faces = [(d["t"], Box(*d["box"])) for d in data["faces"]]
    return samples, faces


def _box_lookup(pairs: list[tuple[float, Box]], max_gap: float = 1.0):
    """Nearest box in time (within max_gap seconds), or None. Same helper as plan 1's clip.py,
    used for faces (close-up y) and for the followed body (close-up fallback, `body_at`)."""
    pairs = sorted(pairs, key=lambda p: p[0])
    times = [t for t, _ in pairs]

    def box_at(t: float) -> Box | None:
        if not pairs:
            return None
        i = bisect.bisect_left(times, t)
        best = min((j for j in (i - 1, i) if 0 <= j < len(pairs)), key=lambda j: abs(times[j] - t))
        return pairs[best][1] if abs(times[best] - t) <= max_gap else None

    return box_at


def _segment_joins(tm: TimeMap, segments: list[Span]) -> list[float]:
    """Clip-time cut points where playback jumps from one segment to another."""
    return [cut for i, cut in enumerate(tm.cut_points())
            if _seg_index(segments, tm.edl[i].start) != _seg_index(segments, tm.edl[i + 1].start)]


def _body_jumps(tm: TimeMap, samples: list[tuple[float, float | None]], crop_w: float,
                segments: list[Span]) -> list[float]:
    """Silence cuts inside one segment where the body moved more than JUMP_FRACTION of the crop."""
    known = sorted((t, cx) for t, cx in samples if cx is not None)
    if not known:
        return []
    times = [t for t, _ in known]

    def cx_near(t: float) -> float:
        return known[min(bisect.bisect_left(times, t), len(known) - 1)][1]

    jumps = []
    for i, cut in enumerate(tm.cut_points()):
        before, after = tm.edl[i].end, tm.edl[i + 1].start
        if _seg_index(segments, before) != _seg_index(segments, after):
            continue  # segment joins always switch (see _force_switch)
        if abs(cx_near(after) - cx_near(before)) > JUMP_FRACTION * crop_w:
            jumps.append(cut)
    return jumps


def _force_switch(shots: list[Shot], joins: list[float], min_len: float) -> list[Shot]:
    """Spec 8.2 ("a join between distant segments always switches shot"): every join inside a shot
    becomes a boundary and flips the kind, so the jump in the footage is hidden by the cut.

    Each shot is split by all of its joins at once (order-independent) into alternating pieces. The
    head keeps the shot's kind, except when it is a flash (under MIN_FRAGMENT) or the only short side
    of a single join: then the head takes the other kind and merges with the previous shot. A join
    closer than MIN_FRAGMENT to the previous join in the same shot is skipped. Finally adjacent
    shots of one kind merge and fragments under MIN_FRAGMENT are absorbed."""
    out: list[Shot] = []
    for s in shots:
        js: list[float] = []
        for j in sorted(joins):
            if s.start + 1e-6 < j < s.end - 1e-6 and (not js or j - js[-1] >= MIN_FRAGMENT):
                js.append(j)
        if not js:
            out.append(s)
            continue
        head, tail = js[0] - s.start, s.end - js[-1]
        flip = s.start > 0 and (head < MIN_FRAGMENT or (len(js) == 1 and head < min_len <= tail))
        first = out[-1].kind if flip and out else s.kind  # a flipped head joins the previous shot
        cuts = [s.start, *js, s.end]
        for i in range(len(cuts) - 1):
            out.append(Shot(cuts[i], cuts[i + 1], first if i % 2 == 0 else ("wide" if first == "close" else "close")))
    return settle_shots(out)


def _bodies_per_frame(samples, frame_times: list[float]) -> list[Box | None]:
    known = sorted(((t, b) for t, b in samples), key=lambda s: s[0])
    times = [t for t, _ in known]
    out: list[Box | None] = []
    for t in frame_times:
        i = bisect.bisect_right(times, t) - 1
        out.append(known[i][1] if i >= 0 and t - times[i] <= 0.5 else None)
    return out


def produce(req: ClipRequest) -> ClipResult:
    # the missing template must fail before any probing, tracking, color or loudness work
    sz = req.repo_root / "assets" / "safe-zone.png" if req.safe_zone else None
    if sz is not None and req.stop_after == "render" and not sz.exists():
        raise FileNotFoundError(f"{sz} is missing; copy Natã's safe-zone template there (see CLAUDE.md)")
    for p in (req.work_dir, req.repo_root / "assets" / "fonts", req.work_dir / "captions.ass",
              req.work_dir / "crop.cmd"):
        _quote(p)  # a single quote breaks the filter graph: fail now, not after the tracking
    info = probe(req.master)
    _validate(req, info)
    if info.height < 1080:
        print(f"warning: input is {info.height}p; the close-up will be soft (use the camera master)", file=sys.stderr)

    segments = list(req.segments)
    clip_words = [w for seg in segments for w in req.words if seg.start <= w.t < seg.end]
    if not clip_words:
        raise ValueError("no transcribed words inside the clip segments")
    silences: list[Span] = []
    if req.channel.silence and info.has_audio:
        for seg in segments:
            silences += detect_silences(req.master, seg)
    edl = build_edl(segments, silences, req.words, fps=FPS)  # each segment on its own frame grid
    tm = TimeMap(edl)
    work = req.work_dir
    work.mkdir(parents=True, exist_ok=True)
    jobs.write_json_atomic(work / "edl.json", {"segments": [[s.start, s.end] for s in segments],
                                               "edl": [asdict(s) for s in edl]})

    opts = FORMATS[req.fmt]
    crop_w = _even(info.height * 9 / 16)
    track_file = work / "track.json"
    loaded = _load_track(track_file, segments) if req.reuse_track and track_file.exists() else None
    if loaded is None:
        samples, faces = [], []
        for seg in segments:
            seg_samples, seg_faces = _track_segment(req.master, seg, info.width, info.height,
                                                    opts["upper_body_only"])
            samples += seg_samples
            faces += seg_faces
        _save_track(track_file, segments, samples, faces)
    else:
        samples, faces = loaded
    missing = sum(1 for _, b in samples if b is None) / max(len(samples), 1)
    weak = missing > WEAK_TRACKING
    if weak:
        print(f"warning: weak tracking ({missing:.0%} of samples without a person)", file=sys.stderr)

    params = CameraParams(crop_w=crop_w, src_w=info.width, dead_zone=opts["dead_zone"])
    n = int(round(tm.duration * FPS))
    frame_times = [tm.to_class(i / FPS) for i in range(n)]
    frame_seg = [_seg_index(segments, t) for t in frame_times]
    path = [info.width / 2] * n
    for k, seg in enumerate(segments):
        idx = [i for i in range(n) if frame_seg[i] == k]
        if not idx:
            continue
        seg_cx = sorted((t, None if b is None else b.cx) for t, b in samples
                        if seg.start - 1e-6 <= t <= seg.end + 1e-6)
        for i, x in zip(idx, smooth_path(seg_cx, params, [frame_times[i] for i in idx])):
            path[i] = x

    def wide_cx(t: float) -> float:
        i = int(round(tm.snap_to_clip(t) * FPS))
        return path[min(max(i, 0), n - 1)]

    sents = sentences(clip_words)
    hook = req.hook
    if hook is None:
        hook = hook_span(clip_words, sents[0])
    cx_samples = [(t, None if b is None else b.cx) for t, b in samples]
    joins = _segment_joins(tm, segments)
    jumps = sorted(set(_body_jumps(tm, cx_samples, crop_w, segments)) | set(joins))
    shots = plan_shots(tm, clip_words, sents, hook, list(req.emphasis), jumps)
    shots = _force_switch(shots, joins, MIN_SHOT)
    bodies = [(t, b) for t, b in samples if b is not None]
    face_at, body_at = _box_lookup(faces), _box_lookup(bodies)
    crops = crop_windows(shots, tm, FPS, wide_cx, face_at, info.width, info.height, req.fmt,
                         body_at=body_at, close_zoom=req.close_zoom)
    assert_in_bounds(crops, info.width, info.height)
    jobs.write_json_atomic(work / "shots.json", {"shots": [asdict(s) for s in shots], "joins": joins})

    preview_path = None
    if req.preview:
        preview_path = track_preview(req.master, info, edl, segments, crops,
                                     _bodies_per_frame(samples, frame_times), work / "track-preview.mp4")
    if req.stop_after == "track":
        return ClipResult(None, tm.duration, edl, weak, shots, None, preview_path)

    ass_path = None
    if req.channel.captions:
        ass_path = work / "captions.ass"
        jobs.write_text_atomic(
            ass_path,
            render_ass(clip_words, build_screens(clip_words, req.channel.language), tm, caption_style(req.channel), tm.duration),
        )
    if req.stop_after == "captions":
        return ClipResult(None, tm.duration, edl, weak, shots, None, preview_path)

    grade = None
    if req.channel.color:
        longest = max(segments, key=lambda s: s.duration)
        points = list(req.color_points) if req.color_points is not None else measure_points(req.master, info.duration)
        grade = interpolate_grade(points, (longest.start + longest.end) / 2)
    audio_files = None
    if req.channel.sound and info.has_audio and req.dereverb > 0:
        # a child process per window; it exits before the video render starts (spec 4.5)
        audio_files = dereverb_windows(
            req.master, [w for w, _ in group_edl(edl, segments)], req.dereverb,
            req.dereverb_cfg or DereverbConfig(), req.audio_cache or work / "audio",
            req.master_id or jobs.quick_hash(req.master), info.duration)
    measured = (loudnorm_measure(req.master, edl, segments, audio_files)
                if req.channel.sound and info.has_audio else None)
    cfg = req.broll_cfg or BrollConfig()
    inserts = make_inserts(req.broll, tm, crops, face_at, body_at, cfg, FPS) if req.broll else ()
    missing = [i.file.name for i in inserts if not i.file.exists()]
    if missing:
        raise BrollFileMissing(f"B-roll file missing: {', '.join(missing)}; add it again on the review page")
    render_clip(
        RenderInputs(
            master=req.master, info=info, edl=edl, crops=crops,
            ass_path=ass_path if req.burn_captions else None,
            fonts_dir=req.repo_root / "assets" / "fonts", grade=grade, audio_measured=measured,
            sound=req.channel.sound, safe_zone=sz, out=req.out_path, segments=segments,
            audio_files=audio_files, broll=inserts, pan_px_per_s=cfg.pan_px_per_s,
        ),
        work,
    )
    return ClipResult(req.out_path, tm.duration, edl, weak, shots, grade, preview_path)


def make_clip(
    video: Path,
    channel: ChannelConfig,
    fmt: str,
    t_from: float,
    t_to: float,
    words_path: Path,
    app: AppConfig,
    repo_root: Path,
    safe_zone: bool,
    workdir: Path,
    dereverb: int = 0,
) -> Path:
    """`shorts clip`: one segment from a manual start/end, rendered under media_root/renders/<channel>/manual/."""
    if fmt not in FORMATS:
        raise ValueError(f"format {fmt!r} arrives in phase 1b" if fmt == "conversation" else f"unknown format {fmt!r}")
    if t_to <= t_from:
        raise ValueError("--to must be after --from")
    if t_from < 0 or t_to - t_from < MIN_CLIP:
        raise ValueError(f"the clip must start at 0 or later and last at least {MIN_CLIP:.0f} s")
    info = probe(video)
    if t_to > info.duration + 0.01:
        raise ValueError(f"--to {t_to:.2f}s is past the end of the video ({info.duration:.2f}s)")
    words = load_words(words_path)
    if not any(t_from <= w.t < t_to for w in words):
        raise ValueError("no transcribed words between --from and --to")
    stamp = datetime.now().strftime("%y%m%d-%H%M%S")
    out = app.media_root / "renders" / channel.id / "manual" / f"{stamp}.mp4"
    result = produce(ClipRequest(master=video, segments=[Span(t_from, t_to)], words=words, channel=channel,
                                 fmt=fmt, out_path=out, work_dir=workdir, safe_zone=safe_zone,
                                 repo_root=repo_root, dereverb=dereverb, dereverb_cfg=app.dereverb,
                                 audio_cache=app.media_root / "cache" / "_manual" / workdir.name / "audio"))
    meta = {
        "source": str(video), "channel": channel.id, "format": fmt,
        "from": t_from, "to": t_to, "duration": result.duration,
        "edl": [asdict(s) for s in result.edl], "shots": [asdict(s) for s in result.shots],
        "grade": asdict(result.grade) if result.grade else None, "weak_tracking": result.weak_tracking,
        # what was applied: produce skips UVR without a sound treatment or a sound track
        "dereverb": dereverb if channel.sound and info.has_audio else 0,
    }
    jobs.write_json_atomic(out.with_suffix(".json"), meta)
    return out
