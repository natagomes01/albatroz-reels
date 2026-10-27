# 0001: Per-frame crop windows through sendcmd on two fixed-size crops

Date: 2026-09-29 | Status: accepted

## Context

The render needs a different crop window on every output frame (tracking) and two window sizes
(wide, close-up). In the brainstorming preview, a piecewise `between()` formula for the crop x
returned zero at segment edges (and double-counted shared boundaries), which showed the door at
the left of the room for a frame. The spec requires a per-frame list, never a formula.

## Decision

Split the video into two `crop` filters of fixed size (`crop@wide`, `crop@close`), drive their
`x`/`y` per frame with a `sendcmd` file generated from the list, scale both to 1080x1920, and pick
between them with `overlay=enable='gte(t,a)*lt(t,b)+...'`. Crop `w`/`h` never change mid-stream,
so no filter reinitialises. Verified by `tests/test_render_mechanism.py` on a synthetic gradient.

Command times are written as `i/fps - 0.0005` (floored at 0). `sendcmd` fires when the frame time
is at or past the command time; `f"{i/fps:.4f}"` rounds about a third of the frame times up
(frame 2 is 0.066667 s but prints `0.0667`), so the change would land one frame late: the first
frame of a new close-up would show the previous close-up's window. Pinned in
`tests/test_render.py::test_first_frame_of_second_close_up_is_exact`.

Order of work per frame (review M1): `fps`, then `select`/`setpts` (drop silence gaps first),
then `sendcmd`, then per branch `crop`, HDR tone-map, grade, `scale`. Tone-mapping and grading
run only on kept frames and only on the cropped area (1216x2160 of a 4K frame, not 3840x2160).

## Rejected

- Changing crop `w`/`h` through `sendcmd`: forces `scale` to reinitialise mid-stream.
- Piecewise expressions in the crop `x`: the door bug.
- Piping frames through Python: breaks the no-frames-in-Python rule and memory budget on 8 GB.
