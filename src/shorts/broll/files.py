"""B-roll files (S8B spec 3, 6, 8.8): download a pick, save an upload, list the owner's files,
and the content digest the render key uses. Everything lives in <media_root>/broll/<job>/."""
from __future__ import annotations

import hashlib
import json
import os
import re
import unicodedata
from pathlib import Path

from shorts.broll.model import check_name
from shorts.broll.sources import Candidate, http_download
from shorts.ffmpeg import FFMPEG, FFPROBE, HDR_TRANSFERS, run

KINDS = {".jpg": "image", ".jpeg": "image", ".png": "image",
         ".mp4": "video", ".mov": "video", ".m4v": "video"}
UPLOAD_TYPES = {"image/jpeg": ".jpg", "image/png": ".png", "video/mp4": ".mp4", "video/quicktime": ".mov"}
DOWNLOAD_CAP = 500 << 20
_PICKED = ("commons-", "pexels-", "pixabay-")


class BrollFileMissing(FileNotFoundError):
    """A picked own file is gone; only the owner can add it again."""


def media_kind(name: str) -> str | None:
    return KINDS.get(Path(name).suffix.lower())


def _rotation(stream: dict) -> int:
    """Display rotation in degrees from the display matrix side data, else the legacy rotate tag."""
    for sd in stream.get("side_data_list") or []:
        if "rotation" in sd:
            try:
                return int(round(float(sd["rotation"])))
            except (TypeError, ValueError):
                return 0
    try:
        return int(round(float((stream.get("tags") or {}).get("rotate", 0))))
    except (TypeError, ValueError):
        return 0


def media_info(path: Path) -> dict:
    out = run([FFPROBE, "-v", "error", "-print_format", "json", "-show_streams", "-show_format",
               str(path)], capture_stdout=True).stdout
    data = json.loads(out or b"{}")
    v = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
    if v is None or not v.get("width") or not v.get("height"):
        raise ValueError(f"{Path(path).name}: no picture in the file")
    duration = None
    if media_kind(Path(path).name) == "video":
        duration = round(float((data.get("format") or {}).get("duration") or 0.0), 3)
    w, h = int(v["width"]), int(v["height"])
    if _rotation(v) % 180 == 90:  # ffmpeg autorotates on decode: report the display size
        w, h = h, w
    return {"w": w, "h": h, "duration": duration,
            "hdr": v.get("color_transfer") in HDR_TRANSFERS}


def clean_upload_name(name: str, ext: str) -> str:
    stem = Path(str(name).replace("\\", "/")).name
    stem = unicodedata.normalize("NFKD", stem).encode("ascii", "ignore").decode()
    stem = re.sub(r"\.[A-Za-z0-9]+$", "", stem)
    stem = re.sub(r"[^A-Za-z0-9_-]+", "-", stem).strip("-_")[:60] or "file"
    return check_name(f"own-{stem}{ext}")


def _free_name(dest_dir: Path, name: str) -> str:
    stem, ext = name.rsplit(".", 1)
    n, candidate = 1, name
    while (dest_dir / candidate).exists():
        n += 1
        candidate = f"{stem}-{n}.{ext}"
    return check_name(candidate)


def _entry(name: str, meta: dict) -> dict:
    return {"name": name, "kind": media_kind(name), "w": meta["w"], "h": meta["h"],
            "duration": meta["duration"]}


def save_upload(stream, length: int, name: str, ctype: str, dest_dir: Path, max_bytes: int,
                info=media_info) -> dict:
    if ctype not in UPLOAD_TYPES:
        raise ValueError(f"file type {ctype!r} is not accepted (JPEG, PNG, MP4 or MOV)")
    if length > max_bytes:
        raise ValueError(f"the file is over {max_bytes >> 20} MB")
    dest_dir.mkdir(parents=True, exist_ok=True)
    fname = _free_name(dest_dir, clean_upload_name(name, UPLOAD_TYPES[ctype]))
    path, part = dest_dir / fname, dest_dir / f"{fname}.part"
    try:
        with open(part, "wb") as f:
            left = length
            while left > 0:
                chunk = stream.read(min(1 << 20, left))
                if not chunk:
                    raise ValueError("the upload ended early")
                f.write(chunk)
                left -= len(chunk)
        os.replace(part, path)
        try:
            meta = info(path)
        except Exception:
            path.unlink(missing_ok=True)
            raise ValueError(f"{fname} is not a readable image or video") from None
    finally:
        part.unlink(missing_ok=True)
    return _entry(fname, meta)


def own_files(dest_dir: Path, info=media_info) -> list[dict]:
    """Media files the owner put in the folder (by upload or by hand); downloaded picks, sidecars,
    partial files and names with unsafe characters are left out."""
    if not dest_dir.is_dir():
        return []
    out = []
    for p in sorted(dest_dir.iterdir(), key=lambda p: p.name):  # same order on every OS
        if p.is_symlink() or not p.is_file() or media_kind(p.name) is None or p.name.startswith(_PICKED):
            continue
        try:
            check_name(p.name)
            out.append(_entry(p.name, info(p)))
        except Exception:
            continue
    return out


def video_thumb(src: Path, dest: Path, at: float = 3.0, width: int = 360) -> None:
    """One small JPEG of an own video for the page (a Mira insert has built its picture by 3 s);
    a video shorter than `at` gives its last frame."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part.jpg")
    short = (media_info(src)["duration"] or 0) < at
    seek = ["-sseof", "-0.1"] if short else ["-ss", f"{at:g}"]
    run([FFMPEG, "-y", "-v", "error", *seek, "-i", str(src), "-frames:v", "1",
         "-vf", f"scale={width}:-2", str(tmp)])
    os.replace(tmp, dest)


def own_pick(name: str, dest_dir: Path, info=media_info) -> dict:
    check_name(name)
    path = dest_dir / name
    if not path.is_file():
        raise BrollFileMissing(f"B-roll file missing: {name}; add it again on the review page")
    meta = info(path)
    if meta["hdr"]:          # spec 3: no tone-mapping for B-roll, so HDR footage is refused
        raise ValueError(f"{name}: HDR video is not supported; convert it to SDR first")
    return {"source": "own", "id": name, "kind": media_kind(name) or "image", "file": name,
            "download_url": "", "w": meta["w"], "h": meta["h"], "duration": meta["duration"],
            "title": name, "author": "", "license": "", "license_url": "", "page_url": ""}


def fetch_pick(cand: Candidate, dest_dir: Path, user_agent: str, download=http_download,
               info=media_info) -> dict:
    url_path = cand.download_url.split("?")[0].lower()
    ext = ".mp4" if cand.kind == "video" else (".png" if url_path.endswith(".png") else ".jpg")
    name = check_name(f"{cand.key}{ext}")
    path = dest_dir / name
    if not path.exists():
        download(cand.download_url, path, {"User-Agent": user_agent}, DOWNLOAD_CAP)
    try:
        meta = info(path)
    except ValueError:
        path.unlink(missing_ok=True)        # an unreadable download is fetched again on the next click
        raise
    if meta["hdr"]:
        path.unlink(missing_ok=True)
        raise ValueError(f"{name}: HDR video is not supported; pick another candidate")
    return {"source": cand.source, "id": cand.id, "kind": cand.kind, "file": name,
            "download_url": cand.download_url, "w": meta["w"], "h": meta["h"],
            "duration": meta["duration"] if cand.kind == "video" else None,
            "title": cand.title[:500], "author": cand.author[:500], "license": cand.license,
            "license_url": cand.license_url, "page_url": cand.page_url}


def file_digest(path: Path) -> str:
    """sha256 of the file, cached in `<file>.sha256` against its size and mtime."""
    st = path.stat()
    side = path.with_name(path.name + ".sha256")
    try:
        cached = json.loads(side.read_text(encoding="utf-8"))
        if cached.get("size") == st.st_size and cached.get("mtime_ns") == st.st_mtime_ns:
            return cached["sha256"]
    except (OSError, ValueError, AttributeError, KeyError):
        pass
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    digest = h.hexdigest()
    try:
        side.write_text(json.dumps({"size": st.st_size, "mtime_ns": st.st_mtime_ns, "sha256": digest}),
                        encoding="utf-8")
    except OSError:
        pass
    return digest


def ensure_files(moments: list[dict], dest_dir: Path, user_agent: str, download=http_download) -> None:
    """Spec 8.8: before a render, a missing stock or Commons file is downloaded again; a missing
    own file stops this clip with a message (SourceError from a failed download does too)."""
    for m in moments:
        pick = m.get("pick")
        if not pick or (dest_dir / pick["file"]).exists():
            continue
        if pick["source"] == "own" or not pick.get("download_url"):
            raise BrollFileMissing(f"B-roll file missing: {pick['file']}; add it again on the review page")
        download(pick["download_url"], dest_dir / check_name(pick["file"]),
                 {"User-Agent": user_agent}, DOWNLOAD_CAP)
