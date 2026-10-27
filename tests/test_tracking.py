from shorts.tracking import CameraParams, pick_subject, smooth_path
from shorts.vision import Box


P = CameraParams(crop_w=405, src_w=1280, dead_zone=0.25)


TIMES = [i / 30 for i in range(300)]


def test_jitter_inside_dead_zone_does_not_move():
    s = [(i / 3, 640 + (20 if i % 2 else -20)) for i in range(30)]
    xs = smooth_path(s, P, TIMES)
    assert max(xs) - min(xs) == 0


def test_step_glides_without_overshoot_and_speed_cap():
    s = [(i / 3, 640 if i / 3 < 2 else 900) for i in range(30)]
    xs = smooth_path(s, P, TIMES)
    assert xs[-1] == 900 and max(xs) == 900
    speeds = [abs(b - a) * 30 for a, b in zip(xs, xs[1:])]
    assert max(speeds) <= 0.6 * 405 + 1e-6
    assert next(i for i, x in enumerate(xs) if x != 640) / 30 >= 2.3  # waited for 2 confirmations


def test_single_outlier_ignored_and_none_holds():
    s = [(i / 3, 640 if i != 10 else 1000) for i in range(30)]
    assert max(smooth_path(s, P, TIMES)) == 640
    s = [(i / 3, 640 if i < 5 else None) for i in range(30)]
    assert set(smooth_path(s, P, TIMES)) == {640}


def test_path_stays_inside_frame():
    s = [(i / 3, 5.0) for i in range(30)]
    assert min(smooth_path(s, P, TIMES)) >= 405 / 2


def test_pick_subject():
    a, b = Box(0, 0, 10, 10), Box(500, 0, 50, 100)
    assert pick_subject([a, b], None) == b
    assert pick_subject([a, b], 0) == a
    assert pick_subject([], 3) is None
