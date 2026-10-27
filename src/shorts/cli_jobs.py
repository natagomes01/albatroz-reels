"""Job subcommands (spec 4.1)."""
from __future__ import annotations

import functools
import sys
from pathlib import Path

from shorts import jobs

REPO = Path(__file__).resolve().parents[2]


class CliError(Exception):
    """A user-facing failure: printed as one line, exit code 2."""


def _guarded(fn):
    """Turn missing files, unknown jobs and channels into one readable line instead of a traceback."""
    @functools.wraps(fn)
    def wrapper(args) -> int:
        try:
            return fn(args)
        except CliError as e:
            return _fail(str(e))
        except FileNotFoundError as e:
            return _fail(str(e))
        except ValueError as e:
            if "is not valid JSON" in str(e):
                return _fail(str(e))
            raise
        except KeyError as e:
            return _fail(f"missing key {e} (unknown job or channel?)")
    return wrapper


def _run_boundary(command: str, summary: bool = True):
    """Write run_start/run_end around a job command (S4). With `summary`, print the one-line LLM
    cost of the run at the end when the run called an LLM or hit its cache. Commands that can
    call an LLM use it (`analyze`, `run`, `fixwords`)."""
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(args) -> int:
            from shorts import runlog
            try:
                _, _, job, _ = _ctx(args, args.job)
            except Exception:
                return fn(args)            # fn reports the unknown job or channel itself
            plain = {k: v for k, v in vars(args).items() if k != "func"}
            with runlog.command_run(job, command, plain) as run:
                run.exit_code = fn(args)
            if summary and not run.nested:
                totals = runlog.run_totals(runlog.read_log(job.log_path)[0], run.id)
                if totals["calls"] or totals["cache_hits"]:
                    print(runlog.run_line(totals))
            return run.exit_code
        return wrapper
    return deco


def _ctx(args, job_ref: str | None = None):
    """Config, channels, job and its channel; honors the global --config/--channels flags."""
    from shorts.config import load_channels, load_config
    app = load_config(getattr(args, "config", None) or REPO / "config.toml")
    channels = load_channels(getattr(args, "channels", None) or REPO / "channels.toml")
    if job_ref is None:
        return app, channels, None, None
    job = jobs.load_job(job_ref, app.jobs_dir)
    ch_id = jobs.read_json(job.job_json)["channel"]
    if ch_id not in channels:
        raise CliError(f"job {job.id} uses channel '{ch_id}', which is not in channels.toml")
    return app, channels, job, channels[ch_id]


def _fail(msg: str) -> int:
    print(f"error: {msg}", file=sys.stderr)
    return 2


@_guarded
def cmd_ingest(args) -> int:
    from shorts.ingest import check_format, ingest
    try:
        check_format(args.format)
        app, channels, _, _ = _ctx(args)
        if args.channel not in channels:
            return _fail(f"unknown channel '{args.channel}' (see channels.toml)")
        job = ingest(Path(args.video), channels[args.channel], args.format, app, topic=args.topic)
    except (ValueError, RuntimeError, FileExistsError) as e:
        return _fail(str(e))
    print(f"job {job.id} ready: {job.root}")
    return 0


def _cost_confirmed(args, app, job) -> bool:
    """Opt-in question before spending (S4 spec 6, decision 1). Off unless config.toml sets
    cost_confirm_above_usd above 0; `--yes` skips it; no estimate (no earlier job) means no
    question. The estimate is printed whenever the key is on; the question only when the
    estimate is above the threshold."""
    limit = getattr(app, "cost_confirm_above_usd", 0.0) or 0.0
    if limit <= 0 or getattr(args, "yes", False):
        return True
    from shorts.cost import estimate_cost
    duration = (jobs.read_json(job.job_json, {}) or {}).get("duration")
    try:
        minutes = float(duration) / 60 if duration else None
    except (TypeError, ValueError):
        minutes = None
    estimate = estimate_cost(app.jobs_dir, minutes, exclude=job.id)
    if estimate is None:
        return True
    print(f"Estimated LLM cost: ${estimate:.2f} API-equivalent for {minutes:.1f} class minutes "
          f"(from earlier jobs).")
    if estimate <= limit:
        return True
    try:
        reply = input(f"That is above cost_confirm_above_usd (${limit:.2f}). Continue? [y/N] ")
    except EOFError:
        reply = ""
    return reply.strip().lower() in ("y", "yes")


def _over_ceiling_question(args):
    """The answer to "more windows qualified than scan_ceiling": all of them go to detail (more
    opus calls, more cost) or only the best `scan_ceiling`. `--yes` sends all; no terminal
    input keeps the ceiling, the cheap side."""
    def ask(qualified: int, ceiling: int) -> bool:
        if getattr(args, "yes", False):
            return True
        print(f"{qualified} windows scored high enough for detail, above the ceiling of {ceiling}. "
              f"Each one is one more detail call (the costly pass).")
        try:
            reply = input(f"Send all {qualified} to detail? [y/N] (N keeps the best {ceiling}) ")
        except EOFError:
            reply = ""
        yes = reply.strip().lower() in ("y", "yes")
        if not yes:
            print(f"Keeping the best {ceiling}.")
        return yes
    return ask


@_run_boundary("analyze")
@_guarded
def cmd_analyze(args) -> int:
    from shorts.analyze.run import ReviewInProgress, run_analyze
    from shorts.llm.base import LLMError
    app, _, job, channel = _ctx(args, args.job)
    if not _cost_confirmed(args, app, job):
        print("analyze cancelled: nothing was sent to the LLM", file=sys.stderr)
        return 1
    try:
        res = run_analyze(job, app, channel, REPO, force=getattr(args, "force", False),
                          over_ceiling=_over_ceiling_question(args))
    except ReviewInProgress as e:
        return _fail(str(e))
    except LLMError as e:
        if e.kind == "limit":
            return _fail(f"LLM usage limit reached ({e}). Finished calls are cached; "
                         f"run `shorts analyze {job.id}` again when the limit resets.")
        return _fail(str(e))
    except Exception as e:  # e.g. a KeyError from a malformed LLM reply: short message, not a traceback
        return _fail(f"analyze failed: {type(e).__name__}: {e} (see {job.log_path})")
    fixes = f"{res.get('fixes', 0)} caption fixes ({res.get('fix_dropped', 0)} dropped)"
    if res["candidates"] == 0:
        print(f"{res['windows']} windows scanned; none reached the threshold. 0 candidates.")
    else:
        print(f"{res['candidates']} candidates from {res['selected']} of {res['windows']} windows; "
              f"{fixes}. Next: shorts review {job.id}")
    if res.get("fix_error"):
        when = " when the limit resets" if res.get("fix_error_kind") == "limit" else ""
        print(f"warning: caption fixes skipped ({res['fix_error']}); the review page shows raw "
              f"words. Run `shorts fixwords {job.id}`{when} to retry.", file=sys.stderr)
    if res["candidates"] and channel.sound:     # S8 audio spec 5.1; the page retries on load
        try:
            from shorts.excerpt import make_excerpts
            make_excerpts(job, app, channel)
            print("audio excerpt ready: choose the strength on the review page")
        except Exception as e:
            print(f"warning: audio excerpt not made ({type(e).__name__}: {e}); the review page "
                  f"will make it", file=sys.stderr)
    return 0


@_run_boundary("fixwords")
@_guarded
def cmd_fixwords(args) -> int:
    from shorts.analyze.fixwords import run_fixwords
    from shorts.llm.base import LLMError
    app, _, job, channel = _ctx(args, args.job)
    try:
        res = run_fixwords(job, app, channel, REPO, all_chunks=args.all, force=args.force,
                           topic=args.topic)
    except LLMError as e:
        if e.kind == "limit":
            return _fail(f"LLM usage limit reached ({e}). Finished chunks are cached; run "
                         f"`shorts fixwords {job.id}` again when the limit resets.")
        return _fail(str(e))
    except FileNotFoundError as e:
        return _fail(str(e))
    except Exception as e:  # a malformed file or reply: one line, not a traceback
        return _fail(f"fixwords failed: {type(e).__name__}: {e} (see {job.log_path})")
    print(f"{res['edits']} caption fixes ({res['dropped']} dropped) from {res['chunks']} of "
          f"{res['total_chunks']} chunks. Next: shorts review {job.id}")
    if res["rejected"]:
        print(f"warning: {res['rejected']} chunk(s) rejected: the model edited more than 15% of "
              f"their words (see {job.log_path}); run `shorts fixwords {job.id}` again to retry "
              f"them.", file=sys.stderr)
    return 0


@_run_boundary("broll")
@_guarded
def cmd_broll(args) -> int:
    from shorts.broll.search import source_keys
    from shorts.broll.suggest import read_result, suggest_clip
    from shorts.llm.base import LLMError, get_backend
    from shorts.stages import approved_clips
    app, _, job, channel = _ctx(args, args.job)
    plans = approved_clips(job)
    if args.clip:
        unknown = set(args.clip) - {p.id for p in plans}
        if unknown:
            return _fail(f"not approved: {', '.join(sorted(unknown))}")
        plans = [p for p in plans if p.id in set(args.clip)]
    todo = [p for p in plans if args.force or read_result(job, p.id) is None]
    if not todo:
        print("nothing to suggest: every approved clip has B-roll suggestions (use --force to redo)")
        return 0
    backend = get_backend("broll", app, log=lambda ev: jobs.log_event(job, **{**ev, "pass": "broll"}))
    keys = source_keys()
    for p in todo:
        try:
            res = suggest_clip(job, app, channel, p, backend, keys, force=args.force)
        except LLMError as e:
            if e.kind == "limit":
                return _fail(f"LLM usage limit reached ({e}). Run `shorts broll {job.id}` again when "
                             f"the limit resets.")
            return _fail(f"{p.id}: {e}")
        except (OSError, ValueError) as e:
            return _fail(f"{p.id}: B-roll suggestion failed: {e}")
        extra = f" ({len(res['errors'])} search errors, see the review page)" if res["errors"] else ""
        print(f"{p.id}: {len(res['moments'])} B-roll moments{extra}")
    return 0


def _shorts_base(args) -> list[str]:
    """This same `shorts`, with this command's config files (for the page's subprocesses)."""
    base = [sys.executable, "-m", "shorts.cli"]
    for flag in ("config", "channels"):
        value = getattr(args, flag, None)
        if value is not None:
            base += [f"--{flag}", str(value)]
    return base


def _render_command(args, job_id: str):
    """The page's render subprocess."""
    base = _shorts_base(args)
    return lambda clip_id: [*base, "render", job_id, "--clip", clip_id]


def _excerpt_command(args, job_id: str) -> list[str]:
    """The page's excerpt subprocess (S8 audio spec 5.4)."""
    return [*_shorts_base(args), "excerpt", job_id]


def _broll_command(args, job_id: str):
    """The page's B-roll suggestion subprocess (S8B spec 5.1): one clip, always asked again."""
    base = _shorts_base(args)
    return lambda clip_id: [*base, "broll", job_id, "--clip", clip_id, "--force"]


@_guarded
def cmd_excerpt(args) -> int:
    from shorts.dereverb import DereverbError
    from shorts.excerpt import make_excerpts
    from shorts.ffmpeg import FFmpegError
    app, _, job, channel = _ctx(args, args.job)
    problem = _master_problem(job)
    if problem:
        return _fail(problem)
    try:
        paths = make_excerpts(job, app, channel)
    except (DereverbError, FFmpegError, ValueError) as e:
        return _fail(f"audio excerpt failed: {e}")
    for p in paths:
        print(p)
    return 0


@_guarded
def cmd_review(args) -> int:
    from shorts.review.server import serve
    app, _, job, channel = _ctx(args, args.job)
    serve(job, port=args.port, open_browser=not args.no_browser, app=app, channel=channel,
          command=_render_command(args, job.id),
          excerpt_command=_excerpt_command(args, job.id),
          broll_command=_broll_command(args, job.id))
    return 0


def _master_problem(job) -> str | None:
    meta = jobs.read_json(job.job_json) if hasattr(job, "job_json") else None
    if not meta or not meta.get("master"):
        return None
    master = Path(meta["master"])
    return None if master.exists() else f"master not found: {master} (was it moved?)"


def _refused_clips(job, clip_ids: set[str], stage: str) -> list[tuple[str, str]]:
    """Named clips that cannot run: unknown ids and clips that are not approved (S7 spec 5.1)."""
    known = {c["id"] for c in jobs.read_json(job.candidates_json, {"candidates": []})["candidates"]}
    decisions = jobs.read_json(job.review_json, {"decisions": {}})["decisions"]
    why_not = "not approved, nothing rendered" if stage == "render" else "not approved, skipped"
    out = []
    for cid in sorted(clip_ids):
        if cid not in known:
            out.append((cid, "unknown clip"))
        elif decisions.get(cid, {}).get("status") != "approved":
            out.append((cid, why_not))
    return out


def _stage(name):
    @_guarded
    def run(args) -> int:
        from shorts.stages import run_clip_stage
        app, _, job, channel = _ctx(args, args.job)
        problem = _master_problem(job)
        if problem:
            return _fail(problem)
        safe_zone = getattr(args, "safe_zone", False)
        clip_ids = set(getattr(args, "clip", None) or []) or None
        refused = _refused_clips(job, clip_ids, name) if clip_ids else []
        for cid, why in refused:
            print(f"{cid}: {why}", file=sys.stderr)
        if clip_ids:
            clip_ids -= {cid for cid, _ in refused}
            if not clip_ids:
                return 1
        from shorts.dereverb import StrengthNotChosen
        try:
            out = run_clip_stage(job, app, channel, name, safe_zone=safe_zone,
                                 preview=getattr(args, "preview", False), clip_ids=clip_ids)
        except StrengthNotChosen as e:
            print(f"error: {e}: shorts review {job.id}", file=sys.stderr)
            return 1
        if not out and clip_ids is None:
            print("no approved clips: run `shorts review` first")
        failed = 0
        for r in out:
            if "error" in r:
                failed += 1
                print(f"{r['clip']}: FAILED {name}: {r['error']} (details in {job.log_path})",
                      file=sys.stderr)
                continue
            print(f"{r['clip']}: {'skipped (fresh)' if r['skipped'] else name + ' done'}"
                  + (f" -> {r['render']}" if r.get("render") else "")
                  + (f" (preview: {r['preview']})" if r.get("preview") else ""))
        if safe_zone and name == "render" and failed < len(out):
            print("note: --safe-zone overlay renders overwrite the deliverable path; "
                  f"run `shorts render {job.id}` without it for the final files")
        return 1 if failed or refused else 0
    return _run_boundary(name, summary=False)(run)


@_run_boundary("run")
@_guarded
def cmd_run(args) -> int:
    from shorts.stages import next_stage
    app, _, job, channel = _ctx(args, args.job)
    step = next_stage(job, app, channel)
    if step == "done":
        print(f"every approved clip of {job.id} is rendered")
        return 0
    if step == "analyze":
        return cmd_analyze(args)
    if step == "review":
        print(f"next: approve clips with `shorts review {job.id}`")
        return 0
    if step == "render":
        return _stage("render")(args)
    print(f"next step: {step}")
    return 0


@_guarded
def cmd_cost(args) -> int:
    import json
    from shorts import cost
    app, _, _, _ = _ctx(args)
    if args.all:
        if args.job or args.run or args.project is not None:
            return _fail("--all takes no job, --run or --project")
        rows = cost.all_jobs(app.jobs_dir)
        print(json.dumps({"jobs": rows}, indent=2) if args.json else cost.format_all(rows))
        return 0
    if not args.job:
        return _fail("name a job, or use --all (see `shorts cost --help`)")
    job = jobs.load_job(args.job, app.jobs_dir)
    try:
        rep = cost.job_report(job, run=args.run)
    except LookupError as e:
        return _fail(str(e))
    proj = cost.projection(rep, args.project, app.scan_ceiling) if args.project else None
    if args.json:
        print(json.dumps(rep if args.project is None else {**rep, "projection": proj}, indent=2))
    else:
        print(cost.format_report(rep, proj, project_minutes=args.project))
    return 0


@_guarded
def cmd_metrics(args) -> int:
    from shorts import metrics
    app, _, job, _ = _ctx(args, args.job)
    print(metrics.write(job))
    print(f"written to {job.root / 'metrics.md'}")
    return 0


@_guarded
def cmd_export(args) -> int:
    from shorts.export import export_job
    app, _, job, channel = _ctx(args, args.job)
    results = export_job(app, job, channel, Path(args.dest) if args.dest else None)
    for r in results:
        print(f"{r['clip']}: {r['folder']}" if "folder" in r else f"{r['clip']}: skipped ({r['skipped']})")
    if not results:
        print("no approved clips")
    return 0


@_guarded
def cmd_backup(args) -> int:
    from shorts.backup import run_backup
    app, _, job, channel = _ctx(args, args.job) if args.job else (*_ctx(args)[:2], None, None)
    codes = run_backup(app, job=job, channel_id=channel.id if channel else None,
                       masters=args.masters, dry_run=args.dry_run)
    return 0 if all(c == 0 for c in codes) else 1


@_guarded
def cmd_clean(args) -> int:
    from shorts.clean import run_clean
    app, _, job, channel = _ctx(args, args.job)
    for p in run_clean(job, app, channel.id):
        print(f"removed {p}")
    return 0


def register(sub) -> None:
    p = sub.add_parser("ingest", help="create a job and transcribe the master")
    p.add_argument("video")
    p.add_argument("--channel", required=True)
    p.add_argument("--format", required=True)
    p.add_argument("--topic", default="",
                   help="one line about the class, used by the caption fixes (e.g. 'Salmo 22 na Septuaginta')")
    p.set_defaults(func=cmd_ingest)

    p = sub.add_parser("analyze", help="scan, detail and review candidates")
    p.add_argument("job")
    p.add_argument("--force", action="store_true",
                   help="archive review.json (it holds decisions) and analyze again")
    p.add_argument("--yes", action="store_true",
                   help="answer yes to the questions: the estimated cost (cost_confirm_above_usd) and "
                        "sending every window above scan_ceiling to detail")
    p.set_defaults(func=cmd_analyze)

    p = sub.add_parser("fixwords", help="correct misheard words in the captions (caption context pass)")
    p.add_argument("job")
    p.add_argument("--all", action="store_true",
                   help="every chunk of the class, not only the chunks near the candidates")
    p.add_argument("--force", action="store_true", help="ignore the cached answers and ask again")
    p.add_argument("--topic", default=None,
                   help="one-line topic for this run (overrides the topic given at ingest)")
    p.set_defaults(func=cmd_fixwords)

    p = sub.add_parser("broll", help="suggest B-roll moments and images for approved clips")
    p.add_argument("job")
    p.add_argument("--clip", action="append", metavar="ID",
                   help="only this approved clip (repeat for more)")
    p.add_argument("--force", action="store_true",
                   help="suggest again even when a suggestion exists (asks the model again)")
    p.set_defaults(func=cmd_broll)

    p = sub.add_parser("review", help="open the local review page")
    p.add_argument("job")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--no-browser", action="store_true")
    p.set_defaults(func=cmd_review)

    p = sub.add_parser("excerpt", help="make the audio excerpt at every dereverb strength")
    p.add_argument("job")
    p.set_defaults(func=cmd_excerpt)

    for name in ("track", "captions", "render"):
        p = sub.add_parser(name, help=f"{name} approved clips")
        p.add_argument("job")
        p.add_argument("--clip", action="append", metavar="ID",
                       help="only this approved clip (repeat for more)")
        if name == "track":
            p.add_argument("--preview", action="store_true")
        if name == "render":
            p.add_argument("--safe-zone", action="store_true")
        p.set_defaults(func=_stage(name))

    p = sub.add_parser("run", help="run the next pending stage")
    p.add_argument("job")
    p.add_argument("--yes", action="store_true",
                   help="answer yes to the analyze questions (estimated cost; every window above "
                        "scan_ceiling to detail)")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("cost", help="API-equivalent LLM cost of a job, a run or every job")
    p.add_argument("job", nargs="?")
    p.add_argument("--run", help="only this run (run ids are listed in the report)")
    p.add_argument("--all", action="store_true", help="one line per job, side by side")
    p.add_argument("--json", action="store_true", help="print the report as JSON")
    p.add_argument("--project", type=float, metavar="MINUTES",
                   help="project the cost of a class this many minutes long")
    p.set_defaults(func=cmd_cost)

    p = sub.add_parser("metrics", help="time and cost of every step of a job, written to metrics.md")
    p.add_argument("job")
    p.set_defaults(func=cmd_metrics)

    p = sub.add_parser("export", help="one folder per rendered clip for the content kit")
    p.add_argument("job")
    p.add_argument("--dest", help="folder to write to (default: <final_dir>/<channel>/<job>; final_dir defaults to <media_root>/final)")
    p.set_defaults(func=cmd_export)

    p = sub.add_parser("backup", help="one-way copy of renders to Google Drive")
    p.add_argument("job", nargs="?")
    p.add_argument("--masters", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_backup)

    p = sub.add_parser("clean", help="delete renders of rejected clips (pending and approved stay)")
    p.add_argument("job")
    p.set_defaults(func=cmd_clean)
