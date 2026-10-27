import json

import pytest

from shorts.broll.model import BrollConfig
from shorts.broll.search import search_moment, source_keys
from shorts.broll.sources import (Candidate, SourceError, commons_licence, commons_search,
                                  pexels_search, pixabay_search)
from shorts.keychain import MissingSecret

CFG = BrollConfig(user_agent="test-agent (t@example.com)")


def fake_fetch(routes, calls):
    def fetch(url, headers):
        calls.append((url, headers))
        for prefix, body in routes.items():
            if url.startswith(prefix):
                if isinstance(body, Exception):
                    raise body
                return body if isinstance(body, bytes) else json.dumps(body).encode()
        raise SourceError(f"no route for {url}")
    return fetch


def commons_page(i, title, lic, w=4000, h=3000, mime="image/jpeg"):
    return {"pageid": 100 + i, "index": i, "title": f"File:{title}",
            "imageinfo": [{"width": w, "height": h, "mime": mime,
                           "descriptionurl": f"https://commons.wikimedia.org/wiki/File:{title}",
                           "extmetadata": {
                               "LicenseShortName": {"value": lic},
                               "Artist": {"value": '<a href="//x">Leonardo &amp; workshop</a>'},
                               "ObjectName": {"value": "The Last Supper"},
                               "LicenseUrl": {"value": "https://creativecommons.org/licenses/by/4.0"}}}]}


def commons_reply(*pages):
    return {"query": {"pages": {str(p["pageid"]): p for p in pages}}}


COMMONS = commons_reply(commons_page(1, "Ceia.jpg", "Public domain"),
                        commons_page(2, "Altar.jpg", "CC BY 4.0"),
                        commons_page(3, "Nave.jpg", "CC BY-SA 4.0"),
                        commons_page(4, "Icon.png", "CC0", mime="image/png"),
                        commons_page(5, "Odd.jpg", "Custom licence"),
                        commons_page(6, "Map.svg", "Public domain", mime="image/svg+xml"))
PEXELS_PHOTOS = {"photos": [{"id": 11, "width": 6000, "height": 4000, "url": "https://www.pexels.com/photo/11/",
                             "photographer": "Ana", "alt": "Catholic Mass altar",
                             "src": {"original": "https://images.pexels.com/photos/11/a.jpeg",
                                     "medium": "https://images.pexels.com/photos/11/a.jpeg?h=350"}}]}
PEXELS_VIDEOS = {"videos": [{"id": 21, "width": 3840, "height": 2160, "duration": 12,
                             "url": "https://www.pexels.com/video/21/", "user": {"name": "Rui"},
                             "image": "https://images.pexels.com/videos/21/t.jpg",
                             "video_files": [
                                 {"file_type": "video/mp4", "width": 640, "height": 360, "link": "https://v/360.mp4"},
                                 {"file_type": "video/mp4", "width": 3840, "height": 2160, "link": "https://v/2160.mp4"},
                                 {"file_type": "video/mp4", "width": 1920, "height": 1080, "link": "https://v/1080.mp4"}]},
                            {"id": 22, "width": 1280, "height": 720, "duration": 3,
                             "url": "https://www.pexels.com/video/22/", "user": {"name": "Rui"},
                             "image": "https://images.pexels.com/videos/22/t.jpg",
                             "video_files": [{"file_type": "video/mp4", "width": 1280, "height": 720,
                                              "link": "https://v/720.mp4"}]}]}
PIXABAY_IMAGES = {"hits": [{"id": 31, "imageWidth": 6000, "imageHeight": 4000, "tags": "church, nave",
                            "user": "Bia", "pageURL": "https://pixabay.com/photos/31/",
                            "webformatURL": "https://cdn.pixabay.com/31_640.jpg",
                            "largeImageURL": "https://cdn.pixabay.com/31_1280.jpg"}]}
PIXABAY_VIDEOS = {"hits": [{"id": 41, "duration": 9, "tags": "candles", "user": "Bia",
                            "pageURL": "https://pixabay.com/videos/41/",
                            "videos": {"large": {"url": "https://cdn.pixabay.com/41_l.mp4", "width": 1920,
                                                 "height": 1080, "thumbnail": "https://cdn.pixabay.com/41_l.jpg"},
                                       "medium": {"url": "https://cdn.pixabay.com/41_m.mp4", "width": 1280,
                                                  "height": 720, "thumbnail": "https://cdn.pixabay.com/41_m.jpg"}}}]}
THUMBS = {"https://commons.wikimedia.org/wiki/Special:FilePath/": b"jpg",
          "https://images.pexels.com/": b"jpg", "https://cdn.pixabay.com/": b"jpg"}
ROUTES = {"https://commons.wikimedia.org/w/api.php": COMMONS,
          "https://api.pexels.com/v1/search": PEXELS_PHOTOS,
          "https://api.pexels.com/videos/search": PEXELS_VIDEOS,
          "https://pixabay.com/api/videos/": PIXABAY_VIDEOS,
          "https://pixabay.com/api/": PIXABAY_IMAGES, **THUMBS}
KEYS = {"pexels": "pk", "pixabay": "xk"}


@pytest.mark.parametrize("short,expected", [
    ("Public domain", "Public domain"), ("PD-Art", "Public domain"), ("pd", "Public domain"),
    ("CC0", "CC0"), ("CC0 1.0", "CC0"), ("CC BY 4.0", "CC BY 4.0"), ("CC-BY-2.5", "CC BY 2.5"),
    ("CC BY", "CC BY"), ("CC BY-SA 4.0", None), ("CC BY-NC 2.0", None), ("CC BY-ND 3.0", None),
    ("GFDL", None), ("", None),
])
def test_commons_licence(short, expected):
    assert commons_licence(short) == expected


def test_commons_search_keeps_pd_cc0_ccby_bitmaps_only():
    calls = []
    found = commons_search("Last Supper painting", fake_fetch(ROUTES, calls), CFG.user_agent, 4096, 320)
    assert [c.license for c in found] == ["Public domain", "CC BY 4.0", "CC0"]
    c = found[0]
    assert c.title == "The Last Supper" and c.author == "Leonardo & workshop"
    assert c.page_url.endswith("File:Ceia.jpg") and c.key == "commons-101"
    assert calls[0][1]["User-Agent"] == CFG.user_agent
    assert "gsrsearch=Last+Supper+painting" in calls[0][0]


def test_commons_download_url_caps_the_long_side():
    reply = commons_reply(commons_page(1, "Wide.jpg", "Public domain", w=20000, h=10000),
                          commons_page(2, "Tall.jpg", "Public domain", w=6000, h=12000))
    found = commons_search("x", fake_fetch({"https://commons": reply}, []), "ua", 4096, 320)
    assert (found[0].w, found[0].h) == (4096, 2048) and found[0].download_url.endswith("Wide.jpg?width=4096")
    assert (found[1].w, found[1].h) == (2048, 4096) and found[1].download_url.endswith("Tall.jpg?width=2048")
    assert found[0].thumb_url.endswith("?width=320")


def test_pexels_photos_are_capped_and_videos_take_the_smallest_file_that_fills():
    fetch = fake_fetch(ROUTES, [])
    photo = pexels_search("altar", "image", fetch, "pk", "full", CFG)[0]
    assert (photo.w, photo.h) == (4096, 2731) and "w=4096" in photo.download_url
    assert photo.license == "Pexels License" and photo.author == "Ana"
    videos = pexels_search("mass", "video", fetch, "pk", "full", CFG)
    assert [v.download_url for v in videos] == ["https://v/1080.mp4"]       # video 22 has no 1080 file
    assert videos[0].duration == 12.0 and (videos[0].w, videos[0].h) == (1920, 1080)


def test_pexels_sends_the_key():
    calls = []
    pexels_search("altar", "image", fake_fetch(ROUTES, calls), "pk", "full", CFG)
    assert calls[0][1]["Authorization"] == "pk"


def test_pixabay_stills_are_1280_and_videos_pick_a_variant():
    fetch = fake_fetch(ROUTES, [])
    still = pixabay_search("church", "image", fetch, "xk", "full", CFG)[0]
    assert (still.w, still.h) == (1280, 853) and still.download_url.endswith("31_1280.jpg")
    video = pixabay_search("candles", "video", fetch, "xk", "full", CFG)[0]
    assert video.download_url.endswith("41_l.mp4") and video.duration == 9.0
    assert video.thumb_url.endswith("41_l.jpg")


def test_search_moment_filters_interleaves_and_caps(tmp_path):
    found, errors = search_moment(["Last Supper"], "painting", "full", 3.0, CFG, KEYS,
                                  fake_fetch(ROUTES, []), tmp_path / "cache", tmp_path / "thumbs", now=0)
    assert errors == []
    assert [c.source for c in found] == ["commons", "pexels", "pixabay", "commons", "commons"]
    assert len({c.key for c in found}) == len(found)
    small = CFG.__class__(candidates=2)
    found, _ = search_moment(["Last Supper"], "painting", "full", 3.0, small, KEYS,
                             fake_fetch(ROUTES, []), tmp_path / "c2", tmp_path / "t2", now=0)
    assert len(found) == 2


def test_low_resolution_stills_and_short_videos_are_dropped(tmp_path):
    reply = commons_reply(commons_page(1, "Tiny.jpg", "Public domain", w=900, h=700))
    found, _ = search_moment(["x"], "painting", "full", 3.0, CFG, {}, fake_fetch({**THUMBS,
                             "https://commons.wikimedia.org/w/api.php": reply}, []),
                             tmp_path / "c", tmp_path / "t", now=0)
    assert found == []                                     # under 1080 even as "whole"
    found, _ = search_moment(["x"], "video", "full", 10.0, CFG, KEYS, fake_fetch(ROUTES, []),
                             tmp_path / "c3", tmp_path / "t3", now=0)
    assert [c.id for c in found] == ["21"]                 # 12 s passes, Pixabay's 9 s does not


def test_search_cache_reuses_within_24_hours(tmp_path):
    calls = []
    fetch = fake_fetch(ROUTES, calls)
    args = (["Last Supper"], "painting", "full", 3.0, CFG, KEYS, fetch, tmp_path / "c", tmp_path / "t")
    search_moment(*args, now=1000.0)
    api = lambda: [u for u, _ in calls if "api" in u]           # noqa: E731
    first = len(api())
    search_moment(*args, now=1000.0 + 3600)
    assert len(api()) == first
    search_moment(*args, now=1000.0 + 25 * 3600)
    assert len(api()) == 2 * first


def test_a_failing_source_does_not_stop_the_others(tmp_path):
    routes = {**ROUTES, "https://api.pexels.com/v1/search":
              SourceError("api.pexels.com: HTTP Error 401: Unauthorized")}
    found, errors = search_moment(["Last Supper"], "painting", "full", 3.0, CFG, KEYS,
                                  fake_fetch(routes, []), tmp_path / "c", tmp_path / "t", now=0)
    assert errors == ["pexels: api.pexels.com: HTTP Error 401: Unauthorized"]
    assert {c.source for c in found} == {"commons", "pixabay"}


def test_missing_keys_skip_the_source_silently(tmp_path):
    calls = []
    found, errors = search_moment(["x"], "painting", "full", 3.0, CFG, {"pexels": None},
                                  fake_fetch(ROUTES, calls), tmp_path / "c", tmp_path / "t", now=0)
    assert errors == [] and {c.source for c in found} == {"commons"}
    assert not any("pexels" in u or "pixabay" in u for u, _ in calls)


def test_thumbnails_are_written_once(tmp_path):
    calls = []
    args = (["Last Supper"], "painting", "full", 3.0, CFG, KEYS, fake_fetch(ROUTES, calls),
            tmp_path / "c", tmp_path / "t")
    found, _ = search_moment(*args, now=0)
    assert all((tmp_path / "t" / f"{c.key}.jpg").read_bytes() == b"jpg" for c in found)
    n = len(calls)
    search_moment(*args, now=1)
    assert len(calls) == n                                  # cache hit, thumbnails already there


def test_candidate_round_trip():
    c = Candidate("pexels", "11", "image", 10, 20, None, "t", "d", "T", "A", "L", "LU", "P")
    assert Candidate.from_dict(c.to_dict()) == c and c.to_dict()["key"] == "pexels-11"


def test_source_keys_read_the_keychain():
    def get(service):
        if service == "pexels-api":
            return "pk"
        raise MissingSecret(service)
    assert source_keys(get) == {"pexels": "pk", "pixabay": None}


def test_a_commons_api_error_with_http_200_is_reported_and_not_cached(tmp_path):
    routes = {**ROUTES, "https://commons.wikimedia.org/w/api.php":
              {"error": {"code": "ratelimited", "info": "You are doing that too often"}}}
    found, errors = search_moment(["Last Supper"], "painting", "full", 3.0, CFG, KEYS,
                                  fake_fetch(routes, []), tmp_path / "c", tmp_path / "t", now=0)
    assert errors == ["commons: commons.wikimedia.org: You are doing that too often"]
    assert not any(c.source == "commons" for c in found)
    from shorts import jobs
    key = jobs.stage_key("1", source="commons", media="image", term="last supper", layout="full")
    assert not (tmp_path / "c" / f"{key}.json").exists()


def test_pixabay_fresh_asks_by_id_and_keeps_the_same_file():
    from shorts.broll.sources import pixabay_fresh
    asked = []

    def fetch(url, headers):
        asked.append(url)
        if "videos" in url:
            return json.dumps({"hits": [{"id": 7, "videos": {
                "large": {"url": "https://cdn/v-large.mp4", "width": 1920, "height": 1080},
                "small": {"url": "https://cdn/v-small.mp4", "width": 960, "height": 540}}}]}).encode()
        return json.dumps({"hits": [{"id": 5, "largeImageURL": "https://pixabay.com/get/new_1280.jpg"}]}).encode()
    img = Candidate("pixabay", "5", "image", 1280, 853, None, "t", "https://pixabay.com/get/old_1280.jpg",
                    "a", "u", "l", "lu", "p")
    vid = Candidate("pixabay", "7", "video", 960, 540, 12.0, "t", "https://cdn/old.mp4", "a", "u", "l", "lu", "p")
    assert pixabay_fresh(img, fetch, "K", "ua").download_url == "https://pixabay.com/get/new_1280.jpg"
    assert pixabay_fresh(vid, fetch, "K", "ua").download_url == "https://cdn/v-small.mp4"
    assert "id=5" in asked[0] and "key=K" in asked[0] and "/videos/" in asked[1]
    assert pixabay_fresh(img, lambda u, h: b'{"hits": []}', "K", "ua") is None
