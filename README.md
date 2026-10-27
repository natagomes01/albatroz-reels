# Albatroz Reels

Turn recorded video into vertical Reels, Shorts and TikToks, on your own Mac or Windows PC, with
Claude Code doing the editing.

- **Class cut**: give it a long class or YouTube video; it transcribes, picks the moments worth a Short,
  lets you review them on a local page, then tracks the face, cuts silences, cleans the sound and burns
  word-highlight captions (1080x1920).
- **Faceless quote**, **motion hook**, **reaction** and **long cut**: four edit formats with a playbook
  skill each, learned on real published videos (see `CLAUDE.md`, "Formats").

Made by Natã Gomes at Albatroz Studio for the channel Católico na Bíblia,
whose profile stays in `profiles/catholic-br/` as a worked example. MIT licence.

**Portuguese speakers: start at [COMECE-AQUI.md](COMECE-AQUI.md).**

## Quick start

You need [Claude Code](https://claude.com/claude-code) on a Claude plan, Git, and about 20 GB free.

1. Fork this repo on GitHub, then clone your fork.
2. Open the folder in Claude Code and say: *"Read CLAUDE.md and use the setup skill to install this on
   my computer."* It follows `documentation/runbooks/new-machine-setup.md` and stops when
   `uv run shorts doctor` is green.
3. Say: *"Use the new-channel skill to create my channel."* It interviews you about your audience,
   your terms and your reference videos, and writes `profiles/<your-channel>/`.
4. Make a first Short: *"Make a Short from 1:10 to 1:45 of `<video>` for my channel."*

`.claude/settings.json` pre-approves the commands the pipeline runs (uv, ffmpeg, git, Remotion), so
Claude can edit and render without asking at every step, and blocks force-push and `rm -rf`.

## Requirements

| | macOS | Windows |
|---|---|---|
| ffmpeg | Homebrew `ffmpeg-full` (needs libass) | Gyan build on PATH |
| face and person detection | Apple Vision | YuNet + YOLOX-S (ONNX), downloaded on first use |
| transcription | whisper.cpp + [transcreve](https://github.com/natagomes01/transcreve) | same |
| LLM passes | the `claude` CLI on your plan, or any OpenAI-compatible API | same |
| Remotion formats | Node 20+ and pnpm | same |

Environment overrides: `SHORTS_FFMPEG_DIR`, `SHORTS_DETECTOR` (`vision` or `onnx`), `SHORTS_ENCODER`,
`SHORTS_MODELS_DIR`.

## Tests

```
uv sync
uv run pytest -q
```

Video tests skip themselves without ffmpeg-full or a sample (`SHORTS_SAMPLE=<video> uv run pytest`).
