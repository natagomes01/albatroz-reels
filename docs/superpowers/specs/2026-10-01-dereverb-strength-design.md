# Dereverb with a per-class strength: design

Status: approved in conversation by the owner on 01/10/2026 (five sections), written spec waiting for the owner's review.
Written in a brainstorming session with the owner; every choice below is an owner answer unless marked "our extension".
Roadmap: phase S8, audio part (moved ahead of B-roll; `_think/sdd-runs/2026-10-01-S8/SESSION.md`).
Parent specs: `2026-09-28-shorts-pipeline-design.md` (section 10.4 sound, 10.5 render),
`2026-09-30-review-undo-and-choose-design.md` (undo and redo), `2026-10-01-review-render-control-design.md` (render state, drawers).

## 1. Goal

The channel's content producer judged the sample's audio not good enough to go viral: the voice carries
the room. The lapel mic also picks up the voice returned by the PA speaker and the temple, so the
reverb is fused with the voice. EQ, gates and `afftdn` did not help, nor did Instagram's Edits app.
Of thirteen ML variants tried on a 22 s excerpt (SESSION.md, rounds 1 and 2), only
**UVR-DeEcho-DeReverb at aggression 20** helped. Every room is different, so the strength is chosen
per class, by ear, and can be overridden per clip.

Success, on the 10-minute sample: the review page opens with an audio panel holding four players
(off, 10, 20, 30) on the first 20 s of the first candidate; render buttons are disabled until a
strength is chosen; after choosing 20, `render all` renders the four approved clips with dereverbed
sound; setting one clip to 30 re-renders only that clip; a second render at the same strength does
not run UVR again.

## 2. Non-goals

- Fixing the reverb at the source (that is a recording practice: keep the PA from returning the voice
  near the lapel; noted for the owner, not built).
- Other models or a model picker. The Roformer de-reverb models found nothing to remove in this
  material (SESSION.md round 2).
- A per-clip listening comparison of the four strengths. The per-clip override is checked by
  rendering that clip.
- Keyboard shortcuts for the audio panel.
- Dereverb on channels with `sound = false` (their audio stays untouched, as today; our extension).

## 3. Strength and where it is stored

- **Levels** come from `config.toml`:

  ```toml
  [dereverb]
  levels = [0, 10, 20, 30]          # 0 = off; the others are UVR VR-arch aggression values
  model = "UVR-DeEcho-DeReverb.pth"
  model_dir = "~/dev/albatroz-media/models"
  separator = "~/.local/bin/audio-separator"   # the uv tool install (section 7)
  excerpt_seconds = 20
  ```

- **Class strength** lives in the class's `review.json`, top level: `"dereverb": 20`. Absent means
  not chosen yet. The value must be one of `levels`.
- **Clip override** lives in the clip's decision: `decisions[<id>]["dereverb"] = 30`. It is a clip edit
  (`apply_edit` accepts the key `dereverb`; value in `levels`, or `null` to drop the override and follow
  the class). It goes through the S5 undo and redo history like any other edit.
- **Effective strength** of a clip: its override if present, else the class strength.
- **Render key:** the effective strength enters `render_key` in `stages._keys`. Changing the class
  strength re-renders every clip that follows the class; changing a clip's override re-renders that
  clip only. No `RENDER_VERSION` bump: the key change alone marks old renders out of date (our extension).
- **Render gate:** when the channel has `sound = true`, the master has audio and the class strength is
  not chosen, rendering refuses: the page's render buttons are disabled, `POST` render endpoints answer
  409, and `shorts render <job>` exits 1 with `choose the audio strength on the review page first`.
  The existing sample job is gated too.
- **`shorts clip`** (manual flow, no review page) gets `--dereverb N` (N in `levels`); without it the
  sound is not dereverbed, as today. No gate there.

## 4. Processing a clip

New module `src/shorts/dereverb.py`, used by `clip.produce()` before the loudness pass.

1. For each segment window of the clip (`group_edl` windows, the same groups the render reads), cut
   the master audio with 1.0 s of padding on each side (clamped to the master), as 44.1 kHz stereo
   PCM WAV, with `FFMPEG` mapping `0:a:0`.
2. Run UVR on it as an external program, one window at a time:
   `audio-separator <in.wav> --model_filename <model> --model_file_dir <model_dir>
   --output_dir <tmp> --output_format WAV --vr_aggression <N> --single_stem "No Reverb"`.
   Strength 0 skips this whole step.
3. Trim the padding back off and store the result in the media root:
   `<media_root>/cache/<job>/audio/<key>.wav`, `key` = hash of (master hash, window start and end,
   strength, model file name). A cached file is reused; UVR does not run again for the same key.
4. The render's audio inputs become these WAVs, one per window, starting at the window start, so the
   existing `select_expr` and concat logic stay the same with times relative to each window. The
   loudness first pass (`loudnorm_measure`) runs on the same dereverbed inputs, then the existing
   `CLEANUP` (`highpass`, `afftdn`) and `loudnorm` apply as today.
5. Memory: UVR runs as a child process and exits before the video render starts, so its about 3.3 GB
   peak never overlaps the render.
6. Errors: a missing program or model, a non-zero exit, or an output whose duration differs from the
   input by more than 50 ms stops that clip's render with a message naming the cause and the setup
   runbook. A clip is never rendered without dereverb silently.

Measured on 01/10/2026 (M1 8 GB, `audio-separator` 0.47.0): about 7 s for 22 s of audio at
aggression 20, peak memory footprint 3.3 GB.

## 5. The strength excerpt

1. **When:** at the end of `run_analyze` (after the caption pass), and on review page load when the
   excerpt files are missing (a class analysed before this build, like the sample).
2. **What:** the first `excerpt_seconds` of the first candidate's sound (its segments in order, silence cuts applied as in the render), the first candidate in class order. One
   file per level, each through dereverb (except 0), `CLEANUP` and two-pass `loudnorm`, as AAC in
   `.m4a`, so each sounds like the final render.
3. **Where:** `<media_root>/cache/<job>/audio/excerpt-<level>.m4a`, never in Git. Served by the review
   server at `/media/excerpt/<level>`.
4. **On the page while missing:** the panel shows `Preparing audio…` and asks again every 2 s (same
   polling as the render state). Generation runs in the server's existing background worker, never
   while a render runs (one heavy job at a time; our extension).
5. **On error:** the panel shows the message and a `Try again` button; the rest of the page works;
   only rendering stays gated.

## 6. Review page

1. **Audio panel**, between the header and the video. Open while no strength is chosen: four rows
   `off`, `10`, `20`, `30`, each with a play button and a `Choose` button. Playing one stops any other
   playback (players and the master video).
2. **After choosing**, the panel collapses to one line: `Audio: dereverb 20 · change`. `change` opens the
   four rows again. Choosing writes the class strength (`POST /api/audio`, body `{"dereverb": 20}`).
3. **Gate on the page:** while unchosen, `render all` and every clip's `render` are disabled with the
   tooltip `Choose the audio strength first`.
4. **Per clip:** a select among the clip's edits, `Audio: class (20)` (the default, meaning no override)
   plus `off`, `10`, `20`, `30`. A clip whose effective strength differs from the class shows
   `audio 30` in its drawer head, in the chip style of S6.
5. All new controls are buttons or selects reachable by Tab and Enter. Interface text is English, as
   the rest of the page. Colours come from `tokens.css`; the S6 contrast test covers any new token.

## 7. Install, doctor and documentation

**Install** (in the new runbook below, the owner's request):

```
uv tool install --python 3.12 "audio-separator[cpu]==0.47.0" \
  --with audioread --with standard-aifc --with standard-sunau
```

and the model file `UVR-DeEcho-DeReverb.pth` in `model_dir` (downloaded by `audio-separator` on first
use, or copied from the media root backup).

- **`shorts doctor`** gains two checks: the `separator` program runs (`--version`) and the model file
  exists. A failure names the runbook section.
- **New runbook** `documentation/runbooks/new-machine-setup.md`: everything to start the app on a new
  Mac (uv, `uv sync`, ffmpeg-full, the git hook, transcreve, and the UVR install above), each step with
  its check command. Linked from `documentation/README.md` "Start here".
- **User guide:** choosing the strength on the review page and the per-clip override, in
  `documentation/features/shorts-cli.md`.

## 8. Tests

- **Without UVR** (always run): a fake separator script that copies its input to the expected output
  name. Covers effective strength, the render gate (page endpoints, `shorts render`), the render key
  per strength, the clip edit with undo and redo, cache reuse (the fake counts its calls), padding trim
  and window alignment, duration-mismatch error, excerpt generation and its endpoint.
- **With UVR** (skipped when the separator or model is missing): 5 s of the sample through strength
  20; output differs from the input and keeps its duration within 50 ms.
- **Measure at the end of the build:** time and peak memory of one full sample clip at strength 20,
  recorded in the SDD run record.
