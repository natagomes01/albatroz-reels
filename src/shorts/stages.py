"""Per-job clip stages over plan 1's clip pipeline (spec 4.1, 4.3, 10.6).

Job clips and `shorts clip` share one render path: both call `shorts.clip.produce()`.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, replace
from pathlib import Path

from shorts import clip as clip_mod
from shorts import dereverb as dv
from shorts import jobs
from shorts import wordfix
from shorts.analyze.boundaries import validate_spans
from shorts.analyze.textutil import word_end
from shorts.broll import paths as broll_paths
from shorts.broll.files import ensure_files
from shorts.broll.inserts import broll_digest, credits, meta_entries, on_screen, picked_plans
from shorts.broll.sources import http_download
from shorts.color import Grade, measure_points
from shorts.ffmpeg import probe, video_encoder
from shorts.timeline import Span, TimeMap
from shorts.vision import detector_name
from shorts.words import Word, find_phrase_span, load_words, sentences

STAGES = ("track", "captions", "render")
RENDER_CHANNEL_FIELDS = ("language", "captions", "color", "sound", "silence")
KEY_PAD = 2.0   # seconds around each segment whose words and automatic edits enter the render key
JOB_SETTINGS = ("color", "caption_y", "split_face_y", "close_zoom", "open_close", "burn_captions")


def _settings(meta_job: dict) -> dict:
    s = meta_job.get("settings") or {}
    unknown = sorted(set(s) - set(JOB_SETTINGS))
    if unknown:
        raise ValueError(f"unknown job setting {unknown} in job.json; known: {', '.join(JOB_SETTINGS)}")
    for k in ("color", "open_close", "burn_captions"):
        if k in s and not isinstance(s[k], bool):
            raise ValueError(f"job setting {k} must be true or false")
    for k in ("caption_y", "split_face_y"):
        if k in s and (not isinstance(s[k], int) or isinstance(s[k], bool) or not 0 < s[k] < 1920):
            raise ValueError(f"job setting {k} must be an output row between 1 and 1919")
    z = s.get("close_zoom")
    if z is not None and (not isinstance(z, (int, float)) or isinstance(z, bool) or not 1.0 <= z <= 2.0):
        raise ValueError("job setting close_zoom must be a number from 1.0 to 2.0")
    return s


def job_settings(meta_job: dict, channel, app):
    """`job.json` "settings", for a video that arrives already cut and lit (a phone Short): the
    colour grade off, the caption baseline and the face row of a split moved, a gentler close-up
    (`close_zoom`), no close-up on the opening sentence (`open_close` false) and captions written
    to captions.ass but not burned (`burn_captions` false, for a body whose captions are drawn
    elsewhere), all three read by `run_clip_stage`. A job without settings gets its channel and app back
    unchanged, and `_keys` adds the settings only when there are some, so its keys stay as they were."""
    s = _settings(meta_job)
    if channel is not None:
        if "color" in s:
            channel = replace(channel, color=s["color"])
        if "caption_y" in s:
            channel = replace(channel, caption_y=s["caption_y"])
    if app is not None and "split_face_y" in s:
        app = replace(app, broll=replace(app.broll, split_face_y=s["split_face_y"]))
    return channel, app


def _render_channel(channel) -> dict:
    return {k: getattr(channel, k) for k in RENDER_CHANNEL_FIELDS}


@dataclass(frozen=True)
class ClipPlan:
    id: str
    spans: list[Span]
    title: str
    hook_text: str
    hook: Span | None
    emphasis: tuple[Span, ...]
    candidate: dict
    decision: dict


def _prefer_auto(decision: dict) -> frozenset[int]:
    """The automatic edits the owner chose over their own fix (review spec 4.4), by `first`.
    A hand-edited or stale value is ignored rather than fatal."""
    vals = decision.get("use_auto")
    if not isinstance(vals, list):
        return frozenset()
    return frozenset(v for v in vals if isinstance(v, int) and not isinstance(v, bool))


def _clip_inputs(base_words: list[Word], edits: list[wordfix.Edit],
                 plan: ClipPlan) -> tuple[list[Word], str]:
    """Effective words for one clip (raw + owner fixes + automatic edits, caption spec 5, with the
    owner's per-range choice, review spec 4.4) and the digest of the automatic edits that reach
    its segments (caption spec 8)."""
    fixes = plan.decision.get("word_fixes", {})
    prefer = _prefer_auto(plan.decision)
    words = wordfix.effective_words(base_words, edits, fixes, prefer)
    active = wordfix.active_edits(len(base_words), edits, fixes, prefer)
    return words, wordfix.edits_digest(active, base_words, plan.spans, KEY_PAD)


def _hook_span(words, sents, first: Span) -> Span | None:
    idx = next((i for i, w in enumerate(words) if w.t >= first.start), None)
    if idx is None:
        return None
    s = next((s for s in sents if s.first <= idx <= s.last), None)
    if s is None:
        return None
    return Span(first.start, min(word_end(words, s.last), first.end))


def _emphasis_spans(words, sents, spans: list[Span], phrases: list[str]) -> tuple[Span, ...]:
    out = []
    for ph in phrases:
        for sp in spans:
            start_idx = next((i for i, w in enumerate(words) if w.t >= sp.start), None)
            if start_idx is None:
                continue
            end_before = next((i for i, w in enumerate(words) if w.t >= sp.end), len(words))
            m = find_phrase_span(words, ph, start_idx, end_before)   # stays inside the segment
            if m is None:
                continue
            a, b = m
            out.append(Span(words[a].t, min(word_end(words, b), sp.end)))
            break
    return tuple(out)


def ensure_color(job, master: Path, duration: float, measure=measure_points) -> list:
    """Measure color once per job (every 600 s of the class) and reuse it for every render."""
    data = jobs.read_json(job.color_json)
    if data is not None:
        return [(p["t"], Grade(**p["grade"])) for p in data["points"]]
    points = measure(master, duration)
    jobs.write_json_atomic(job.color_json, {"points": [
        {"t": t, "grade": {k: getattr(g, k) for k in Grade.__dataclass_fields__}} for t, g in points]})
    return points


def _approved_entries(job) -> list[tuple[str, ClipPlan | Exception]]:
    """Every approved candidate as (id, plan), or (id, the error) when it cannot be planned."""
    data = jobs.read_json(job.candidates_json, {"candidates": []})
    decisions = jobs.read_json(job.review_json, {"decisions": {}})["decisions"]
    words = load_words(job.words_json)
    sents = sentences(words)
    entries: list[tuple[str, ClipPlan | Exception]] = []
    for c in data["candidates"]:
        d = decisions.get(c["id"], {})
        if d.get("status") != "approved":
            continue
        try:
            spans = [Span(a, b) for a, b in (d.get("segments") or [s["snapped"] for s in c["segments"]])]
            entries.append((c["id"], ClipPlan(
                id=c["id"], spans=spans, title=d.get("title", c["title"]),
                hook_text=d.get("hook", c["hook"]), hook=_hook_span(words, sents, spans[0]),
                emphasis=_emphasis_spans(words, sents, spans, c.get("emphasis", [])),
                candidate=c, decision=d)))
        except Exception as e:  # a malformed candidate must not hide the others
            entries.append((c["id"], e))
    return entries


def approved_clips(job) -> list[ClipPlan]:
    return [p for _, p in _approved_entries(job) if isinstance(p, ClipPlan)]


def effective_clip_words(job, plan: ClipPlan) -> list[Word]:
    """The words a render of this clip would use (raw, owner fixes, automatic edits)."""
    words, _ = _clip_inputs(load_words(job.words_json), wordfix.read_edits(job), plan)
    return words


def _keys(meta_job: dict, plan: ClipPlan, words: list[Word], fmt: str, render_channel: dict,
          safe_zone: bool, auto_digest: str = "",
          dereverb: int | None = None, broll: str = "", settings: dict | None = None) -> tuple[str, str]:
    """(track_key, render_key): only what changes the pixels or sound (spec 4.3). Only the words
    near the clip enter the render key, so a correction elsewhere in the class re-renders nothing
    here (caption spec 8)."""
    seg = [[s.start, s.end] for s in plan.spans]
    near = [[w.t, w.w] for w in words
            if any(s.start - KEY_PAD <= w.t < s.end + KEY_PAD for s in plan.spans)]
    det = detector_name()     # Vision keeps the key it always had; another detector re-tracks
    track_key = jobs.stage_key(jobs.RENDER_VERSION, stage="track",
                               master=meta_job.get("master_hash"), segments=seg, fmt=fmt,
                               **({} if det == "vision" else {"detector": det}))
    extra = {"broll": broll} if broll else {}    # S8B spec 8.7: no picks, same key as before S8B
    enc = video_encoder()
    if enc != "h264_videotoolbox":             # same rule as the detector: the Mac keeps its keys
        extra["encoder"] = enc
    if settings:
        extra["settings"] = settings             # job settings: none, same key as before
    render_key = jobs.stage_key(jobs.RENDER_VERSION, stage="render", track=track_key,
                                words=near, auto_edits=auto_digest, channel=render_channel,
                                emphasis=[[e.start, e.end] for e in plan.emphasis],
                                safe_zone=safe_zone, dereverb=dereverb, **extra)
    return track_key, render_key


def _key_strength(render_channel: dict, review: dict, decision: dict) -> int | None:
    """The strength that goes into keys and meta: None on a channel that does not treat sound,
    so its renders keep their pre-S8 keys and a strength edit never invalidates them."""
    if not render_channel.get("sound", True):
        return None
    return dv.effective_strength(review, decision)


def _broll_plans(app, job, plan: ClipPlan, raw: list[Word]):
    return picked_plans(plan.decision, raw, plan.spans, broll_paths.broll_dir(app, job))


def render_path(app, channel_id: str, job, clip_id: str) -> Path:
    return Path(app.media_root).expanduser() / "renders" / channel_id / job.id / f"{clip_id}.mp4"


def _render_version(out_path: Path) -> str | None:
    """`render_version` of the meta next to a render; None when it is missing or unreadable."""
    try:
        meta = jobs.read_json(out_path.with_suffix(".json"))
    except (ValueError, OSError):
        return None
    v = meta.get("render_version") if isinstance(meta, dict) else None
    return None if v is None else str(v)


def render_status(job, app, channel) -> dict[str, dict]:
    """Render state of every candidate, from the files on disk (S7 spec 3, 5.2). The key is the
    one `run_clip_stage` would write now (safe zone off), so the page and the render agree."""
    meta_job = jobs.read_json(job.job_json)
    channel, app = job_settings(meta_job, channel, app)
    candidates = jobs.read_json(job.candidates_json, {"candidates": []})["candidates"]
    plans = dict(_approved_entries(job))
    base_words = load_words(job.words_json)
    edits = wordfix.read_edits(job)
    review = jobs.read_json(job.review_json, {"decisions": {}})
    rc = _render_channel(channel)
    out: dict[str, dict] = {}
    for c in candidates:
        cid = c["id"]
        path = render_path(app, channel.id, job, cid)
        plan = plans.get(cid)
        state = "not_rendered"
        if path.exists():
            fresh = False
            if isinstance(plan, ClipPlan):
                words, auto = _clip_inputs(base_words, edits, plan)
                _, key = _keys(meta_job, plan, words, meta_job["format"], rc, False, auto,
                         _key_strength(rc, review, plan.decision),
                         broll=broll_digest(_broll_plans(app, job, plan, base_words), app.broll),
                         settings=_settings(meta_job))
                fresh = jobs.is_fresh(path, key)
            state = "rendered" if fresh else "out_of_date"
        out[cid] = {"state": state, "version": _render_version(path),
                    "approved": cid in plans, "file": path.exists()}
    return out


def _broll_label(e: dict) -> str:
    return f"{e['start']:g}-{e['end']:g} s {e['layout']} {e['title']}"


def _broll_revision(out_path: Path, entries: list[dict]) -> tuple[int, list[str]]:
    """Revision of a clip's B-roll renders (v4.01, v4.02...) and what changed since the render it
    replaces: the previous meta next to `out_path`, read before it is overwritten."""
    try:
        prev = jobs.read_json(out_path.with_suffix(".json"))
    except (ValueError, OSError):
        prev = None
    prev = prev if isinstance(prev, dict) else {}
    before = prev.get("broll") if isinstance(prev.get("broll"), list) else []
    rev = prev.get("broll_revision")
    same_base = str(prev.get("render_version", "")).split(".")[0] == jobs.RENDER_VERSION
    rev = rev + 1 if isinstance(rev, int) and same_base else 1
    old, new = [_broll_label(e) for e in before], [_broll_label(e) for e in entries]
    changes = [f"added {x}" for x in new if x not in old] + [f"removed {x}" for x in old if x not in new]
    return rev, changes


def _meta(job, channel, fmt, plan: ClipPlan, result, out_path: Path, render_channel: dict,
          safe_zone: bool, broll_plans=()) -> dict:
    c = plan.candidate
    tm = TimeMap(result.edl) if result.edl else None
    shown = on_screen(broll_plans, tm) if tm else []
    analysis = jobs.read_json(job.candidates_json, {}) or {}
    entries = meta_entries(shown, tm) if tm else []
    rev_fields = {}
    if entries:         # only a clip with B-roll gets a revision; others keep their meta as before
        rev, changes = _broll_revision(out_path, entries)
        rev_fields = {"broll_revision": rev, "broll_changes": changes}
    return {"clip_id": plan.id, "job": job.id, "channel": channel.id,
            "content_language": channel.language, "format": fmt,
            "title": plan.title, "hook": plan.hook_text,
            "segments": [[s.start, s.end] for s in plan.spans],
            "duration": round(result.duration, 2), "render": str(out_path),
            "render_hash": jobs.file_hash(out_path) if out_path.exists() else None,
            "warnings": ["weak_tracking"] if result.weak_tracking else [],
            "score": {"total": c["total"], "dimensions": c["scores"],
                      "controversy": c["controversy"], "controversy_why": c["controversy_why"],
                      "who_reacts": c["who_reacts"], "verdict": c["verdict"],
                      "review_warnings": c.get("warnings", []),
                      "blind": c.get("blind"), "faithful": c.get("faithful")},
            "analysis": {k: analysis.get(k) for k in ("profile_digest", "prompts", "llm")},
            "broll": entries,
            "credits": credits([p.pick for p in shown], channel.language),
            "render_version": (f"{jobs.RENDER_VERSION}.{rev_fields['broll_revision']:02d}"
                               if rev_fields else jobs.RENDER_VERSION),
            **rev_fields,
            "render_channel": render_channel, "safe_zone": safe_zone}


def run_clip_stage(job, app, channel, stage: str, produce=None, safe_zone: bool = False,
                   preview: bool = False, measure=None,
                   clip_ids: set[str] | None = None, download=None) -> list[dict]:
    if stage not in STAGES:
        raise ValueError(f"stage must be one of {STAGES}")
    produce = produce or clip_mod.produce
    meta_job = jobs.read_json(job.job_json)
    channel, app = job_settings(meta_job, channel, app)
    settings = _settings(meta_job)
    fmt, master = meta_job["format"], Path(meta_job["master"])
    base_words = load_words(job.words_json)
    edits = wordfix.read_edits(job)
    duration = float(meta_job.get("duration") or (base_words[-1].t + 1.0 if base_words else 0.0))
    color_points = None
    entries = _approved_entries(job)     # reads review.json first: a corrupt file fails clearly
    if clip_ids is not None:     # `--clip`: only the named approved clips (S7 spec 5.1)
        entries = [(cid, plan) for cid, plan in entries if cid in clip_ids]
    review = jobs.read_json(job.review_json, {"decisions": {}})
    if stage == "render" and entries:   # S8 audio spec 3: nothing renders before the class strength is chosen
        dv.gate(channel, review, has_audio=lambda: not master.exists() or probe(master).has_audio)
    results = []
    if stage == "render" and channel.color:
        try:
            color_points = tuple(ensure_color(job, master, duration, measure or measure_points))
        except Exception as e:  # a moved master or a failed measurement: one failure, no traceback
            _fail(job, results, "(color)", stage, e)
            return results
    render_channel = _render_channel(channel)
    for clip_id, plan in entries:
        if not isinstance(plan, ClipPlan):
            _fail(job, results, clip_id, stage, plan)
            continue
        work = job.clip_dir(plan.id)
        try:
            reason = validate_spans(plan.spans, duration)
            if reason:
                raise ValueError(f"invalid segments: {reason}")
            words, auto = _clip_inputs(base_words, edits, plan)
            strength = _key_strength(render_channel, review, plan.decision)
            plans_b = _broll_plans(app, job, plan, base_words)
            if stage == "render" and plans_b:   # spec 8.8: missing stock files come back first
                ensure_files([m for m in plan.decision.get("broll") or []
                              if m.get("pick") and m.get("id") in {p.id for p in plans_b}],
                             broll_paths.broll_dir(app, job), app.broll.user_agent,
                             download=download or http_download)
            track_key, render_key = _keys(meta_job, plan, words, fmt, render_channel, safe_zone, auto,
                                          strength, broll=broll_digest(plans_b, app.broll),
                                          settings=settings)
            out_path = render_path(app, channel.id, job, plan.id)
            if stage == "render" and jobs.is_fresh(out_path, render_key):
                results.append({"clip": plan.id, "render": str(out_path), "skipped": True})
                continue
            reuse = jobs.is_fresh(work / "track.json", track_key)
            req = clip_mod.ClipRequest(master=master, segments=plan.spans, words=words,
                                       channel=channel, fmt=fmt, out_path=out_path, work_dir=work,
                                       hook=(plan.hook if settings.get("open_close", True)
                                             else Span(plan.spans[0].start, plan.spans[0].start)),
                                       emphasis=plan.emphasis, reuse_track=reuse,
                                       stop_after=stage, safe_zone=safe_zone,
                                       preview=preview and stage == "track",
                                       color_points=color_points,
                                       dereverb=strength or 0, dereverb_cfg=app.dereverb,
                                       audio_cache=dv.audio_cache_dir(app, job),
                                       master_id=meta_job.get("master_hash") or "",
                                       broll=tuple(plans_b), broll_cfg=app.broll,
                                       close_zoom=settings.get("close_zoom"),
                                       burn_captions=settings.get("burn_captions", True))
            started = time.monotonic()
            result = produce(req)
            jobs.log_event(job, kind="clip_stage", clip=plan.id, stage=stage, reused_track=reuse,
                           duration=result.duration, weak_tracking=result.weak_tracking,
                           wall_s=round(time.monotonic() - started, 2))
            if (work / "track.json").exists():
                jobs.write_key(work / "track.json", track_key)
            meta = _meta(job, channel, fmt, plan, result, out_path, render_channel, safe_zone, plans_b)
            if channel.sound:
                meta["dereverb"] = strength
            jobs.write_json_atomic(work / "meta.json", meta)
            if stage == "render":
                jobs.write_json_atomic(out_path.with_suffix(".json"), meta)
                jobs.write_key(out_path, render_key)   # the freshness marker goes last
        except Exception as e:  # one bad clip must not stop the others (spec 11)
            _fail(job, results, plan.id, stage, e)
            continue
        results.append({"clip": plan.id, "render": str(out_path) if stage == "render" else None,
                        "preview": str(result.preview_path) if result.preview_path else None,
                        "skipped": False})
    ok = [r for r in results if "error" not in r]
    if stage == "render" and getattr(app, "backup_auto", False) and ok:
        try:
            from shorts.backup import run_backup
            codes = run_backup(app, job=job, channel_id=channel.id)
            bad = [c for c in codes if c != 0]
            if bad:
                jobs.log_event(job, kind="error", stage="backup",
                               error=f"rclone exited with code(s) {bad}")
        except Exception as e:  # a backup failure must not lose the render results
            jobs.log_event(job, kind="error", stage="backup", error=str(e)[:500])
    return results


def _fail(job, results: list[dict], clip_id: str, stage: str, e: Exception) -> None:
    jobs.log_event(job, kind="error", clip=clip_id, stage=stage, error=str(e)[:500],
                   cmd=getattr(e, "cmd", None), stderr_tail=getattr(e, "stderr_tail", None))
    results.append({"clip": clip_id, "error": str(e)[:300]})


def next_stage(job, app=None, channel=None) -> str:
    """"done" only when every approved clip has a render whose key matches what a render would
    write now, plus its meta. Without `channel`, the channel render fields and safe-zone flag
    come from the render's own meta, so edits to the clip, words or RENDER_VERSION still show."""
    if not job.words_json.exists():
        return "ingest"
    if not job.candidates_json.exists():
        return "analyze"
    entries = _approved_entries(job)
    if not entries:
        return "review"
    if app is not None:
        meta_job = jobs.read_json(job.job_json)
        channel, app = job_settings(meta_job, channel, app)
        settings = _settings(meta_job)
        base_words = load_words(job.words_json)
        edits = wordfix.read_edits(job)
        review = jobs.read_json(job.review_json, {"decisions": {}})
        for _, plan in entries:
            if not isinstance(plan, ClipPlan):
                return "render"
            out = render_path(app, meta_job["channel"], job, plan.id)
            meta = jobs.read_json(out.with_suffix(".json"))
            if not out.exists() or meta is None or meta.get("safe_zone"):
                return "render"   # a safe-zone overlay is a check render, never the deliverable
            rc = _render_channel(channel) if channel is not None else meta.get("render_channel")
            if rc is None:
                return "render"
            words, auto = _clip_inputs(base_words, edits, plan)
            _, key = _keys(meta_job, plan, words, meta_job["format"], rc, False, auto,
                         _key_strength(rc, review, plan.decision),
                         broll=broll_digest(_broll_plans(app, job, plan, base_words), app.broll),
                         settings=settings)
            if not jobs.is_fresh(out, key):
                return "render"
        return "done"
    return "render"
