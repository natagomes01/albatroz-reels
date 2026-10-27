---
name: long-cut-reel
description: Playbook for a Reel/Short cut from a long recorded class or YouTube video, with a Remotion motion hook in front and the body dressed in Remotion (big middle-row captions, full-screen and split-screen paintings, a readable verse or quote card, reference tags, a spoken CTA). Use when the owner picks a moment of a long video for a dynamic Short with animations, or says "o mesmo formato da Divinização / da Eleição".
---

# Long-cut Reel: playbook

Learned on the catholic-br Reels "Divinização" (22/10/2026) and "Eleição" (25/10/2026), both cut from long
classes. Model project: `remotion/projects/261025-catolico-eleicao/` (copy it to
`remotion/projects/<yymmdd>-<channel>-<slug>/`, then edit). The look and the safe-zone rules are the same
as the motion-hook format: read the `motion-hook-reel` skill first.

## The format

1. **Motion hook, about 4 s** (`Hook.tsx`): the speaker's strongest sentence, face shots interleaved with
   kinetic typography and images of the theme. Each image holds about 1 s while the words change over it.
2. **Body**: the pipeline render of the chosen clip, rendered **without** burned captions (job setting
   `burn_captions: false`). Remotion draws over it (`Body.tsx`, data in `src/body.json`):
   - captions bigger and on the middle row, near the face (on the split line during split moments);
   - many images: full-screen inserts and split screen, never only full overlays;
   - any verse or quote the speaker cites as a readable text card;
   - reference tags (e.g. "MT 22,34-40") never over a face;
   - the CTA spoken under the end text, no silent end card.
3. Nothing below y 1080 or above y 252 (the Reels safe zone, `assets/safe-zone.png`).

## Steps

1. **Pick the moment** on the review page (`shorts review <job>`) or with `shorts clip`. A clip takes at
   most 3 segments; with more cuts, pre-cut the master with ffmpeg and re-ingest.
2. **Render the body** with `"settings": {"burn_captions": false}` in `jobs/<job>/job.json`, then
   `uv run shorts render <job> --clip <id>`. The clip folder keeps `edl.json`, `meta.json` and `captions.ass`.
3. **Public dir** `<media_root>/remotion/<project>/`: `body.mp4` (a hard link to the render, never a
   symlink), `hook-src.mp4`, `Anton-Regular.ttf`, `hook/*.jpg` and `inserts/*.jpg`.
4. **Overlays**: edit `INSERTS`, `TAGS` and the CTA words in `build_body.py` (times are master seconds),
   then `python3 -I build_body.py <clip dir> <body.mp4 seconds>` writes `src/body.json`.
5. **Render**: `npx remotion render projects/<project>/src/index.ts Reel <out> --public-dir=<public dir>
   --concurrency=2 --crf=16` from `remotion/`. `<out>` goes under `<media_root>/renders/`.
6. **Check** loudness (about -14 LUFS) and frame-step every seam: hook end, each insert edge, the card, the CTA.
