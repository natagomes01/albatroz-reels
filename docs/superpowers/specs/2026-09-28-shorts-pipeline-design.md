# albatroz-shorts: long-form class to vertical Shorts pipeline

> Design spec | 2026-09-28, revised 2026-09-29 after Natã's review | Author: Natã Gomes, with Claude | Status: in review
> Sub-project 1 of 4. The other three get their own specs and are only outlined in section 2.

## 1. Goal

Turn a long recorded video (10 min to 2 h, fixed camera) into vertical 1080x1920 Shorts ready for
YouTube Shorts, Instagram Reels and TikTok, with Natã deciding what becomes a clip.

The pipeline runs natively on a MacBook M1 with 8 GB: Python, ffmpeg and Apple frameworks, no Docker,
one clip at a time, low memory.

It serves three channels from day one, each with its own ICP and audience:

| Channel id    | Content language | Topic                                |
| ------------- | ---------------- | ------------------------------------ |
| `catholic-br` | pt-BR            | Catholic formation, apologetics      |
| `ai-en`       | en               | automation and AI                    |
| `ai-br`       | pt-BR            | automation and AI                    |

**Language rule.** Code, identifiers, config keys, specs, plans, prompt instructions and repo docs
are in English. Video content (transcript, captions, titles, hooks, attribution text) is in the
channel's content language.

**Recording formats.** Every job declares one:

| Format          | Phase | Frame                                   |
| --------------- | ----- | --------------------------------------- |
| `solo-standing` | 1a    | one speaker, full body, walks around    |
| `solo-seated`   | 1a    | one speaker, waist up, facing camera    |
| `conversation`  | 1b    | two or more people (interview, podcast) |

The camera logic (tracking, wide/close-up cuts) is the same across formats; only the defaults
change (section 8).

**Phase 1a success:** from one class, Natã gets a list of scored, justified candidates, approves the
ones he wants, and gets rendered Shorts with framing, captions, color and sound handled, without
opening a video editor.

## 2. Context: the four sub-projects

| #   | Sub-project                                                                                   | Repo                         | Depends on                    |
| --- | --------------------------------------------------------------------------------------------- | ---------------------------- | ----------------------------- |
| 0   | `transcreve --palavras`: JSON with per-word timing                                            | `transcreve/` (public, MIT)  | nothing                       |
| 1   | **This one.** Shorts pipeline: analyze, review, frame, caption, render (+ B-roll in phase 2)  | `albatroz-shorts/` (private) | 0                             |
| 2   | Multi-brand CMO: folder per brand, posting to YT/IG/TikTok, metrics and comments, self-study  | `attentionagent_framework/`  | output of 1 + API approvals   |
| 3   | Metrics dashboard: responsive React, subdomain behind Cloudflare Access                       | new, private                 | data from 2                   |

Sub-project 0 is small and a prerequisite, so it goes into this spec's plan; its contract is in
section 5. The API approval runbook already exists at
`attentionagent_framework/automation/post/RUNBOOK-aprovacao-apis.md`.

## 3. Decisions closed during brainstorming

- **Port, don't import.** Useful algorithms from `mutonby/openshorts` (MIT) are copied and adapted,
  credited in `THIRD_PARTY.md`. No third-party repo becomes a dependency. openshorts targets Docker
  and NVIDIA GPUs; none of it runs as-is on the M1.
- **`yukitorido/short-video-generator-AI` is malware** (XOR loader that `exec`s a payload on import,
  bought stars). Never clone it, never cite it as a source.
- **Channel profile lives in attentionagent**, in the brand folder. This repo only reads it. One
  source of truth, no drift, and what sub-project 2's self-study learns reaches the next analysis.
- **Review page is local only** (`localhost`). Never opened on the phone. What goes to the phone is
  sub-project 3's dashboard.
- **Preferred input is the camera master.** The YouTube download (720p, 815 kb/s) is fine for
  development and tests; in production it raises a quality warning (10.1).
- **Media lives outside both repos**, in one shared media root (4.4). No clones, no copies.
- **Spec and plan follow the superpowers layout** (`docs/superpowers/specs|plans`).

## 4. Architecture

Python 3.12 via `uv`. Dependencies: `anthropic`, `openai` (for OpenAI-compatible backends),
`pyobjc-framework-Vision` (pulls `Quartz`), `pytest`. Review page on stdlib `http.server`. Video via
Homebrew **`ffmpeg-full`** (keg-only, `/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg`), required: the
regular Homebrew `ffmpeg` has no libass, and without libass there are no ASS captions.

### 4.1 CLI

```
shorts doctor                              check the environment (11)
shorts ingest   <video> --channel <id> --format <format>
                                           create the job, run transcreve --palavras
shorts analyze  <job>                      scan, detail, review; write candidates
shorts review   <job>                      open the local review page
shorts track    <job> [--preview]          Apple Vision, approved clips only
shorts captions <job>                      .ass per clip
shorts render   <job> [--safe-zone]        one clip at a time; --safe-zone overlays the template
shorts run      <job>                      run the next pending stage
shorts clip     <video> --channel <id> --format <format> --from MM:SS --to MM:SS
                                           vertical slice: one manual clip, no analysis
shorts backup   [<job>]                    upload final renders to Google Drive (4.4)
shorts clean    <job>                      delete renders of rejected clips
```

`shorts clip` exists to test framing, captions and render before analysis and the review page
exist, and stays useful for one-off cuts.

### 4.2 Repo layout

The repo has a `CLAUDE.md` at its root (built with the `folder-structure` skill) with the folder
map, routing ("working on X? read Y first") and the repo rules: English only, no media in Git,
`ffmpeg-full` required, one clip at a time.

```
albatroz-shorts/
  CLAUDE.md                folder map, routing, repo rules
  config.toml              media root, LLM backends per pass, defaults
  channels.toml            channel -> brand folder in attentionagent + local settings
  prompts/                 scan.md, detail.md, review_blind.md, review_faithful.md
  assets/fonts/            Anton-Regular.ttf + OFL.txt
  assets/safe-zone.png     Natã's safe-zone template (1080x1920)
  jobs/<yymmdd>-<slug>/    one job per class: text artifacts only
  src/shorts/              code
  tests/
  THIRD_PARTY.md
```

A job holds only text; every video path points into the media root:

```
jobs/260927-catequese-permanente-1/
  job.json                 channel, format, master path, duration, master hash
  words.json               transcreve --palavras output
  color.json               color correction points, one every 10 min
  analyze/scan.json        score per window
  analyze/candidates.json  full rubric, proposed and snapped boundaries, segments
  review.json              Natã's decisions and edits (the only hand-written file)
  clips/c07/edl.json       kept segments after silence cutting
  clips/c07/track.json     Vision samples and smoothed path
  clips/c07/shots.json     wide/close-up per span
  clips/c07/captions.ass
  clips/c07/meta.json      title, hook, score record, final duration, render path and hash
  log.jsonl                LLM calls (backend, model, tokens), ffmpeg commands, errors
```

### 4.3 Cache

Each artifact stores a **hash of its inputs**: upstream artifact hash, stage config, prompt version,
code version. A stage reruns only if that hash changed.

| Change                            | What reruns                                           |
| --------------------------------- | ----------------------------------------------------- |
| caption style                     | `captions` and `render` for the clip                  |
| a clip's start/end in review      | `edl`, `track`, `captions`, `render` for that clip    |
| rubric weight                     | only the total recalculation, no LLM call             |
| a prompt's text                   | that pass and the ones after it                       |

Atomic writes: every artifact is written as `.tmp` and renamed at the end. The previous render is
replaced only when the new one finishes.

### 4.4 Media root: one place for every video

All video lives in **one folder outside both repos**, `~/dev/albatroz-media/` (a support folder,
not a Git repo; path set in `config.toml`):

```
albatroz-media/
  masters/<yymmdd>-<slug>.mp4                         camera masters
  renders/<channel>/<yymmdd>-<slug>/c07.mp4           final renders
  renders/<channel>/<yymmdd>-<slug>/c07.json          copy of meta.json, next to the video
```

- **Both repos point here.** albatroz-shorts writes renders; attentionagent (sub-project 2) reads
  them by path. Nothing is cloned or copied, so Time Machine sees each file once.
- **Git never sees video.** `.gitignore` blocks `*.mp4 *.mov *.m4a *.wav`; a pre-commit hook
  rejects any file over 5 MB.
- **No intermediate video files.** The render reads straight from the master. The whisper `.wav` is
  deleted once transcription ends. Each clip has one render, overwritten on re-render.
- **Google Drive backup, one-way.** `shorts backup` uploads final renders (and their `.json`) to a
  Drive folder with `rclone copy`: it only adds and updates, never deletes on Drive, and never
  syncs back. The media root is not a Drive-synced folder, because two-way sync inside `~/dev`
  conflicts with the workspace rule of no cloud sync. Masters are not backed up by default
  (20 to 40 GB each); `--masters` opts in. Runs after each render when `backup.auto = true`.
- `shorts clean` removes renders of rejected clips from the media root.

### 4.5 Channel profile

`channels.toml` points each channel to its brand folder in attentionagent, which provides: ICP,
audience, anti-audience and triggers, and learned lessons (`memory/`). Locally, `channels.toml` holds
video settings: content language, whisper glossary, caption style, color/sound/silence toggles,
rubric weights (with a global default), B-roll source (phase 2).

The per-brand structure in attentionagent is sub-project 2's job. Until it exists, the reader
accepts a path to any directory with the same files, and the plan creates the one for `catholic-br`.

### 4.6 LLM backends

Every LLM pass goes through one interface, `LLMBackend.complete(system, user, schema) -> dict`,
chosen per pass in `config.toml`:

| Backend             | How                                                                                     | When                              |
| ------------------- | --------------------------------------------------------------------------------------- | --------------------------------- |
| `claude-cli`        | `claude -p --model <m> --system-prompt <s> --json-schema <schema> --output-format json --tools "" --no-session-persistence` (checked on Claude Code 2.1.284) | **default**; uses Natã's Max plan |
| `anthropic-api`     | Anthropic SDK, key from the Keychain                                                    | unattended automation             |
| `openai-compatible` | OpenAI SDK with a base URL: OpenAI, Gemini's compatible endpoint, OpenRouter, Ollama    | other models                      |

- Default models: scan `claude-haiku-4-5`, detail `claude-opus-5-5`, both reviews `claude-sonnet-5`.
- The Max plan covers Natã's personal use on his machine. If this ever runs as a service for
  clients, it must use `anthropic-api`.
- Max has usage limits per 5-hour window. A long class can stop mid-analysis; the cache means the
  rerun resumes from the last finished call.
- **Token budget, text only** (no audio or video is ever sent). Estimate for a 2 h class
  (about 18k words, about 30k tokens of transcript):

  | Pass          | Calls        | Input tokens | Output tokens |
  | ------------- | ------------ | ------------ | ------------- |
  | scan          | ~8 batches   | ~50k         | ~8k           |
  | detail        | up to 40     | ~150k        | ~35k          |
  | reviews (x2)  | up to 16     | ~150k        | ~15k          |
  | **total**     |              | **~350k**    | **~60k**      |

  Reviews batch 5 candidates per call to keep the fixed prompt overhead down. Real numbers come
  from `log.jsonl` on the first real run and replace this estimate.

## 5. Sub-project 0: `transcreve --palavras`

New flag in the public `transcreve`. Measured on 2026-09-28 on the 10-min sample (lesson
`albatroz-claude/_lessons/260928-whisper-dtw-palavras.md`).

- Call: `whisper-cli ... -nfa -ojf -dtw large.v3.turbo`. **`-nfa` is required**: with flash
  attention on (the default) DTW is silently skipped and every `t_dtw` comes back `-1`.
- Word = a token starting with a space plus the following tokens without one (`" re"` + `"i"`).
  `[_...]` tokens dropped. Punctuation stays attached to the word.
- Word time = the first token's `t_dtw` (hundredths of a second) **minus 0.15 s** (measured bias;
  p90 error dropped from 0.29-0.46 s to 0.14 s). The shift is written into the JSON and revalidated
  on the first iPhone master.
- **Fails loudly** if any word has no `t_dtw`. Never falls back to `offsets` (p90 0.95 s; 195 of
  1,594 words had end before start).
- `--prompt` still works; `channels.toml` passes the channel glossary.
- Output `<video>.palavras.json` (the flag and file name stay Portuguese: `transcreve` is a
  Portuguese-first public tool with Portuguese flags):

```json
{
  "version": 1, "model": "large-v3-turbo", "language": "pt",
  "dtw_shift_s": -0.15, "duration_s": 600.2,
  "words": [ {"t": 79.02, "p": 0.99, "w": "Aí"}, {"t": 79.12, "p": 1.0, "w": "eu"} ]
}
```

Measured cost: 87 s per 10 min of audio, 1.9 GB peak.

## 6. Clip selection

### 6.1 Inputs

`words.json` grouped into sentences (ending in `.?!`), the channel profile (4.5), and the versioned
prompts in `prompts/`. Prompt instructions are in English; the model is told the content language
and writes titles and hooks in it.

### 6.2 Pass 1: scan

- 120 s windows with 30 s overlap, cut at sentence ends, covering the whole class.
- Batches of about 10 windows per call.
- Per window: score 0 to 100 and a reason of up to 15 words.
- **No target count.** Every window scoring **60 or more** goes to detail (configurable). A ceiling
  of **40** windows is kept only as a cost guard. A strong class yields many clips, a weak one few.
  (Amended 30/09/2026 by the owner: above the ceiling `analyze` asks "send all N to detail?"; yes sends
  all of them, no keeps the best 40; no terminal input keeps the 40; `--yes` sends all.)

### 6.3 Pass 2: detail

For each selected window, with 60 s of context on each side, plus the one-line summary of every
other high-scoring window (so the model can reach a distant payoff), the model returns one or more
candidates. A candidate has:

- `segments`: **1 to 3**, each with `first_words` and `last_words`, the first and last **6 literal
  words** of that segment. Segments may be far apart in the class. A hook taken from after the
  development (cold open) is allowed and marked `out_of_order`.
- `title` (up to 60 characters, content language) and `hook`
- four dimensions 0 to 10, each with a one-line justification:

| Dimension     | Measures                                              | Default weight |
| ------------- | ----------------------------------------------------- | -------------- |
| hook          | the first sentence holds attention on its own         | 30%            |
| value         | the audience saves, quotes or forwards it             | 25%            |
| conversation  | a disputable claim that pulls in the anti-audience    | 25%            |
| emotion       | awe or indignation (high arousal), not melancholy     | 20%            |

- `controversy`: 0 consensus, 1 disputed, 2 inflammatory, with a reason. Level 1 is the target;
  level 2 gets a warning in review (inverted-U curve, Chen and Berger 2013, *Journal of Consumer
  Research* 40(3):580-593).
- `who_reacts`: descriptive note, not scored ("Protestant, will quote Rom 3:28").
- `emphasis`: 1 to 3 literal sentences from the clip shown in close-up (8.2).
- `hook_id`: when several candidates share the same hook with different developments, they share
  this id (6.6).

Rubric basis: signals from `Anil-matcha/AI-Youtube-Shorts-Generator`, dimensions from Opus Clip and
`xixihhhh/hotclip`, the "STANDS ALONE" rule from openshorts. A simulated persona panel was rejected:
Maiorano 2026 (arXiv 2609.25010) measured τ = 0.084 with personas vs τ = 0.361 without, and Cheng et
al. 2023 (EMNLP) found persona caricature worst for religious groups.

### 6.4 Boundaries (code, not the LLM)

For each segment:

1. Find `first_words` and `last_words` in `words.json` (normalized match: lowercase, no punctuation,
   no accents). No match: candidate dropped, reason logged.
2. Start 0.35 s before the first word, end 0.45 s after the last, never entering a neighbor word.
3. Proposed and snapped times are both stored.

For the whole candidate: under 30 s total, the last segment extends to the end of its next
sentence; over 60 s, the last segment is trimmed back to an earlier sentence end, or the candidate
is marked `too_long`.

### 6.5 Pass 3: two reviews

- **Self-contained (blind):** gets only the clip text, "as a stranger scrolling the feed". Fails if
  it opens on a pronoun, a continuation word ("então", "aí", "so"), or an answer to an earlier
  question. May propose moving the start back; never cuts the ending.
- **Faithful (with context):** gets the clip plus 3 min around **each** segment. Fails if the cut
  or the splice between segments changes the meaning of the argument, or makes the doctrine sound
  like something that was not said. Splicing distant segments is the main quote-mining risk, so
  this check is strict for multi-segment candidates.
- Verdict: publish, review, drop. Nothing disappears: dropped candidates show collapsed in review.

### 6.6 Building the list

- **Duplicates:** two candidates are duplicates only if they overlap by **80% or more of the
  shorter one's total duration**; the higher total stays. Sharing a hook is not duplication.
- **Variations:** candidates with the same `hook_id` are shown grouped, side by side, so Natã picks
  the angle (or keeps several).
- Total computed in code from the weights in `channels.toml`. Sorted by total.

### 6.7 Call robustness

Every response is JSON validated against a schema (`--json-schema` on `claude-cli`, tool/response
schemas on the SDKs). Transient errors retry with backoff; a response that fails the schema gets up
to 2 extra attempts; then the stage stops with a clear message, never continuing with half the
candidates. Each call logs backend, model and tokens to `log.jsonl`. API keys come from the Keychain.

## 7. Review page

`shorts review <job>` opens `localhost:8765`, listening on the Mac only.

One card per candidate (variations grouped), sorted by total:

- a player that plays the clip's segments straight from the master
- editable title and hook
- total and the four bars, each with its justification line
- controversy badge, `who_reacts`, warnings (failed check, controversy 2, `out_of_order`,
  weak tracking after `track`, input under 1080p)
- the clip text with clickable words to move a segment's start or end to that word; ±0.5 s and
  previous/next sentence buttons
- word correction: changing a word's text keeps its time (a transcription error burned into the
  video stays forever)
- estimated duration after silence cutting
- approve and reject, written to `review.json` on every click

The server must answer **HTTP Range requests** (the browser asks for byte ranges of the video to
seek). Stdlib `http.server` does not, so the repo has its own handler of about 40 lines: parse
`Range: bytes=START-END`, seek, reply `206 Partial Content` with `Content-Range`, with tests for
open-ended and invalid ranges. No new dependency; Starlette's `FileResponse` is the upgrade path if
the page grows.

## 8. Framing

### 8.1 Tracking

- Approved clips only. ffmpeg decodes each segment at **3 fps and 640 px**, one frame at a time,
  into Apple Vision: `VNDetectHumanRectanglesRequest` (body; `upperBodyOnly` for `solo-seated`)
  and `VNDetectFaceRectanglesRequest` (face, for close-ups).
- More than one person detected in a solo format: follow the box nearest the previous position;
  size breaks ties.
- Camera ported from openshorts' `SmoothedCameraman`:
  - **dead zone** of 25% of the crop width (`solo-standing`) or 15% (`solo-seated`);
  - follows only after **2 consecutive samples** outside it (about 0.7 s);
  - eased acceleration and braking with a speed cap (openshorts uses a constant 3 px per frame;
    not here);
  - no detection: camera **holds still**.
- More than 30% of samples without detection: the clip gets a "weak tracking" warning.
- `track.json` stores raw samples and the smoothed path.
- **Per-frame path:** the render gets a list with the crop window for every output frame, never a
  piecewise formula. Required test: every frame has a window inside the image. (In the preview, a
  piecewise formula returned zero at segment edges and showed the door of the room.)
- `shorts track --preview` renders a small video with the box and the crop window drawn.

### 8.2 Shots: wide and close-up

| Format          | Wide                                  | Close-up                          |
| --------------- | ------------------------------------- | --------------------------------- |
| `solo-standing` | full height, 9:16 width, tracked      | about 1.4x, centered on the face  |
| `solo-seated`   | full height (waist up), 9:16, tracked | about 1.6x, centered on the face  |

- Close-up falls back to the top of the body box when the face is lost.
- Hard cuts, **no animated zoom**. Cuts only at sentence ends, silence cuts, or segment joins;
  minimum shot length 4 s.
- A clip **opens in close-up on the hook** and cuts to wide. `emphasis` sentences go in close-up.
- A silence cut in a wide shot where the body moved beyond a threshold switches shot, hiding the
  jump. A join between distant segments always switches shot.
- `shots.json` stores the spans.

### 8.3 Phase 1b: `conversation`

Built after 1a works; not in 1a's plan beyond keeping interfaces open for it.

- Starts with a spike on a real recording of Natã's, comparing two ways of knowing **who is
  speaking**:
  - (a) **one mic per person**: per-channel audio energy;
  - (b) **mouth movement** per face, from Vision face landmarks at about 10 fps on the face crops.
- Audio diarization (pyannote) is out: it pulls in PyTorch (about 2 GB) on an 8 GB machine.
- Layouts: cut to the active speaker; **split top/bottom** when both speak or for a reaction.
- The same shot rules as 8.2 apply.

## 9. Captions

Validated in the 2026-09-28 preview (720p sample, 78.9 to 101.2 s).

- ASS with `PlayResX 1080`, `PlayResY 1920`. Anton bundled in `assets/fonts/` (OFL allows it),
  loaded via `fontsdir`.
- Always **uppercase**, white, **6 px** black outline, no shadow, size **128**.
- Spoken word in yellow `#FFE500` (ASS `&H00E5FF&`). One event per word redraws the screen with
  that word highlighted.
- **Position:** inside the white area of `safe-zone.png` (x 70 to 1025, y 250 to 1082). One line per
  event with `\an2\pos(547, y)`; baseline of the last line at y = 1060 on two-line screens; a one-line screen sits at 956, the upper line's height (S7); x = 547 is the center of
  the safe zone, not of the frame.
- **Line pitch:** 104 px between baselines (about 28 px of visible gap between capitals). Rises to
  116 px only on screens where the top line has Ç, Q, comma or semicolon and the bottom line has an
  accent. Measured for Anton 128 with outline: capital 76 px, accent +16 px above, cedilla/tail
  +18 px below.
- **Line breaking by characters:**
  1. segments close at `.?!`, at a pause over 0.7 s (only if the segment already has 12 or more
     characters), and at a comma once past 14 characters;
  2. a segment over 30 characters becomes screens of similar size, never ending a screen on a
     function word (pt: "que", "na", "ou", "de", "se"...; en: "the", "a", "of", "to", "and"...);
  3. a screen of up to 16 characters is one line; above that, two lines split at the word that
     makes them closest in length, with a penalty for a line ending on a function word.
- Timing: each word runs from its start to the next word's start; the last word of a screen runs
  until the next screen.
- Times are mapped through the EDL (10.2) to the cut clip's timeline.
- Word corrections from review go into the text.
- Golden test cases: real sentences from the classes (pt and en), with the expected break written
  by hand.

## 10. Treatment and render

### 10.1 Input

- `ffprobe` detects HDR (`color_transfer` HLG or PQ): converted to SDR bt709 before anything else.
- Forced to constant 30 fps (the iPhone records at a variable rate).
- Height under 1080 raises a quality warning at `ingest` and in review.
- Color correction and the DTW shift are revalidated on the first master.

### 10.2 Silence cutting (EDL)

Measured on the sample: 211 pauses over 0.3 s in 10 min; 124 under 0.8 s.

- `silencedetect` at -35 dB on each segment's audio.
- Pause under 0.8 s: untouched.
- Pause of 0.8 s or more: shortened to **0.5 s**, keeping half on each side.
- After a word ending in `?` or `!`: shortened to **0.8 s** (rhetorical pause).
- Measured gain: 12% on average across the sample; 22% on the most paused stretch (44.6 s to
  34.6 s).
- `edl.json` lists the kept spans across all segments. Tracking, shots and captions are computed on
  the class timeline and mapped to the clip's.
- Can be turned off per channel.

### 10.3 Color

- Frames sampled every **10 min** of the class, reusing the tracking decode.
- Per point: per-channel black and white levels from the 1st and **99th** percentile (protects
  highlights), gray-world white balance, gamma. Applied with `colorlevels` and `eq`.
- Linear interpolation between points. Each clip uses the value at its midpoint, constant across
  the whole clip (no pulsing).
- Reference measured on the 720p sample: before, mean Y 96, highlights 147, U/V 120.7/133.5; after,
  118, 189, 126.1/127.5.
- Can be turned off per channel.

### 10.4 Sound

`highpass=f=70`, `afftdn=nr=6:nf=-45` (gentle; 12 dB sounded overdone), two-pass `loudnorm` per
clip to **-14 LUFS**, -1.5 dBTP peak, 48 kHz. No de-reverb. Can be turned off per channel.

### 10.5 Render

One ffmpeg pass per clip, one clip at a time: read the segments, HDR to SDR if needed, 30 fps,
color, EDL on video and audio, per-frame crop window from the shots, scale to 1080x1920, ASS
captions, sound, and `h264_videotoolbox` at about 10 Mbps, yuv420p, bt709 tags, `+faststart`, AAC
160 kb/s. A 60 s clip lands near 75 MB (Reels: up to 300 MB and 25 Mbps).

The plan's first render task confirms the per-frame crop mechanism (`sendcmd` on `crop`, or two
`crop`s with `overlay` as in the preview).

No frame goes through Python during render. The 22 s preview rendered in 5.3 s.

`shorts render --safe-zone` overlays the template for visual checks.

### 10.6 Handoff

The render and a copy of `meta.json` land in `albatroz-media/renders/<channel>/<job>/`, where
sub-project 2 reads them. `meta.json` carries title, hook, content language, channel, format, final
duration, segments, and the full score record (four dimensions, controversy, who reacts, verdict,
prompt versions, backend and model). That record lets sub-project 2 compare prediction with result.

## 11. Errors

- Atomic, resumable stages (4.3).
- LLM calls: 6.7. Max-plan limit hit: stage stops, rerun resumes.
- ffmpeg: on failure, the stderr tail and the exact command go to `log.jsonl`.
- Vision without detection: 8.1.
- A candidate whose literal words are not in the transcript: dropped with a reason.
- `shorts doctor`: `ffmpeg-full` with libass and VideoToolbox, `whisper-cli` and model, `transcreve`
  with `--palavras`, Anton, the configured LLM backend reachable (`claude` on PATH and logged in, or
  API key in the Keychain), brand folder, media root writable, disk space, `rclone` remote when
  `backup.auto = true`.

## 12. Tests

- **Unit (pytest)** on all pure logic: tokens to words, DTW shift, windows, literal word search,
  boundary snapping, multi-segment assembly, duplicates at 80%, hook grouping, weighted total,
  caption breaking (golden cases, pt and en), line pitch, EDL across segments, time mapping, camera
  smoothing (jitter inside the dead zone does not move; a jump produces a ramp with no overshoot;
  speed cap), crop window inside the image on every frame, color interpolation, Range parsing.
- **LLM:** real responses saved as fixtures; tests run without any backend. `--live` runs one smoke
  test per configured backend.
- **End to end:** the 10-min sample through the vertical slice (`shorts clip`); `ffprobe` checks
  1080x1920, 30 fps, H.264, AAC 48 kHz, loudness -14 ± 1 LUFS, duration equal to the EDL.
- Tests that need video skip when the sample is not on the machine.
- Human checks: `track --preview` and `render --safe-zone`.

## 13. Phase 2: B-roll (outline; own spec after phase 1a is approved)

- The LLM proposes terms and moments per approved clip.
- Search the Wikimedia Commons API; keep only PD, CC0, CC BY and CC BY-SA; store author, license
  and link.
- Each slot in review shows candidates: approve, swap or none. Nothing goes in on its own.
- Layouts: full screen, or split (art on top, Natã below).
- Generates the attribution text for the description.
- Open: Ken Burns (slow zoom over a still image) to be decided by watching it, since slow zoom on
  video was rejected; B-roll source for the AI channels.

## 14. Out of scope for this spec

Posting, metrics, comments and self-study (sub-project 2). Dashboard (sub-project 3). Thumbnails.
De-reverb. Audio diarization. Any transcription engine other than whisper.cpp.

## 15. Open risks

- The DTW shift and color correction were calibrated on 720p recompressed by YouTube; the master may
  need other values.
- The "faithful" check depends on the model's judgment, and multi-segment clips raise the stakes;
  human review stays the gate.
- Rubric weights and the scan threshold of 60 are an informed guess until sub-project 2 brings real
  metrics.
- Close-up in 720p is soft (about 290 px blown up to 1080); a 4K master fixes it.
- The token budget in 4.6 is an estimate until the first real run.
