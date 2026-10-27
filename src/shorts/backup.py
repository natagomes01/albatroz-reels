"""One-way Google Drive backup with `rclone copy` (spec 4.4). Never `sync`."""
from __future__ import annotations

import subprocess
from pathlib import Path

from shorts import machine


def build_cmds(app, job=None, channel_id: str | None = None, masters: bool = False,
               dry_run: bool = False) -> list[list[str]]:
    root = Path(app.media_root).expanduser()
    remote = app.backup_remote.rstrip("/")
    pairs = []
    if job is not None and channel_id:
        rel = f"renders/{channel_id}/{job.id}"
        pairs.append((root / rel, f"{remote}/{rel}"))
    else:
        pairs.append((root / "renders", f"{remote}/renders"))
    if masters:
        pairs.append((root / "masters", f"{remote}/masters"))
    extra = ["--exclude", "*.tmp.mp4", "--exclude", "*.tmp", "--exclude", "*.key"]
    if dry_run:
        extra += ["--dry-run", "-v"]
    return [["rclone", "copy", str(src), dst, *extra] for src, dst in pairs]


def run_backup(app, job=None, channel_id=None, masters=False, dry_run=False,
               runner=subprocess.run) -> list[int]:
    codes = []
    for cmd in build_cmds(app, job, channel_id, masters, dry_run):
        assert cmd[1] == "copy"  # never sync: sync deletes on Drive
        codes.append(runner(cmd).returncode)
    return codes


def rclone_remote_ok(remote: str, runner=subprocess.run) -> tuple[bool, str]:
    name = remote.split(":")[0] + ":"
    try:
        r = runner(["rclone", "listremotes"], capture_output=True, text=True)
    except FileNotFoundError:
        return False, f"rclone not installed: {machine.install_hint('rclone')} (see docs/runbooks/drive-backup.md)"
    if name in r.stdout.split():
        return True, f"{name} configured"
    return False, f"remote {name} missing: run `rclone config` (docs/runbooks/drive-backup.md)"
