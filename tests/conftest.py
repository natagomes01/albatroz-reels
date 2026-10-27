"""Shared fixtures: ffmpeg availability, synthetic videos, and the optional real sample."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from shorts.ffmpeg import FFMPEG

HAS_FFMPEG = Path(FFMPEG).exists()
needs_ffmpeg = pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg-full not installed")


@pytest.fixture
def synth_video(tmp_path):
    """Factory: a gradient video (red channel = x/5, green = y/3) with a sine tone.

    silent=(a, b) mutes the tone between a and b seconds, to exercise silence cutting.
    """

    def make(
        seconds: float = 6.0,
        size: str = "1280x720",
        silent: tuple[float, float] | None = None,
        ext: str = "mp4",
        data_stream: bool = False,
        hlg: bool = False,
    ) -> Path:
        """ext="mov" + data_stream=True adds a `tmcd` data stream, like the extra Core Media
        Metadata streams of an iPhone master. hlg=True tags the video HLG/bt2020 (8-bit is
        enough for ffprobe and zscale to treat it as HDR)."""
        tag = f"{seconds}-{size}-{'s' if silent else ''}{'d' if data_stream else ''}{'h' if hlg else ''}"
        out = tmp_path / f"synth-{tag}.{ext}"
        af = ["-af", f"volume='if(between(t,{silent[0]},{silent[1]}),0,1)':eval=frame"] if silent else []
        tc = ["-timecode", "00:00:00:00"] if data_stream else []
        # setparams tags the frames; encoder-side -color_trc alone is dropped by libx264 here
        hdr = ",setparams=color_trc=arib-std-b67:color_primaries=bt2020:colorspace=bt2020nc" if hlg else ""
        color = (["-color_trc", "arib-std-b67", "-color_primaries", "bt2020", "-colorspace", "bt2020nc"]
                 if hlg else [])
        subprocess.run(
            [FFMPEG, "-y", "-loglevel", "error",
             "-f", "lavfi", "-i", f"nullsrc=s={size}:r=30:d={seconds},geq=r='X/5':g='Y/3':b=128{hdr}",
             "-f", "lavfi", "-i", f"sine=f=300:d={seconds}:sample_rate=44100",
             *af, "-c:v", "libx264", "-pix_fmt", "yuv420p", *color, "-c:a", "aac", *tc,
             "-shortest", str(out)],
            check=True,
        )
        return out

    return make


@pytest.fixture
def sample() -> Path:
    """The real 10-minute class excerpt; tests using it skip when SHORTS_SAMPLE is unset."""
    value = os.environ.get("SHORTS_SAMPLE")
    if not value or not Path(value).exists():
        pytest.skip("SHORTS_SAMPLE not set or missing")
    return Path(value)


import sys

FAKE_UVR = '''#!{python}
import os, sys, wave
from pathlib import Path
args = sys.argv[1:]
src = Path(args[0])
out = Path(args[args.index("--output_dir") + 1])
agg = args[args.index("--vr_aggression") + 1]
calls = os.environ.get("FAKE_UVR_CALLS")
if calls:
    with open(calls, "a") as f:
        f.write(agg + " " + " ".join(args[1:]) + "\\n")
first = int(os.environ.get("FAKE_UVR_FAIL_FIRST", "0"))
if first and calls and len(open(calls).read().splitlines()) <= first:
    out.mkdir(parents=True, exist_ok=True)
    (out / "partial.wav").write_bytes(b"junk")     # a crashed run may leave a file behind
    mode = os.environ.get("FAKE_UVR_MODE", "")
    if mode == "abort":                                  # killed by SIGABRT: returncode -6
        import signal
        os.kill(os.getpid(), signal.SIGABRT)
    if mode == "segv":                                   # killed by SIGSEGV: returncode -11
        import signal
        os.kill(os.getpid(), signal.SIGSEGV)
    if mode == "complete":                               # crashed after finishing
        print("cli - Separation complete! Output file(s): x.wav", file=sys.stderr)
        sys.exit(1)
    if mode == "mutex":                                  # the known message, any exit code
        print("libc++abi: recursive_mutex lock failed: Invalid argument", file=sys.stderr)
        sys.exit(134)
    print("boom", file=sys.stderr)
    sys.exit(3)
if os.environ.get("FAKE_UVR_FAIL"):
    print("boom", file=sys.stderr)
    sys.exit(3)
out.mkdir(parents=True, exist_ok=True)
with wave.open(str(src)) as r:
    params = r.getparams()
    frames = r.readframes(r.getnframes())
if os.environ.get("FAKE_UVR_SHORT"):
    frames = frames[: len(frames) // 2]
with wave.open(str(out / (src.stem + "_(No Reverb)_UVR-DeEcho-DeReverb.wav")), "wb") as w:
    w.setparams(params)
    w.writeframes(frames)
'''


@pytest.fixture
def fake_uvr(tmp_path, monkeypatch):
    """A stand-in for `audio-separator`: copies its input WAV to the 'No Reverb' output name and
    logs one line per call (aggression first) to the returned calls file."""
    from shorts import machine
    from shorts.dereverb import DereverbConfig
    if machine.WINDOWS:   # a shebang script that dies by SIGABRT/SIGSEGV; UVR is not set up on Windows yet
        pytest.skip("fake audio-separator is a POSIX script")
    script = tmp_path / "fake-uvr"
    script.write_text(FAKE_UVR.format(python=sys.executable), encoding="utf-8")
    script.chmod(0o755)
    models = tmp_path / "models"
    models.mkdir()
    (models / "UVR-DeEcho-DeReverb.pth").write_bytes(b"x")
    calls = tmp_path / "uvr-calls.txt"
    monkeypatch.setenv("FAKE_UVR_CALLS", str(calls))
    return DereverbConfig(model_dir=models, separator=script), calls
