# Spike: reaction edit 261016-stedfast (reference, not pipeline code)

The scripts that produced the approved reaction Short on 17/10/2026 (v3). They are hard-coded to
that job (`~/dev/albatroz-media/reactions/261016-stedfast/`): times, crops, cards and paintings
are literals. Copy and edit them for the next reaction until the format gets its own spec and
module. The playbook that explains every rule in them: `.claude/skills/reaction-edit/SKILL.md`.

| Script | What it does | Run |
|---|---|---|
| `find_offset.py` | audio cross-correlation of the original against the reaction recording; prints the offset per 4 s window | `uv run --with numpy --no-project python -I find_offset.py <dir with orig.raw and reac.raw>` (8 kHz mono f32le, see the playbook) |
| `faces.py` | Apple Vision faces and bodies at 10 fps on the original, to `faces.json` | `uv run python faces.py <original.mp4> <faces.json>` |
| `blur.py` | blurs the children's faces (Vision tracks plus hand keyframes) into `original_blur.mp4` | `python3 -I blur.py` |
| `edit.py` | the whole edit: hook, split screen, full phase, cards, B-roll, captions, sfx, loudness | `uv run --with numpy python edit.py` |
| `check_sync.py` | measures voice sync at every cut of the final file against the recording | `uv run --with numpy --no-project python -I check_sync.py <spike dir> <reaction.mov> <final.mp4>` |
| `timed.sh` | runs a step under `/usr/bin/time -l` and appends wall, CPU and peak RAM to `$COSTS` | `COSTS=costs.tsv ./timed.sh <step> <command...>` |
| `tokens.py` | sums the session's token usage from the Claude Code jsonl at `pricing.toml` rates | `python3 -I tokens.py <session.jsonl>` |
| `enlarge_reaction_captions.py` | v5 patch: split captions 92 -> 128 px, pastor translation 50 -> 68 px with a manual line break | `python3 -I enlarge_reaction_captions.py cap_split.ass overlay.ass` |
