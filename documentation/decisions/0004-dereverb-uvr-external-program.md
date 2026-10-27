# ADR-0004: Dereverb runs UVR as an external program, strength chosen per class

- **Status:** accepted
- **Date:** 02/10/26

## Context
The content producer judged the sample audio too reverberant to go viral. The lapel mic also picks up the voice returned by the PA speaker, so the reverb is fused with the voice. Thirteen variants were tried on a 22 s excerpt (`_think/sdd-runs/2026-10-01-S8/SESSION.md`): ffmpeg filters, DeepFilterNet, Resemble Enhance, four Roformer models, three UVR models, MDX23C. Only UVR-DeEcho-DeReverb at aggression 20 helped. Rooms differ per class. UVR peaks at about 3.3 GB on an 8 GB Mac and `audio-separator` needs Python 3.12 with its own dependencies.

## Decision
- Run UVR through the `audio-separator` program (a `uv tool` install, pinned to 0.47.0) as a child process, one padded window at a time, before the video render starts.
- The strength is a level from `[dereverb] levels` (0 = off). It is chosen by ear on the review page, once per class (`review.json["dereverb"]`), with an optional per-clip override (`decisions[id]["dereverb"]`). The effective strength is part of the render key. Rendering is gated until the class strength is chosen.
- Cache each dereverbed window under `<media_root>/cache/<job>/audio/`, keyed by master, window, strength and model.
- Retry `audio-separator` up to 3 times only on its known exit-time crash (exit -6 or -11, `recursive_mutex`, or a crash after "Separation complete"). Output of a non-zero run is never used.

## Consequences
- The project venv gets no ML dependency, and the UVR memory peak never overlaps the video render.
- A new machine needs the install in `documentation/runbooks/new-machine-setup.md`; `shorts doctor` checks the program and the model.
- A clip is never rendered without the chosen dereverb silently: a missing program, a failed run or a wrong output length stops that clip with a message.
- No UVR timeout and no cross-process lock exist yet; two UVR processes started from two terminals can run together (backlog in `_think/roadmap.md`).

## Alternatives considered
- **Call UVR from the project venv:** pulls torch and its dependencies into the repo environment and ties it to one Python version.
- **Resemble Enhance, Roformer models, MDX23C:** found nothing to remove, kept the reverb, or swapped on 8 GB (7.7 GB, 17 min).
- **ffmpeg filters (EQ, gates, `afftdn`):** the reverb is baked into the voice; filters did not remove it and a strong gate added chatter.
- **One fixed strength for every class:** the owner heard that rooms differ, so the strength is tunable.
