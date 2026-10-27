# Set up a new machine (macOS or Windows)

One codebase for both systems. `src/shorts/machine.py` finds out at run time which one it is on and
picks the defaults; the same `pip install -e .` (or `uv sync`) installs the right packages on each
(the platform markers in `pyproject.toml`).

| | macOS (the M1) | Windows (the PC, since 23/10/2026) |
|---|---|---|
| person and face detection | Apple Vision (pyobjc) | YuNet + YOLOX-S in ONNX (opencv, onnxruntime) |
| H.264 encoder | `h264_videotoolbox` | `libx264`, crf 19 (`h264_nvenc` only by `SHORTS_ENCODER`) |
| ffmpeg | `/opt/homebrew/opt/ffmpeg-full/bin` | the one on PATH |
| secrets | Keychain (`security`) | Windows Credential Manager (`keyring`) |
| paths | top of `config.toml` | `[platform.win32]` in `config.toml` |

`SHORTS_FFMPEG_DIR`, `SHORTS_DETECTOR` (`vision` or `onnx`), `SHORTS_ENCODER` and `SHORTS_MODELS_DIR`
override those defaults on either system.

Each step is followed by the command that checks it. Last updated 23/10/2026. Part A is the Mac,
Part B is Windows; sections 6 and 7 (B-roll keys, final check) are for both.

# Part A: macOS

## 1. Homebrew tools

```
brew install uv ffmpeg-full whisper-cpp git-lfs rclone
```

Check: `uv --version` and `/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg -hide_banner -filters | grep subtitles`
(the second must list the `subtitles` filter, which needs libass).

## 2. The repo

```
git clone https://github.com/natagomes01/albatroz-reels.git ~/dev/albatroz-reels
cd ~/dev/albatroz-reels
uv sync
sh scripts/install-hooks.sh
```

Check: `uv run pytest -q`.

## 3. Media root

```
mkdir -p ~/dev/albatroz-media/{renders,samples,models}
```

Check: `media_root` in `config.toml` points at that folder (default `~/dev/albatroz-media`).

## 4. Transcription

Put transcreve at `~/dev/transcreve/transcreve.py` and the whisper model where `shorts doctor`
names it. Check: `uv run shorts doctor` shows the transcreve and whisper lines `[ok  ]`.

## 5. Dereverb (UVR)

```
uv tool install --python 3.12 "audio-separator[cpu]==0.47.0" \
  --with audioread --with standard-aifc --with standard-sunau
```

Check: `~/.local/bin/audio-separator --version` prints `audio-separator 0.47.0` and exits 0.

Model: copy `UVR-DeEcho-DeReverb.pth` (213 MB) and `vr_model_data.json` into
`~/dev/albatroz-media/models/` from the Drive backup, or let the first `shorts excerpt <job>`
download them (needs network once). Check: `ls -la ~/dev/albatroz-media/models/`.

Offline check (once, by the owner): turn Wi-Fi off, run `uv run shorts excerpt <job>` on any
analysed job; it must finish. If it fails asking for the network, note the file it wanted, copy it
into the model folder, and record it here.

UVR sometimes crashes at exit (exit -6 or -11, or a non-zero exit after "Separation complete"); the tool retries only those crashes, up to 3 attempts, and never keeps output from a run that exited non-zero. Do not run `shorts render` or `shorts analyze` in a terminal while the review page prepares an excerpt: two UVR processes at once need about 6.6 GB.

Footprint measured on 01/10/2026: tool env about 1.0 GB, model 213 MB, about 3.3 GB peak memory
while it runs.

# Part B: Windows

Tested on Windows 10 Pro 19045 (Ryzen 5 5600X, 32 GB, GTX 1060 6GB) on 23/10/2026. Everything lives
under `C:\albatroz`: repos in `C:\albatroz\dev`, programs in `C:\albatroz\programs`, media in
`C:\albatroz\media`. If you prefer another drive or folder, change the commands and `[platform.win32]` in `config.toml` the same way.

Run the commands in **PowerShell as administrator**, one block at a time. You need Git and Python
3.13 first (on Windows the command is `python`; `python3` opens the Microsoft Store).

## B1. ffmpeg

```powershell
winget install --id Gyan.FFmpeg -e --scope machine --location C:\albatroz\programs\ffmpeg --accept-package-agreements --accept-source-agreements
```

Gyan's full build (9.0.2 on 23/10/2026) brings ffprobe, libass (captions), zscale (iPhone HDR to
SDR), libx264 and nvenc. winget links `ffmpeg.exe` and `ffprobe.exe` in
`C:\Program Files\WinGet\Links`, which is on PATH. If ffmpeg is somewhere else, set
`SHORTS_FFMPEG_DIR` to its folder.

Check, in a new PowerShell: `ffmpeg -hide_banner -filters | Select-String ' subtitles | zscale '`
lists both filters.

## B2. whisper.cpp

No winget package: it is the zip of the official release (build `b5454`, whisper.cpp 1.9.5, CPU with
OpenBLAS).

```powershell
Invoke-WebRequest https://github.com/ggml-org/whisper.cpp/releases/download/b5454/whisper-blas-bin-x64.zip -OutFile $env:TEMP\whisper-cpu.zip; Expand-Archive $env:TEMP\whisper-cpu.zip C:\albatroz\programs\whisper-cpp\cpu -Force
```

That leaves `C:\albatroz\programs\whisper-cpp\cpu\Release\whisper-cli.exe`. The CUDA build
(`whisper-bin-win-cuda-11.8.0-x64.zip`) is optional and stays **off PATH**: the GTX 1060 shut the
PC down twice on 19/10/2026, so the GPU only runs in a supervised test.

## B3. Whisper model

`ggml-large-v3-turbo.bin` (1.6 GB) lives in `C:\albatroz\programs\whisper-models`:

```powershell
New-Item -ItemType Directory -Force C:\albatroz\programs\whisper-models; Invoke-WebRequest https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3-turbo.bin -OutFile C:\albatroz\programs\whisper-models\ggml-large-v3-turbo.bin
```

## B4. PATH and the model variable

```powershell
$p=[Environment]::GetEnvironmentVariable('Path','Machine'); foreach($d in 'C:\albatroz\programs\whisper-cpp\cpu\Release'){ if(($p -split ';') -notcontains $d){$p="$p;$d"} }; [Environment]::SetEnvironmentVariable('Path',$p,'Machine')
```

```powershell
[Environment]::SetEnvironmentVariable('WHISPER_MODELOS','C:\albatroz\programs\whisper-models','Machine')
```

`WHISPER_MODELOS` tells `shorts doctor` where the model is. transcreve from GitHub (B5) still looks
in `%USERPROFILE%\.cache\whisper-models`, so link that folder to the real one instead of downloading
1.6 GB onto C: (once; it fails if the folder already exists):

```powershell
New-Item -ItemType Directory -Force $env:USERPROFILE\.cache; cmd /c mklink /J "$env:USERPROFILE\.cache\whisper-models" C:\albatroz\programs\whisper-models
```

Check, in a new PowerShell: `whisper-cli --version`.

## B5. transcreve

`shorts ingest` runs transcreve with `--palavras` (one timestamp per word). It is public and uses
only the Python standard library:

```powershell
git clone https://github.com/natagomes01/transcreve.git C:\albatroz\dev\transcreve
```

Its `install.sh` is for the Mac; on Windows the clone is all it needs, since ffmpeg and whisper-cli
come from B1 and B2. `[platform.win32.transcreve]` in `config.toml` points at
`C:/albatroz/dev/transcreve/transcreve.py` and runs it with `python`.

## B6. The repo

```powershell
git clone https://github.com/natagomes01/albatroz-reels.git C:\albatroz\dev\albatroz-reels
```

```powershell
python -m pip install -e C:\albatroz\dev\albatroz-reels pytest
```

On Windows this adds opencv-python-headless, onnxruntime, numpy and keyring to jsonschema, anthropic
and openai, and puts `shorts` in `C:\albatroz\programs\Python313\Scripts`. `uv sync` works too. The
pre-commit media guard needs Git Bash: `bash scripts/install-hooks.sh`. The review page opens with
`scripts\review.cmd` (the twin of `review.command`).

Check, from `C:\albatroz\dev\albatroz-reels`: `python -m pytest -q`. What the machine cannot run is skipped:
Apple Vision on Windows, and the fake UVR, which is a POSIX script.

## B7. Media root

```powershell
New-Item -ItemType Directory -Force C:\albatroz\media\renders, C:\albatroz\media\samples, C:\albatroz\media\models
```

Check: `media_root` in `[platform.win32]` of `config.toml` names that folder.

## B8. Detection models (YuNet and YOLOX-S)

The first `shorts track` downloads both, checks their sha256 and keeps them out of the repo, in
`%LOCALAPPDATA%\albatroz-shorts\models` (or `SHORTS_MODELS_DIR`). A file with the wrong hash is an
error, never a silent download: delete it to fetch it again. To place them by hand on an offline
machine:

| file | download | sha256 |
|---|---|---|
| `face_detection_yunet_2023mar.onnx` (227 KB, MIT) | `https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx` | `8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4` |
| `yolox_s.onnx` (34 MB, Apache-2.0) | `https://github.com/Megvii-BaseDetection/YOLOX/releases/download/0.1.1rc0/yolox_s.onnx` | `c5c2d13e59ae883e6af3b45daea64af4833a4951c92d116ec270d9ddbe998063` |

Check: `shorts doctor` shows `detector models` as ok. Measured on 23/10/2026 on the sample class
(1080p, frames at 640x360): about 100 ms per frame on the Ryzen CPU, at 3 frames per second of video.

## B9. Encoder

Nothing to install: renders use `libx264` (crf 19, preset medium). `h264_nvenc` exists in Gyan's
build but only runs when asked for, and only with someone watching the GPU temperature:

```powershell
$env:SHORTS_ENCODER='h264_nvenc'
```

The detector enters the track key and the encoder the render key, so switching either one re-tracks
or re-renders. The Mac's own choices keep the keys it always had.

## B10. Secrets

Windows keeps API keys in the Credential Manager through keyring instead of the Keychain. The user
is your Windows login (`$env:USERNAME`); the command asks for the key, so it stays out of the shell
history:

```powershell
python -m keyring set anthropic-api $env:USERNAME
```

Only the backends you use need one (`anthropic-api` for `backend = "anthropic-api"`; the default
`claude-cli` needs none). B-roll keys: section 6.

## B11. Dereverb (UVR) on Windows

UVR gets its own Python environment on E: (about 1.2 GB with torch for CPU), apart from the repo's,
so its pins never meet the repo's packages:

```powershell
python -m venv C:\albatroz\programs\audio-separator
```

```powershell
C:\albatroz\programs\audio-separator\Scripts\python -m pip install "audio-separator[cpu]==0.47.0" audioread standard-aifc standard-sunau
```

`[platform.win32.dereverb]` in `config.toml` points `separator` at
`C:/albatroz/programs/audio-separator/Scripts/audio-separator.exe` and `model_dir` at
`C:\albatroz\media\models`. The model (`UVR-DeEcho-DeReverb.pth`, 213 MB, and
`vr_model_data.json`) comes from the Mac's model folder or the Drive backup, as in section 5.

Check: `C:\albatroz\programs\audio-separator\Scripts\audio-separator.exe --version` prints
`audio-separator 0.47.0`, and `shorts doctor` shows `UVR (audio-separator)` and `UVR model` as ok.
Measured on 23/10/2026: 20 s of class audio in 25 s on the CPU (strength 20). The tests' fake UVR
is a POSIX script, so the dereverb tests are skipped on Windows; this real run is the check.

# Both systems

## 6. B-roll keys

B-roll searches Wikimedia Commons with no key. Pixabay needs a free key; without it the search
uses Commons and your own files only, and `shorts doctor` shows a warning. Pexels no longer issues
API keys, so doctor does not warn about it (a `pexels-api` Keychain entry, if one exists, still works).

- Pexels: create an account at pexels.com, open pexels.com/api, click `Your API Key`, give the
  project a name and a one-line reason; the key shows at once (200 searches per hour).
- Pixabay: create an account at pixabay.com, open pixabay.com/api/docs while logged in; the key is
  in the `Parameters` section (100 searches per minute).

Store both in the Keychain (the `-w` without a value asks for the key, so it stays out of the
shell history):

```
security add-generic-password -s pexels-api -a shorts -w
security add-generic-password -s pixabay-api -a shorts -w
```

Check: `security find-generic-password -s pexels-api` and `-s pixabay-api` each exit 0.

On Windows the keys go to the Credential Manager through keyring (the command asks for the key):

```powershell
python -m keyring set pixabay-api $env:USERNAME
```

Check: `shorts doctor` shows `Keychain: pixabay-api` as ok.

Commons asks every client for a contact: set `[broll] user_agent` in `config.toml`, for example
`albatroz-shorts (your e-mail)`. Check: `uv run shorts doctor` shows `B-roll User-Agent` as ok.

## 7. Final check

`uv run shorts doctor` with every required line `[ok  ]`, including `UVR (audio-separator)` and
`UVR model`. On Windows, `shorts doctor` in a new PowerShell. Doctor checks what the system it runs
on uses: ffmpeg and ffprobe with libass, zscale and this machine's encoder; whisper-cli and the
model; transcreve; the detector (Apple Vision on the Mac, the ONNX pair and its models on Windows);
the secret store.
