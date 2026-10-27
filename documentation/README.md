# Documentation

Team reference for albatroz-reels: how the tool works, what it runs, and how to operate it.
This project follows the Albatroz Documentation Standard (ADS): `documentation/` (this folder) holds reference, and `help/` holds the user guide in Portuguese
([help/pt-BR/guia-de-uso.md](../help/pt-BR/guia-de-uso.md)). Style: direct, no hype, dates DD/MM/YYYY, English.

## Start here

| If you want to | Read |
|---|---|
| Use the tool end to end, each step as a Claude Code prompt or a terminal command (Portuguese) | [../help/pt-BR/guia-de-uso.md](../help/pt-BR/guia-de-uso.md) |
| Set up a new Mac (tools, repo, media root, UVR dereverb, doctor) | [runbooks/new-machine-setup.md](runbooks/new-machine-setup.md) |
| Run the pipeline on the 10-minute sample, step by step | [runbooks/live-run-sample.md](runbooks/live-run-sample.md) |
| Know every `shorts` subcommand, flag, file and error message | [features/shorts-cli.md](features/shorts-cli.md) |
| Understand what the tool runs behind the scenes (`uv`, `claude -p`, ffmpeg, whisper, Vision, rclone) | [architecture/commands-and-external-programs.md](architecture/commands-and-external-programs.md) |
| Understand dereverb: strength per class and per clip, UVR, cache, excerpts, the gate | [features/dereverb.md](features/dereverb.md) |
| Understand the review page's look: tokens, fonts, light/dark/system theme, contrast tests | [features/review-page-brand.md](features/review-page-brand.md) |
| Set up and use the Google Drive backup | [../docs/runbooks/drive-backup.md](../docs/runbooks/drive-backup.md) |

## Layout

```
documentation/
  architecture/   how the system is built (cross-cutting pages)
  decisions/      ADRs (0002 LLM cost, 0003 review page brand assets, 0004 dereverb with UVR as an external program; 0001 is in docs/decisions/)
  features/       one reference page per feature
  api/            unused (the tool has no API)
  runbooks/       operator how-tos
  _templates/     ADS templates copied by the scaffold
```

## Older docs that stay put for now

`docs/decisions/` (ADR 0001, the per-frame crop mechanism), `docs/runbooks/drive-backup.md` and
`docs/superpowers/` (the design spec and the build plans) predate this standard. They stay where
they are; moving them into `documentation/` is a later task on the roadmap.

The full standard: `~/.claude/skills/albatroz-docs/references/documentation.md`.
