import json
import io
import os
import subprocess

import pytest

from conftest import needs_ffmpeg
from shorts.broll.files import (BrollFileMissing, clean_upload_name, ensure_files, fetch_pick,
                                file_digest, media_info, own_files, own_pick, save_upload)
from shorts.broll.sources import Candidate
from shorts.ffmpeg import FFMPEG

CAND = Candidate("pexels", "11", "image", 4096, 2731, None, "t", "https://images.pexels.com/a.jpeg?w=4096",
                 "Altar", "Ana", "Pexels License", "https://www.pexels.com/license/", "https://www.pexels.com/photo/11/")
VIDEO = Candidate("pixabay", "41", "video", 1920, 1080, 9.0, "t", "https://cdn.pixabay.com/41_l.mp4",
                  "candles", "Bia", "Pixabay Content License", "", "https://pixabay.com/videos/41/")


def info_of(w=4096, h=2731, duration=None, hdr=False):
    return lambda path: {"w": w, "h": h, "duration": duration, "hdr": hdr}


def fake_download(calls):
    def download(url, dest, headers, max_bytes):
        calls.append((url, dest.name, headers))
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"media")
    return download


@pytest.mark.parametrize("name,ext,expected", [
    ("../../x.png", ".png", "own-x.png"),
    ("Tela do n8n (1).PNG", ".png", "own-Tela-do-n8n-1.png"),
    ("Ação.jpg", ".jpg", "own-Acao.jpg"),
    ("....", ".jpg", "own-file.jpg"),
    ("a" * 300 + ".mp4", ".mp4", "own-" + "a" * 60 + ".mp4"),
])
def test_clean_upload_name(name, ext, expected):
    assert clean_upload_name(name, ext) == expected


def test_save_upload_writes_inside_the_folder_and_never_overwrites(tmp_path):
    out = save_upload(io.BytesIO(b"png-bytes"), 9, "../shot.png", "image/png", tmp_path, 1000,
                      info=info_of(1920, 1080))
    assert out == {"name": "own-shot.png", "kind": "image", "w": 1920, "h": 1080, "duration": None}
    assert (tmp_path / "own-shot.png").read_bytes() == b"png-bytes"
    again = save_upload(io.BytesIO(b"other"), 5, "shot.png", "image/png", tmp_path, 1000, info=info_of())
    assert again["name"] == "own-shot-2.png"
    assert not list(tmp_path.glob("*.part"))


def test_save_upload_refuses_bad_type_size_and_unreadable_files(tmp_path):
    with pytest.raises(ValueError, match="type"):
        save_upload(io.BytesIO(b"x"), 1, "a.exe", "application/x-msdownload", tmp_path, 10, info=info_of())
    with pytest.raises(ValueError, match="over"):
        save_upload(io.BytesIO(b"x" * 20), 20, "a.png", "image/png", tmp_path, 10, info=info_of())

    def broken(path):
        raise ValueError("not media")
    with pytest.raises(ValueError, match="readable"):
        save_upload(io.BytesIO(b"x"), 1, "a.png", "image/png", tmp_path, 10, info=broken)
    assert list(tmp_path.iterdir()) == []


def test_fetch_pick_downloads_once_and_builds_the_pick(tmp_path):
    calls = []
    pick = fetch_pick(CAND, tmp_path, "ua", download=fake_download(calls), info=info_of())
    assert pick["file"] == "pexels-11.jpg" and pick["source"] == "pexels" and pick["kind"] == "image"
    assert pick["w"] == 4096 and pick["duration"] is None and pick["license"] == "Pexels License"
    assert calls[0][2] == {"User-Agent": "ua"}
    fetch_pick(CAND, tmp_path, "ua", download=fake_download(calls), info=info_of())
    assert len(calls) == 1


def test_fetch_pick_refuses_hdr_video(tmp_path):
    with pytest.raises(ValueError, match="HDR"):
        fetch_pick(VIDEO, tmp_path, "ua", download=fake_download([]), info=info_of(1920, 1080, 9.0, hdr=True))
    assert not (tmp_path / "pixabay-41.mp4").exists()
    pick = fetch_pick(VIDEO, tmp_path, "ua", download=fake_download([]), info=info_of(1920, 1080, 9.04))
    assert pick["file"] == "pixabay-41.mp4" and pick["duration"] == 9.04


def test_own_files_lists_media_only(tmp_path):
    for name in ("own-a.png", "Tela.jpg", "clip.mov", "pexels-11.jpg", "own-a.png.sha256",
                 "b.png.part", "notes.txt", "with space.png"):
        (tmp_path / name).write_bytes(b"x")
    names = [f["name"] for f in own_files(tmp_path, info=info_of())]
    assert names == ["Tela.jpg", "clip.mov", "own-a.png"]
    assert own_files(tmp_path / "missing") == []


def test_own_pick(tmp_path):
    (tmp_path / "own-a.png").write_bytes(b"x")
    pick = own_pick("own-a.png", tmp_path, info=info_of(1920, 1080))
    assert pick["source"] == "own" and pick["file"] == "own-a.png" and pick["title"] == "own-a.png"
    with pytest.raises(BrollFileMissing):
        own_pick("own-b.png", tmp_path, info=info_of())
    (tmp_path / "own-v.mov").write_bytes(b"x")
    with pytest.raises(ValueError, match="HDR"):
        own_pick("own-v.mov", tmp_path, info=info_of(1920, 1080, 5.0, hdr=True))
    with pytest.raises(ValueError):
        own_pick("../etc.png", tmp_path, info=info_of())


def test_file_digest_follows_the_content(tmp_path):
    f = tmp_path / "a.jpg"
    f.write_bytes(b"one")
    d1 = file_digest(f)
    assert d1 == file_digest(f) and (tmp_path / "a.jpg.sha256").exists()
    f.write_bytes(b"two")
    os.utime(f, ns=(1, 1))
    assert file_digest(f) != d1


def test_missing_files_are_fetched_again_or_named(tmp_path):
    stock = {"id": "s1", "pick": {"source": "pexels", "file": "pexels-11.jpg", "download_url": "https://x/a.jpg"}}
    own = {"id": "o1", "pick": {"source": "own", "file": "own-a.png", "download_url": ""}}
    calls = []
    ensure_files([stock, {"id": "s2", "pick": None}], tmp_path, "ua", download=fake_download(calls))
    assert calls[0][:2] == ("https://x/a.jpg", "pexels-11.jpg")
    with pytest.raises(BrollFileMissing, match="B-roll file missing: own-a.png; add it again on the review page"):
        ensure_files([own], tmp_path, "ua", download=fake_download(calls))


@needs_ffmpeg
def test_media_info_reads_stills_and_videos(tmp_path):
    png, mp4 = tmp_path / "a.png", tmp_path / "v.mp4"
    subprocess.run([FFMPEG, "-v", "error", "-f", "lavfi", "-i", "color=red:s=1600x900:d=1",
                    "-frames:v", "1", str(png)], check=True)
    subprocess.run([FFMPEG, "-v", "error", "-f", "lavfi", "-i", "color=blue:s=640x360:d=2:r=30",
                    "-pix_fmt", "yuv420p", str(mp4)], check=True)
    assert media_info(png) == {"w": 1600, "h": 900, "duration": None, "hdr": False}
    v = media_info(mp4)
    assert (v["w"], v["h"], v["hdr"]) == (640, 360, False) and v["duration"] == pytest.approx(2.0, abs=0.1)


@needs_ffmpeg
@pytest.mark.parametrize("rotation", [90, -90, 270, 180])
def test_media_info_returns_display_size_for_rotated_files(tmp_path, rotation):
    mp4 = tmp_path / "r.mp4"
    base = tmp_path / "base.mp4"
    subprocess.run([FFMPEG, "-v", "error", "-f", "lavfi", "-i", "color=blue:s=640x360:d=1:r=30",
                    "-pix_fmt", "yuv420p", str(base)], check=True)
    subprocess.run([FFMPEG, "-v", "error", "-display_rotation", str(rotation), "-i", str(base),
                    "-c", "copy", str(mp4)], check=True)
    v = media_info(mp4)
    expected = (640, 360) if rotation == 180 else (360, 640)
    assert (v["w"], v["h"]) == expected


def test_fetch_pick_removes_a_file_whose_info_fails_so_the_next_click_downloads_again(tmp_path):
    def bad(path):
        raise ValueError("unreadable")
    with pytest.raises(ValueError):
        fetch_pick(CAND, tmp_path, "ua", download=fake_download([]), info=bad)
    assert not (tmp_path / "pexels-11.jpg").exists()


def test_file_digest_recomputes_when_the_sidecar_has_no_sha(tmp_path):
    f = tmp_path / "a.jpg"
    f.write_bytes(b"one")
    d1 = file_digest(f)
    st = f.stat()
    (tmp_path / "a.jpg.sha256").write_text(json.dumps({"size": st.st_size, "mtime_ns": st.st_mtime_ns}), encoding="utf-8")
    assert file_digest(f) == d1


@needs_ffmpeg
def test_video_thumb_takes_a_frame_at_3_s_or_the_last_one(tmp_path):
    from shorts.broll.files import video_thumb
    for secs in (5, 1):
        mp4 = tmp_path / f"own-v{secs}.mp4"
        subprocess.run([FFMPEG, "-v", "error", "-f", "lavfi", "-i", f"color=blue:s=1080x1920:d={secs}:r=30",
                        "-pix_fmt", "yuv420p", str(mp4)], check=True)
        out = tmp_path / "thumbs" / f"own-{mp4.name}.jpg"
        video_thumb(mp4, out)
        assert media_info(out)["w"] == 360 and not list(out.parent.glob("*.part*"))
