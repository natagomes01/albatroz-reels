# `shorts` command reference

> Reader: Natã, and anyone running or debugging the pipeline. Style: reference. Flags come from
> `uv run shorts <cmd> --help` on 29/09/2026; behaviour from the code, cited as `file:line`.
> What each command starts behind the scenes (ffmpeg, claude, Vision): see
> [commands-and-external-programs.md](../architecture/commands-and-external-programs.md).

Every command is typed from the repo folder as `uv run shorts <subcommand> ...`. Two global flags
go before the subcommand: `--config <file>` (default `config.toml`) and `--channels <file>`
(default `channels.toml`) (`src/shorts/cli.py:76-77`).

## Where things live

`config.toml` sets `media_root = "~/dev/albatroz-media"` and `jobs_dir = "jobs"` (relative to
`config.toml`, so `~/dev/albatroz-shorts/jobs`) (`config.toml:2-3`, `src/shorts/config.py:36-54`).
`pricing.toml`, next to it, holds the API list price of each model for `shorts cost`
(`src/shorts/pricing.py`); see [commands-and-external-programs.md](../architecture/commands-and-external-programs.md),
section 1.2.

**Job folder** `jobs/<job>/` (paths from `src/shorts/jobs.py:17-71` and the stage code):

```
jobs/<job>/
  job.json                 channel, format, master path, master_hash, duration, width, height, warnings, topic
  words.json               word-level transcript (renamed from <stem>.palavras.json)
  <stem>.md                readable transcript that transcreve also writes (not used by shorts)
  log.jsonl                one JSON event per line (see "Debugging")
  color.json               colour grade points, measured once per job at the first render
  review.json              your decisions and edits (the only job file Git versions)
  review.<yymmdd-hhmmss>.json   an older review.json archived by `analyze --force`
  analyze/
    scan.json              every 120 s window with its score and reason
    candidates.json        the candidate list the review page shows
    corrections.json       automatic caption fixes (caption context pass); words.json is never changed
    class_sheet.json       what the class is about: topic, references, terms, spellings
    cache/scan/<sha256>.json      one cached LLM answer per scan batch
    cache/detail/<sha256>.json    one per detail call
    cache/review/<sha256>.json    one per blind or faithful review batch
    cache/class_sheet/<sha256>.json   one cached answer per class-sheet part
    cache/wordfix/<sha256>.json       one per caption-fix chunk
  clips/<clip_id>/
    edl.json               kept time spans after the silence cut
    track.json             Vision samples (body and face boxes, 3 per second)
    track.json.key         freshness key of track.json
    shots.json             wide and close-up shots, and segment joins
    track-preview.mp4      only after `track --preview` (+ .cmd and .graph.txt)
    captions.ass           burned-in captions
    crop.cmd, graph.txt    the render's crop commands and filter graph
    meta.json              clip metadata (title, hook, segments, score, warnings, render path)
```

`profiles/<channel>/captions.md` holds the channel caption notes (canon, spellings, recurring terms); it is optional and the owner grows it.

**Render folder** (`src/shorts/stages.py:139-140`):

```
<media_root>/renders/<channel>/<job>/
  <clip_id>.mp4            the deliverable, 1080x1920
  <clip_id>.json           copy of meta.json (the hand-off to sub-project 2)
  <clip_id>.mp4.key        freshness key; written last, after a successful render
  <clip_id>.mp4.tmp.mp4    only while a render is running
```

Clip ids are `c` plus 6 hex characters derived from the clip's time spans, for example
`c3f9a1b` (`src/shorts/analyze/candidates.py:119-131`). The same clip found again gets the same
id, so a decision never moves to another clip.

## Stage keys and caching

Every expensive step stores a **key**: a SHA-256 fingerprint of everything that affects its
result (`src/shorts/jobs.py:114-120`). If the key still matches, the step is skipped or its cached
result reused; if anything in it changed, the step runs again.

- **LLM calls** (`analyze`): one cache file per call, keyed by the exact prompt text sent, the
  prompt file, the model and `LLM_CACHE_VERSION` (`src/shorts/analyze/scan.py:20-23`,
  `detail.py:48-49`, `reviews.py:71-72`). Rerunning `analyze` with nothing changed makes zero LLM
  calls. A usage-limit stop resumes at the first unfinished call. The class sheet and each caption-fix chunk are cached the same way; a caption-fix key also holds the glossary, the caption notes, the class sheet and the topic, so changing any of them asks again. Each cache file also keeps
  `_cost_usd`, the cost of the call that filled it; a hit logs `llm_cache_hit` with `saved_usd`
  (`src/shorts/analyze/llmcache.py`, `cache_fns`).
- **Tracking**: key = `RENDER_VERSION`, master hash, the clip's segments, format
  (`src/shorts/stages.py:130-131`). If fresh, Vision is skipped and `track.json` reused.
- **Render**: key = tracking key, the effective words inside the clip's segments ±2 s (raw words,
  your word fixes, then the automatic caption fixes), the automatic fixes that touch those
  segments, the channel's render settings (`language`, `captions`, `color`, `sound`, `silence`),
  emphasis spans and the `--safe-zone` flag (`stages.py:122-135`). A correction elsewhere in the
  class does not re-render this clip. A fresh render prints `skipped (fresh)`. `RENDER_VERSION` is 3
  since the caption pass (`src/shorts/jobs.py:14`), so every clip renders again once after the update.
- Changing a clip's start or end on the review page changes its segments, so tracking and render
  rerun for that clip only. Changing a word reruns the render, not the tracking.
- `track` and `captions` always redo their cheap work (silence detection, shot plan, captions);
  only Vision is skipped when fresh. Only `render` skips the whole clip.
- Every file is written as `.tmp` then renamed, so an interrupted command never leaves a half
  file (`jobs.py:91-96`, `src/shorts/render.py:174-184`).

## Exit codes

`0` success. `1` a clip failed in `track`/`captions`/`render`/`run`, ffmpeg failed in `clip`, a
required `doctor` check failed, or `backup` had an rclone error. `2` a readable user error:
unknown job or channel, missing file, corrupt JSON, bad format, usage limit, and so on; printed
as one `error: ...` line (`src/shorts/cli_jobs.py:17-52`).

## Subcommands

### `doctor`

`uv run shorts doctor`. No flags. Checks the machine before a run and prints one line per check:
`[ok  ]`, `[warn]` (optional check failed) or `[FAIL]` (required check failed)
(`src/shorts/doctor.py:94-105`). Exit 1 if any required check fails. Checks: ffmpeg-full,
libass, h264_videotoolbox, zscale, whisper-cli, whisper model, transcreve `--palavras`, Anton font,
safe-zone template (optional), media root writable, disk space (warn below 10 GB, fail below
3 GB), `claude CLI` version, three B-roll warnings (`Keychain: pexels-api`, `Keychain: pixabay-api`,
`B-roll User-Agent`; never a failure), and, when configured, Keychain items and the rclone remote
(`src/shorts/doctor_jobs.py:11-37`). It does **not** check that `claude` is logged in; `claude
--version` works logged out too.

### `clip`

`uv run shorts clip <video> --channel <id> --format {solo-standing,solo-seated,conversation} --from <time> --to <time> [--words <file>] [--safe-zone]`

The S1 manual path: one Short from a start and end you give. Times are `SS`, `MM:SS` or
`HH:MM:SS`, decimals allowed (`src/shorts/cli.py:13-27`). Reads `<video>.palavras.json` unless
`--words` is given. Writes `<media_root>/renders/<channel>/manual/<yymmdd-hhmmss>.mp4` and a
`.json` next to it; work files go to `jobs/_manual/<video stem>/` (`cli.py:58`,
`src/shorts/clip.py:354-365`). Prints the render path. Messages: `error: <words> not found; run:
trs --palavras <video>`, `error: format 'conversation' arrives in phase 1b`, `error: --to must be
after --from`, `error: ffmpeg failed` plus the ffmpeg error tail (exit 1).

### `ingest`

`uv run shorts ingest <video> --channel <id> --format <solo-standing|solo-seated> [--topic TEXT]`

Creates the job and transcribes the master (`src/shorts/ingest.py:74-119`).

- **Job id** (`ingest.py:39-46`): if the video is already in `<media_root>/masters/`, the job id is
  its file name without extension. Otherwise it is today's date `yymmdd-` plus a slug of the file
  name (lower case, accents removed, anything else turned into `-`).
- **The master is moved, never copied.** A video outside `masters/` is **renamed** into
  `masters/<job id>.<ext>` (`ingest.py:49-62`). It must be on the same disk; otherwise:
  `error: <video> is on another volume; move it into <masters> yourself (the pipeline never copies masters)`.
  A video already in `masters/` stays where it is.
- Writes `jobs/<job>/job.json`, runs transcreve (section "External programs" in the reference),
  renames its output to `words.json`. Prints `job <job> ready: <jobs dir>/<job>`.
- Warnings on stderr: `warning: input is below 1080p; close-ups will be soft (use the camera master)`,
  `warning: input is HDR; the render converts it to SDR bt709 before grading` (`ingest.py:65-76`).
- `--topic`: one line about the class (for example `--topic "Salmo 22 na Septuaginta"`), stored as `topic` in `job.json` and given to the caption fixes. Rerunning ingest on an unfinished job with `--topic` updates it.
- **Resumable:** if transcreve fails, the job folder stays; rerun the same command on the master
  in `masters/` and it retries only the transcription.
- Messages: `error: transcreve failed (exit N); fix it and run the same `shorts ingest` again on
  <master> (it resumes). Log: <log>`; `error: transcreve finished but <file> is missing (is it the
  --palavras version?)`; `error: job <job> is already ingested (<words.json>)`;
  `error: <path> already exists` (a different file with the target name is already in `masters/`);
  `error: unknown channel '<id>' (see channels.toml)`; `error: unknown format '<f>' (use one of
  solo-standing, solo-seated)`.

### `analyze`

`uv run shorts analyze <job> [--force] [--yes]`

Runs the three LLM passes and writes `analyze/candidates.json` (`src/shorts/analyze/run.py:54-95`).
Needs the channel profile (`profiles/<channel>/icp.md`, `audience.md`, optional `memory/*.md`;
`src/shorts/analyze/profile.py:37-50`).

- Prints `<N> candidates from <S> of <W> windows; <F> caption fixes (<M> dropped). Next: shorts review <job>`, or
  `<W> windows scanned; none reached the threshold. 0 candidates.` (`src/shorts/cli_jobs.py:86-91`).
- Last stage, the caption fixes (same as `shorts fixwords <job>`, below). It never blocks the analysis: on failure it prints `warning: caption fixes skipped (<reason>); the review page shows raw words. Run `shorts fixwords <job>` to retry.` (with `when the limit resets` for a usage limit) (`src/shorts/cli_jobs.py:92-95`).
- Then, when the run called an LLM or used its cache (also after a usage-limit stop), one more
  line: `LLM cost this run: $X.XX API-equivalent (N calls, cache saved $Y.YY)`
  (`src/shorts/cli_jobs.py`, `_run_boundary`; `src/shorts/runlog.py`, `run_line`). It is Claude
  Code's list-price estimate, not a bill; `shorts cost` breaks it down.
- Ceiling question: when more windows than `scan_ceiling` (40 in `config.toml`) score at least
  `scan_threshold`, analyze prints `<N> windows scored high enough for detail, above the ceiling of 40.`
  and asks `Send all <N> to detail? [y/N]`. `y` sends all of them to detail (one more costly call each);
  anything else, or no terminal input, keeps the best 40. `--yes` answers yes. Either way the log gets
  a `scan_ceiling` event (`src/shorts/analyze/run.py`; `src/shorts/cli_jobs.py`, `_over_ceiling_question`).
- Cost question, off by default: with `cost_confirm_above_usd` above 0 in `config.toml`, analyze
  first prints `Estimated LLM cost: $X.XX API-equivalent for M class minutes (from earlier jobs).`
  and, when the estimate is above the setting, asks `... Continue? [y/N]`. Anything but `y` or `yes`
  prints `analyze cancelled: nothing was sent to the LLM` (exit 1). `--yes` skips the question.
  With no earlier job that has a cost there is no estimate and no question
  (`src/shorts/cli_jobs.py`, `_cost_confirmed`; `src/shorts/cost.py`, `estimate_cost`).
- **Refuses** once `review.json` holds a decision:
  `error: <review.json> already holds review decisions; rerunning analyze could change the candidate list under them. Use `shorts analyze <job> --force` to archive the review and start over.`
  `--force` renames `review.json` to `review.<yymmdd-hhmmss>.json` and analyzes again; cached LLM
  answers are still reused (`run.py:42-51`).
- Usage limit: `error: LLM usage limit reached (<detail>). Finished calls are cached; run `shorts analyze <job>` again when the limit resets.`
- Other failures: `error: claude -p failed: <text>`, `error: the `claude` CLI is not on PATH
  (install Claude Code and log in)`, `error: claude -p timed out after 900s`,
  `error: response did not match the schema after 3 attempts: ...`,
  `error: scan reply is missing windows [...]`,
  `error: analyze failed: <type>: <detail> (see <log>)` (the catch-all; a missing profile file
  shows as `error: analyze failed: FileNotFoundError: channel '<id>': missing <file> (see <log>)`,
  `src/shorts/cli_jobs.py:84-85`).

### `fixwords`

`uv run shorts fixwords <job> [--all] [--force] [--topic TEXT]`

Corrects misheard words in the captions (Hebrew, Greek, Aramaic and Latin terms, names, scripture
references, split or joined words) using the whole class as context, and writes
`analyze/corrections.json` (`src/shorts/analyze/fixwords.py`, `src/shorts/cli_jobs.py:99-122`).
`words.json` is never changed: the review page, captions and renders
show raw words + your word fixes + these automatic fixes; scan, detail and the reviews keep reading
the raw words.

- Two LLM passes: a class sheet (`claude-haiku-4-5`, 1 to 3 calls: topic, references, terms,
  spellings) and the caption fixes (`claude-sonnet-5`, one call per 500-word chunk). Default scope:
  chunks within 60 s of a candidate or of a segment you edited; `--all` corrects every chunk.
- Context sent: channel language and glossary, `profiles/<channel>/captions.md`, the topic (from
  `ingest --topic`, or `--topic` for this run), the class sheet, the words of the chunk with their
  confidence, and the sentence before and after it (read-only).
- Every edit is checked in code and dropped with a logged reason (`fixword_dropped`): out of range,
  more than 12 words, bad tokens, confidence under 0.6, no change, overlap with a better edit. A
  chunk where the model edited more than 15% of the words is rejected (`fixword_chunk_rejected`)
  and asked again on the next run.
- `--force` ignores cached answers. Allowed while `review.json` holds decisions: it never changes
  `candidates.json` or your decisions. Your fix on any word of an automatic fix wins over the whole
  automatic fix.
- Every run rewrites `corrections.json` with only its own scope, so a plain `fixwords` or `analyze`
  after `fixwords --all` drops the automatic fixes outside the new scope (cached chunks make a rerun
  cheap; approved clips' segments stay in scope).
- `fixwords --topic` applies to that run only and is not saved to `job.json`; use `ingest --topic`
  to keep it (a later `analyze` uses the ingest topic, which changes the cache key).
- Prints `<F> caption fixes (<M> dropped) from <C> of <T> chunks. Next: shorts review <job>`.
- Usage limit: `error: LLM usage limit reached (<detail>). Finished chunks are cached; run `shorts fixwords <job>` again when the limit resets.`
- Missing `candidates.json` without `--all`: `error: <path> is missing: run `shorts analyze <job>` first, or `shorts fixwords <job> --all` to correct the whole class` (`fixwords.py:205-207`).

### `review`

`uv run shorts review <job> [--port <n>] [--no-browser]`

Starts the review page at `http://127.0.0.1:8765/` (port changeable) and opens the browser. Prints
`review page: http://127.0.0.1:8765/  (Ctrl+C to stop)`. It keeps running until you press Ctrl+C,
so use a second Terminal window for other commands (`src/shorts/review/server.py:193-205`).

- Listens on 127.0.0.1 only and refuses requests from other sites (Host, Origin and Content-Type
  checks, `server.py:6-8`, `155-163`).
- Plays the master straight from `masters/` with byte-range support so the player can seek.
- Every click is saved at once to `jobs/<job>/review.json` (`src/shorts/review/state.py:129-236`).
  Edits are checked first: a title longer than 60 characters, an empty title or hook, overlapping
  or out-of-range segments are refused and nothing is written. The page shows
  `Not saved: <reason>` (`src/shorts/review/static/app.js:219-220`).
- Automatic caption fixes are shown in light blue with a dotted underline; hovering shows the transcribed text and the model's reason; a card badge counts them (`3 automatic caption fixes`) (`src/shorts/review/static/app.js:353`, `376-378`).
- Shortcuts: click sets the start, Shift+click sets the end, Option (⌥)+click on a Mac or Alt+click on Windows corrects a word. On an automatic fix it replaces the whole corrected range (the first word gets your text, the rest are dropped); on a plain word, leave the box blank to remove a word. The page names the key of your own keyboard first (`app.js:116-123`).
- Undo and redo: Command (⌘)+Z / Shift+Command (⌘)+Z on a Mac, Ctrl+Z / Ctrl+Y or Ctrl+Shift+Z on Windows, or the Undo and Redo buttons on each card. The keys act on the clip you changed last, meaning the clip whose last save succeeded (playing a clip or a rejected save does not count); its Undo button is outlined. They do nothing while a text box has focus, and a held key counts once. Saves of one clip go out one at a time, in click order. Each saved change is one step (a range replace too); up to 100 steps per clip. The history lives in the running `shorts review` only: stopping it clears the history, `review.json` keeps the last state. Server: `POST /api/undo` and `POST /api/redo` with `{"id": "<clip>"}`; an empty history answers 409 `nothing to undo`.
- Removed words stay on the page as faint, struck-through chips marked ⌫; a click brings the word back by erasing your fix for that slot, as if you had never touched it (one undo step). They never reach the captions or the render.
- When you corrected words inside an automatic fix, the page shows `Suggestion: ...` and `Mine: ...` side by side; the outlined one is rendered. Click the other one to switch; Option (⌥)+click / Alt+click edits the range starting from that side's text. Before your text replaces a suggestion that is applied, the page asks you to confirm. The choice is stored in `review.json` as `use_auto` (the `first` indices of the automatic fixes you chose) and switching it re-renders only that clip.
- Look (S6): Albatroz colors and fonts, with a `LIGHT` / `DARK` / `SYSTEM` switch in the header. `SYSTEM` follows the Mac; the choice is kept in this browser only (not in `review.json`). Approved cards have an army bar and `APPROVED`, rejected ones a brick bar, `REJECTED` and grey text; the first and last word (or chooser) of each cut has a thin orange outline; your own fixes are bold and underlined; a card flashes orange once when a save lands; Tab shows an orange focus ring. Fonts come from `assets/fonts/` through `GET /fonts/<name>.ttf`; the page makes no request outside `127.0.0.1`. Reference: [review-page-brand.md](review-page-brand.md).
- Drawers and rendering (S7): every clip is a drawer; the closed line shows the clip id, the title, the review status and the render state: `not rendered`, `rendered vN` (the file matches the page now), `out of date (vN)` (you edited the clip after its render, the code's `RENDER_VERSION` changed, or it was a `--safe-zone` render), `queued`, `rendering…` or `failed` (hover for the last error line; the detail is in `log.jsonl`). `render` on an approved clip queues it; `render all (N)` queues every approved clip that needs one. The page renders one clip at a time, each as `shorts render <job> --clip <id>` in its own process, and you can keep editing meanwhile; it checks the state every 2 s while something is queued. `▶ watch` opens the render file in a new tab. The state comes from the files next to each render (`<clip>.mp4.key`, `<clip>.json`), so it is the same after a restart; the queue is not kept. Open drawers are remembered in this browser only. Ctrl+C stops a render in progress and keeps the previous file. Server: `GET /api/renders`, `POST /api/render` with `{"id": "<clip>"}`, `POST /api/render-all`, `GET /renders/<clip>.mp4` (never cached). Spec: `docs/superpowers/specs/2026-10-01-review-render-control-design.md`.
- If port 8765 is taken, Python raises an "Address already in use" error (not a clean message; not
  verified): use `--port 8766`.

### `track`, `captions`, `render`

`uv run shorts track <job> [--preview] [--clip ID ...]`, `uv run shorts captions <job> [--clip ID ...]`,
`uv run shorts render <job> [--safe-zone] [--clip ID ...]`

Each works on every **approved** clip, one at a time, and stops after its stage
(`src/shorts/stages.py:164-234`). One failed clip does not stop the others.

- `--clip <id>` (repeatable) limits the stage to the named clips. A name that is not a candidate prints `<id>: unknown clip`; a clip that is not approved prints `<id>: not approved, nothing rendered` (`... skipped` for `track` and `captions`); either makes the exit code 1, and the other named clips still run.

- Per clip it prints `<clip>: <stage> done`, `<clip>: skipped (fresh)` (render only), with
  ` -> <render path>` for renders and ` (preview: <path>)` with `--preview`
  (`src/shorts/cli_jobs.py:161-164`).
- A failed clip: `<clip>: FAILED <stage>: <reason> (details in <log>)` on stderr; exit code 1.
- No approved clip: `no approved clips: run `shorts review` first`.
- Before starting: `error: master not found: <path> (was it moved?)` if the master is gone
  (`cli_jobs.py:133-138`).
- `render` also measures colour once per job into `color.json`; if that fails, you get one
  `(color): FAILED render: ...` line and nothing renders.
- `render --safe-zone` burns the safe-zone template on top **and overwrites the deliverable path**.
  It prints `note: --safe-zone overlay renders overwrite the deliverable path; run `shorts render <job>` without it for the final files`.
  A safe-zone render never counts as done (`stages.py:262`).
- Warnings during tracking: `warning: weak tracking (NN% of samples without a person)` when over
  30% of samples find no person (`src/shorts/clip.py:269-271`); the clip's meta then carries
  `weak_tracking` and the review page shows it as a badge.
- Clip-level reasons you may see: `invalid segments: ...`, `segment ends at Xs, past the end of
  the video (Ys)`, `no transcribed words inside the clip segments`, `ffmpeg failed: <command>`
  plus the last 20 lines of ffmpeg's stderr.

### `run`

`uv run shorts run <job> [--yes]`

Does the next pending thing (`src/shorts/cli_jobs.py:171-188`, `src/shorts/stages.py:242-275`):
no candidates yet runs `analyze`; no approved clip prints `next: approve clips with `shorts review <job>``;
any approved clip without a fresh, non-safe-zone render runs `render`; otherwise prints
`every approved clip of <job> is rendered`. It never runs `ingest` (it prints `next step: ingest`).
When it runs `analyze`, the log holds one run (command `run`) and one cost line is printed;
`--yes` skips the cost question of `analyze`.

### `cost`

`uv run shorts cost [<job>] [--run ID] [--all] [--json] [--project MINUTES]`

Reads `log.jsonl`, `job.json`, `candidates.json` and `review.json` and prints what the LLM calls
cost, in API list-price terms (`src/shorts/cost.py`, `job_report` and `format_report`). Nothing is
called and nothing is written. Every number is an estimate, not a bill: `claude -p` reports its
own `total_cost_usd` at list price (`cost_basis: "list"`) even on the Max plan.

- `shorts cost <job>`: a table per pass and model (calls, retries, failed calls, cost, share of
  the total, wall time), a token table (input, cache write, cache read, output), the total, cache
  hits and what they saved (never counted as spent), cost per class minute (from `job.json`
  duration), per candidate and per approved clip, local steps (transcription, `track`, `captions`,
  `render`) with their wall time and `$0.00 (local)`, plan use (calls and every usage-limit event
  with its time), and one line per run.
- `--run ID`: only that run (run ids are in the "Runs" table). An unknown id:
  `error: no run <ID> in <log> (run ids are listed by `shorts cost <job>`)`.
- `--project MINUTES`: the cost of a class that long, linear from the cost per class minute, with
  the warning that detail is capped at `scan_ceiling` windows, so linear scaling overstates long
  classes.
- `--all`: one line per job (folders starting with `_` are skipped), with class minutes, calls,
  cost, cost per minute and the models used; takes no job, `--run` or `--project`.
- `--json`: the same data as JSON (`{"jobs": [...]}` with `--all`).
- Logs written before S4 are reported with the fields they have: their pass is inferred from the
  model in `candidates.json`, their token columns lack the cache columns (their cost is complete),
  and a "Notes" section says so.
- Errors are one `error:` line, exit 2: no job and no `--all`, `--all` with a job, an unknown job,
  an unknown run.

### `backup`

`uv run shorts backup [<job>] [--masters] [--dry-run]`

One-way copy to Google Drive with `rclone copy` (`src/shorts/backup.py`). With a job: only
`renders/<channel>/<job>`; without: all of `renders/`. `--masters` also sends `masters/`.
`--dry-run` lists what would be sent without sending. Never deletes on Drive. Needs rclone and a
`gdrive` remote: [docs/runbooks/drive-backup.md](../../docs/runbooks/drive-backup.md). Without
rclone installed the command fails with `error: [Errno 2] No such file or directory: 'rclone'`
(exit 2; message shape from Python, not verified by running it). Exit 1 if rclone returns an
error.

### `broll`

`uv run shorts broll <job> [--clip ID ...] [--force]`

Suggests B-roll moments and images for approved clips; `--clip ID` limits it to the named clips,
`--force` asks the model again even when a suggestion exists. See the B-roll section below.

### `clean`

`uv run shorts clean <job>`

Deletes the renders (`.mp4`, `.json`, `.key`) of clips whose status is **rejected** in
`review.json`, only inside `<media_root>/renders/<channel>/<job>/` (`src/shorts/clean.py:18-41`).
Approved and pending clips stay; masters can never be reached; Drive is untouched. Prints
`removed <path>` per file; prints nothing when there is nothing to remove.

## Audio strength (dereverb)

Rooms differ per class, so the dereverb strength is chosen by ear, once per class, on the review
page. The model is UVR-DeEcho-DeReverb, run as the separate `audio-separator` program (setup:
[runbooks/new-machine-setup.md](../runbooks/new-machine-setup.md), section "Dereverb (UVR)").

- The audio panel at the top of the page first shows `Preparing audio…` while the excerpts are made, then one row per strength (`[dereverb] levels` in `config.toml`, default 0, 10, 20, 30; 0 is off), each with `▶ play` and `Choose`. `Try again` appears if the excerpts failed.
- Choosing a strength collapses the panel to `Audio: dereverb N · change` (`off` for 0). `change` opens it again. The strength is saved in `review.json`; every approved clip then shows `out of date`, because the strength is part of the render key.
- Each clip has a select with `class (N)` (follows the class strength) and the other levels. A clip with its own value shows the chip `audio N` in its head, and only that clip goes out of date.
- Rendering waits until a strength is chosen: the render buttons are disabled with `Choose the audio strength first`, and `shorts render` stops with `choose the audio strength on the review page first`.
- `uv run shorts excerpt <job>` makes the excerpts without the page (the page also starts it itself after `analyze`).
- `uv run shorts clip <video> ... --dereverb 20` applies one of the levels to a manual clip (default 0, off).
- Cache: `<media_root>/cache/<job>/audio/` holds the excerpts and the dereverbed audio windows. It is safe to delete; it is rebuilt on demand. A render whose clip is already cached does not run UVR again.
- UVR and a render never run together when started from the review page (it answers 409), because both are heavy on 8 GB. Running `shorts render` or `shorts analyze` in a terminal while the page prepares an excerpt can start two UVR processes at once (about 3.3 GB each, heavy on 8 GB): wait for one to finish. Spec: `docs/superpowers/specs/2026-10-01-dereverb-strength-design.md`.

## B-roll

An approved clip gets up to three B-roll moments: a painting from Wikimedia Commons, a photo or a
short video from Pexels or Pixabay, or a file of your own (a screenshot). Nothing goes into a
render until you pick it. Spec: `docs/superpowers/specs/2026-10-02-broll-design.md`.

- Approving a clip asks the Haiku pass for moments and search terms (`Suggesting B-roll…` in its
  drawer); the code searches the sources and shows up to six candidates per moment. `Suggest again`
  replaces the suggested moments and keeps yours. `uv run shorts broll <job> [--clip ID] [--force]`
  does the same from the terminal; `shorts cost` counts the calls under the pass `broll`.
- Per moment: `full screen` or `split` (image on top, you below; the captions never move), `fill` or
  `whole` (the whole image on a blurred band), and the motion of a still (`left to right`, ...,
  `still`). Drag the preview, or use the arrow keys, to choose what part of the image shows; the
  pan passes through that point halfway through the moment.
- Your own moment: `Select words`, click the first and the last word, then `B-roll here`. Add a file
  with `Use my file` (pick it, drop it on the moment, or choose one already in
  `<media_root>/broll/<job>/`). Uploads stop at 200 MB (`[broll] upload_max_mb`); an HDR file of
  your own is refused (convert it to SDR first); a rotated phone video counts at its displayed size.
- Amber lines are warnings: a timing rule broken (2 to 5 s, at most three, at most 30% of the clip,
  not in the first 3 s or the last 2 s) or an image too small for its layout. They never block a
  render.
- Typing in a field of the drawer keeps focus while the page refreshes. If a suggestion or search
  failed, its error stays in the clip head while the clip is queued or working again, until the new
  task ends.
- `Credit` shows the text to paste in the description for CC BY images; `meta.json` carries it too.
- A clip without picked B-roll renders exactly as before. Changing a pick, a layout, a motion or
  the framing re-renders only that clip.
- Files: thumbnails in `<media_root>/cache/<job>/broll/` (`shorts clean` removes them), picks and
  your files in `<media_root>/broll/<job>/`, never in Git, not in the backup. A missing stock file
  is downloaded again at render time; a missing own file stops that clip with a message.
- Keys and setup: [runbooks/new-machine-setup.md](../runbooks/new-machine-setup.md), section
  "B-roll keys".

## Job settings (a video that arrives already cut)

A phone video that was already cut, framed and lit can go through a job with a `settings` object
in `jobs/<job>/job.json` (`src/shorts/stages.py`, `job_settings`). Every key is optional; a job
without `settings` renders exactly as before (same keys, nothing re-renders).

| Key | Effect |
|---|---|
| `color` | `false` skips the colour grade (the video keeps its own colour) |
| `caption_y` | caption baseline row, 1 to 1919 (default 1060); higher is lower on screen |
| `close_zoom` | close-up zoom from 1.0 to 2.0, instead of the format's (1.4 standing, 1.6 seated) |
| `open_close` | `false` opens the clip wide instead of in close-up on the first sentence |
| `split_face_y` | output row of the face in a `split` B-roll moment (default 1250) |
| `burn_captions` | `false` writes `clips/<id>/captions.ass` but leaves the captions out of the render (they are drawn elsewhere, e.g. in a Remotion pass) |

Example: `"settings": {"color": false, "caption_y": 1400, "close_zoom": 1.25, "open_close": false}`.
Changing a setting puts the clip's render out of date on the review page. An unknown key or a value
out of range stops the stage with `unknown job setting ...` or `job setting <key> must be ...`.

## Debugging

1. Read the one-line `error:` message; most name the file and the next command.
2. Open `jobs/<job>/log.jsonl`. Each line is one event with a `ts` (Unix time) and a `kind`
   (`src/shorts/jobs.py:157-161`):

| `kind` | Written by | Meaning |
|---|---|---|
| `transcreve` | `ingest.py`, `ingest` | The transcreve command, its exit code, the last 2000 characters of its stderr, and `wall_s` (from S4). |
| `llm` | `llm/base.py`, `LLMBackend._record` | One LLM call attempt (a schema or transient retry is its own event). `pass`, `job`, `run`, `backend`, `model`, `attempt`, `ok`; tokens `input_tokens`, `cache_creation_input_tokens` (of which `cache_creation_1h_input_tokens`), `cache_read_input_tokens`, `output_tokens`, `thinking_tokens`; `duration_ms`, `duration_api_ms` (reported by `claude -p`), `wall_ms` (measured); `cost_usd` (as reported, or from `pricing.toml` for the API backends), `cost_table_usd` (from `pricing.toml`, a cross-check), `cost_basis` (`list`, `table` or `reported`; null when there is no cost). `ok: false` adds `error` and `error_kind` (`transient`, `limit`, `schema`, `fatal`) and keeps any cost the failed call reported. Events from before S4 have only `backend`, `model`, `ok`, `input_tokens`, `output_tokens`, `cost_usd`. |
| `llm_cache_hit` | `analyze/llmcache.py`, `cache_fns` | An answer came from the cache: `pass`, `job`, `run`, `saved_usd` (the cost of the call that filled the entry; `null` for entries cached before S4). |
| `run_start`, `run_end` | `runlog.py`, `command_run` | The bounds of one `analyze`, `run`, `fixwords`, `track`, `captions` or `render` command: `run` id, `command`, `args`; then `exit_code` and `wall_s`. The cost of a run is the sum of its `llm` events. |
| `scan_ceiling` | `analyze/run.py`, `run_analyze` | More windows qualified than `scan_ceiling`: `qualified`, `ceiling`, `asked` (a question was possible), `sent_to_detail`. |
| `scan_missing_windows`, `scan_duplicate_windows` | `analyze/scan.py:52`, `58` | The scan answer skipped or repeated a window; analyze stops. |
| `candidate_dropped` | `analyze/detail.py:60` | The model quoted words that are not in the transcript (or ambiguous); the candidate was dropped, with the reason. |
| `review_missing` | `analyze/reviews.py:81`, `91` | A review batch failed its schema; those candidates get a `review_missing` warning; the next `analyze` retries that batch. |
| `clip_stage` | `stages.py:207-208` | A clip finished a stage: `reused_track`, `duration`, `weak_tracking`. |
| `error` | `stages.py:237-238`, `229`, `232` | A clip or backup failed: `error`, and for ffmpeg the exact `cmd` and `stderr_tail`. |

3. For an ffmpeg failure, the `cmd` in the `error` event is the exact command; the filter graph it
   used is `jobs/<job>/clips/<clip>/graph.txt`.
4. Corrupt JSON (for example a hand-edited `review.json`):
   `error: review.json is not valid JSON: <path> (<reason> at line N); fix or restore the file`
   (`src/shorts/jobs.py:103-111`). The review page shows the same text as `Error: ...`.
