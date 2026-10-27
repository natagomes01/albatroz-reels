"""`shorts` command line: every subcommand sets `func`; main() calls it."""
from __future__ import annotations

import argparse
import math
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def parse_time(text: str) -> float:
    """'SS', 'SS.s', 'MM:SS' or 'HH:MM:SS(.s)' -> seconds."""
    parts = text.strip().split(":")
    if not 1 <= len(parts) <= 3 or any(p == "" for p in parts):
        raise argparse.ArgumentTypeError(f"bad time {text!r}; use MM:SS or HH:MM:SS")
    try:
        values = [float(p) for p in parts]
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"bad time {text!r}") from exc
    if any(not math.isfinite(v) or v < 0 for v in values):
        raise argparse.ArgumentTypeError(f"bad time {text!r}; must be a finite, non-negative time")
    seconds = 0.0
    for v in values:
        seconds = seconds * 60 + v
    return seconds


def cmd_doctor(args) -> int:
    from shorts.config import load_config
    from shorts.doctor import run_doctor

    return run_doctor(REPO_ROOT, load_config(args.config))


def cmd_clip(args) -> int:
    from shorts.config import load_channels, load_config

    app = load_config(args.config)
    if args.dereverb not in app.dereverb.levels:
        print(f"error: dereverb must be one of {list(app.dereverb.levels)}", file=sys.stderr)
        return 2
    if args.format == "conversation":
        print("error: format 'conversation' arrives in phase 1b", file=sys.stderr)
        return 2
    channels = load_channels(args.channels)
    if args.channel not in channels:
        print(f"error: unknown channel {args.channel!r}; known: {', '.join(channels)}", file=sys.stderr)
        return 2
    if args.dereverb > 0 and not channels[args.channel].sound:
        print(f"error: channel {args.channel} does not treat sound; --dereverb has no effect", file=sys.stderr)
        return 2
    words = args.words or args.video.with_suffix(".palavras.json")
    if not words.exists():
        print(f"error: {words} not found; run: trs --palavras {args.video}", file=sys.stderr)
        return 2
    if not args.video.exists():
        print(f"error: {args.video} not found", file=sys.stderr)
        return 2
    from shorts.clip import make_clip
    from shorts.ffmpeg import FFmpegError

    work = app.jobs_dir / "_manual" / re.sub(r"[^\w.-]+", "_", args.video.stem)
    try:
        out = make_clip(args.video, channels[args.channel], args.format, args.t_from, args.t_to,
                        words, app, REPO_ROOT, args.safe_zone, work, dereverb=args.dereverb)
    except (ValueError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except FFmpegError as exc:
        print(f"error: ffmpeg failed\n{exc.stderr_tail}", file=sys.stderr)
        return 1
    print(out)
    return 0


def build_parser() -> argparse.ArgumentParser:
    from shorts import cli_jobs

    parser = argparse.ArgumentParser(prog="shorts", description="Long-form class to vertical Shorts")
    parser.add_argument("--config", type=Path, default=REPO_ROOT / "config.toml")
    parser.add_argument("--channels", type=Path, default=REPO_ROOT / "channels.toml")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="check the environment").set_defaults(func=cmd_doctor)
    clip = sub.add_parser("clip", help="render one Short from a manual start/end")
    clip.add_argument("video", type=Path)
    clip.add_argument("--channel", required=True)
    clip.add_argument("--format", required=True, choices=["solo-standing", "solo-seated", "conversation"])
    clip.add_argument("--from", dest="t_from", required=True, type=parse_time)
    clip.add_argument("--to", dest="t_to", required=True, type=parse_time)
    clip.add_argument("--words", type=Path, help="default: <video>.palavras.json")
    clip.add_argument("--safe-zone", action="store_true", help="overlay the safe-zone template")
    clip.add_argument("--dereverb", type=int, default=0, metavar="N",
                      help="UVR dereverb strength, one of [dereverb] levels in config.toml (default 0, off)")
    clip.set_defaults(func=cmd_clip)
    cli_jobs.register(sub)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    from shorts.config import ConfigError
    try:
        return args.func(args)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
