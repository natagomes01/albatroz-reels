"""Virtual camera: follow the speaker's horizontal position with a dead zone and eased motion.

Ported and adapted from mutonby/openshorts `SmoothedCameraman` (MIT), see THIRD_PARTY.md:
dead zone and jump confirmation come from there; the constant 3 px/frame pan is replaced by
eased, speed-capped motion that brakes onto its target without overshoot.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from shorts.vision import Box


@dataclass(frozen=True)
class CameraParams:
    crop_w: float  # crop window width in source px
    src_w: float
    dead_zone: float  # fraction of crop_w (0.25 standing, 0.15 seated)
    confirm: int = 2  # consecutive samples outside the dead zone before moving
    max_speed: float = 0.6  # crop widths per second
    accel: float = 1.2  # crop widths per second^2


def pick_subject(boxes: list[Box], prev_cx: float | None) -> Box | None:
    """The box nearest the previous position; with no history, the largest box."""
    if not boxes:
        return None
    if prev_cx is None:
        return max(boxes, key=lambda b: b.w * b.h)
    return min(boxes, key=lambda b: (abs(b.cx - prev_cx), -(b.w * b.h)))


def smooth_path(
    samples: list[tuple[float, float | None]], params: CameraParams, times: list[float]
) -> list[float]:
    """Crop CENTER x (source px) for each t in `times` (ascending, class timeline).

    samples: (t_class, subject_cx or None), ascending. The camera re-targets only after
    `confirm` consecutive samples outside the dead zone; with no detection it keeps its
    current target (it never goes looking). Motion accelerates and brakes within
    `accel` and `max_speed`, and stops exactly on target.
    """
    half = params.crop_w / 2
    lo, hi = half, params.src_w - half
    clamp = lambda x: min(max(x, lo), hi)  # noqa: E731
    known = [cx for _, cx in samples if cx is not None]
    pos = clamp(known[0] if known else params.src_w / 2)
    target = pos
    vel = 0.0
    outside = 0
    band = params.dead_zone * params.crop_w / 2
    vmax = params.max_speed * params.crop_w
    acc = params.accel * params.crop_w
    si = 0
    prev_t = times[0] if times else 0.0
    out: list[float] = []
    for t in times:
        while si < len(samples) and samples[si][0] <= t:
            cx = samples[si][1]
            if cx is None:
                outside = 0
            elif abs(cx - pos) > band:
                outside += 1
                if outside >= params.confirm:
                    target = clamp(cx)
            else:
                outside = 0
            si += 1
        dt = min(max(t - prev_t, 0.0), 0.1)
        prev_t = t
        gap = target - pos
        if gap == 0.0:
            vel = 0.0
        else:
            direction = math.copysign(1.0, gap)
            brake_speed = math.sqrt(2 * acc * abs(gap))
            desired = direction * min(vmax, brake_speed)
            if vel < desired:
                vel = min(vel + acc * dt, desired)
            else:
                vel = max(vel - acc * dt, desired)
            pos += vel * dt
            if (target - pos) * direction <= 0:  # reached or crossed the target: stop on it
                pos, vel = target, 0.0
        out.append(clamp(pos))
    return out
