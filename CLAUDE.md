# CLAUDE.md: albatroz-reels

Turns recorded video into vertical 1080x1920 Reels, Shorts and TikToks: long classes cut into Shorts by
the pipeline (Python, ffmpeg, face tracking, word-highlight captions, an LLM that picks the moments), plus
four edit formats built around it (see "Formats"). Runs natively on macOS (Apple Vision, VideoToolbox;
an M1 with 8 GB is enough) and on Windows (YuNet + YOLOX-S in ONNX, libx264). Only
`src/shorts/machine.py` reads the OS; Windows paths are in `[platform.win32]` of `config.toml`.

Open source (MIT) by Natã Gomes, Albatroz Studio. Fork it and make it yours: the `setup` skill installs
it, the `new-channel` skill builds your channel profile and style. Design:
`docs/superpowers/specs/2026-09-28-shorts-pipeline-design.md`. The design docs keep their history and
may name internal files that are not in this repo.

## Rules

- **English only** in code, identifiers, config keys, docs, plans and prompt instructions. Video
  content (captions, titles, hooks) is in the channel's content language.
- **No media in Git.** Videos live in the media root (`config.toml` -> `media_root`, default
  `~/dev/albatroz-media`). `.gitignore` and `scripts/hooks/pre-commit` block media extensions and
  files over 5 MB. Install the hook once: `sh scripts/install-hooks.sh`.
- **ffmpeg with libass is required**: on the Mac, Homebrew's ffmpeg-full
  (`/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg`); the regular Homebrew ffmpeg has no libass. Never call a bare `ffmpeg` from code; use `shorts.ffmpeg.FFMPEG`.
- **One clip at a time.** Never decode a whole clip into memory; frames go through Python only for
  Vision (3 fps, 640 px, one frame at a time). The render never passes frames through Python.
- **Crop windows are a per-frame list**, checked by `assert_in_bounds` (docs/decisions/0001).
- Do not rename shared names and types: tests, job files and the review page depend on them.
- **Never commit someone else's video**, nor footage of minors without consent; reference videos are
  links and notes in `profiles/<channel>/references.md`.

## Folder map

```
config.toml            media root, LLM backends per pass, thresholds
pricing.toml           API list prices per model (USD per million tokens) for `shorts cost`
channels.toml          one table per channel: language, profile folder, glossary
profiles/<channel>/    channel profile (icp.md, audience.md, memory/) and caption notes (captions.md);
                       profiles/_template/ is the blank one, profiles/catholic-br/ the author's example
assets/fonts/          Anton (captions, via fontsdir) + Raleway, IBM Plex Mono (review page, /fonts/), with OFL licences
assets/safe-zone.png   1080x1920 Reels safe-zone template (used by --safe-zone and the format checks)
src/shorts/            the package (one module per concern, see below)
tests/                 pytest; video tests skip without ffmpeg-full or SHORTS_SAMPLE
scripts/hooks/         git hooks (pre-commit media guard)
scripts/spikes/        one-video scripts behind the formats (copy, then edit)
remotion/              Remotion workspace; projects/ holds the model project of each Remotion format
.claude/skills/        setup, new-channel and one playbook per format
help/pt-BR/            user guide in Portuguese
docs/superpowers/      design specs
docs/decisions/        ADRs for this repo
jobs/                  per-video text artifacts (only review.json is versioned); jobs/_manual/ holds `shorts clip` work files
```

## Routing: working on X? read Y first

| Working on | Read |
|---|---|
| captions (breaks, pitch, ASS) | spec section 9, `src/shorts/captions.py`, `tests/test_captions.py` |
| tracking, shots, crop windows | spec 8, `tracking.py`, `shots.py`, docs/decisions/0001 |
| silence cutting, time mapping | spec 10.2, `timeline.py`, `silence.py` |
| color, sound | spec 10.3 and 10.4, `color.py`, `audio.py` |
| render command / filter graph | spec 10.5, `render.py`, `tests/test_render_mechanism.py` |
| `shorts clip` flow | `clip.py`, `cli.py` |
| environment problems | `shorts doctor` (`doctor.py`) |
| the LLM passes | `src/shorts/llm/base.py`, then `src/shorts/analyze/run.py`; prompts live in `prompts/` |
| LLM cost, `shorts cost`, pricing | S4 spec `docs/superpowers/specs/2026-09-30-llm-cost-accounting-design.md`, `cost.py`, `runlog.py`, `pricing.py`, `llm/context.py`, `llm/base.py` |
| the review page | `src/shorts/review/` (server, state, static UI); undo, redo, ghost chips and suggestion-or-mine: `docs/superpowers/specs/2026-09-30-review-undo-and-choose-design.md`, `tests/test_review_state.py`; brand, themes and fonts: `docs/superpowers/specs/2026-09-30-review-page-brand-design.md`, `static/tokens.css`, `tests/test_review_contrast.py`; render state, queue and drawers: docs/superpowers/specs/2026-10-01-review-render-control-design.md, src/shorts/review/renders.py, tests/test_review_renders.py |
| dereverb, audio strength, excerpt | docs/superpowers/specs/2026-10-01-dereverb-strength-design.md, src/shorts/dereverb.py, src/shorts/excerpt.py, src/shorts/review/audio.py, tests/test_dereverb*.py |
| job stages, handoff | `src/shorts/stages.py` (calls `clip.produce()`) |
| pre-cut vertical videos (phone Shorts that arrive cut and lit) | `settings` in `jobs/<job>/job.json`, `stages.job_settings`, `documentation/features/shorts-cli.md` "Job settings" |
| backup | `docs/runbooks/drive-backup.md`, `src/shorts/backup.py` (rclone copy only, never sync) |
| job subcommands | `src/shorts/cli_jobs.py`, `tests/test_cli_jobs.py` |
| caption fixes (automatic word corrections) | `docs/superpowers/specs/2026-09-29-caption-context-pass-design.md`, `src/shorts/wordfix.py`, `src/shorts/analyze/fixwords.py`, `tests/test_wordfix.py`, `tests/test_wordfix_pass.py` |
| documentation (ADS), live-run runbook | `documentation/README.md` |
| installing on a new Mac or PC | `.claude/skills/setup/SKILL.md`, `documentation/runbooks/new-machine-setup.md` |
| a new channel, the owner's style, reference videos | `.claude/skills/new-channel/SKILL.md`, `profiles/_template/` |
| any of the four formats | "Formats" below |

## Formats

Each format has a playbook skill: read it before editing a video in that format. The examples come
from the author's catholic-br channel; the skills say what to change for another channel.

| Format | Skill | Scripts / model project |
|---|---|---|
| Class cut: the pipeline picks moments of a long video and renders captioned Shorts | `help/pt-BR/guia-de-uso.md` | `src/shorts/` |
| Faceless quote: a voice reads a quote over paintings, Ken Burns, captions, credit card | `faceless-quote-reel` | `scripts/spikes/quote-reel-261026/` |
| Motion hook: phone takes, kinetic-typography hook, retention strip, CTA, end card | `motion-hook-reel` | `scripts/spikes/catolico-reel-261018/`, `remotion/projects/261018-catolico-exodo-20-hook/` |
| Reaction: third-party clip plus the owner's reaction, split screen then full screen | `reaction-edit` | `scripts/spikes/reaction-261016/` |
| Long cut: a moment of a long video with a motion hook and a body dressed in Remotion | `long-cut-reel` | `remotion/projects/261025-catolico-eleicao/` |

A spike is a throwaway script tied to one video, written to find out whether a format works. Once the
owner approves a render, the lessons go into a playbook skill; only a format used again and again
becomes pipeline code with a spec and tests (`new-channel` skill, section 4).

## Commands

```
uv sync                                   install (Python 3.12 via uv)
uv run pytest                             all tests
SHORTS_SAMPLE=~/dev/albatroz-media/samples/amostra-10min.mov uv run pytest   include the real-sample tests
uv run shorts doctor
uv run shorts cost <job> [--run ID] [--all] [--json] [--project MINUTES]   API-equivalent LLM cost
uv run shorts clip <video> --channel <channel> --format solo-standing --from 1:18.9 --to 1:41.2 [--safe-zone] [--dereverb N]
uv run shorts excerpt <job>                make the four-strength audio excerpts the review page plays
uv run shorts render <job> [--clip ID ...]   render approved clips (all, or only the named ones)
uv run shorts metrics <job>                time and cost of every step, written to jobs/<job>/metrics.md
uv run shorts export <job>                one folder per rendered clip for the content kit (documentation/features/content-kit-handoff.md)
uv run shorts fixwords <job> [--all] [--force] [--topic TEXT]   rerun only the caption fixes
```

`shorts clip` reads `<video>.palavras.json` (from `trs --palavras <video>`) and writes to
`<media_root>/renders/<channel>/manual/<yymmdd-hhmmss>.mp4` plus a `.json` next to it.

## ffmpeg gotchas learned here

- Filter graph files: `-/filter_complex <file>` (ffmpeg 9).
- Inside a single-quoted expression, commas need no backslash.
- `between(t,a,b)` is inclusive at both ends: use `gte(t,a)*lt(t,b)` so shared boundaries are not
  counted twice.
- Per-pixel checks in tests: convert to rgb24 before `crop=1:1` (a 1x1 crop of yuv420p fails).
- iPhone `.mov` masters carry extra `data` streams: always map `0:v:0` / `0:a:0`, never `-map 0`.
- `sendcmd` fires a command when the frame time is at or past it: write each frame's time as
  `i/fps - 0.0005` (floored), or the change lands one frame late.
- HDR masters are tone-mapped (`HDR_TO_SDR`) before anything measures or shows pixels.
