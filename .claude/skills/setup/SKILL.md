---
name: setup
description: Install Albatroz Reels on a new Mac or Windows PC and leave `shorts doctor` green. Use when someone has just cloned or forked the repo, says "instala isso", "configura no meu computador", "set this up", or when `shorts doctor` shows a required line as missing.
---

# Setup: install on a new machine

The full runbook, with a check after every step, is `documentation/runbooks/new-machine-setup.md`
(Part A for macOS, Part B for Windows, sections 6 and 7 for both). Follow it in order; this skill is the
route through it and the decisions to ask the owner about.

## Before starting

1. Ask which system this is (or read it: `uname` on the Mac, `$env:OS` on Windows) and how much disk is
   free. Masters, renders and the whisper model need about 20 GB.
2. Ask where the videos should live. Defaults: `~/dev/albatroz-media` on the Mac, `C:\albatroz\media`
   on Windows. Write the answer into `config.toml` (`media_root`, `final_dir`, and the
   `[platform.win32]` tables on Windows) before running anything that writes media.
3. Ask for the e-mail to put in `[broll] user_agent` (Wikimedia Commons asks for a contact).

## Order

- macOS: Homebrew tools, including **ffmpeg-full** (the regular ffmpeg has no libass and the captions
  fail), then uv, the repo (`uv sync`, `sh scripts/install-hooks.sh`), the media root, transcreve
  (`git clone https://github.com/natagomes01/transcreve.git ~/dev/transcreve`), whisper, UVR.
- Windows: Part B1 to B11, all under `C:\albatroz` unless the owner chose another folder.
- Both: B-roll keys (optional, section 6), then section 7.
- The LLM passes run through the `claude` CLI on the owner's own Claude plan (`[backends.*]` in
  `config.toml`). Check `claude --version`; another provider is set per pass with
  `backend = "openai-compatible"` (example at the end of `config.toml`).
- For the Remotion formats (motion hook, long cut): Node 20+ and pnpm, then `pnpm install` in `remotion/`.

## Done when

- `uv run shorts doctor` shows every required line `[ok  ]`. Warnings for optional parts (Pixabay key,
  UVR) are fine if the owner does not want them; say which ones remain.
- `uv run pytest -q` passes (tests that need a sample video or ffmpeg-full skip themselves).
- Then offer the `new-channel` skill: the pipeline needs one channel of the owner's before the first run.
