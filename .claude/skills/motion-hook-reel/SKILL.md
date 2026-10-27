---
name: motion-hook-reel
description: Playbook for the motion-hook format (worked example from the catholic-br channel), a Reel/Short/TikTok made from phone recordings (a short hook take plus a development take) with a Remotion motion hook, the pipeline body, a "stay until the end" strip, the ebook passing on screen at the CTA, and an end card, all in the Católico na Bíblia IDV tones. Use whenever the owner sends phone takes (hook plus development), asks for a motion hook, kinetic typography, a Reel with a free-material CTA, or "o mesmo formato do Êxodo 20", for any channel. Holds the delivery approved as V5 on 19/10/2026 and the bugs met on the way.
---

# Motion-hook Reel: playbook

Learned on the Reel "A Bíblia proíbe imagens?" (job `261018-biblia-proibe-imagens`, published as V5 on
19/10/2026). The author keeps this delivery for every catholic-br short video. It is a worked example:
for another channel, keep the five layers and the rules learned, and swap the palette, the strip text,
the free material and the end card for that channel's (see "Adapting to another channel").

- Style rule (author's decision): short vertical video aims at the feed. Anton, inked type with a hard
  shadow, halftone, word-by-word cuts, escalating repetition, in the channel's tones (catholic-br: navy
  #0A1530/#182C52, gold #C9A54E/#E0C87F, red #B02A2A, ivory #F3EBDC).
- Model Remotion project: `remotion/projects/261018-catolico-exodo-20-hook/`. Copy it to a new
  `remotion/projects/<yymmdd>-<channel>-<slug>/`, then edit; do not grow the model in place.
- Helper scripts (hard-coded to that job; copy, then edit): `scripts/spikes/catolico-reel-261018/`.

This is not a pipeline feature: there is no spec, module or test. The body comes from the pipeline;
everything around it is a Remotion project per video.

## The delivery (V5, do not relitigate)

1. **Motion hook, 4 to 5 s** (`Exodo20Hook`, `SHOTS`): the owner's face (hook take) alternates word by word
   with kinetic typography of the key phrase, repetition escalating until it fills the screen ("Killing
   Joke" madness), closing on a short question on the clean face. Keep the whole spoken repetition: cutting
   the hook under 2 s kills the joke. Shot cuts sit on the audio onsets, not on Whisper word times.
2. **Retention strip** right after the hook, top of screen, 5 s (`src/v5/ReelV5.tsx`, `StayBanner`):
   "FIQUE ATÉ O FINAL PARA RECEBER / O PRESENTE GRATUITO 🎁". Gold band, navy rules, red second line, the gift
   hops. Sits at y 170 to 430, above the eyes. It exists because the ebook is only named past the middle.
3. **Body**: the pipeline render of the development take (pre-cut job, B-roll from the ebook's public-domain
   paintings, burned captions), plus reference tags ("76 VERSÍCULOS", "1Cr 28,19") at y 300.
4. **Ebook pass at the CTA** (`src/v4/ReelV4.tsx`): while he talks about the free material, the ebook slides
   by: cover, summary, chapter openers with their images, then full verse-list pages. Captions are redrawn
   over the pages. Hard cut in and out.
5. **End card**: "COMENTE [WORD] E RECEBA O EBOOK" and @catoliconabiblia.

Style: Anton, inked type with hard navy shadow, halftone, palette `IDV_TONES` (`src/v3/ReelV3.tsx`). Never the
Byzantine frame, tesserae, halo or mosaic in short video (V2 was tried and rejected as slow for the feed).
Final loudness -14 LUFS, hook included.

## Steps

1. **Media.** Copy the takes to `<media_root>/raw/<job>/`. Concat hook + development into
   `<media_root>/masters/<job>.mp4` (1080x1920, 30 fps, x264 CRF 12, map `0:v:0`/`0:a:0`). Note where the
   hook ends.
2. **Pipeline job** on `main`, with `"settings"` in `job.json` for a pre-cut phone video (here
   `{"color": false, "caption_y": 1400, "close_zoom": 1.25, "open_close": false}`; keys in
   `documentation/features/shorts-cli.md`, "Job settings"): `shorts ingest`, then a body-only candidate (segments that
   drop flubs and wrong numbers), `review.json` from `write_review.py` (B-roll moments are word indices into
   `words.json`, origin `"owner"`, at most 6; own pictures go to `<media_root>/broll/<job>/own-*.jpg`, resized
   with `sips -Z 4096`), word fixes for mis-heard words, then `shorts render`.
3. **Remotion public dir** `<media_root>/remotion/<project>/`: `hook-src.mp4` (hook part of the master,
   audio cleaned and gained to the body's loudness), `Anton-Regular.ttf`, `body.mp4` as a **hard link** to the
   pipeline render, and `ebook/page-NN.jpg` from `export_pages.sh` (look at `contact-sheet.jpg` first; pick
   pages that are mostly image or dense lists, not near-empty ones).
4. **Lettering** frames from master times through the clip's `edl.json`: `lettering.py` -> `src/lettering.json`.
5. **Ebook pass** times in clip seconds from the clip's `captions.ass` / words; captions JSON from
   `ebook_captions.py`. End the pass exactly at the clip cut where the B-roll under it ends.
6. **Render**: `npx remotion render src/index.ts ReelV5 <out> --public-dir=<media>/remotion/<project>
   --concurrency=2 --crf=16` (about 6 min on an M1 with 8 GB; nothing else heavy at the same time).
   `<out>` is `<media>/renders/<channel>/<job>/remotion/<YYMMDD-channel-slug>-vN.mp4`, never a path
   inside the repo.
   The version the owner approves moves to `<media>/final/catholic-br/<YYMMDD-catolico-slug>.mp4`; that
   folder is the only place a video to post lives.
7. **Check before reporting**: loudness (`ebur128`, about -14), duration, and stills at every seam (hook end,
   strip in/out, both ebook pass edges, end card). Frame-step the seams, do not trust one still.

## Rules learned (each one cost a render)

- **Remotion does not serve symlinks from the public dir** (404 on `body.mp4`). Use a hard link, and re-link
  after every pipeline re-render (a new file breaks the old link).
- **Always pass `--public-dir`** to `remotion still` and `remotion render`: the `setPublicDir` in
  `remotion.config.ts` did not apply to CLI runs here (404 on `body.mp4` and the font).
- **libass font size is the full line height.** Anton 128 in ASS is about 75 px CSS with `lineHeight 128px`;
  outline 6 ASS is about `WebkitTextStroke 9px` with `paintOrder: stroke fill`. Compare side by side.
- **Hook audio must match the body.** The raw hook was -19.4 LUFS against -14.1: apply the pipeline cleanup
  (`highpass=f=70,afftdn=nr=6:nf=-45`), the gain, and `alimiter`.
- **Audio across cards**: keep one always-mounted `<Audio>` for the hook and mute the `OffthreadVideo`s, or
  the sound drops on every typography card.
- **Whisper word times run about 3 frames late.** Put cuts on the audio onsets (per-frame RMS with `astats`).
- **First frame**: if the take starts with eyes closed, open on a typography card (the "stamp").
- **Rotated face shots** need extra zoom, or black corners show.
- **Overlays over B-roll end with a hard cut.** A fade let the Fouquet painting under the ebook flash for a
  frame; an end time short of the clip cut flashed it for half a second.
- **Garamond is wider than Anton**: any serif test needs smaller sizes and `nowrap` tags.
- **Ebook pages are a snapshot** of the PDF on the render day; re-export them when the ebook changes.
- **A clip takes at most 3 segments.** With more cuts, pre-cut the master with ffmpeg (trim + concat, 10 ms fades),
  re-ingest, and give the body one segment (job `261022-catolico-divinizacao`).
- **Whisper can skip a whole sentence** on a re-ingest. Scan `words.json` for gaps over 3 s before writing B-roll
  indices; re-insert the missing words from an earlier transcript, shifted to the new master.
- **Leave 0.3 s of silence after the last word** of the master: the render trims the tail and clipped the end of
  "perfil" before the end card.
- **Everything inside the Reels safe zone** (`assets/safe-zone.png`: y 252 to 1080, x 72 to 1026): captions, tags,
  hook words and the CTA. A tag at y 1500 or 1740 sits under the app's buttons (owner, 2026-10-22). Check stills
  with the template overlaid.
- **Hook images need about 1 s on screen** each, the spoken words changing over them; 0.2 to 0.6 s reads as a flash.
- **No free material, no strip and no ebook pass**: the CTA becomes "SIGA @CATOLICONABIBLIA" on the end card.
- **Machine etiquette**: renders take the whole machine. When the owner is using it (a class, a call)
  or asked to plan only, write the plan and run nothing heavy.

## Open on the model video

The Chipiez plate still shows the book page and gutter (needs a crop). "Fique com Deus" was left out of the
body. `v1.mp4` keeps the old "Imagina," word.

## Adapting to another channel

Copy the model project and change, in this order: the palette (`IDV_TONES` in `src/v3/ReelV3.tsx`), the
hook words and shots (`SHOTS` in the hook), the retention strip text (or drop the strip when there is no
free material), the CTA and the end card handle. Keep Anton, or swap the font in `public/` and in the
`@font-face` of the hook. Every rule in "Rules learned" still applies.
