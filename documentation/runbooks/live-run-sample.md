# Live run on the 10-minute sample

> Reader: Natã, during the first real end-to-end run of S2. Print it or keep it open next to
> Terminal, tick each step and write in the "Owner notes" space. Every command was checked
> against `uv run shorts <cmd> --help` and the code on 29/09/2026 (branch `s2-analysis-review`).
> What each command starts behind the scenes:
> [commands-and-external-programs.md](../architecture/commands-and-external-programs.md).
> Every flag and message: [shorts-cli.md](../features/shorts-cli.md).

## Purpose and what success looks like

The code is finished and 337 tests pass, but no test has run the real `claude`, a real browser
or a real render of an analyzed clip. This run proves the chain on real footage, from the master
to finished Shorts, and records numbers that only a real run can give (tokens, times, sizes).

Success means:

- `ingest` creates job `260927-amostra-10min` with a `words.json`.
- `analyze` prints at least one candidate, and a second `analyze` makes zero new LLM calls.
- The review page plays the master, and approvals and edits survive a page reload.
- `track`, `captions` and `render` finish for every approved clip, a second `render` prints
  `skipped (fresh)`, and `run` prints `every approved clip of 260927-amostra-10min is rendered`.
- Each render is 1080x1920 H.264 with AAC audio, and looks and sounds right to you.

## Sample quality

Measured with ffprobe (`/opt/homebrew/opt/ffmpeg-full/bin/ffprobe`) on 29/09/2026.

| | Sample `samples/amostra-10min.mov` | Full master `masters/260927-catequese-permanente-1.mov` |
|---|---|---|
| Video | HEVC Main, 1920x1080, yuv420p, bt709 (SDR) | HEVC Main, 1920x1080, yuv420p, bt709 (SDR) |
| Frame rate | 30 fps nominal (average 29.997, variable) | 30 fps nominal (average 29.997, variable) |
| Video bitrate | 7,688,543 bit/s (about 7.69 Mbps) | 8,202,221 bit/s (about 8.20 Mbps) |
| Audio | AAC LC, mono, 48 kHz, about 98.6 kbps | AAC LC, mono, 48 kHz, about 98.6 kbps |
| Duration | 600.07 s | 6,056.9 s (1 h 41 min) |
| Size | 585,037,881 bytes | 6,340,388,026 bytes |
| Extra streams | none | 4 QuickTime "data" streams (Core Media Metadata) |
| Container tags | written by `Lavf63.1.102` (ffmpeg's muxer); the video stream still says `HEVC` | iPhone software 26.6.1, created 27/09/2026 19:08:10 UTC |

**What this means.** Same codec, profile, resolution, pixel format, colour tags and audio, and a
near-identical bitrate (the difference is normal, since HEVC spends more bits on busier minutes).
The container was rewritten by ffmpeg and the data streams dropped. This is **consistent with**
a 10-minute cut taken at 40:00 of the master without a second lossy re-encode (for example an
ffmpeg stream copy), but these numbers cannot prove it. The plan docs only say "a 10-min cut at
40:00 of the real master" (`docs/superpowers/plans/2026-09-29-01-vertical-slice.md:33`) and do
not say how it was cut. Either way, the sample is a fair stand-in for the master.

**The honest limit on sharpness.** The source is 1080 px tall. A vertical 9:16 window cut from
it is only about 608 px wide, and the output is 1080x1920, so every Short is an **enlarged crop**
(code: `src/shorts/shots.py:143-145`, `CLOSE_ZOOM` at `shots.py:11`; sizes printed from the
code):

| Shot | Crop from 1080p | Enlargement to 1920 px tall | Same shot from a 4K (2160p) master |
|---|---|---|---|
| Wide | 608 x 1080 | 1.78x | 1216 x 2160, shrunk 0.89x (sharp) |
| Close-up, standing (zoom 1.4) | 434 x 772 | 2.49x | 868 x 1542, 1.25x |
| Close-up, seated (zoom 1.6) | 380 x 676 | 2.84x | 760 x 1350, 1.42x |

The render enlarges with the Lanczos filter (`src/shorts/render.py:124`), which is the best
general-purpose choice, but no filter adds detail that was never recorded. Expect wide shots to
look acceptable and close-ups visibly soft, whatever the sample. Recording in 4K would fix most of
it: the roadmap already plans 4K masters (`_think/roadmap.md`, owner checklist) and `shorts
doctor` sizes its disk warning for them (`src/shorts/doctor.py:15`). 4K decode and render times
are not measured.

**Output encoder** (`src/shorts/render.py:163-170`): H.264 by `h264_videotoolbox` (the Mac's
hardware encoder), 10 Mbps average, 14 Mbps peak, High profile, yuv420p, bt709 tags, 30 fps,
`+faststart`; audio AAC 160 kbps, 48 kHz. The spec expects about 75 MB for 60 s (spec 10.5).

## Pre-flight checklist

Open two Terminal windows. In both: `cd ~/dev/albatroz-shorts`. Window 1 runs the commands;
window 2 will hold the review page server (it keeps running until Ctrl+C).

- [ ] **Right branch, clean tree.** `git status` shows `On branch s2-analysis-review` and nothing
      to commit.
- [ ] **Environment in sync.** `uv sync` ends without errors.
- [ ] **Disk space.** `df -h ~/dev/albatroz-media`: at least 10 GB available (19.7 GB on
      29/09/2026). This run needs well under 1 GB: the master copy below is a clone and costs
      almost nothing, and each render is roughly 40 to 75 MB.
- [ ] **`claude` is logged in on the Max plan.** `claude --version` only proves the program starts,
      and `shorts doctor` checks nothing more. Run `claude auth status` (read-only). Look for
      `"loggedIn": true`, `"authMethod": "claude.ai"` and `"subscriptionType": "max"`. On
      29/09/2026 it showed exactly that. Also run `echo $ANTHROPIC_API_KEY`: an empty line is
      expected. The tool removes that variable before calling `claude` anyway
      (`src/shorts/llm/claude_cli.py:25`, `53-54`), so this is only for your peace of mind.
      The tool itself does not verify the login.
- [ ] **Usage window.** Start with a fresh Max usage window if you can: the detail pass uses
      `claude-opus-5-5` (`config.toml:19-21`). If the limit hits, nothing is lost (Step 3).
- [ ] **Place a copy of the sample in `masters/`.** This is required, see the note below.

      cp -c ~/dev/albatroz-media/samples/amostra-10min.mov ~/dev/albatroz-media/masters/260927-amostra-10min.mov

      `cp -c` makes an APFS clone: a second file name that shares the same bytes on disk until one
      of them changes (`man cp`: "copy files using clonefile(2)"). Check:
      `ls -la ~/dev/albatroz-media/masters ~/dev/albatroz-media/samples` shows both files at
      585037881 bytes.

**Why the copy matters (verified in `src/shorts/ingest.py`).** `shorts ingest` never copies a
master. If the video is outside `<media_root>/masters/`, it **renames (moves)** it into
`masters/<job id>.<ext>` (`ingest.py:43-56`, the move is `video.rename(dst)` at line 55). Running
ingest on `samples/amostra-10min.mov` directly would move the test sample away, and the
`SHORTS_SAMPLE` tests (and `shorts clip` examples) would lose it. A file that is already in
`masters/` is left where it is, and its job id is its file name without the extension
(`make_job_id`, `ingest.py:33-40`). So the copy above gives:

- job id: **`260927-amostra-10min`** (260927 = the recording date of the master, the same naming
  rule as `260927-catequese-permanente-1`, and the name the plan uses);
- job folder: `~/dev/albatroz-shorts/jobs/260927-amostra-10min/`;
- render folder: `~/dev/albatroz-media/renders/catholic-br/260927-amostra-10min/`.

If you pick another file name, the job id changes with it; replace it everywhere below.

---

### Step 1: Environment check
Command: `uv run shorts doctor`
What it does behind the scenes: checks that ffmpeg-full has libass, VideoToolbox and zscale
(runs `ffmpeg -filters` and `ffmpeg -encoders`), that `whisper-cli` and its model exist, that
transcreve has `--palavras` (runs `python3 transcreve.py --help`), that the Anton font and
safe-zone template exist, that the media root is writable, free disk space, and runs
`claude --version` (reference section 4, row `doctor`).
Expected: 12 lines, all `[ok  ]`, exit code 0. On 29/09/2026:
```
[ok  ] ffmpeg-full: /opt/homebrew/opt/ffmpeg-full/bin/ffmpeg
[ok  ] libass (subtitles filter): needed for captions
[ok  ] h264_videotoolbox: hardware H.264 encoder
[ok  ] zscale (HDR to SDR): needed for iPhone HDR masters
[ok  ] whisper-cli: /opt/homebrew/bin/whisper-cli
[ok  ] whisper model: ~/.cache/whisper-models/ggml-large-v3-turbo.bin
[ok  ] transcreve --palavras: ~/dev/transcreve/transcreve.py
[ok  ] Anton font: ~/dev/albatroz-reels/assets/fonts/Anton-Regular.ttf
[ok  ] safe-zone template: ~/dev/albatroz-reels/assets/safe-zone.png (only for --safe-zone)
[ok  ] media root writable: ~/dev/albatroz-media
[ok  ] disk space: 19.7 GB free (warn below 10, fail below 3)
[ok  ] claude CLI: 2.1.284 (Claude Code)
```
A few seconds.
Check: no `[FAIL]` line. A `[warn]` on disk space means under 10 GB free: fine for this run.
There is no rclone line because `backup.auto = false`.
If it fails: each `[FAIL]` line names what is missing and usually how to install it
(`brew install ffmpeg-full`, `brew install whisper-cpp`, "set SHORTS_TRANSCREVE"). Fix it and run
doctor again; doctor changes nothing, so rerunning is always safe.
Owner notes:



Result: [ ] pass  [ ] fail  [ ] needs discussion

### Step 2: Create the job and transcribe
Command: `uv run shorts ingest ~/dev/albatroz-media/masters/260927-amostra-10min.mov --channel catholic-br --format solo-standing`
What it does behind the scenes: reads the file header with `ffprobe`, creates
`jobs/260927-amostra-10min/job.json`, then runs
`/usr/bin/python3 ~/dev/transcreve/transcreve.py <master> --palavras --idioma pt --saida jobs/260927-amostra-10min --prompt "<catholic-br glossary>"`.
transcreve extracts the audio with ffmpeg and transcribes it with `whisper-cli`
(large-v3-turbo). The tool then renames `260927-amostra-10min.palavras.json` to `words.json`
(reference section 2, rows transcreve, ffmpeg, whisper-cli). The master is not moved, because it
is already in `masters/`.
Expected: nothing for a while, then `job 260927-amostra-10min ready: ~/dev/albatroz-reels/jobs/260927-amostra-10min`.
No warning (the sample is 1080p SDR). About 1.5 minutes: transcription was measured at 87 s per
10 min of audio (spec section 5).
Check: `ls jobs/260927-amostra-10min` shows `job.json`, `words.json`, `log.jsonl` and
`260927-amostra-10min.md` (transcreve's readable transcript). Open the `.md` and skim a paragraph:
are the words right, including glossary terms (Agostinho, Magistério, Eucaristia)? Note that the
existing `samples/amostra-10min.palavras.json` is not used; ingest transcribes again.
If it fails:
- `error: transcreve failed (exit N); fix it and run the same `shorts ingest` again ... (it resumes)`:
  the reason is in `log.jsonl` (the `transcreve` event has its stderr). Rerunning the same
  command is safe: it reuses `job.json` and only retries the transcription.
- `error: transcreve finished but ... is missing (is it the --palavras version?)`: the script in
  `config.toml` `[transcreve]` is an old copy without `--palavras`.
- `error: job 260927-amostra-10min is already ingested (...)`: it already worked; go on.
- `error: ... already exists` or `... is on another volume`: the file is not where this runbook
  put it; check the pre-flight copy.
Owner notes:



Result: [ ] pass  [ ] fail  [ ] needs discussion

### Step 3: Analyze (the three LLM passes)
Command: `uv run shorts analyze 260927-amostra-10min`
What it does behind the scenes: cuts the transcript into 120 s windows that overlap by 30 s,
sends them in batches of 10 to `claude -p` with `claude-haiku-4-5` to score each window 0 to 100,
keeps windows scoring 60 or more (at most 40), sends each kept window to `claude-opus-5-5` to
propose clips, then sends the clips in batches of 5 to `claude-sonnet-5` twice (a blind review
without context and a faithful review with 3 minutes of context). Every answer is cached.
The only external program is `claude` (reference sections 1.1 and 4). For 10 minutes of class
the code gives about 6 or 7 windows, so expect 1 scan call, one detail call per kept window and 2
review calls per 5 candidates (an estimate from the code, not measured).
Last, the caption fixes: a class sheet (`claude-haiku-4-5`, 1 call for 10 minutes) and one `claude-sonnet-5` call per 500-word chunk near a candidate (the sample has 1,587 words, so at most 4 chunks).
Expected: `<N> candidates from <S> of <W> windows; <F> caption fixes (<M> dropped). Next: shorts review 260927-amostra-10min`.
Duration not measured; each call can take up to the 900 s timeout
(`src/shorts/llm/claude_cli.py:39`).
Check:
- `ls jobs/260927-amostra-10min/analyze` shows `scan.json`, `candidates.json` and `cache/`.
- Count the LLM calls and write the number down (Step 4 compares it):
  `grep -c '"kind": "llm"' jobs/260927-amostra-10min/log.jsonl`
- Tokens per model (one line per model, so per pass), for the "Numbers to record" table:
  ```
  uv run python - jobs/260927-amostra-10min/log.jsonl <<'PY'
  import json, sys
  totals = {}
  for line in open(sys.argv[1]):
      e = json.loads(line)
      if e.get("kind") == "llm" and e.get("ok"):
          t = totals.setdefault(e["model"], [0, 0, 0])
          t[0] += 1; t[1] += e.get("input_tokens") or 0; t[2] += e.get("output_tokens") or 0
  for model, (calls, tin, tout) in totals.items():
      print(f"{model}: {calls} calls, {tin} input tokens, {tout} output tokens")
  PY
  ```
  (haiku = scan + class sheet, opus = detail, sonnet = both reviews + caption fixes; with `config.toml` backends the caption-pass `llm` events also carry `"pass": "class_sheet"` or `"caption_fix"`.)
- `grep -c candidate_dropped jobs/260927-amostra-10min/log.jsonl`: clips the model proposed with
  words not found in the transcript. A few are normal; many would be worth discussing.
- Cost check: the last printed line is
  `LLM cost this run: $X.XX API-equivalent (N calls, cache saved $0.00)`. Then run
  `uv run shorts cost 260927-amostra-10min` and write down, in "Numbers to record", the total,
  the cost per class minute and the token table (with the cache columns). For comparison, this
  sample's first run (30/09/2026, before S4) logged 11 calls and $0.96: haiku scan 1 call $0.04,
  opus detail 6 calls $0.67, sonnet reviews 4 calls $0.25. A list-price estimate, not a bill.
If it fails:
- `error: LLM usage limit reached (...). Finished calls are cached; run `shorts analyze 260927-amostra-10min` again when the limit resets.`:
  write down the exact wording in the notes (the limit detection matches words like "usage
  limit", "hit your limit", "quota", `claude_cli.py:22`; real wording is unverified). Wait, then
  rerun the same command. Safe and resumable.
- `<W> windows scanned; none reached the threshold. 0 candidates.`: not a crash. The rest of the
  runbook needs candidates; note it, open `analyze/scan.json` to see the scores and reasons, and
  discuss (the threshold is `scan_threshold = 60` in `config.toml:4`).
- `error: claude -p failed: ...`: read the text; if it mentions login, run `claude auth status`.
- `error: the `claude` CLI is not on PATH ...`: open a new Terminal window and retry.
- `error: analyze failed: <type>: ... (see <log>)`: an unexpected answer; copy the whole line and
  the last lines of `log.jsonl` into the notes. Rerunning is safe (cached calls are not repeated).
Owner notes:



Result: [ ] pass  [ ] fail  [ ] needs discussion

### Step 4: Analyze again (cache proof)
Command: `uv run shorts analyze 260927-amostra-10min`
What it does behind the scenes: the same passes, but each call's key (prompt text, prompt file,
model, cache version) matches a file in `analyze/cache/`, so no `claude` process starts
(reference section 4; shorts-cli.md, "Stage keys and caching").
Do this **before** Step 6: once `review.json` holds a decision, analyze refuses to run.
Expected: the same line as Step 3, with the same numbers. A few seconds.
Check: `grep -c '"kind": "llm"' jobs/260927-amostra-10min/log.jsonl` gives the same number as in
Step 3 (cache hits write `llm_cache_hit` events, never `llm` events). `candidates.json` has the
same clip ids.
- Cost check: the printed line is
  `LLM cost this run: $0.00 API-equivalent (0 calls, cache saved $X.XX)`, with X.XX close to
  Step 3's cost. `uv run shorts cost 260927-amostra-10min` lists both runs; the second one has
  0 calls and the cache savings.
If it fails:
- The count went up: look at the new `llm` lines. If Step 3 logged `review_missing` events, those
  batches were not cached on purpose and are retried now; that is expected. Any other new call is
  a finding to discuss.
- `error: ... already holds review decisions ...`: you clicked approve or reject already. Skip
  this step (do not use `--force` just for this; it archives your review).
Owner notes:



Result: [ ] pass  [ ] fail  [ ] needs discussion

### Step 4b: Caption fixes on the sample

Command: `uv run shorts fixwords 260927-amostra-10min --topic "<one line about the class>"`
What it does behind the scenes: reruns only the caption context pass (reference section 4, row
`fixwords`). The class sheet and the chunks already answered in Step 3 come from the cache unless
the topic changed; a new topic asks again.
Expected: `<F> caption fixes (<M> dropped) from <C> of <T> chunks. Next: shorts review 260927-amostra-10min`.
Check:
- The Aramaic phrase: `grep -n "sabact" jobs/260927-amostra-10min/analyze/corrections.json` shows
  an edit over the raw slots of `la massa bactamia.` (about 393.4 s, raw indices 1089-1091) with
  tokens like `"lamá", "sabactâni?"`, and an edit giving `Eloí` its accent.
- The Hebrew pair: an edit or an unchanged word reads `kaaru` near "cavaram"; `kaari` stays if the
  speaker says it.
- No false edits: open `corrections.json` and read every edit. Each one should fix a real
  mishearing. Write down any edit that changes a word that was already right; that is a finding.
- Dropped and rejected: `grep -c fixword_dropped jobs/260927-amostra-10min/log.jsonl` and
  `grep -c fixword_chunk_rejected jobs/260927-amostra-10min/log.jsonl` (rejected should be 0).
- Tokens: the token script of Step 3 now shows the caption calls under haiku and sonnet.
If it fails:
- `error: LLM usage limit reached (...)`: wait, rerun the same command; finished chunks are cached.
- `warning: 1 chunk(s) rejected ...`: the model rewrote a passage; rerun once. If it repeats on the
  same words, note the chunk and the `fixword_chunk_rejected` line.
Owner notes:



Result: [ ] pass  [ ] fail  [ ] needs discussion

### Step 5: Open the review page
Command (in Terminal window 2): `uv run shorts review 260927-amostra-10min`
What it does behind the scenes: starts a small web server on your Mac only (127.0.0.1, port
8765) and opens your default browser. The page reads the candidates, and the video player
streams the master straight from `masters/` (reference section 4, row `review`).
Expected: `review page: http://127.0.0.1:8765/  (Ctrl+C to stop)` and a browser tab with the
title `Shorts review · 260927-amostra-10min` and the line
`<N> candidates · 0 approved · 0 rendered · channel catholic-br · solo-standing`.
Check (click and watch):
- [ ] Every clip is a closed drawer (clip id, title, status, render state); a click on the line opens it, and after Cmd+R the same drawers are open.
- [ ] Cards appear, best total score first. Near-identical variations of one hook sit together in
      a dashed box labelled `variations of hook h-... (hook_id)`. Candidates the faithful review
      rejected are under "Dropped candidates" at the bottom.
- [ ] Each card shows: total score, `▶ play`, the clip id with `~Ns after silence cut`,
      `approve`, `reject`, editable title and hook, badges (controversy, verdict, warnings such as
      `blind_failed`, `too_long`, `out_of_order`), "who reacts", four score bars (hook, value,
      conversation, emotion) with the model's reason, the words of the clip, and segment buttons.
- [ ] `▶ play` on a card: the player jumps to the clip start and plays. At the end of a segment it
      stops, or jumps to the next segment, within a frame or two (fix I5, not yet tried in a real
      browser). The line next to the player shows `<clip id> · <title>`.
- [ ] While it plays, drag the player's own time bar: the clip playback stops following the
      segments (your seek wins).
- [ ] Seeking far into the video responds within a few seconds (a 585 MB `.mov` served in
      byte ranges; not tested in a browser before).
- [ ] Words corrected automatically are light blue with a dotted underline; hovering shows `automatic fix of "<transcribed text>": <reason>`; the card shows `N automatic caption fixes`.
- [ ] The hint line names your keyboard's key first (on the Mac: `Option (⌥)+click (Alt on Windows)`).
If it fails:
- The video stays black or will not play: note the browser and version. Try Safari. Which
  browsers play this HEVC `.mov` is not verified.
- `Error: ...` in the header: the page could not read the job; the text says which file (for a
  corrupt `review.json`: `review.json is not valid JSON: ...`).
- The server does not start because the port is busy: stop the other server, or run
  `uv run shorts review 260927-amostra-10min --port 8766` and open `http://127.0.0.1:8766/`.
- Closing the tab does not stop the server; Ctrl+C in window 2 does. Restarting it is safe.
Owner notes:



Result: [ ] pass  [ ] fail  [ ] needs discussion

### Step 6: Approve, reject and edit
Command: none (clicks on the review page from Step 5; the server keeps running in window 2).
What it does behind the scenes: every click sends a small request to the local server, which
checks it and writes `jobs/260927-amostra-10min/review.json` at once
(`src/shorts/review/state.py:65-149`). No external program.
Expected: approve 2 or 3 clips, reject at least 1, leave the rest pending. On approve, the card's
left border turns green and the header count goes up; a rejected card turns red-bordered and
fades.
Check:
- [ ] Reload the page (Cmd+R): every decision and edit is still there.
- [ ] On one approved clip, click `start +0.5` then `start −0.5`: the `seg 1: MM:SS–MM:SS` label
      and the `~Ns after silence cut` estimate change and change back.
- [ ] `start ◀ sentence` with the start in the middle of a sentence goes to the start of **that**
      sentence; pressing it again goes to the previous sentence. Same for `end ▶ sentence` at the
      end (fix I4, not yet tried in a real browser).
- [ ] Click a word: the clip now starts just before it. Shift+click a word: it ends just after it.
- [ ] Option (⌥)+click a word on a Mac, or Alt+click on Windows: a box asks `Correct this word (its timing is
      kept). Leave it blank to remove the word:`. Type the fix: the word turns yellow. This fix will be burned into the captions.
- [ ] Option-click an automatic fix and type a different text: the whole range shows your text in yellow; after a reload it is still there.
- [ ] Change a title and press Enter (it saves when you leave the field). Try a title longer than
      60 characters: the line next to the player shows
      `Not saved: title is longer than 60 characters`.
- [ ] Edit a rendered clip: its drawer turns from `rendered vN` to `out of date (vN)` without a reload.
- [ ] In window 1: `cat jobs/260927-amostra-10min/review.json` shows `"status": "approved"` or
      `"rejected"` per clip id, and your `segments`, `title` and `word_fixes`.
If it fails: `Not saved: <reason>` means the server refused the edit and wrote nothing (for
example `segments overlap`, `title cannot be empty`); the reason is the message. A click that
does nothing: note which button and check the browser's console (View, Developer). Safe to retry.
Owner notes:



Result: [ ] pass  [ ] fail  [ ] needs discussion

### Step 7: Track the approved clips (with preview)
Command: `uv run shorts track 260927-amostra-10min --preview`
What it does behind the scenes: for each approved clip, `ffprobe`, then ffmpeg `silencedetect`
on each segment (the silence cut), then ffmpeg decodes the segments at 3 fps and 640 px into
Apple Vision (body and face boxes), smooths the virtual camera, plans wide and close-up shots,
and renders a small preview with ffmpeg (reference sections 3.1, 3.2, 3.6).
Expected: one line per approved clip,
`<clip id>: track done (preview: ~/dev/albatroz-reels/jobs/260927-amostra-10min/clips/<clip id>/track-preview.mp4)`.
Possibly `warning: weak tracking (NN% of samples without a person)`. Duration not measured.
Check: open each preview: `open jobs/260927-amostra-10min/clips/<clip id>/track-preview.mp4`.
The lime rectangle is the 9:16 window the Short will show; the red one is the person Vision
follows. The lime box should keep you inside, move smoothly, and hold still while you stand
still; it switches to a smaller box during close-ups.
If it fails: `<clip id>: FAILED track: <reason> (details in .../log.jsonl)`; the `error` event in
`log.jsonl` holds the exact ffmpeg command and its error. Other clips still run. `error: master
not found: ... (was it moved?)`: the master copy is gone; redo the pre-flight copy. Rerunning is
safe; Vision is skipped for clips whose tracking is still fresh.
Owner notes:



Result: [ ] pass  [ ] fail  [ ] needs discussion

### Step 8: Captions
Command: `uv run shorts captions 260927-amostra-10min`
What it does behind the scenes: redoes the cheap part of tracking (silence detection, shots)
while reusing the saved Vision data, then writes the burned-in caption file `captions.ass`
(reference section 4, row `captions`). No Vision, no `claude`.
Expected: `<clip id>: captions done` per approved clip. Faster than Step 7 (not measured).
Check: `jobs/260927-amostra-10min/clips/<clip id>/captions.ass` exists; open it in TextEdit: the
`Dialogue:` lines hold the words, with your word fix from Step 6. In `log.jsonl`, the new
`clip_stage` events say `"reused_track": true`.
If it fails: same pattern as Step 7 (`FAILED captions: ...`, details in `log.jsonl`). Safe to rerun.
Owner notes:



Result: [ ] pass  [ ] fail  [ ] needs discussion

### Step 9: Render
Command: `uv run shorts render 260927-amostra-10min`
Or on the review page: `render` on one drawer, or `render all (N)` in the header; the drawer shows `queued`, `rendering…`, then `rendered v4`, and `▶ watch` plays it.
What it does behind the scenes: measures colour once for the job (ffmpeg, 2 points for a 10-minute
master, saved to `color.json`), then per approved clip: tracking and captions as above, a
loudness measurement pass, and one ffmpeg render with the silence cut, crop windows, colour,
Lanczos enlargement, captions, voice cleanup and loudness, encoded by VideoToolbox (reference
sections 3.3, 3.4, 3.5).
Expected: per clip,
`<clip id>: render done -> ~/dev/albatroz-media/renders/catholic-br/260927-amostra-10min/<clip id>.mp4`.
Duration not measured (record it). Then run the same command a second time: every line should
read `<clip id>: skipped (fresh) -> ...` within seconds.
Check: `ls -la ~/dev/albatroz-media/renders/catholic-br/260927-amostra-10min/` shows, per clip,
`<clip id>.mp4`, `<clip id>.json` and `<clip id>.mp4.key`, and no `.tmp.mp4` left. Watch every
render (see "What to judge in the renders").
If it fails: `<clip id>: FAILED render: ...`; the `error` event in `log.jsonl` has the exact ffmpeg
command and the last 20 lines of its error; the filter graph is in
`jobs/260927-amostra-10min/clips/<clip id>/graph.txt`. A failed render leaves the old file (if
any) untouched. `(color): FAILED render: ...` means the colour measurement failed and nothing
rendered. Rerunning is safe and only redoes clips that are not fresh.
Owner notes:



Result: [ ] pass  [ ] fail  [ ] needs discussion

### Step 10: `run` says everything is done
Command: `uv run shorts run 260927-amostra-10min`
What it does behind the scenes: works out the next stage from the files and keys; nothing to do
means no external program (reference section 4, row `run`).
Expected: `every approved clip of 260927-amostra-10min is rendered`. Instant.
Check: exit code 0 (`echo $?`).
If it fails: if it starts rendering instead, some approved clip was not fresh (for example you
edited it on the review page after Step 9). Let it finish and run the command again.
Owner notes:



Result: [ ] pass  [ ] fail  [ ] needs discussion

### Step 11: Safe-zone check render (never the deliverable)
Command: `uv run shorts render 260927-amostra-10min --safe-zone`
What it does behind the scenes: the same render with `assets/safe-zone.png` overlaid, half
transparent, on the orange areas (where Instagram and YouTube draw buttons and text). It
**overwrites** the deliverable `.mp4` files (reference section 3.5, item 8).
Expected: every clip renders again (the flag changes the render key), then
`note: --safe-zone overlay renders overwrite the deliverable path; run `shorts render 260927-amostra-10min` without it for the final files`.
Check: in each render, captions and your face stay out of the orange areas. Then restore the
final files and prove a safe-zone render does not count as done:
1. `uv run shorts run 260927-amostra-10min`: it must **not** say "rendered"; it re-renders every
   clip without the overlay (`src/shorts/stages.py:242-243`).
2. `uv run shorts run 260927-amostra-10min` again: `every approved clip of 260927-amostra-10min is rendered`.
3. Open one render: no orange overlay.
If it fails: `<clip id>: FAILED render: .../assets/safe-zone.png is missing; copy Natã's safe-zone
template there (see CLAUDE.md)`: copy the template to `assets/safe-zone.png`. If `run` in check 1 says "rendered", that is a bug to report.
Owner notes:



Result: [ ] pass  [ ] fail  [ ] needs discussion

### Step 12: Clean the renders of rejected clips
Command: `uv run shorts clean 260927-amostra-10min`
What it does behind the scenes: deletes `.mp4`, `.json` and `.key` files of clips marked
**rejected**, only inside `renders/catholic-br/260927-amostra-10min/`. Approved and pending clips,
masters and Drive are never touched (`src/shorts/clean.py:18-41`). No external program.
Expected: rejected clips were never rendered, so a first run prints nothing. To really test it:
on the review page, reject one clip you rendered in Step 9, then run the command. This deletes
that clip's render; approve it again and run `shorts render` to get it back. Output:
`removed ~/dev/albatroz-media/renders/catholic-br/260927-amostra-10min/<clip id>.json`
and `removed .../<clip id>.mp4`.
Check: `ls` of the render folder: the rejected clip's files are gone, the others are there.
If it fails: `error: unsafe ...` means an odd job or channel id; report it. Safe to rerun.
Owner notes:



Result: [ ] pass  [ ] fail  [ ] needs discussion

### Step 13 (optional): Backup to Google Drive
Command: `uv run shorts backup 260927-amostra-10min --dry-run`, then `uv run shorts backup 260927-amostra-10min`
What it does behind the scenes: runs
`rclone copy ~/dev/albatroz-media/renders/catholic-br/260927-amostra-10min gdrive:albatroz-media-backup/renders/catholic-br/260927-amostra-10min --exclude '*.tmp.mp4' --exclude '*.tmp' --exclude '*.key'`
(plus `--dry-run -v` for the dry run). Copy only, never sync, never deletes on Drive (reference
section 2, row rclone).
Expected: rclone lists the `.mp4` and `.json` files it would send, then sends them. rclone was
not installed on 29/09/2026, so first do the one-time setup in
[docs/runbooks/drive-backup.md](../../docs/runbooks/drive-backup.md).
Check: the Drive folder `albatroz-media-backup/renders/catholic-br/260927-amostra-10min` holds the
files; no `.key` files.
If it fails: `error: [Errno 2] No such file or directory: 'rclone'` (message shape not verified):
rclone is not installed. rclone's own errors print above the exit code 1. Rerunning is safe:
`copy` skips files already on Drive.
Owner notes:



Result: [ ] pass  [ ] fail  [ ] needs discussion

### Step 14: Verify the output files
Command (per render; replace `<clip id>`):
`/opt/homebrew/opt/ffmpeg-full/bin/ffprobe -v error -show_entries format=duration,size:stream=codec_name,profile,width,height,avg_frame_rate,bit_rate,sample_rate,channels -of default=nw=1 ~/dev/albatroz-media/renders/catholic-br/260927-amostra-10min/<clip id>.mp4`
and, for loudness:
`/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg -hide_banner -nostats -i ~/dev/albatroz-media/renders/catholic-br/260927-amostra-10min/<clip id>.mp4 -map 0:a:0 -af ebur128=peak=true -f null -`
What it does behind the scenes: `ffprobe` reads the file header; the ffmpeg line decodes the audio
and prints an EBU R128 loudness summary at the end (read-only; it writes nothing).
Expected (from the render code, `src/shorts/render.py:163-170`): video `h264`, profile `High`,
`1080` x `1920`, `30/1`, bit rate near 10,000,000; audio `aac`, `48000`, 1 channel (the master is
mono and nothing up-mixes it; expected, not verified); duration a little shorter than the clip's
span because pauses are cut. Loudness summary: `I:` near `-14.0 LUFS` and true peak at or below
about `-1.5 dBFS` (`src/shorts/audio.py:12`).
Check: compare the duration with the `duration` field of `<clip id>.json`, and the size with
about 1.3 MB per second.
If it fails: a different size or codec is a finding; copy the ffprobe output into the notes.
Owner notes:



Result: [ ] pass  [ ] fail  [ ] needs discussion

---

## Numbers to record

| What | Where to read it | Value |
|---|---|---|
| Windows scanned / selected / candidates | Step 3 printed line | |
| Candidates dropped by the faithful review | "Dropped candidates" on the page | |
| `candidate_dropped` events | `grep -c candidate_dropped jobs/260927-amostra-10min/log.jsonl` | |
| LLM calls, Step 3 | `grep -c '"kind": "llm"' .../log.jsonl` | |
| LLM calls after Step 4 (should be equal) | same command | |
| LLM cost, Step 3 (API-equivalent) | Step 3 cost line, or `shorts cost` Total | |
| Cost per class minute; projection for 100 min | `uv run shorts cost 260927-amostra-10min --project 100` | |
| Cache saved, Step 4 | Step 4 cost line | |
| Scan tokens (haiku): calls / in / out | token script, Step 3 | |
| Detail tokens (opus): calls / in / out | token script, Step 3 | |
| Review tokens (sonnet): calls / in / out | token script, Step 3 | |
| Caption fixes / dropped / rejected chunks | Step 4b line and log greps | |
| Caption tokens (class sheet haiku, fixes sonnet): calls / in / out | token script | |
| Compare: spec 4.6 estimate for a 2 h class | spec 4.6: ~350k in, ~60k out | |
| Approved / rejected / pending | review page header, `review.json` | |
| Renders produced | Step 9 lines | |
| Wall time: ingest | stopwatch or `time` in front of the command | |
| Wall time: analyze (first) | | |
| Wall time: analyze (cached) | | |
| Wall time: track --preview | | |
| Wall time: captions | | |
| Wall time: render (all clips) | | |
| Wall time: render (second, fresh) | | |
| Per render: clip id, duration, size | Step 14 | |
| Loudness per render (I, true peak) | Step 14 | |
| `weak tracking` warnings | Step 7 output, `.json` `warnings` | |

Tip: prefix a command with `time` (for example `time uv run shorts render 260927-amostra-10min`)
and the shell prints how long it took.

## What to judge in the renders

Watch each render full screen on the phone if you can (AirDrop), and at least once on the Mac.

- **Crop and framing.** Are you inside the frame all the time? Does the camera move only when you
  move, smoothly, without hunting? In close-ups, is your face in the upper third, not cut at the
  top? Any door, wall edge or empty frame?
- **Close-ups.** Do they land on the hook and on emphasis phrases, and switch at a sentence end?
  How soft do they look (see "Sample quality")?
- **Captions.** Words in sync with speech (a word should appear as it is said)? Line breaks at
  natural places, never a lone "de" or "a" at the end of a line? Accents and Ç not clipped?
  Your word fix present?
- **Cuts.** Do the silence cuts feel natural or choppy? Any cut in the middle of a word? For a
  multi-segment clip, does the join make sense?
- **Loudness.** Is the voice clear and as loud as other Shorts on the phone, with no pumping or
  hiss?
- **Colour.** Skin tones natural, not too dark, orange or washed out?
- **Hook.** Do the first 3 seconds make you want to keep watching? Does the clip open mid-thought?
- **Title and hook text** in `<clip id>.json`: would you publish them?

**How to report a problem:** write the file name (`<clip id>.mp4`), the time in the render where
it happens (for example 0:12), what you expected and what you saw. For captions, copy the wrong
words. For framing, a screenshot helps (Cmd+Shift+4 on the paused player).

## Known limits and things only this run can prove

- **Real `claude` usage-limit wording.** The limit is detected by keywords (`src/shorts/llm/claude_cli.py:22`);
  the real message from Claude Code when the Max window runs out has not been seen yet. If it
  happens, copy the exact `error:` line.
- **transcreve's real output name.** The tool expects `jobs/<job>/<master stem>.palavras.json`
  (`src/shorts/ingest.py:105`); the transcreve code writes `<video stem>.palavras.json` into
  `--saida` (`~/dev/transcreve/transcreve.py:408`), which should match, but ingest has never run on
  a real file.
- **Multi-segment and out-of-order renders on real footage.** The render joins 1 to 3 segments in
  playback order, even when a later moment plays first (a cold open). Only fixtures have tested
  this; look for one on the review page and approve it.
- **Browser seeking on a large `.mov`.** The page streams the 585 MB master with byte ranges. It has
  not been tried in Safari or Chrome.
- **Real token counts versus the spec 4.6 estimate** (about 350k input and 60k output for a 2 h
  class). The logged `input_tokens` is what `claude -p` reports; whether it includes prompt-cache
  reads is not verified.
- **Review page fixes I4 and I5** (sentence buttons stop at the current sentence; playback hops
  per video frame) are only covered by a string-level test (`final-fixes-report.md`), not by a
  browser.
- **The upscale limit** above is a property of 1080p masters, not of this sample: judge sharpness
  with it in mind.
