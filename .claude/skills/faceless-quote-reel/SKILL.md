---
name: faceless-quote-reel
description: Playbook for a faceless Reel/Short built around a quote (a Church Father, an author, a historical text) read by a synthetic or recorded voice over public-domain paintings and mosaics with slow Ken Burns drift, cross-fades, word-highlight captions and a punch-in on key words, ending on a credit card. Use when the owner asks for a video "sem rosto", "sem aparecer", a quote Reel, a citação, or "o mesmo formato do Santo Ambrósio".
---

# Faceless quote Reel: playbook

Learned on EP 01 of the catholic-br quote series (Saint Ambrose, *Commentary on Luke* IV,26), approved as
v4 on 26/10/2026. Reference scripts: `scripts/spikes/quote-reel-261026/` (tied to that episode; copy the
folder for a new one, then edit the constants at the top). No face, no camera: the whole video is the
voice, the pictures and the captions.

## The format

1. **Lead, 0.4 s**: the first painting alone before the voice starts. The title goes on in the app.
2. **Body**: one painting per sentence or idea, each with a slow zoom (`DRIFT` 7 %) toward a focus point,
   0.35 s cross-fades. On one or two key words, an extra 10 % punch-in eased over 7 frames (a one-frame jump
   read as a skip).
3. **Captions**: the pipeline's word-highlight captions, set lower, smaller and longer than for speech,
   about 24 characters a line, because a quote reads in longer lines (`QUOTE_STYLE`, `captions.LINE_MAX`).
4. **Credit card, about 3 s**: author, work and reference in capitals (`CREDIT`), over the last picture.
5. Loudness -14 LUFS (two-pass `loudnorm`).

## Steps

1. **Text**: the quote exactly as the source prints it goes in `QUOTE`. The captions use this spelling;
   speech-to-text only gives the times.
2. **Voice**: record it, or generate it (the episode used an ElevenLabs voice). Save it as
   `<media_root>/raw/<job>/<name>.mp3` and set `JOB` and `VOICE` in `make_reel.py`.
3. **Word times**: `python3 ~/dev/transcreve/transcreve.py --palavras <voice file>`. The script stops if
   the word count differs from `QUOTE`; fix the text or re-run with a `--prompt`.
4. **Pictures**: edit `TERMS` in `find_images.py` (two to four searches per group, in several languages),
   run `uv run python scripts/spikes/quote-reel-261026/find_images.py <media_root>/broll/<job>`, then
   look at the `contact-<group>.jpg` sheets and pick by tile number.
5. **Shots**: fill `SHOTS` (group, tile number, first word of the shot, focus x/y, zoom in or out, punch
   word). Then `uv run python scripts/spikes/quote-reel-261026/make_reel.py <version>`.
6. **Check** stills at every cross-fade and at the punch words, with `assets/safe-zone.png` over them.
   `credits.txt` next to the render lists every picture's author and licence for the post.

## Rules learned

- Commons asks for a contact in the User-Agent: `[broll] user_agent` in `config.toml` must carry yours.
- Keep only public-domain or CC pictures, and post the credits.
- Captions stay inside the Reels safe zone and above the app's caption area (baseline about y 1430).
