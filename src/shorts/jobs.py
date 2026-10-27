"""Job folder layout, atomic writes and stage keys (spec 4.2, 4.3)."""
from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

# Two independent cache versions (spec 4.3). Never merge them: bumping the render version after a
# caption-style change must not wipe the analysis cache and re-spend the Max plan.
LLM_CACHE_VERSION = "1"   # bump when an LLM pass builds its request or parses its answer differently
RENDER_VERSION = "4"      # bump when track, captions or render output changes (3: caption pass, 4: one-line caption height)


@dataclass(frozen=True)
class Job:
    root: Path

    @property
    def id(self) -> str:
        return self.root.name

    @property
    def job_json(self) -> Path:
        return self.root / "job.json"

    @property
    def words_json(self) -> Path:
        return self.root / "words.json"

    @property
    def color_json(self) -> Path:
        return self.root / "color.json"

    @property
    def analyze_dir(self) -> Path:
        return self.root / "analyze"

    @property
    def scan_json(self) -> Path:
        return self.analyze_dir / "scan.json"

    @property
    def candidates_json(self) -> Path:
        return self.analyze_dir / "candidates.json"

    @property
    def corrections_json(self) -> Path:
        return self.analyze_dir / "corrections.json"

    @property
    def class_sheet_json(self) -> Path:
        return self.analyze_dir / "class_sheet.json"

    @property
    def review_json(self) -> Path:
        return self.root / "review.json"

    @property
    def clips_dir(self) -> Path:
        return self.root / "clips"

    @property
    def log_path(self) -> Path:
        return self.root / "log.jsonl"

    def clip_dir(self, clip_id: str) -> Path:
        return self.clips_dir / clip_id


def create_job(jobs_dir: Path, job_id: str, meta: dict) -> Job:
    root = Path(jobs_dir) / job_id
    if root.exists():
        raise FileExistsError(f"job {job_id} already exists at {root}")
    root.mkdir(parents=True)
    job = Job(root)
    write_json_atomic(job.job_json, {"id": job_id, **meta})
    return job


def load_job(ref: str, jobs_dir: Path) -> Job:
    as_path = Path(ref).expanduser()
    root = as_path if as_path.is_dir() else Path(jobs_dir) / ref
    if not (root / "job.json").exists():
        raise FileNotFoundError(f"no job at {root} (run `shorts ingest` first)")
    return Job(root)


def write_text_atomic(path: Path, text: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def write_json_atomic(path: Path, data) -> None:
    write_text_atomic(path, json.dumps(data, ensure_ascii=False, indent=2, default=str))


def read_json(path: Path, default=None):
    path = Path(path)
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"{path.name} is not valid JSON: {path} ({e.msg} at line {e.lineno}); "
                         f"fix or restore the file") from e


def canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def stage_key(version: str, **inputs) -> str:
    payload = canonical({"version": version, **inputs})
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def quick_hash(path: Path, edge: int = 4 << 20) -> str:
    """Hash of size + first and last `edge` bytes. Masters are 20-40 GB; a full hash is too slow."""
    path = Path(path)
    size = path.stat().st_size
    h = hashlib.sha256(str(size).encode())
    with open(path, "rb") as f:
        h.update(f.read(edge))
        if size > edge:
            f.seek(max(size - edge, edge))
            h.update(f.read(edge))
    return h.hexdigest()


def _key_path(path: Path) -> Path:
    return Path(path).with_name(Path(path).name + ".key")


def write_key(path: Path, key: str) -> None:
    write_text_atomic(_key_path(path), key)


def is_fresh(path: Path, key: str) -> bool:
    kp = _key_path(path)
    return Path(path).exists() and kp.exists() and kp.read_text(encoding="utf-8") == key


def log_event(job: Job, /, **fields) -> None:
    # `job` is positional-only: S4 events carry a `job` field of their own.
    job.log_path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps({"ts": round(time.time(), 3), **fields}, ensure_ascii=False, default=str)
    with open(job.log_path, "a", encoding="utf-8") as f:
        f.write(line + "\n")
