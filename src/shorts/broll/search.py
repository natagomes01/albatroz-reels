"""Search one moment across the sources (S8B spec 5.6), with a 24 h cache and thumbnails."""
from __future__ import annotations

import itertools
import os
import time
from pathlib import Path

from shorts import jobs, keychain
from shorts.broll.model import BrollConfig, fill_ok
from shorts.broll.sources import (Candidate, Fetch, SourceError, commons_search, pexels_search,
                                  pixabay_search)

ORDER = {"painting": [("commons", "image"), ("pexels", "image"), ("pixabay", "image")],
         "photo": [("pexels", "image"), ("pixabay", "image"), ("commons", "image")],
         "video": [("pexels", "video"), ("pixabay", "video")]}
KEY_SERVICES = {"pexels": "pexels-api", "pixabay": "pixabay-api"}
CACHE_SECONDS = 24 * 3600       # Pixabay requires a 24 h cache; applied to every source


def source_keys(get_secret=keychain.get_secret) -> dict[str, str | None]:
    out: dict[str, str | None] = {}
    for name, service in KEY_SERVICES.items():
        try:
            out[name] = get_secret(service)
        except keychain.MissingSecret:
            out[name] = None
    return out


def _query(source: str, media: str, term: str, layout: str, cfg: BrollConfig, keys: dict,
           fetch: Fetch) -> list[Candidate]:
    if source == "commons":
        return commons_search(term, fetch, cfg.user_agent, cfg.max_still_px, cfg.thumb_width)
    if source == "pexels":
        return pexels_search(term, media, fetch, keys["pexels"], layout, cfg)
    return pixabay_search(term, media, fetch, keys["pixabay"], layout, cfg)


def _cached(cache_dir: Path, source: str, media: str, term: str, layout: str, run, now: float):
    path = cache_dir / f"{jobs.stage_key('1', source=source, media=media, term=term.lower(), layout=layout)}.json"
    try:
        data = jobs.read_json(path)
    except ValueError:
        data = None                         # a broken cache file is just a miss
    if isinstance(data, dict) and 0 <= now - data.get("t", -1e18) < CACHE_SECONDS:
        return [Candidate.from_dict(d) for d in data["items"]]
    items = run()
    jobs.write_json_atomic(path, {"t": now, "items": [c.to_dict() for c in items]})
    return items


def _keep(c: Candidate, layout: str, min_duration: float, cfg: BrollConfig) -> bool:
    if c.kind == "video":
        return (c.duration or 0.0) + 1e-6 >= min_duration
    return any(fill_ok(c.w, c.h, layout, fit, cfg.min_fill_px) for fit in ("cover", "whole"))


def fetch_thumbs(cands: list[Candidate], fetch: Fetch, thumbs_dir: Path, user_agent: str) -> None:
    """One small JPEG per candidate for the page; a failed thumbnail only leaves a blank tile."""
    thumbs_dir.mkdir(parents=True, exist_ok=True)
    for c in cands:
        path = thumbs_dir / f"{c.key}.jpg"
        if path.exists() or not c.thumb_url:
            continue
        try:
            data = fetch(c.thumb_url, {"User-Agent": user_agent})
        except SourceError:
            continue
        part = path.with_suffix(".part")
        part.write_bytes(data)
        os.replace(part, path)


def search_moment(terms: list[str], kind: str, layout: str, min_duration: float, cfg: BrollConfig,
                  keys: dict, fetch: Fetch, cache_dir: Path, thumbs_dir: Path,
                  now: float | None = None) -> tuple[list[Candidate], list[str]]:
    """Up to `cfg.candidates` candidates, interleaved across sources in `kind` order, filtered by
    licence (in the sources), resolution and duration; plus one error line per failed source."""
    now = time.time() if now is None else now
    lists: list[list[Candidate]] = []
    errors: list[str] = []
    for source, media in ORDER.get(kind, ORDER["photo"]):
        if source != "commons" and not keys.get(source):
            continue                        # spec 3: a missing key drops that source silently
        found: list[Candidate] = []
        try:
            for term in terms:
                found += _cached(cache_dir, source, media, term, layout,
                                 lambda term=term: _query(source, media, term, layout, cfg, keys, fetch), now)
        except (SourceError, ValueError, KeyError, TypeError) as e:
            errors.append(f"{source}: {e}")
        lists.append([c for c in found if _keep(c, layout, min_duration, cfg)])
    out: list[Candidate] = []
    seen: set[str] = set()
    for row in itertools.zip_longest(*lists):
        for c in row:
            if c is not None and c.key not in seen and len(out) < cfg.candidates:
                seen.add(c.key)
                out.append(c)
    fetch_thumbs(out, fetch, thumbs_dir, cfg.user_agent)
    return out, errors
