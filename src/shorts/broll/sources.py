"""B-roll sources (S8B spec 3): Wikimedia Commons, Pexels and Pixabay, and the HTTP helpers.

Every source takes a `fetch(url, headers) -> bytes`, so tests replay recorded replies and nothing
here touches the network on its own.
"""
from __future__ import annotations

import html
import json
import os
import re
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from shorts.broll.model import BrollConfig, fill_ok

Fetch = Callable[[str, dict], bytes]
COMMONS_API = "https://commons.wikimedia.org/w/api.php"
COMMONS_FILE = "https://commons.wikimedia.org/wiki/Special:FilePath/"
PEXELS_PHOTOS = "https://api.pexels.com/v1/search"
PEXELS_VIDEOS = "https://api.pexels.com/videos/search"
PIXABAY_IMAGES = "https://pixabay.com/api/"
PIXABAY_VIDEOS = "https://pixabay.com/api/videos/"
PEXELS_LICENSE = ("Pexels License", "https://www.pexels.com/license/")
PIXABAY_LICENSE = ("Pixabay Content License", "https://pixabay.com/service/license-summary/")
PIXABAY_LARGE = 1280            # largeImageURL is at most 1280 px on the long side
_BITMAPS = ("image/jpeg", "image/png")
_REPLY_CAP = 20 << 20


class SourceError(RuntimeError):
    """A source failed (network, HTTP status, bad reply); the message names the host."""


def http_fetch(url: str, headers: dict, timeout: float = 20.0) -> bytes:
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read(_REPLY_CAP)
    except (OSError, ValueError) as e:    # URLError and HTTPError are OSErrors
        raise SourceError(f"{urllib.parse.urlsplit(url).netloc}: {e}") from None


def http_download(url: str, dest: Path, headers: dict, max_bytes: int, timeout: float = 60.0) -> None:
    """Stream a file to `<dest>.part`, then move it into place; never keeps a partial file."""
    part = Path(str(dest) + ".part")
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r, open(part, "wb") as f:
            got = 0
            while chunk := r.read(1 << 20):
                got += len(chunk)
                if got > max_bytes:
                    raise SourceError(f"{urllib.parse.urlsplit(url).netloc}: file is over {max_bytes >> 20} MB")
                f.write(chunk)
        os.replace(part, dest)
    except (OSError, ValueError) as e:
        raise SourceError(f"{urllib.parse.urlsplit(url).netloc}: {e}") from None
    finally:
        part.unlink(missing_ok=True)


@dataclass(frozen=True)
class Candidate:
    source: str
    id: str
    kind: str                 # "image" | "video"
    w: int                    # size of the file download_url gives
    h: int
    duration: float | None    # seconds, videos only
    thumb_url: str
    download_url: str
    title: str
    author: str
    license: str
    license_url: str
    page_url: str

    @property
    def key(self) -> str:
        return f"{self.source}-{re.sub(r'[^A-Za-z0-9_-]', '_', self.id)[:60]}"

    def to_dict(self) -> dict:
        return {**asdict(self), "key": self.key}

    @classmethod
    def from_dict(cls, d: dict) -> Candidate:
        return cls(**{k: d[k] for k in cls.__dataclass_fields__})


def commons_licence(short: str) -> str | None:
    """Spec 3: public domain, CC0 and CC BY (any version) are kept; everything else is dropped."""
    s = " ".join((short or "").lower().replace("-", " ").split())
    if s in ("public domain", "pd") or s.startswith("pd ") or s.startswith("public domain "):
        return "Public domain"
    if s in ("cc0", "cc0 1.0", "cc zero"):
        return "CC0"
    m = re.fullmatch(r"cc by( \d(?:\.\d)?)?", s)
    if m:
        return "CC BY" + (m.group(1) or "")
    return None


def _plain(text) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", "", str(text or ""))).split())


def _capped(w: int, h: int, max_px: int) -> tuple[int, int]:
    s = min(1.0, max_px / max(w, h))
    return max(1, round(w * s)), max(1, round(h * s))


def _meta(meta: dict, name: str) -> str:
    return str((meta.get(name) or {}).get("value", ""))


def commons_search(term: str, fetch: Fetch, user_agent: str, max_px: int, thumb_w: int) -> list[Candidate]:
    q = {"action": "query", "format": "json", "generator": "search",
         "gsrsearch": f"{term} filetype:bitmap", "gsrnamespace": "6", "gsrlimit": "20",
         "prop": "imageinfo", "iiprop": "url|size|mime|extmetadata",
         "iiextmetadatafilter": "LicenseShortName|Artist|ObjectName|LicenseUrl"}
    data = json.loads(fetch(f"{COMMONS_API}?{urllib.parse.urlencode(q)}", {"User-Agent": user_agent}))
    if "error" in (data or {}):
        err = data["error"] if isinstance(data["error"], dict) else {}
        raise SourceError(f"{urllib.parse.urlsplit(COMMONS_API).netloc}: {err.get('info') or err.get('code') or 'API error'}")
    pages = ((data or {}).get("query") or {}).get("pages") or {}
    out = []
    for p in sorted(pages.values(), key=lambda p: p.get("index", 0)):
        info = (p.get("imageinfo") or [{}])[0]
        meta = info.get("extmetadata") or {}
        lic = commons_licence(_meta(meta, "LicenseShortName"))
        w, h = int(info.get("width") or 0), int(info.get("height") or 0)
        if info.get("mime") not in _BITMAPS or lic is None or not w or not h:
            continue
        name = str(p.get("title", "")).split(":", 1)[-1]
        quoted = urllib.parse.quote(name.replace(" ", "_"))
        cw, ch = _capped(w, h, max_px)
        out.append(Candidate(
            source="commons", id=str(p.get("pageid")), kind="image", w=cw, h=ch, duration=None,
            thumb_url=f"{COMMONS_FILE}{quoted}?width={thumb_w}",
            download_url=f"{COMMONS_FILE}{quoted}?width={cw}",
            title=_plain(_meta(meta, "ObjectName")) or re.sub(r"\.\w+$", "", name),
            author=_plain(_meta(meta, "Artist")) or "unknown", license=lic,
            license_url=_meta(meta, "LicenseUrl"), page_url=str(info.get("descriptionurl", ""))))
    return out


def _smallest_filling(files: list[tuple[int, int, str, str]], layout: str, min_px: int):
    ok = [f for f in files if f[0] and f[1] and fill_ok(f[0], f[1], layout, "cover", min_px)]
    return min(ok, key=lambda f: f[0] * f[1]) if ok else None


def pexels_search(term: str, media: str, fetch: Fetch, key: str, layout: str,
                  cfg: BrollConfig) -> list[Candidate]:
    base = PEXELS_PHOTOS if media == "image" else PEXELS_VIDEOS
    data = json.loads(fetch(f"{base}?{urllib.parse.urlencode({'query': term, 'per_page': 15})}",
                            {"Authorization": key, "User-Agent": cfg.user_agent}))
    lic, lic_url = PEXELS_LICENSE
    out = []
    if media == "image":
        for p in data.get("photos") or []:
            cw, ch = _capped(int(p["width"]), int(p["height"]), cfg.max_still_px)
            out.append(Candidate("pexels", str(p["id"]), "image", cw, ch, None,
                                 p["src"].get("medium", ""), f"{p['src']['original']}?auto=compress&w={cw}",
                                 p.get("alt") or f"Pexels photo {p['id']}", p.get("photographer", ""),
                                 lic, lic_url, p.get("url", "")))
        return out
    for v in data.get("videos") or []:
        files = [(int(f.get("width") or 0), int(f.get("height") or 0), f.get("link", ""), "")
                 for f in v.get("video_files") or [] if f.get("file_type") == "video/mp4"]
        best = _smallest_filling(files, layout, cfg.min_fill_px)
        if best is None:
            continue
        out.append(Candidate("pexels", str(v["id"]), "video", best[0], best[1], float(v["duration"]),
                             v.get("image", ""), best[2], f"Pexels video {v['id']}",
                             (v.get("user") or {}).get("name", ""), lic, lic_url, v.get("url", "")))
    return out


def pixabay_search(term: str, media: str, fetch: Fetch, key: str, layout: str,
                   cfg: BrollConfig) -> list[Candidate]:
    base = PIXABAY_IMAGES if media == "image" else PIXABAY_VIDEOS
    q = {"key": key, "q": term[:100], "per_page": 20, "safesearch": "true"}
    if media == "image":
        q["image_type"] = "photo"
    data = json.loads(fetch(f"{base}?{urllib.parse.urlencode(q)}", {"User-Agent": cfg.user_agent}))
    lic, lic_url = PIXABAY_LICENSE
    out = []
    for hit in data.get("hits") or []:
        title = hit.get("tags") or f"Pixabay {media} {hit['id']}"
        if media == "image":
            cw, ch = _capped(int(hit["imageWidth"]), int(hit["imageHeight"]), PIXABAY_LARGE)
            out.append(Candidate("pixabay", str(hit["id"]), "image", cw, ch, None,
                                 hit.get("webformatURL", ""), hit["largeImageURL"], title,
                                 hit.get("user", ""), lic, lic_url, hit.get("pageURL", "")))
            continue
        files = [(int(v.get("width") or 0), int(v.get("height") or 0), v.get("url", ""), v.get("thumbnail", ""))
                 for v in (hit.get("videos") or {}).values() if v.get("url")]
        best = _smallest_filling(files, layout, cfg.min_fill_px)
        if best is None:
            continue
        out.append(Candidate("pixabay", str(hit["id"]), "video", best[0], best[1], float(hit["duration"]),
                             best[3], best[2], title, hit.get("user", ""), lic, lic_url,
                             hit.get("pageURL", "")))
    return out


def pixabay_fresh(cand: Candidate, fetch: Fetch, key: str, user_agent: str) -> Candidate | None:
    """Pixabay's download links expire after about a day: the same hit again, by id, with a new
    link for the same file (None when the hit or that file is gone)."""
    base = PIXABAY_IMAGES if cand.kind == "image" else PIXABAY_VIDEOS
    data = json.loads(fetch(f"{base}?{urllib.parse.urlencode({'key': key, 'id': cand.id})}",
                            {"User-Agent": user_agent}))
    hit = next(iter(data.get("hits") or []), None)
    if hit is None:
        return None
    if cand.kind == "image":
        url = hit.get("largeImageURL", "")
    else:
        url = next((v["url"] for v in (hit.get("videos") or {}).values()
                    if v.get("url") and int(v.get("width") or 0) == cand.w
                    and int(v.get("height") or 0) == cand.h), "")
    return replace(cand, download_url=url) if url else None
