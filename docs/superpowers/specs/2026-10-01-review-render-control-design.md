# Review page render control and one-line caption height: design

Status: approved in conversation by the owner on 01/10/2026 (three sections), written spec waiting for the owner's review.
Written in a brainstorming session with the owner; every choice below is an owner answer unless marked "our extension".
Roadmap: phase S7 (`_think/roadmap.md`, "What comes next" item 1). Branch for the build: `s7-render-control`, from `main`.
Origin: the final pass on the 10-minute sample (`_think/sdd-runs/2026-09-30-final-pass/SESSION.md`, "Owner judgement").
Parent specs: `2026-09-28-shorts-pipeline-design.md` (section 7 review page, section 9 captions, section 10.5 render),
`2026-09-30-review-undo-and-choose-design.md` (S5), `2026-09-30-review-page-brand-design.md` (S6: tokens, chips, contrast).

## 1. Goal

Close the loop between reviewing and rendering. The owner found a caption typo only on the phone, after
every review: fixing it meant the page, then `shorts render` in Terminal, with no sign on the page of
which clips are rendered. With about 40 clips per class, reviewed over several days, the page must
show the render state of every clip, render one clip or all pending clips on request, and stay short
enough to move between clips without long scrolling.

Also: a one-line caption screen sits on the lower line's height today, so the eye jumps between two
heights. It should sit at the upper line's height.

Success, on the 10-minute sample: after the build, the page lists the four clips as one-line drawers
showing `out of date (v3)`; the owner fixes the typo, clicks `render` on that clip, watches it with
`▶ watch` and sees `rendered v4`; after a server restart every state is the same; `render all` renders
the other three, one at a time, while the owner keeps using the page.

## 2. Non-goals

- Translating the interface (English stays; backlog line "Interface translation" in the roadmap).
- Locking against a `shorts render` started in Terminal while the page renders (not guarded today either).
- Any change to `review.json`, `state.py` decisions or edits, or the S5 undo history.
- Persisting the render queue across a server restart (only the per-clip state persists, from disk).
- Rendering pending or rejected clips from the page (only approved clips render, as in the CLI).
- Safe-zone renders from the page (`--safe-zone` stays a CLI flag).

## 3. Render state

Each clip has a **render state**, computed on request from files that exist today; nothing new is stored.

| State | Meaning | Source |
|---|---|---|
| `not rendered` | no `<clip>.mp4` in the render folder | file absent |
| `rendered vN` | `<clip>.mp4.key` equals the key the render would compute now | `jobs.is_fresh`, version from `<clip>.json` `render_version` |
| `out of date (vN)` | a file exists but the key differs (an edit after the render, a new `RENDER_VERSION`, or a safe-zone render) | file present, key differs |
| `queued` | waiting in the page's render queue | server memory |
| `rendering…` | the worker is rendering it now | server memory |
| `failed` | the last render from the page exited with an error; hover shows the last error line | server memory; `log.jsonl` has the detail |

`queued`, `rendering…` and `failed` override the disk state while the server runs. After a restart a
failed clip shows its disk state again (`not rendered` or `out of date`).

`vN` is read from `<clip>.json`; a missing or unreadable `.json` next to an existing `.mp4` shows `v?`.

## 4. Page

### 4.1 Drawers

Every card (candidates and "Dropped candidates") becomes a drawer. The closed drawer is one line:

```
▸ c6e1125 · Salmo 22: 'transpassaram' ou 'como leão'?   approved   rendered v3        ▶ watch
▸ ce6331b · Moisés escreveu a própria morte em Deut…     approved   out of date (v3)   render
▸ cf02d53 · Os apóstolos usavam a Bíblia grega…          approved   rendering…
▸ cc85036 · Moisés escreveu mesmo a própria morte?       approved   queued
```

- Clip id, title (ellipsis when long), review status chip (approved, rejected, pending), render state
  chip, and actions.
- `render` appears only on an approved clip whose state is `not rendered`, `out of date` or `failed`.
- `▶ watch` appears whenever `<clip>.mp4` exists (even when out of date); it opens the file in a new tab.
- Clicking the header (not its buttons) opens or closes the drawer; `▸` turns to `▾` when open, and the
  header is a button with `aria-expanded`. The open drawer shows today's card body unchanged.
- Open drawers are remembered per job in `localStorage` and reopened on load; first visit: all closed.
  Storage access is wrapped in try/catch (as `theme.js` does); without storage, all start closed.
- Editing the title in the open body updates the drawer header.

### 4.2 Header

The count line gains the rendered count and a button: `4 candidates · 4 approved · 3 rendered` and
`render all (N)`, where N is the number of approved clips in `not rendered`, `out of date` or `failed`
that are not already queued or rendering. The button is disabled when N is 0.

### 4.3 Updates

The page reads `GET /api/renders` on load, after every decision or edit response (an edit can make a
clip out of date), and every 2 s while any clip is `queued` or `rendering…`. Polling stops when the
queue is empty.

### 4.4 Style

Chips and buttons use the S6 tokens and components. New chips (render states) must pass the S6
contrast floor in light and dark (`tests/test_review_contrast.py`). `rendering…` may pulse only under
`prefers-reduced-motion: no-preference` (our extension).

## 5. Server

### 5.1 CLI: `--clip`

`shorts render <job> --clip <id> [--clip <id> ...]` renders only the named clips, with today's rules:
only approved clips, fresh ones print `skipped (fresh)`. `run_clip_stage` gains `clip_ids: set[str] | None`
(None means all approved clips). A named clip that is not approved or not in the job prints
`<id>: not approved, nothing rendered` (or `unknown clip`) and exits 1. `track` and `captions`
get the same flag for symmetry (our extension; same code path).

### 5.2 State function

`stages.render_status(job, app, channel) -> dict[str, dict]` returns, per candidate id,
`{"state": "not_rendered" | "rendered" | "out_of_date", "version": str | None, "approved": bool,
"file": bool}` (`file`: the `.mp4` exists, which is when `▶ watch` shows).
It reuses `_approved_entries`, `_clip_inputs`, `_keys` and `render_path` (with `safe_zone=False`), so
the page and the render cannot disagree on freshness. Non-approved clips get their disk state too
(a rejected clip may still have a file until `shorts clean`).

### 5.3 Queue

A `RenderQueue` in the review server process: an ordered list of clip ids, one worker thread, and a
per-clip `{state, error}` overlay. The worker pops one id, runs
`[sys.executable, "-m", "shorts.cli", "--config", <config>, "--channels", <channels>, "render", <job>, "--clip", <id>]`
as a subprocess (stdout and stderr captured; `shorts.cli` already runs `main()` as a module, and the
review command's own `--config` and `--channels` are passed on), waits, then marks the clip done (overlay cleared) or `failed` with the last non-empty error
line. Enqueueing an id that is queued or rendering is a no-op. The subprocess is the only thing that
touches ffmpeg or Vision, so memory goes back to the system after each clip.

Before spawning, the worker checks that the clip is still approved (`review.json`); a clip rejected or
set back to pending while queued is dropped from the queue and its overlay cleared, so it shows its disk
state again.

The runner is injectable (`RenderQueue(runner=...)`) so tests use a fake.

On server shutdown (Ctrl+C), the queue is cleared and the running subprocess gets up to 5 s to exit:
Ctrl+C in Terminal already sends SIGINT to the whole foreground process group, the subprocess
included, so `render.py` deletes its `.tmp.mp4` in its `finally`. A subprocess still running after
5 s gets one SIGINT (the case of a server stopped some other way), 5 s more, then is killed. The
render writes to `.tmp.mp4` and replaces the `.mp4` only on success, so the previous file stays intact.
A leftover `.tmp.mp4` after a kill is overwritten by the next render of that clip.

### 5.4 Routes

All new routes keep today's guards (host check; POST needs JSON and same origin).

| Route | Body / reply |
|---|---|
| `GET /api/renders` | `{"clips": {<id>: {state, version, approved, file, error?}}, "queue": [<id>...]}` (state includes `queued`, `rendering`, `failed`) |
| `POST /api/render` | `{"id": <clip>}`; 400 if unknown or not approved; replies with the `/api/renders` body |
| `POST /api/render-all` | `{}`; enqueues every approved clip in `not_rendered`, `out_of_date` or `failed`; replies like above |
| `GET /renders/<id>.mp4` | the render file, with byte ranges (same code as `/media/master`) and `Cache-Control: no-store` (a re-render keeps the same path, so the browser must not replay the old file); 404 unless `<id>` is a candidate id of this job and the file exists |

`make_handler` gains `app` and `channel` (resolved once in `serve`, as `cmd_render` does).

## 6. One-line caption height

In `captions.render_ass`, line `li` of an `n`-line screen sits at
`baseline_y - (n - 1 - li) * pitch`, so a one-line screen sits at `baseline_y` (1060 px). New rule: a
one-line screen sits at `baseline_y - style.pitch` (956 px), the normal upper-line height. Two-line
screens do not change. Their upper line sits at 956 px, or 944 px when `line_pitch` picks the tall
pitch; the 12 px difference is accepted (owner to judge at the live check).

`RENDER_VERSION` goes from 3 to 4, so every existing render shows `out of date (v3)`.

## 7. Errors

- Subprocess exit code not 0: `failed`, hover text is the last non-empty line of its output; the CLI
  already logs the `error` event with the ffmpeg command to `log.jsonl`.
- A clip edited while it renders: the render uses `review.json` as read at subprocess start; afterwards
  the key differs and the clip shows `out of date`, which is correct.
- A clip rejected while queued: dropped before its subprocess starts (section 5.3). If it is rejected
  in the instant after the subprocess starts, the CLI prints `not approved, nothing rendered`, exits 1,
  and the page shows `failed` with that line.
- `render_status` failing (for example a corrupt `review.json`): `GET /api/renders` replies 500 with the
  message, and the page shows it in the existing error line; drawers keep their last known state.

## 8. Testing

- `tests/test_captions.py`: a one-line screen's events sit at y=956; a two-line screen's events are
  unchanged (104 and 116 pitch cases).
- `tests/test_stages*.py`: `render_status` goes `not_rendered` -> `rendered` -> `out_of_date` after an
  edit and after a `RENDER_VERSION` change; version read from `.json`, `v?` when missing; `--clip`
  renders only the named clip; a pending clip named with `--clip` renders nothing and exits 1.
- `tests/test_review_server*.py` with a fake runner: one clip at a time in order; duplicate enqueue is a
  no-op; a failing run records `failed` and its last line; `render-all` enqueues only clips that need
  it; `/renders/<id>.mp4` serves ranges and refuses ids outside the job (including `../`).
- `tests/test_review_static.py`: drawer header markup, `aria-expanded`, storage wrapped in try/catch,
  polling only while the queue is busy (string checks, as today).
- `tests/test_review_contrast.py`: the new render chips in light and dark.
- Live check (owner): the success scenario in section 1.

## 9. Documentation

- `documentation/features/shorts-cli.md`: `--clip` on `render`, `track`, `captions`; the page's render
  controls.
- `documentation/runbooks/live-run-sample.md`: Steps 5, 6 and 9 mention the drawers, the render state
  and rendering from the page.
- `CLAUDE.md` routing table: the review row points to this spec.
