# B-roll (phase 2): design

Status: approved by the owner on 02/10/2026 (spec review: points 1, 3, 4 accepted; point 2 changed the
resolution rule for stills that pass only the "whole" minimum). Decisions made by the owner on 02/10/2026 (`_think/sdd-runs/2026-10-02-S8B/SESSION.md`,
decisions 1 to 34, answers in `PERGUNTAS.md`).
Every choice below is an owner answer unless marked "our extension".
Roadmap: phase S8B. Parent specs: `2026-09-28-shorts-pipeline-design.md` (section 13 outline, 10.5
render), `2026-09-30-review-undo-and-choose-design.md` (undo and redo),
`2026-10-01-review-render-control-design.md` (render state, drawers, queue),
`2026-10-01-dereverb-strength-design.md` (the pattern this follows: class or clip setting, render key,
review page panel, background worker).

## 1. Goal

A Short keeps the face at its centre, but a few seconds of a painting, a church or a screen make it
easier to watch. For each approved clip, the system suggests up to three moments of B-roll with
candidate images or short videos; the owner approves, swaps, frames or drops each one on the review
page, can add moments of their own (including own screenshots), and the render lays them over the
speaker under the captions. Nothing goes in on its own.

Success, on the 10-minute sample: approving a clip shows `Suggesting B-roll…` in its drawer and,
within about a minute, up to three moments with up to six candidates each; picking a painting in
full screen and a stock video in split, then rendering, gives a Short where the painting pans slowly
for its moment and the video sits on top with the speaker below, captions untouched in both; the
drawer shows the credit text for the CC BY image with a copy button and `meta.json` carries it; a
clip with no B-roll renders exactly as before (same render key, no re-render).

## 2. Non-goals

- AI-generated images (decision 1). Stock banks may contain them; the owner's review is the filter
  (neither the Pexels nor the Pixabay API can exclude them, checked 02/10/2026).
- Picture in picture (decision 3).
- Showing images to the LLM, or any model judging images (decisions 24, 25).
- Fades or other transitions (decision 26); zoom (Ken Burns) on any image (decision 15).
- An animated preview on the page (decision 20); motion is checked by rendering the clip.
- B-roll in `shorts clip` (decision 33). Backup of B-roll files (decision 31).
- Automatic nudity filtering. Meta allows real-world art that shows nudity but may add a warning
  screen and an 18+ limit when the nudity is the focus of the image; YouTube may age-restrict.
  The owner judges on the page (frame the nudity out or pick another candidate).
- Colour grading of B-roll (our extension: the class grade is for the class footage only).

## 3. Sources and licences

| Source | What | Licences kept | Credit |
|---|---|---|---|
| Wikimedia Commons (MediaWiki API) | stills (paintings, manuscripts, photos) | public domain (any `PD-*`), CC0, CC BY (any version) | CC BY only |
| Pexels (API key) | photos and videos | Pexels licence | none required |
| Pixabay (API key) | photos and videos | Pixabay content licence | none required |
| Own files | stills and videos from the owner (screenshots) | the owner's | none |

- **CC BY-SA and every other licence are dropped** (decision 8): share-alike could reach the whole
  Short as a derivative work. A Commons file is kept only when its `extmetadata.LicenseShortName`
  maps to one of the three kept families; anything unknown is dropped.
- Commons asks every client for a descriptive `User-Agent` with contact details:
  `config.toml` `[broll] user_agent` holds it (set by the owner; `shorts doctor` warns while it is the
  placeholder).
- **Keys** live in the Keychain as `pexels-api` and `pixabay-api` (`keychain.get_secret`). A missing
  key drops that source silently from searches; `shorts doctor` shows a warning per missing key, never
  a failure (decision 32). How to get them goes in the runbook (section 9).
- **API rules we follow:** results are cached for 24 h (Pixabay requires it; applied to all, our
  extension); files are downloaded before use, never hotlinked; the page labels each candidate with
  its source name (Pexels and Pixabay ask apps to show where content comes from).
- **Search terms are in English** for every channel (decision 22).
- **Minimum resolution** (decision 23): a candidate is kept only when the image dimension that sets
  the scale for its space is at least 1080 px: for "cover", the dimension that limits the fill; for
  "whole", the long side. A still that passes only the "whole" minimum is kept, and picking it sets
  `fit = "whole"`; the owner may still choose "cover", with an amber warning (owner, at spec review:
  "we decide whether it blurs around or not"). If the owner later changes the layout or fit and the
  pick falls under the minimum, the moment shows the amber warning.
  Known effect: Pixabay's public API serves stills at most 1280 px on the long side, so most Pixabay
  stills come in as "whole" in full screen; Pixabay videos (1920x1080 variants) are unaffected.
- **Stills are downloaded at most 4096 px on the long side** (Commons thumbnail URLs with
  `iiurlwidth`; Pexels `original` resized by its `?w=` parameter; our extension): this bounds the
  decoder's memory at render time on the 8 GB M1.
- **Videos** are offered only when at least as long as the moment (decision 29), no audio is used,
  and the file variant chosen is the smallest one whose fill dimension is at least 1080 px. A video
  whose probe shows HDR is refused at pick time with a message (our extension).

## 4. Moments

A **moment** is a stretch of a clip covered by B-roll.

```jsonc
{
  "id": "m1",
  "origin": "llm",            // "llm" or "owner"
  "first": 812, "last": 824,  // word indices in words.json (inclusive), the anchor
  "layout": "full",           // "full" or "split"
  "fit": "cover",             // "cover" or "whole"
  "pan": "ltr",               // "ltr", "rtl", "ttb", "btt" or "still"
  "focus": [0.5, 0.5],        // framing point, fraction of the overflow (0 = left/top, 1 = right/bottom)
  "terms": ["Last Supper painting"],
  "note": "",                 // LLM's reason, or what own file to add ("screenshot of the n8n flow")
  "pick": null                // the chosen asset (below), or null
}
```

`pick`: `{"source": "commons|pexels|pixabay|own", "id", "kind": "image|video", "file"` (path relative to
`<media_root>/broll/<job>/`), `"download_url", "w", "h", "duration", "title", "author", "license",
"license_url", "page_url"}`.

- **Anchored to words** (decision 16): start = the first word's start, end = the last word's end
  (`textutil.word_end`), both mapped to clip time through the clip's EDL (`TimeMap.snap_to_clip`), so
  silence cuts move the moment with its words.
- **Timing rules** (decision 5), measured in clip time: each moment lasts 2 to 5 s; at most three
  moments; together at most 30% of the clip; none starts before 3.0 s; none ends after the clip end
  minus 2.0 s; moments do not overlap. All numbers live in `config.toml` `[broll]`.
  For LLM moments the rules are hard: the code drops a moment that breaks one and logs why. For the
  owner's moments the page shows an amber warning and allows it (decision 17).
- **When the clip's cut changes** (decision 18): a moment whose words leave the clip is dropped from
  the decision with a notice in the drawer (`B-roll moment "…" dropped: its words left the clip`); a
  moment that now breaks a rule shows the amber warning. The drop happens inside the same
  `apply_edit` that changes `segments`, so one undo restores both. `Suggest again` replaces the LLM moments and
  keeps the owner's.
- **Clip time needs the EDL.** `broll.timing.clip_map(job, app, channel, plan)` returns the clip's
  `TimeMap`, reading `clips/<id>/edl.json` when its key is fresh, else running the same
  `detect_silences` and `build_edl` that `clip.produce()` runs and writing it (about 1 s for a 60 s
  clip; our extension).

## 5. The suggestion pass

1. **Trigger** (decision 10): `POST /api/decision` with `approved` for a channel with `broll = true`
   (new channel toggle in `channels.toml`, default true; our extension) and no suggestion file yet
   enqueues `suggest` for that clip in the B-roll worker (section 7). `Suggest again` in the drawer
   enqueues it by hand. The CLI `shorts broll <job> [--clip ID ...] [--force]` runs the same pass for
   approved clips without a suggestion (or all named clips with `--force`).
2. **Input** (decision 24): the clip's effective words (owner fixes applied, numbered by word index,
   with clip-time seconds), the class topic from `analyze/class_sheet.json` when present, the channel
   id and its content language, and the timing rules. No profile files, no images.
3. **Model** (decision 25): new pass `broll`, `config.toml` `[backends.broll]` with
   `backend = "claude-cli"`, `model = "claude-haiku-4-5"`. Prompt `prompts/broll.md`. Called through
   `LLMBackend.complete` inside `llm_context(pass_name="broll")`, so `shorts cost` counts it. Cached
   like `fixwords` (`analyze/cache/broll/<key>.json`, key over prompt hash, model and input).
4. **Output schema** (`analyze/schemas.py` `BROLL`): up to 3 moments, each
   `{first, last, layout: "full"|"split", kind: "painting"|"photo"|"video"|"own", terms: [1..3 English
   strings], note}`. `kind = "own"` means "the owner should add a file here" (the AI channels'
   screenshots); it gets no search and its `note` says what to show.
5. **Defaults the code sets** (our extension): `fit` is `cover` except for `own`, which is `whole`;
   `pan` is the reading direction on the axis where the picked image overflows (`ltr` or `ttb`), or
   `still` when it does not. The LLM does not choose the pan: it never sees the image, so the pan is
   set from the picked image's shape and the owner changes it on the page (decision 12 as built).
6. **Search** for every non-`own` moment: each source is queried with each term; `kind` steers the
   source order (`painting` puts Commons first, `video` asks Pexels and Pixabay for videos, `photo`
   asks all for stills). Up to `candidates = 6` results per moment, interleaved across sources,
   filtered by licence, resolution and (videos) duration. Thumbnails (320 px wide) go to
   `<media_root>/cache/<job>/broll/thumbs/`.
7. **Result** is written atomically to `jobs/<job>/broll/<clip>.json` (not versioned):
   `{version, model, prompt_hash, moments: [...], candidates: {<moment id>: [candidate, ...]},
   errors: [...]}`. The server then merges the LLM moments into the clip's decision (section 6) as one
   undoable step, keeping the owner's moments.
8. **Errors:** no network, an API error or an LLM error writes the error into the result file; the
   drawer shows it with `Try again`. A failed source does not stop the others. The rest of the page
   keeps working.

## 6. Where the choices live

- **In `review.json`**, per clip: `decisions[<id>]["broll"] = [moment, ...]` (section 4 shape). It is a
  clip edit: `state._validated` accepts the key `broll` (a list of at most 6 moments, each validated:
  ids unique, `first <= last`, both valid word indices, enums, `focus` in [0, 1], `terms` at most 3
  strings of at most 80 characters, `pick.file` a plain relative name under the job's B-roll folder)
  and it goes through the S5 undo and redo history (whole-entry snapshots, as today).
- **Candidates and errors** stay in `jobs/<job>/broll/<clip>.json` (bulky, regenerable, not versioned).
- **Files:** thumbnails in `<media_root>/cache/<job>/broll/thumbs/`; picked downloads and own files in
  `<media_root>/broll/<job>/`; never in Git (decision 31). `shorts clean` also deletes the job's
  thumbnail cache. Backup leaves B-roll out.

## 7. Review page

1. **B-roll worker** (new, `review/broll.py` `BrollQueue`): one daemon thread, FIFO, with three task
   kinds: `suggest(clip)`, `search(clip, moment, terms)` and `fetch(clip, moment, candidate)` (download
   the full file into `<media_root>/broll/<job>/`, probe it, then set `pick`). It runs in process (network
   and one Haiku call, no heavy memory), so it may run while a render runs (our extension).
   `GET /api/broll` returns per clip `{state: idle|queued|working|failed, error}`; the page polls it every
   2 s while something is queued or working, like the render state.
2. **Routes** (all POSTs keep the JSON, Origin and 1 MiB rules, except upload):
   `POST /api/broll/suggest {id}`, `POST /api/broll/search {id, moment, terms}`,
   `POST /api/broll/pick {id, moment, candidate}`, `GET /api/broll/candidates/<id>`,
   `GET /api/broll/files` (own files in the folder), `POST /api/broll/upload` (raw body, image or video
   content type, same Origin rule, size cap `upload_max_mb = 200`, file name cleaned, written atomically),
   `GET /media/broll/<name>` and `GET /media/broll-thumb/<name>` (Range support as `/media/master`).
   Moment edits (add, layout, fit, pan, focus, drop, pick an own file) go through `POST /api/edit`.
3. **Drawer section `B-roll`**, below the words block:
   - Head line: `B-roll: 2 moments · Suggest again`, or `Suggesting B-roll…`, or the error with `Try again`.
   - Per moment: its clip-time range and words, an origin chip (`suggested` or `mine`), selects for
     layout (`full screen`, `split`), fit (`fill`, `whole`) and motion (`left to right`, `right to left`,
     `top to bottom`, `bottom to top`, `still`, only the ones that apply), the candidate grid (up to 6
     thumbnails, each with a source label and licence, video with its duration; click picks), a search
     box (`Search`), `Use my file` (file picker, drag and drop on the moment, and a list of files already
     in the folder), and `Drop`.
   - **Static preview** (decision 20): a 9:16 frame, 180x320 px, showing the layout, the image at its
     framing, and the caption band (output rows of the caption block) marked. Dragging on the preview
     sets `focus`; arrow keys nudge it by 2% (keyboard access).
   - Amber warnings: a broken timing rule, a pick under the minimum resolution for its layout and fit.
   - `Credit`: the credit text for the clip's CC BY picks (section 8) with `Copy`.
4. **Own moments** (decision 16): a `Select words` toggle in the B-roll section switches word clicks
   from edge-setting to range selection (first click starts, second click ends, the range highlighted);
   `B-roll here` adds an `owner` moment with `layout = "full"`, `fit = "cover"`, no terms, and leaves
   select mode. Plain clicks set edges again outside select mode.
5. **Drawer head chip:** a clip with at least one picked moment shows `B-roll 2` in the S6 chip style.
6. All new controls are buttons, selects or inputs reachable by Tab and Enter; interface text is
   English; colours come from `tokens.css`. There is no warning token yet: the build adds `--warn`
   (amber) for light and dark, and the S6 contrast test covers it.

## 8. Render

1. **Inputs:** after the existing inputs (segment groups, safe zone, WAVs), one input per picked
   moment, in moment order: a still as `-loop 1 -framerate 30 -t <dur> -i <file>`; a video as
   `-t <dur> -an -i <file>`. `RenderInputs` gains `broll: list[BrollInsert]` (clip-time start and end,
   kind, file, layout, fit, pan, focus, image size). Existing index arithmetic is unchanged.
2. **Per insert**, a chain producing a layer of the target size (1080x1920 for `full`, 1080x960 for
   `split`):
   - `cover`: `scale` to cover the target (`force_original_aspect_ratio=increase`), then `crop` to the
     target. A still pans with a time expression on the crop `x` (or `y`) at `pan_px_per_s = 40` output
     px per second, along a path centred on `focus` and clamped to the image (decisions 13, 14); a path
     longer than the overflow shrinks to it. Videos and `still` keep a fixed crop at `focus`.
   - `whole`: the image scaled to fit inside the target, overlaid centred on a background made of the
     same image scaled to cover, blurred (`gblur`) and slightly darkened (decision 11). No motion.
   - Then `fps=30`, `format=yuv420p`, `setsar=1` and `setpts=PTS-STARTPTS+<start>/TB`.
3. **Overlay** between the framed video `[vb]` and the captions (render.py, after the close-up overlay):
   `overlay=x=0:y=0:enable='gte(t,<start>)*lt(t,<end>)'` per insert, chained. Captions are burned after
   it and the safe-zone overlay after that, as today: captions never move (decision 6).
4. **Split speaker** (decisions 6, 27): during a `split` insert, the bottom half (rows 960 to 1920) shows
   rows `y0` to `y0 + 960` of the framed video at the same scale, so the face sits below the captions
   and the lower body is cut. `y0` is constant per insert: the face centre at the insert's middle (from
   the tracking detections, mapped through that frame's crop window) minus `split_face_y - 960`, with
   `split_face_y = 1250` (output row of the face centre, tuned by watching), clamped to [0, 960]; with no
   face, the body box top plus 5% (as the close-up uses), else `y0 = 300`. Built as `split=2` on `[vb]`, a
   `crop` plus `overlay` at y 960 enabled for the insert's time, then the image layer on top at y 0.
5. **No frame goes through Python**; one clip at a time; inputs are at most three extra decoders and
   stills are at most 4096 px. Memory and time are measured on the sample at the end of the build.
6. **Pan smoothness check:** an integer crop moving 1.33 px per frame may judder. The first render task
   renders a 4 s pan and the owner watches it; if it judders, the chain scales the still to twice the
   target, pans there, and scales back down with lanczos (the plan names this fallback).
7. **Render key** (decision 30): `stages._keys` adds `broll=<digest>` **only when the clip has picked
   moments**, the digest covering each insert's clip-time range, layout, fit, pan, focus and file
   content hash (size plus mtime is not enough after a re-download; sha256 of the file, cached in
   `<file>.sha256`). A clip without B-roll keeps its exact current key, so nothing re-renders.
   `RENDER_VERSION` stays 4 because the graph is unchanged for clips without B-roll. `render_status`
   and `next_stage` use the same key.
8. **Missing files:** before rendering, `ensure_broll_files` re-downloads a missing picked stock or
   Commons file from `download_url`; a missing own file stops that clip's render with
   `B-roll file missing: <name>; add it again on the review page`.
9. **`meta.json`** (decision 34): `broll: [{start, end, layout, source, kind, title, author, license,
   page_url}]` and `credits`: the credit text in the channel's language, one line per CC BY pick:
   `pt`: `Imagem: <title>, de <author>, <license> (<page_url>)`; `en`: `Image: <title> by <author>,
   <license> (<page_url>)`. PD, CC0, stock and own picks are listed in `broll` but get no credit line.

## 9. Config, doctor and documentation

```toml
[backends.broll]
backend = "claude-cli"
model = "claude-haiku-4-5"

[broll]
user_agent = "albatroz-shorts (set your contact here)"
candidates = 6
min_fill_px = 1080
max_still_px = 4096
thumb_width = 320
pan_px_per_s = 40
split_face_y = 1250
insert_min_s = 2.0
insert_max_s = 5.0
max_inserts = 3
max_share = 0.30
head_s = 3.0
tail_s = 2.0
upload_max_mb = 200
```

- **`shorts doctor`**: warnings (never failures) for a missing `pexels-api` or `pixabay-api` Keychain
  entry and for the placeholder `user_agent`.
- **Runbook** `documentation/runbooks/new-machine-setup.md`, new section `B-roll keys`: create the
  Pexels key (account, then pexels.com/api, `Your API Key`) and the Pixabay key (account, then
  pixabay.com/api/docs while logged in), and store both with
  `security add-generic-password -s pexels-api -a shorts -w <key>` (same for `pixabay-api`), each with
  its check command.
- **User guide** in `documentation/features/shorts-cli.md`: the B-roll section of the drawer, own
  moments, credits, `shorts broll`.

## 10. Tests

- **Without network** (always run): each source takes an injectable `fetch` function; recorded API
  replies live in `tests/fixtures/broll/` (one Commons search with PD, CC BY, CC BY-SA and an unknown
  licence; one Pexels photo and video search; one Pixabay search). Covered: licence filter, resolution
  and duration filters, interleaving and the cap of 6, 24 h cache reuse, thumbnails written to the cache.
- **Suggestion pass** with a stub backend (as in `test_wordfix_pass.py`): rule enforcement (each rule
  drops the right moment), `own` moments get no search, defaults for fit and pan, cache reuse, error
  written to the result file, `llm_context` pass name `broll`.
- **State:** `broll` edit validation (every field), undo and redo of moment edits, merge of a suggestion
  keeping owner moments, moments dropped when their words leave the clip.
- **Server:** every new route (bad Origin, wrong content type, upload over the cap, path traversal in
  names), approval enqueues a suggestion only once, `GET /api/broll` states.
- **Render** (`needs_ffmpeg`, synthetic inputs): a red still in full screen covers a pixel at the
  moment's middle and not before or after it; a split insert leaves the speaker in the bottom half;
  captions are drawn over the B-roll; a pan moves a marker column by about 40 px per second; `whole`
  shows the full image with a blurred band; a video input ends at the moment's end.
- **Render key:** a clip without B-roll keeps its exact pre-S8B key (fixed expected digest); changing
  any insert field or the file content changes it.
- **Page:** string tests for the new controls as in `test_review_static.py`; contrast for any new token.
- **Measure at the end of the build:** time and peak memory of one sample clip with two inserts (a
  4096 px still panning and a 1080p video in split), recorded in the SDD run record.
