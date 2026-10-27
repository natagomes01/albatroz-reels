# Commands and external programs

> Reader: Natã and anyone auditing what the tool runs on the Mac. Style: reference plus short
> explanations. Every flag and path below was checked against the code or `--help` output on
> 29/09/2026 (branch `s2-analysis-review`). Citations are `file:line` from the repo root.
> Where something could not be checked, the text says "not verified".

## 1. How to read a command

**Terminal command.** A line you type in Terminal. The first word is the program to start; every
word after it is an **argument** handed to that program. In `uv run shorts doctor`, the program is
`uv` and its arguments are `run`, `shorts` and `doctor`.

**CLI (command-line interface).** A program you drive by typing commands instead of clicking.
`shorts`, `uv`, `claude`, `ffmpeg` and `rclone` are all CLIs.

**`uv`.** The Python project manager this repo uses (`/opt/homebrew/bin/uv`). It keeps a private
Python 3.12 and this project's libraries in the `.venv/` folder of the repo, so the tool never
depends on the Mac's own Python (the Mac's `/usr/bin/python3` is 3.9.6).

**`uv run <command>`.** Runs `<command>` inside that pinned environment. `uv sync` installs or
updates it; `uv run` checks it is in sync first. Run every `uv run` command from the repo folder
(`cd ~/dev/albatroz-shorts`), because that is how `uv` finds the project.

**`shorts`.** The program this repo builds. `pyproject.toml` declares it in `[project.scripts]` as
`shorts = "shorts.cli:main"`, which means "the `shorts` command calls the `main` function in
`src/shorts/cli.py`" (`src/shorts/cli.py:93`). It only exists inside the uv environment, so you
always type `uv run shorts ...`.

**Subcommand.** The second word that picks what `shorts` does: `doctor`, `ingest`, `analyze`, and
so on. Each has its own help: `uv run shorts ingest --help`.

**Flag (option).** An argument that starts with `--`. Some take a value (`--channel catholic-br`),
some are on/off switches (`--preview`). A **positional argument** has no `--` and is identified by
its place, like the `job` in `shorts analyze <job>`. `shorts` has two global flags, `--config` and
`--channels`, that go before the subcommand (`src/shorts/cli.py:76-77`); you normally never need
them.

**Quoting.** The shell splits a line at spaces. Quotes keep a value with spaces or special
characters in one piece: `--tools ""` passes one empty argument; `'mcp__*'` stops the shell from
treating `*` as a file-name pattern.

**stdin, stdout, stderr.** Every program has one input stream and two output streams. **stdin**
is what is fed in (the class transcript goes to `claude` this way). **stdout** is normal output
(the path of a finished render). **stderr** is for errors and warnings (every `error: ...` line
from `shorts`). In Terminal you see both outputs mixed together.

**Exit code.** A number a program returns when it ends. `0` means success; anything else means
failure. `shorts` uses `0` (ok), `1` (a render, ffmpeg or doctor failure) and `2` (a readable user
error such as an unknown job; `src/shorts/cli_jobs.py:50-52`). Type `echo $?` right after a
command to see its exit code.

**Environment variable.** A named setting the shell passes to every program it starts. Written
`NAME=value` in front of a command, it applies to that one command:
`SHORTS_SAMPLE=~/dev/albatroz-media/samples/amostra-10min.mov uv run pytest` tells the tests
where the sample is. Others the tool reads: `SHORTS_FFMPEG_DIR` (where ffmpeg-full lives,
`src/shorts/ffmpeg.py:11`) and `SHORTS_TRANSCREVE` (where `shorts doctor` looks for transcreve,
`src/shorts/doctor.py:14`).

**Path.** Where a file lives. `~` means your home folder (`/Users/<you>` on the Mac). `<job>` in this
documentation is a placeholder: replace it with the real job id, without the angle brackets.

### 1.1 What `claude -p` is and why the tool uses it

`claude` is the Claude Code command-line program (installed at `~/.npm-global/bin/claude`,
version 2.1.284 on 29/09/2026). Normally it is an interactive coding assistant. With `-p`
("print", also called **headless mode**) it does something much narrower: read one prompt from
stdin, answer once, print the answer, exit. The tool uses it as a function: **text in, JSON out**.
It is not a chat and keeps no conversation.

Why this and not the Anthropic API: `claude -p` runs on your Claude **Max plan** login, so the
analysis costs nothing extra and needs no API key (`src/shorts/llm/claude_cli.py:1-7`). The API
backends exist for later automation (section 2, `security`).

Two more passes use the same command since the caption context pass: the class sheet (`claude-haiku-4-5`) and the caption fixes (`claude-sonnet-5`), with prompts `prompts/class_sheet.md` and `prompts/caption_fix.md`.

The exact command, printed from `ClaudeCliBackend.build_cmd` (`src/shorts/llm/claude_cli.py:41-51`):

```
claude -p --model claude-haiku-4-5 --system-prompt '<prompt file text>' \
  --json-schema '<JSON schema>' --output-format json --tools '' \
  --setting-sources project --strict-mcp-config --disallowedTools 'mcp__*' \
  --no-session-persistence
```

| Flag | What it does | Why the tool sets it |
|---|---|---|
| `-p` | Headless: one prompt in, one answer out, then exit. | The tool needs a function call, not a chat. |
| `--model <m>` | Which Claude model answers. | Chosen per pass in `config.toml`: scan `claude-haiku-4-5`, detail `claude-opus-5-5`, both reviews `claude-sonnet-5` (`config.toml:15-26`). |
| `--system-prompt <text>` | Replaces Claude Code's own system prompt with this text. | The pass instructions come from `prompts/<pass>.md` (`src/shorts/analyze/prompts.py:9-11`). |
| `--json-schema <schema>` | The answer must match this JSON Schema (a description of the allowed shape). | The tool parses the answer as data; the validated object arrives in the `structured_output` field (`claude_cli.py:77`). The tool validates it again itself (`src/shorts/llm/base.py:68-79`). |
| `--output-format json` | Wraps the answer in a JSON envelope with `result`, `structured_output`, `usage` and `is_error`. | The tool reads token counts from `usage` and errors from `is_error` (`claude_cli.py:74-82`). |
| `--tools ""` | Disables every built-in tool (no Bash, no file reading or editing, no web). | The model can only write text. |
| `--setting-sources project` | Loads only "project" settings, skipping your user settings (`~/.claude/settings.json`) and local ones. | Your hooks, permissions and global `CLAUDE.md` do not reach the call. The call runs in an empty temporary folder, so there is no project setting to load either. |
| `--strict-mcp-config` | Uses only MCP servers given with `--mcp-config` (none here), ignoring all other MCP configuration. | No MCP server (Gmail, Drive, Notion and so on) is started. An MCP server is a plug-in that gives Claude extra tools. |
| `--disallowedTools "mcp__*"` | Denies every tool whose name starts with `mcp__`. | A second lock on the same door, in case an MCP tool loads anyway. |
| `--no-session-persistence` | The session is not saved to disk and cannot be resumed. | Class transcripts do not pile up in `~/.claude/projects`. |

What the tool deliberately does **not** do:

- **No `--bare`.** `claude --help` says `--bare` makes authentication "strictly
  ANTHROPIC_API_KEY or apiKeyHelper (OAuth and keychain are never read)". OAuth is how the Max
  plan login works, so `--bare` would break it (`claude_cli.py:6-7`).
- **A fresh, empty temporary folder as working directory** (`tempfile.mkdtemp(prefix="shorts-llm-")`,
  deleted afterwards; `claude_cli.py:57-69`). Claude Code reads `CLAUDE.md` and settings from the
  folder it runs in; an empty folder has none, and the model has no files near it.
- **`ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN` and `ANTHROPIC_BASE_URL` are removed** from the
  environment handed to `claude` (`claude_cli.py:25`, `53-54`). If a key were present, Claude
  Code would bill the API account instead of the Max plan.

**The isolation guarantee in plain words.** The class transcript travels to `claude` on stdin as
plain text. The model has no tool at all to call (`--tools ""`, no MCP servers), no settings or
hooks of yours, and no files around it. So even if a sentence in the class said "delete the
files" or "send an email", the model can only produce text, and the tool keeps that text only if
it fits the JSON schema. The transcript is data, never instructions the Mac executes. The
docstring records this as verified on Claude Code 2.1.284 on 29/09/2026 (`claude_cli.py:3-7`).

**Errors and retries.** Each call has a 900 s timeout (`claude_cli.py:39`). Failures are sorted
by their text (`claude_cli.py:22-34`): "usage limit", "limit reached", "hit your limit", "reached
your limit" or "quota" mean **limit** (stop; the rerun resumes from cache); "overloaded", "529",
"rate limit", "timeout", "network", "502", "503" mean **transient** (wait 2, 8, then 32 s and try
again, `src/shorts/llm/base.py:59-62`); anything else is **fatal**. An answer that does not match
the schema is retried up to 2 more times with the error appended (`base.py:72-79`).

### 1.2 What an LLM call costs, and where the number comes from

Nothing here is a bill. On the Max plan no invoice arrives; the tool records what each call would
cost at API list price, to judge limits and the cost of a full class.

- **`claude-cli`**: `claude -p --output-format json` returns `total_cost_usd`, computed by Claude
  Code at list price (`modelUsage.<model>.costBasis` is `"list"` whatever the plan), plus
  `usage` (input, cache write, cache read and output tokens, thinking tokens) and `duration_ms`,
  `duration_api_ms`. The tool keeps that cost as `cost_usd` (`src/shorts/llm/claude_cli.py`,
  `usage_from_envelope`). Every call carries Claude Code's own fixed overhead: a tiny test call
  on 30/09/2026 cost $0.0135 and wrote 6,648 cache tokens. Claude Code writes 1-hour cache
  entries; its envelope does not split them by duration, so the tool counts every cache write
  as a 1-hour write.
- **`anthropic-api`, `openai-compatible`**: these return tokens but no cost, so the cost is
  computed from `pricing.toml` at the repo root (`src/shorts/pricing.py`, `cost_from_usage`):
  USD per million tokens for input, output, cache write (5 minutes and 1 hour) and cache read per
  model, with `verified_on` and `source`. A model missing from the table gets no cost.
- **Cross-check**: for `claude-cli` the same table gives `cost_table_usd`. When it differs from
  the reported cost by more than 10%, the command prints once per backend
  `warning: <model>: reported cost $X and pricing.toml cost $Y differ by more than 10%; ...`
  (`src/shorts/llm/base.py`, `LLMBackend._cost`): the table is stale or the envelope changed.
- **Keeping `pricing.toml` right**: refill it from the official list
  (`https://platform.claude.com/docs/en/about-claude/pricing`) and update `verified_on`
  whenever Anthropic changes prices or `config.toml` gets a new model.
- Cost is computed on this machine from tokens and list prices; it does not depend on the region
  or account that served the call. Reports: `shorts cost` ([shorts-cli.md](../features/shorts-cli.md)).

## 2. Every external program the tool runs

"Triggered by" names the `shorts` subcommand. Durations are "not measured" unless a number was
measured and written down somewhere in the repo.

| Program | What for | Triggered by | Command shape | Code | Reads / writes | Typical time |
|---|---|---|---|---|---|---|
| `uv` | Runs `shorts` inside the project's Python 3.12 environment. | You, for every command. | `uv run shorts <subcommand> ...` | `pyproject.toml` `[project.scripts]` | Reads `pyproject.toml`, `uv.lock`, `.venv/`. | Under a second when in sync (not measured). |
| `claude` | The LLM passes (scan, detail, two reviews, class sheet, caption fixes). | `analyze`, `fixwords`, and `run` when analyze is next. `doctor` runs `claude --version`. | Section 1.1. | `src/shorts/llm/claude_cli.py:41-83`; version check `src/shorts/doctor_jobs.py:17` | stdin: prompt text. stdout: JSON envelope. Writes nothing itself; the tool caches each answer in `jobs/<job>/analyze/cache/` (including `analyze/cache/class_sheet/` and `analyze/cache/wordfix/`). | Not measured. |
| `ffmpeg` (ffmpeg-full) | Every audio and video operation of `shorts` itself (section 3). | `clip`, `track`, `captions`, `render`, `run`, `doctor`. | `/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg ...` | `src/shorts/ffmpeg.py:11-13`, runner `ffmpeg.py:31-40` | Reads the master. Writes only the render `.mp4` and the track preview. | Section 3. |
| `ffprobe` (ffmpeg-full) | Reads a file's size, frame rate, duration, colour transfer and audio presence. | `ingest`, `clip`, and every stage (`probe()` at the start of each clip). | `ffprobe -v error -print_format json -show_streams -show_format <file>` | `src/shorts/ffmpeg.py:93-98` | Reads the file header only. | Under a second (not measured). |
| `python3` + `transcreve.py` | Word-level transcription of the master. | `ingest`. `doctor` also runs `python3 <transcreve.py> --help` to look for `--palavras`. | `/usr/bin/python3 ~/dev/transcreve/transcreve.py <master> --palavras --idioma <lang> --saida jobs/<job> [--prompt "<glossary>"]` | `src/shorts/ingest.py:95-108`; doctor `src/shorts/doctor.py:57-61` | Reads the master. Writes `<stem>.palavras.json` and `<stem>.md` into `jobs/<job>/`; the tool then renames the first to `words.json`. | 87 s per 10 min of audio, 1.9 GB peak memory (spec 5, measured 28/09/2026). |
| `ffmpeg` (plain Homebrew, inside transcreve) | Extracts the audio as 16 kHz mono WAV for whisper. | `ingest` (through transcreve). | `ffmpeg -y -loglevel error -i <master> -vn -ac 1 -ar 16000 -c:a pcm_s16le <tmp>/audio.wav` | `~/dev/transcreve/transcreve.py:121-128` | Temporary WAV, deleted when transcreve ends. | Included in the 87 s above. |
| `whisper-cli` (whisper.cpp) | Speech to text with a time for every word. | `ingest` (through transcreve). `doctor` checks it is on PATH. | `whisper-cli -m ~/.cache/whisper-models/ggml-large-v3-turbo.bin -f audio.wav -l <lang> --prompt <glossary> -sns -np -ml 60 -sow -osrt -nfa -ojf -dtw large.v3.turbo -of <tmp>/<stem>` | `~/dev/transcreve/transcreve.py:154-186`; doctor `src/shorts/doctor.py:49-54` | Reads the WAV and the model. Writes `.srt` and `.json` in a temp folder. | Included in the 87 s above. |
| Apple Vision | Finds the person's body and face in each sampled frame. | `track` (and `captions`/`render` when the tracking is not fresh), `clip`. | Not a command: a macOS framework called in-process through the `pyobjc-framework-Vision` Python bindings. | `src/shorts/vision.py:98-122` | Receives one 640 px frame at a time from ffmpeg (section 3.2). Keeps nothing; the tool writes `track.json`. | Not measured. |
| `security` | Reads an API key from the macOS Keychain. **Only** for the optional `anthropic-api` and `openai-compatible` backends; the default `claude-cli` never uses it. | `analyze` with an API backend; `doctor` when such a backend is configured. | `security find-generic-password -s <service> -w` (read the secret); doctor runs the same without `-w` (only checks it exists). | `src/shorts/keychain.py:12-19`; `src/shorts/doctor_jobs.py:21-28` | Reads one Keychain item. | Not measured. |
| `audio-separator` (UVR) | Removes room reverb from the voice (UVR-DeEcho-DeReverb). | `render`, `clip --dereverb N`, `excerpt`, the review page's audio panel, and `analyze` (it makes the excerpts at its end). `doctor` runs `--version`. | `audio-separator <in.wav> --model_filename UVR-DeEcho-DeReverb.pth --model_file_dir <models> --output_dir <tmp> --output_format WAV --vr_aggression <N> --single_stem "No Reverb"` | `src/shorts/dereverb.py:102-137` (`run_separator`); doctor `src/shorts/doctor_jobs.py` | Reads a padded WAV window; writes one WAV, trimmed and cached in `<media_root>/cache/<job>/audio/`. Retries up to 3 times on exit -6 or -11. | About 22 s for a 30 s clip at strength 20 (753 MB resident); 10.5 s from cache. About 3.3 GB peak while the model runs. |
| `rclone` | One-way copy of renders (optionally masters) to Google Drive. | `backup`; `render` when `backup.auto = true` (it is `false` in `config.toml:12`); `doctor` runs `rclone listremotes` when auto is on. | `rclone copy <media_root>/renders/<channel>/<job> gdrive:albatroz-media-backup/renders/<channel>/<job> --exclude '*.tmp.mp4' --exclude '*.tmp' --exclude '*.key'` plus `--dry-run -v` with `--dry-run`. | `src/shorts/backup.py:8-32` | Reads renders; writes to Drive only. **Always `copy`, never `sync`**: the code asserts it (`backup.py:30`), because `sync` deletes on the destination. | Not measured. rclone is **not installed** on 29/09/2026. |
| Web browser | Shows the review page. | `review` (unless `--no-browser`). | Python's `webbrowser.open("http://127.0.0.1:8765/")` opens your default browser. | `src/shorts/review/server.py:187-193` | Talks only to the local server on 127.0.0.1. | Not measured. |
| `git` | Not run by `shorts`. Git runs the repo's pre-commit hook when *you* commit: it blocks media files and files over 5 MB. | Your `git commit`, not the tool. | `scripts/hooks/pre-commit`, active because `core.hooksPath=scripts/hooks` (set by `scripts/install-hooks.sh`). | `scripts/hooks/pre-commit` | Reads the staged file list. | Not measured. |

Why `ffmpeg-full` and not the plain Homebrew `ffmpeg`: the plain build has no **libass**, the
library behind the `subtitles` filter that burns in the captions (CLAUDE.md). `shorts doctor`
checks that ffmpeg-full has `subtitles`, `h264_videotoolbox` and `zscale`
(`src/shorts/doctor.py:35-46`). The code never calls a bare `ffmpeg`; it always uses the full
path in `FFMPEG` (`src/shorts/ffmpeg.py:12`). transcreve is a separate project and uses whatever
`ffmpeg` is first on PATH (`/opt/homebrew/bin/ffmpeg` on this Mac,
`~/dev/transcreve/transcreve.py:73-77`); it only extracts audio, which needs no libass.

## 3. The distinct ffmpeg invocations

All of them map only the first video and first audio stream (`0:v:0`, `0:a:0`): iPhone `.mov`
masters carry extra QuickTime "data" streams that would otherwise break the command
(CLAUDE.md, `src/shorts/ffmpeg.py:66-68`). Command shapes below were printed from the real
builder functions with fake inputs on 29/09/2026.

Common flags: `-y` overwrite the output, `-hide_banner` and `-nostats` keep stderr short,
`-v error` print only errors, `-ss <t>` seek to time t before reading, `-t <d>` read d seconds,
`-to <t>` stop at time t, `-i <file>` the input, `-f null -` decode and throw the result away,
`-f rawvideo ... -` send raw pixels to stdout for Python to read.

### 3.1 Silence detection

`ffmpeg -hide_banner -nostats -ss <start> -t <dur> -i <master> -map 0:a:0 -af silencedetect=noise=-35dB:d=0.3 -f null -`
(`src/shorts/silence.py:35-42`, once per clip segment, at the start of every clip stage in
`src/shorts/clip.py:233-235`).

- **What it does:** listens to the segment and prints every stretch quieter than -35 dB lasting at
  least 0.3 s. The tool then shortens each pause of 0.8 s or more to 0.5 s (0.8 s after a `?` or
  `!`) to build the **EDL** (edit decision list: which pieces of time are kept;
  `src/shorts/timeline.py:27-35`).
- `silencedetect`: the ffmpeg audio filter that reports silent stretches on stderr.

### 3.2 Frame sampling for Apple Vision

`ffmpeg -v error -ss 78.900 -t 22.300 -i <master> -map 0:v:0 -vf fps=3.0,scale=640:360 -f rawvideo -pix_fmt bgra -`
(`src/shorts/vision.py:38-54`, run once per segment of each approved clip by `track`).

- **What it does:** decodes the segment at 3 frames per second, shrinks each frame to 640 px wide,
  and streams raw pixels to Python. Python reads exactly one frame (640 x 360 x 4 bytes) at a
  time and hands it to Vision (`vision.py:57-85`), so a clip is never held in memory.
- `fps=3.0`: keep 3 frames per second. `scale=640:360`: resize. `bgra`: the pixel layout Vision
  reads. For an HDR master, `HDR_TO_SDR` is appended (`src/shorts/ffmpeg.py:18-21`: `zscale`
  converts the colour space, `tonemap=hable` compresses HDR brightness into SDR).

### 3.3 Colour measurement

`ffmpeg -v error -ss 0.000 -i <master> -t 10 -map 0:v:0 -vf fps=0.5,scale=64:36:in_color_matrix=bt709,format=rgb24 -frames:v 5 -f rawvideo -pix_fmt rgb24 -`
(`src/shorts/color.py:55-64`; `measure_points` runs it once every 600 s of the class,
`color.py:72-77`; once per job, cached in `jobs/<job>/color.json` by
`src/shorts/stages.py:70-78`).

- **What it does:** takes 5 tiny 64 x 36 frames from a 10 s stretch; the tool computes levels,
  grey-world white balance and a gamma from their pixels. For the 600.07 s sample that is 2 points
  (at 0 s and 590.07 s).
- `fps=0.5`: one frame every 2 s. `in_color_matrix=bt709`: read colours with the HD standard
  matrix. `rgb24`: plain 8-bit red, green, blue.

### 3.4 Loudness measurement (first loudnorm pass)

`ffmpeg -hide_banner -nostats -ss <a> -to <b> -i <master> -filter_complex "[0:a:0]aselect='<kept spans>',asetpts=N/SR/TB[a0];[a0]concat=n=1:v=0:a=1,highpass=f=70,afftdn=nr=6:nf=-45,loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json[out]" -map [out] -f null -`
(`src/shorts/audio.py:45-63`, once per clip at render).

- **What it does:** measures how loud the kept audio is, after the same cleanup the render will
  apply, and prints the numbers as JSON. The render uses them for an exact, linear correction.
- `aselect`: keep only the EDL spans. `asetpts`: re-time the kept audio so it is continuous.
  `highpass=f=70`: removes rumble below 70 Hz. `afftdn`: gentle noise reduction.
  `loudnorm`: EBU R128 loudness normalisation to -14 LUFS integrated, -1.5 dB true peak
  (`audio.py:11-12`).

### 3.5 The single-pass render

The command, printed from `render.build_render` (`src/shorts/render.py:82-171`):

```
/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg -y -hide_banner -nostats \
  -ss 78.900 -to 82.000 -i <master> \
  -/filter_complex <clip work dir>/graph.txt -map '[v]' -map '[a]' \
  -c:a aac -b:a 160k -ar 48000 \
  -c:v h264_videotoolbox -b:v 10M -maxrate 14M -bufsize 20M -profile:v high -pix_fmt yuv420p \
  -color_primaries bt709 -color_trc bt709 -colorspace bt709 \
  -r 30 -frames:v <frame count> -movflags +faststart <out>.mp4.tmp.mp4
```

One `-ss/-to/-i` group per clip segment (a clip has 1 to 3), plus `-loop 1 -i assets/safe-zone.png`
with `--safe-zone`. `-/filter_complex <file>` reads the filter graph from a file (ffmpeg 9
syntax). The output goes to `<out>.tmp.mp4` and replaces the real file only on success
(`render.py:174-184`), so a failed or interrupted render never leaves a half file.

**What it does, in the order of the filter graph** (example graph from the builder):

1. `fps=30,select='gte(t,..)*lt(t,..)+...',setpts=N/FRAME_RATE/TB`: force 30 fps, keep only the
   EDL spans (the silence cut), re-time the kept frames. `aselect`/`asetpts` do the same for
   audio.
2. `concat`: joins the segments in playback order (only when there are 2 or 3).
3. `sendcmd=f='crop.cmd'`: reads a file of timed commands that move the crop window frame by
   frame (docs/decisions/0001). `split=2`: two copies, one for the wide shot and one for the
   close-up.
4. `crop@wide=w=608:h=1080` and `crop@close=w=434:h=772` (standing): cut the 9:16 window out of the
   1920 x 1080 frame. The grade follows: `scale=in_color_matrix=bt709...,format=gbrp,colorlevels=...,
   ...,eq=gamma=...:saturation=1.05` (`src/shorts/color.py:95-104`; `colorlevels` sets black and
   white points per channel, `eq` sets gamma and a 5% saturation lift).
5. `scale=1080:1920:flags=lanczos,setsar=1`: enlarge to 1080 x 1920 with the Lanczos resampler;
   square pixels.
6. `overlay=enable='gte(t,..)*lt(t,..)'`: show the close-up copy over the wide one only during
   close-up shots.
7. `subtitles=filename='captions.ass':fontsdir='assets/fonts'`: burns in the captions (libass,
   Anton font). The folder also holds Raleway and IBM Plex Mono for the review page;
   libass loads them too, and `tests/test_fonts_dir.py` proves the caption frame is unchanged.
8. With `--safe-zone`: `format=rgba,geq=...` keeps only the orange area of the template, half
   transparent, and `overlay` puts it on top (`render.py:16-19`).
9. Audio: `highpass,afftdn,loudnorm=...:measured_I=...:linear=true,aresample=48000`, the second
   loudness pass using 3.4's numbers.

**Encoder settings** (`render.py:163-170`): video H.264 by `h264_videotoolbox` (the Mac's hardware
encoder), 10 Mbit/s average, 14 Mbit/s peak, High profile, yuv420p, tagged bt709, 30 fps,
`+faststart` (index at the file start, so players start before the whole file loads). Audio AAC
160 kbit/s, 48 kHz. The spec expects a 60 s clip near 75 MB (spec 10.5).

Typical time: not measured for S2 renders. The spec records that an early 22 s preview rendered
in 5.3 s (spec 10.5).

### 3.6 Track preview

`ffmpeg -y -hide_banner -nostats -ss <a> -to <b> -i <master> -/filter_complex <clip dir>/track-preview.graph.txt -map [v] -an -c:v h264_videotoolbox -b:v 2M -frames:v <n> <clip dir>/track-preview.mp4.tmp.mp4`
(`src/shorts/preview.py:42-84`, only with `shorts track <job> --preview`).

- **What it does:** a small 640 px wide, silent video of the source frames with the crop window
  drawn as a lime rectangle and the tracked body as a red rectangle. Use it to judge the tracking
  before spending time on a full render.
- `drawbox@crop`, `drawbox@body`: draw the rectangles; `sendcmd` moves them per frame.
  `scale=640:-2`: 640 px wide, height to match. `-an`: no audio.

### 3.7 Environment checks

`shorts doctor` runs `ffmpeg -hide_banner -filters` and `ffmpeg -hide_banner -encoders` and looks
for `subtitles`, `zscale` and `h264_videotoolbox` in the lists (`src/shorts/doctor.py:38-46`).

## 4. What each `shorts` subcommand runs, in order

| Subcommand | Internal steps | External programs |
|---|---|---|
| `doctor` | Checks ffmpeg-full and its filters, whisper-cli and model, transcreve `--palavras`, Anton font, safe-zone template, media root writable, disk space, then `claude --version`, Keychain items for API backends, rclone remote if `backup.auto` (`src/shorts/doctor.py:94-105`, `src/shorts/doctor_jobs.py:11-37`). | `ffmpeg` x2, `python3 transcreve.py --help`, `claude --version`; `security` and `rclone listremotes` only when configured. |
| `ingest` | Check format, derive the job id, move the master into `masters/` if it is elsewhere, probe it, create `job.json`, transcribe, rename the words file to `words.json` (`src/shorts/ingest.py:74-109`). | `ffprobe`; `python3 transcreve.py` (which runs `ffmpeg` and `whisper-cli`). |
| `analyze` | Refuse if `review.json` holds decisions (unless `--force`), build 120 s windows, scan pass (batches of 10 windows), keep scores of 60 or more (at most 40), detail pass (one call per kept window), give stable ids, blind and faithful reviews (batches of 5), remove near-duplicates, group by hook, write `candidates.json` (`src/shorts/analyze/run.py:54-92`), then the caption fixes (the `fixwords` steps below; a failure there is only a warning). | `claude -p` once per uncached call. Nothing else. |
| `fixwords` | Load raw words, cut 500-word chunks (100 overlap) at sentence ends, keep the chunks within 60 s of a candidate or edited segment (all with `--all`), class sheet over the whole transcript in parts of 6,000 words, one caption-fix call per chunk, validate every edit in code, resolve overlaps, write `class_sheet.json` and `corrections.json`. | `claude -p` once per uncached call. Nothing else. |
| `review` | Starts a local web server on 127.0.0.1 (default port 8765), opens the page, serves the master for playback, saves every click to `review.json` (`src/shorts/review/server.py:187-199`). | Your browser. |
| `track` | For each approved clip: silence detection, EDL, Vision tracking (reused if fresh), smoothing, shot plan, crop windows; `--preview` also renders the preview (`src/shorts/clip.py:215-300`). | `ffprobe`, `ffmpeg` (silencedetect, frame sampling), Apple Vision; `ffmpeg` preview with `--preview`. |
| `captions` | Everything `track` does (Vision reused when fresh), then writes `captions.ass` (`clip.py:302-310`). | `ffprobe`, `ffmpeg` silencedetect; Vision only if the tracking is stale. |
| `render` | Colour measured once per job, then per approved clip: skip if fresh, else track, captions, loudness pass, render, write `<clip>.json` and the freshness key (`src/shorts/stages.py:146-214`). Backup afterwards when `backup.auto = true`. | `ffprobe`, `ffmpeg` (colour, silencedetect, loudnorm, render), Vision if stale; `rclone` if auto backup. |
| `run` | Works out the next stage (`src/shorts/stages.py:223-253`): `analyze` runs analyze; `review` prints a hint; `render` runs render; `done` prints that all approved clips are rendered (`src/shorts/cli_jobs.py:141-156`). | Whatever that stage runs. |
| `backup` | Builds one or two `rclone copy` commands and runs them (`src/shorts/backup.py:8-32`). | `rclone`. |
| `clean` | Deletes the `.mp4`, `.json` and `.key` of **rejected** clips inside `renders/<channel>/<job>/` only (`src/shorts/clean.py:18-41`). | None. |
| `clip` | The S1 manual path: one segment from `--from`/`--to`, same `produce()` as the stages (`src/shorts/clip.py:329-366`). | Same as `render`, colour measured per clip. |
