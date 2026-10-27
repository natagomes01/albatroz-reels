---
name: new-channel
description: Create or change a channel profile so the pipeline cuts, captions and styles Shorts for the owner's own channel. Use when someone forks the repo and wants their own style, says "cria meu canal", "personaliza para o meu canal", "muda o estilo das legendas", "quero usar estas referências de vídeo", or adds a new video format to copy.
---

# New channel: make the pipeline yours

A channel is three things: a table in `channels.toml`, a profile folder in `profiles/<id>/`, and the
format choices (caption look, hooks, palette) that live in the format skills and Remotion projects.
`catholic-br` is the author's channel, kept as a worked example; never edit it for someone else.

## 1. Interview (one question at a time)

- Channel name and id (lowercase, dashes: `historia-br`, `math-en`), language of the captions.
- Who watches, what they already know, what makes them save or share. Who argues in the comments.
- Names, terms and jargon the speaker says often (the speech-to-text will mishear them).
- Reference videos: links or files of Reels the owner wants to look like. Ask what they like in each one
  (the hook, the captions, the pace, the images, the colours), in their words.
- Brand: colours (hex if they have them), fonts, logo or @handle for the end card.

## 2. Write the profile

1. Copy `profiles/_template/` to `profiles/<id>/` and fill `icp.md`, `audience.md` and `captions.md`
   from the interview. Keep the owner's words; do not invent audience facts.
2. Add the table to `channels.toml` (`language`, `brand_dir`, `glossary`).
3. Check: `uv run shorts doctor` still passes, then render one test Short from a video of the owner's:
   `uv run shorts clip <video> --channel <id> --format solo-standing --from 0:10 --to 0:40`
   (it needs `<video>.palavras.json`, from `transcreve --palavras <video>`).

## 3. References and style

- Save the reference notes in `profiles/<id>/references.md`: link, what the owner liked, and what to copy
  (caption position and size, hook length, cuts per second, image use). Never download or commit
  someone else's video into the repo; media lives in the media root.
- Caption look for the pipeline formats: `CaptionStyle` in `src/shorts/captions.py` and the job settings
  (`caption_y`, `close_zoom`, `color`...) in `documentation/features/shorts-cli.md`, "Job settings".
- Motion hook, long cut: copy the model project in `remotion/projects/` to
  `<yymmdd>-<id>-<slug>` and change the palette, fonts and end card there (see the `motion-hook-reel`
  skill, "Adapting to another channel").
- Learned what works after publishing? Write it in `profiles/<id>/memory/content-performance.md`; the
  analysis passes read that folder.

## 4. A new format

When the owner brings a format none of the four skills covers, build it first as a spike in
`scripts/spikes/<name>-<yymmdd>/` (a throwaway script tied to one video), get the owner's approval on a
render, then write a playbook skill in `.claude/skills/<name>/` with the format, the steps and every rule
that cost a render. Only a format used again and again becomes pipeline code, with a spec and tests.
