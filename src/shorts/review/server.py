"""Local review server with a hand-written HTTP Range handler (spec 7).

Range semantics follow RFC 9110 section 14: single ranges only; a multi-range request gets the
whole file with 200, which every browser accepts; an unsatisfiable range gets 416.

It listens on 127.0.0.1 only, and it also checks the Host header on every request (DNS
rebinding) and Content-Type + Origin on every POST (cross-site form/fetch), because any web
page open in the browser can send requests to 127.0.0.1.
"""
from __future__ import annotations

import json
import re
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from shorts import jobs
from shorts.broll.files import BrollFileMissing
from shorts.dereverb import DEFAULT_LEVELS
from shorts.review.audio import Busy
from shorts.review.state import NothingToUndo, apply_decision, apply_edit, load_state, redo, undo

STATIC = Path(__file__).parent / "static"
FONTS = Path(__file__).resolve().parents[3] / "assets" / "fonts"   # shared with the captions (spec 6.4)
_RANGE = re.compile(r"^bytes=(\d*)-(\d*)$")
_RENDER_FILE = re.compile(r"^/renders/([A-Za-z0-9_-]+)\.mp4$")
_EXCERPT_FILE = re.compile(r"^/media/excerpt/(\d{1,3})\.m4a$")
_BROLL_FILE = re.compile(r"^/media/broll/([^/]+)$")
_BROLL_THUMB = re.compile(r"^/media/broll-thumb/([^/]+)$")
_BROLL_DETAILS = re.compile(r"^/api/broll/candidates/([A-Za-z0-9_-]+)$")
GATE_TIP = "Choose the audio strength first"


def _audio_block(audio) -> str | None:
    """Why a render request must wait for the audio panel (S8 audio spec 3, 5.4), or None."""
    if audio is None:
        return None
    if not audio.gate_ok():
        return GATE_TIP
    if audio.preparing():
        return "the audio excerpt is being prepared; render when it is ready"
    return None
_TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
          ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml", ".ttf": "font/ttf"}
_MEDIA = {".mov": "video/quicktime", ".mp4": "video/mp4", ".m4v": "video/x-m4v",
          ".m4a": "audio/mp4", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}
MAX_BODY = 1 << 20


class RangeNotSatisfiable(Exception):
    pass


def media_type(path: Path) -> str:
    return _MEDIA.get(Path(path).suffix.lower(), "application/octet-stream")


def parse_range(header: str | None, size: int) -> tuple[int, int] | None:
    if not header:
        return None
    if "," in header:
        return None
    m = _RANGE.match(header.strip())
    if not m or (m.group(1) == "" and m.group(2) == ""):
        raise RangeNotSatisfiable(header)
    first, last = m.group(1), m.group(2)
    if first == "":
        n = int(last)
        if n == 0:
            raise RangeNotSatisfiable(header)
        return max(size - n, 0), size - 1
    start = int(first)
    end = int(last) if last else size - 1
    if start >= size or end < start:
        raise RangeNotSatisfiable(header)
    return start, min(end, size - 1)


def make_handler(job, master: Path, renders=None, audio=None, broll=None):
    """`renders` is the page's RenderQueue (S7); without it the render routes answer 404.
    `audio` is the page's AudioPanel (S8); without it the audio routes answer 404 and renders
    are not gated. `broll` is the page's BrollQueue (S8B); without it the B-roll routes answer 404."""
    master = Path(master)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):  # keep the terminal quiet
            pass

        def _allowed_hosts(self) -> set[str]:
            port = self.server.server_address[1]
            return {f"127.0.0.1:{port}", f"localhost:{port}"}

        def _host_ok(self) -> bool:
            if self.headers.get("Host") in self._allowed_hosts():
                return True
            self._json(403, {"error": "forbidden host"})
            return False

        def _json(self, status: int, obj, head: bool = False) -> None:
            body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if not head:
                self.wfile.write(body)

        def _static(self, name: str, head: bool = False, root: Path = STATIC,
                    only: str | None = None) -> None:
            path = (root / name).resolve()
            if (root.resolve() not in path.parents or not path.is_file()
                    or (only is not None and path.suffix != only)):
                return self._json(404, {"error": "not found"}, head)
            body = path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", _TYPES.get(path.suffix, "application/octet-stream"))
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if not head:
                self.wfile.write(body)

        def _media(self, head: bool = False) -> None:
            if not master.exists():
                return self._json(404, {"error": f"master not found at {master}"}, head)
            self._send_file(master, head)

        def _send_file(self, path: Path, head: bool = False, no_store: bool = False) -> None:
            size = path.stat().st_size
            try:
                rng = parse_range(self.headers.get("Range"), size)
            except RangeNotSatisfiable:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            start, end = rng if rng else (0, size - 1)
            length = end - start + 1
            self.send_response(206 if rng else 200)
            self.send_header("Content-Type", media_type(path))
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(length))
            if no_store:   # a re-render keeps the same path: never replay the old file (S7 spec 5.4)
                self.send_header("Cache-Control", "no-store")
            if rng:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.end_headers()
            if head:
                return
            with open(path, "rb") as f:
                f.seek(start)
                left = length
                while left > 0:
                    chunk = f.read(min(1 << 20, left))
                    if not chunk:
                        break
                    try:
                        self.wfile.write(chunk)
                    except (BrokenPipeError, ConnectionResetError):
                        return  # the browser cancelled a seek; normal
                    left -= len(chunk)

        def _route_get(self, head: bool) -> None:
            if not self._host_ok():
                return
            p = self.path.split("?")[0]
            if p == "/":
                return self._static("index.html", head)
            if p.startswith("/static/"):
                return self._static(p[len("/static/"):], head)
            if p.startswith("/fonts/"):
                return self._static(p[len("/fonts/"):], head, root=FONTS, only=".ttf")
            if p == "/media/master":
                return self._media(head)
            if p == "/api/job":
                try:
                    return self._json(200, load_state(job), head)
                except (ValueError, OSError) as e:   # e.g. a corrupt review.json: say so, don't drop
                    return self._json(500, {"error": str(e)}, head)
            if p == "/api/renders" and renders is not None:
                try:
                    return self._json(200, renders.snapshot(), head)
                except (ValueError, OSError) as e:   # e.g. a corrupt review.json: say so, don't drop
                    return self._json(500, {"error": str(e)}, head)
            if p == "/api/audio" and audio is not None:
                try:
                    return self._json(200, audio.state(), head)
                except (ValueError, OSError) as e:   # e.g. a corrupt review.json
                    return self._json(500, {"error": str(e)}, head)
            m = _EXCERPT_FILE.match(p)
            if m and audio is not None:
                path = audio.file(int(m.group(1)))
                if path is not None:
                    return self._send_file(path, head, no_store=True)
            m = _RENDER_FILE.match(p)
            if m and renders is not None:
                try:
                    path = renders.file(m.group(1))
                except (ValueError, OSError) as e:
                    return self._json(500, {"error": str(e)}, head)
                if path is not None:
                    return self._send_file(path, head, no_store=True)
            if broll is not None:
                try:
                    if p == "/api/broll":
                        return self._json(200, broll.snapshot(), head)
                    if p == "/api/broll/files":
                        return self._json(200, broll.files(), head)
                    m = _BROLL_DETAILS.match(p)
                    if m:
                        return self._json(200, broll.details(m.group(1)), head)
                except ValueError as e:
                    return self._json(400, {"error": str(e)}, head)
                except Exception as e:      # OSError, FFmpegError, KeyError...: always a JSON reply
                    import sys
                    import traceback
                    traceback.print_exc(file=sys.stderr)    # log_message is silenced: keep the trace
                    return self._json(500, {"error": str(e) or type(e).__name__}, head)
                for pattern, find in ((_BROLL_FILE, broll.media), (_BROLL_THUMB, broll.thumb)):
                    m = pattern.match(p)
                    if m:
                        path = find(m.group(1))
                        if path is not None:
                            return self._send_file(path, head)
                        return self._json(404, {"error": "not found"}, head)
            return self._json(404, {"error": "not found"}, head)

        def _upload(self) -> None:
            """S8B spec 7.2: a raw image or video body; same Origin rule as every POST."""
            import urllib.parse
            from shorts.broll.files import UPLOAD_TYPES
            if self.headers.get("Origin") != f"http://{self.headers.get('Host')}":
                return self._json(403, {"error": "cross-origin request refused"})
            try:
                n = int(self.headers.get("Content-Length") or -1)
            except ValueError:
                n = -1
            if n < 0:
                return self._json(400, {"error": "invalid Content-Length"})
            if n > broll.upload_cap:
                self.close_connection = True       # the body is never read
                return self._json(413, {"error": f"the file is over {broll.upload_cap >> 20} MB"})
            ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            if ctype not in UPLOAD_TYPES:
                self.close_connection = True
                return self._json(415, {"error": "JPEG, PNG, MP4 or MOV only"})
            try:
                name = urllib.parse.unquote(self.headers.get("X-File-Name") or "file")   # sent URI-encoded
                return self._json(200, broll.upload(self.rfile, n, name, ctype))
            except ValueError as e:
                return self._json(400, {"error": str(e)})
            except OSError as e:                   # a disk fault stays a 500
                return self._json(500, {"error": str(e)})

        def do_GET(self):
            self._route_get(head=False)

        def do_HEAD(self):
            self._route_get(head=True)

        def do_POST(self):
            if not self._host_ok():
                return
            if self.path == "/api/broll/upload" and broll is not None:
                return self._upload()
            ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            if ctype != "application/json":
                return self._json(415, {"error": "Content-Type must be application/json"})
            origin = self.headers.get("Origin")
            if origin != f"http://{self.headers.get('Host')}":
                return self._json(403, {"error": "cross-origin request refused"})
            try:
                n = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                n = -1
            if n < 0:
                return self._json(400, {"error": "invalid Content-Length"})
            if n > MAX_BODY:
                return self._json(413, {"error": "body too large"})
            try:
                body = json.loads(self.rfile.read(n) or b"{}")
                if not isinstance(body, dict):
                    raise ValueError("body must be a JSON object")
                if self.path == "/api/decision":
                    reply = apply_decision(job, body["id"], body["status"])
                    if broll is not None and body["status"] == "approved":
                        try:
                            broll.on_approved(body["id"])     # spec 5.1; never fails the decision
                        except Exception:
                            pass
                    return self._json(200, reply)
                if self.path == "/api/edit":
                    levels = audio.levels if audio is not None else DEFAULT_LEVELS
                    return self._json(200, apply_edit(job, body["id"], body["edit"], levels))
                if self.path == "/api/audio" and audio is not None:
                    return self._json(200, audio.choose(body["dereverb"]))
                if self.path == "/api/audio/prepare" and audio is not None:
                    return self._json(200, audio.prepare())
                if self.path == "/api/undo":
                    return self._json(200, undo(job, body["id"]))
                if self.path == "/api/redo":
                    return self._json(200, redo(job, body["id"]))
                if self.path in ("/api/render", "/api/render-all") and renders is not None:
                    blocked = _audio_block(audio)
                    if blocked:
                        return self._json(409, {"error": blocked})
                    if self.path == "/api/render":
                        return self._json(200, renders.enqueue(body["id"]))
                    return self._json(200, renders.enqueue_all())
                if broll is not None and self.path.startswith("/api/broll/"):
                    if self.path == "/api/broll/suggest":
                        return self._json(200, broll.suggest(body["id"]))
                    if self.path == "/api/broll/search":
                        return self._json(200, broll.search(body["id"], body["moment"], body["terms"],
                                                            body.get("kind")))
                    if self.path == "/api/broll/pick":
                        return self._json(200, broll.pick(body["id"], body["moment"], body["candidate"]))
                    if self.path == "/api/broll/use-file":
                        return self._json(200, broll.use_file(body["id"], body["moment"], body["name"]))
            except (NothingToUndo, Busy) as e:              # before ValueError: it is one
                return self._json(409, {"error": str(e)})
            except BrollFileMissing as e:                   # a FileNotFoundError: before the OSError arm
                return self._json(400, {"error": str(e)})
            except (KeyError, ValueError, TypeError, AttributeError) as e:
                return self._json(400, {"error": str(e) or type(e).__name__})
            except OSError as e:
                return self._json(500, {"error": str(e)})
            return self._json(404, {"error": "not found"})

    return Handler


def serve(job, port: int = 8765, open_browser: bool = True, app=None, channel=None,
          command=None, excerpt_command=None, broll_command=None) -> None:
    master = Path(jobs.read_json(job.job_json)["master"])
    renders = None
    audio = None
    broll = None
    if app is not None and channel is not None:
        from shorts.review.renders import RenderQueue
        from shorts.stages import render_path, render_status
        renders = RenderQueue(
            status=lambda: render_status(job, app, channel),
            render_file=lambda cid: render_path(app, channel.id, job, cid),
            command=command,
            ids=lambda: {c["id"] for c in jobs.read_json(job.candidates_json,
                                                         {"candidates": []})["candidates"]})
        from shorts.excerpt import excerpt_path
        from shorts.ffmpeg import probe
        from shorts.review.audio import AudioPanel
        try:   # an unreadable master or a missing ffprobe must not stop the page from opening
            has_audio = not master.exists() or probe(master).has_audio
        except Exception:
            has_audio = True      # the gate stays closed; the excerpt reports the real error
        audio = AudioPanel(job, app.dereverb.levels, lambda lv: excerpt_path(app, job, lv),
                           command=excerpt_command, busy=renders.busy,
                           enabled=channel.sound and has_audio)
        from shorts.review.broll import BrollQueue
        broll = BrollQueue(job, app, channel, command=broll_command)
    httpd = ThreadingHTTPServer(("127.0.0.1", port), make_handler(job, master, renders, audio, broll))
    url = f"http://127.0.0.1:{port}/"
    print(f"review page: {url}  (Ctrl+C to stop)")
    if open_browser:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if renders is not None:
            renders.stop()
        if broll is not None:
            broll.stop()
        httpd.server_close()
