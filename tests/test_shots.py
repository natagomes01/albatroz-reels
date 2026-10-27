import pytest

from shorts.shots import Crop, Shot, assert_in_bounds, crop_windows, plan_shots
from shorts.timeline import Span, TimeMap
from shorts.vision import Box
from shorts.words import Word, sentences


def _grid():
    w = [Word(100 + s * 3 + k * 0.5, "palavra." if k == 5 else "palavra", 1) for s in range(7) for k in range(6)]
    return w, sentences(w), TimeMap([Span(100, 121)])


def test_hook_and_emphasis_close():
    w, s, tm = _grid()
    assert plan_shots(tm, w, s, Span(100, 103), [Span(112, 115)], []) == [
        Shot(0.0, 5.9, "close"), Shot(5.9, 11.9, "wide"), Shot(11.9, 21.0, "close")]


def test_body_jump_switches_to_close():
    w, s, tm = _grid()
    assert plan_shots(tm, w, s, None, [], [5.9]) == [
        Shot(0.0, 5.9, "wide"), Shot(5.9, 11.9, "close"), Shot(11.9, 21.0, "wide")]


def test_no_shot_shorter_than_min_len():
    w, s, tm = _grid()
    for shots in (plan_shots(tm, w, s, Span(100, 101), [Span(118, 119)], [2.9, 8.9]),):
        assert all(sh.end - sh.start >= 4.0 for sh in shots)


def test_crop_windows_sizes_and_bounds():
    w, s, tm = _grid()
    shots = plan_shots(tm, w, s, Span(100, 103), [], [])
    crops = crop_windows(shots, tm, 30, lambda t: 640.0, lambda t: Box(600, 200, 80, 80), 1280, 720, "solo-standing")
    assert len(crops) == 630
    assert crops[0] == Crop(495, 86, 290, 514)  # face centre (640, 240) at 30% of the height
    assert crops[300] == Crop(438, 0, 404, 720)
    assert {(c.w, c.h) for c in crops} == {(290, 514), (404, 720)}
    assert_in_bounds(crops, 1280, 720)


def test_crop_windows_clamped_at_edges():
    w, s, tm = _grid()
    shots = plan_shots(tm, w, s, Span(100, 103), [], [])
    crops = crop_windows(shots, tm, 30, lambda t: 5.0, lambda t: None, 1280, 720, "solo-seated")
    assert_in_bounds(crops, 1280, 720)
    assert crops[0].x == 0 and crops[-1].x == 0


def test_close_up_follows_a_walking_speaker():
    w, s, tm = _grid()
    shots = plan_shots(tm, w, s, Span(100, 103), [Span(112, 115)], [])
    walk = lambda t: 300.0 + 40.0 * (t - 100)  # noqa: E731  body centre crosses the room
    crops = crop_windows(shots, tm, 30, walk, lambda t: Box(walk(t) - 40, 200, 80, 80), 1280, 720, "solo-standing")
    assert_in_bounds(crops, 1280, 720)
    for i, c in enumerate(crops):
        cx = walk(tm.to_class(i / 30))
        assert c.x <= cx <= c.x + c.w, (i, c, cx)
    hook_frames = [c for i, c in enumerate(crops) if i / 30 < shots[0].end]
    assert shots[0].kind == "close" and {(c.w, c.h) for c in hook_frames} == {(290, 514)}
    assert len({c.x for c in hook_frames}) > 1  # x moves inside the close-up shot
    assert len({c.y for c in hook_frames}) == 1  # y stays fixed for the shot


def test_close_up_vertical_fallback_is_the_body_box():
    w, s, tm = _grid()
    shots = plan_shots(tm, w, s, Span(100, 103), [], [])
    crops = crop_windows(shots, tm, 30, lambda t: 640.0, lambda t: None, 1280, 720, "solo-standing",
                         body_at=lambda t: Box(590, 150, 100, 500))
    assert crops[0] == Crop(495, 124, 290, 514)  # 150 - 5% of 514 headroom


def test_assert_in_bounds_catches_the_door_bug():
    with pytest.raises(ValueError, match="frame 1"):
        assert_in_bounds([Crop(0, 0, 404, 720), Crop(-202, 0, 404, 720)], 1280, 720)


def _assert_shot_list_sane(shots, total):
    assert shots[0].start == 0.0 and shots[-1].end == pytest.approx(total)
    assert all(a.end == b.start for a, b in zip(shots, shots[1:]))
    if total >= 1.0:
        assert all(s.end - s.start >= 1.0 for s in shots)
    assert all(a.kind != b.kind for a, b in zip(shots, shots[1:]))


def test_force_switch_never_leaves_a_sub_second_fragment_before_a_join():
    """Real clip ce6331b: a close-up (17.17-27.93) holds a segment join at 17.567, 0.4 s after its start.
    The old split kept the 0.4 s head as close-up and made the tail wide next to another wide shot."""
    from shorts.clip import MIN_SHOT, _force_switch

    planned = [Shot(0.0, 8.967, "close"), Shot(8.967, 17.167, "wide"), Shot(17.167, 27.927, "close"),
               Shot(27.927, 37.3, "wide"), Shot(37.3, 44.72, "close"), Shot(44.72, 58.7, "wide")]
    shots = _force_switch(planned, [17.567, 37.3], MIN_SHOT)
    _assert_shot_list_sane(shots, 58.7)
    assert all(s.end - s.start >= MIN_SHOT for s in shots)


def test_force_switch_tiny_fragments_on_both_sides_still_merge():
    from shorts.clip import _force_switch

    shots = _force_switch([Shot(0.0, 5.0, "wide"), Shot(5.0, 6.0, "close"), Shot(6.0, 11.0, "wide")], [5.4], 4.0)
    _assert_shot_list_sane(shots, 11.0)


def test_force_switch_merges_adjacent_same_kind_shots():
    from shorts.clip import _force_switch

    shots = _force_switch([Shot(0.0, 10.0, "wide"), Shot(10.0, 20.0, "wide")], [], 4.0)
    assert shots == [Shot(0.0, 20.0, "wide")]


def _kind_at(shots, t):
    return next(s.kind for s in shots if s.start <= t < s.end)


def _is_boundary(shots, j):
    return any(abs(s.start - j) < 1e-6 for s in shots)


def test_join_near_the_end_of_a_shot_keeps_the_hook_close_up():
    from shorts.clip import _force_switch

    shots = _force_switch([Shot(0.0, 10.0, "close"), Shot(10.0, 20.0, "wide")], [9.5], 4.0)
    assert shots == [Shot(0.0, 9.5, "close"), Shot(9.5, 20.0, "wide")]
    shots = _force_switch([Shot(0.0, 10.0, "wide"), Shot(10.0, 20.0, "close")], [9.5], 4.0)
    assert shots == [Shot(0.0, 9.5, "wide"), Shot(9.5, 20.0, "close")]


def test_two_joins_inside_one_shot_both_stay_boundaries():
    from shorts.clip import _force_switch

    shots = _force_switch([Shot(0.0, 10.0, "close"), Shot(10.0, 20.0, "wide")], [3.0, 5.0], 4.0)
    assert shots == [Shot(0.0, 3.0, "close"), Shot(3.0, 5.0, "wide"), Shot(5.0, 10.0, "close"),
                     Shot(10.0, 20.0, "wide")]
    assert _force_switch([Shot(0.0, 10.0, "close"), Shot(10.0, 20.0, "wide")], [5.0, 3.0], 4.0) == shots


def test_joins_less_than_a_second_apart_skip_the_second_flip():
    from shorts.clip import _force_switch

    shots = _force_switch([Shot(0.0, 10.0, "close"), Shot(10.0, 20.0, "wide")], [5.0, 5.4], 4.0)
    _assert_shot_list_sane(shots, 20.0)
    assert _is_boundary(shots, 5.0) and not _is_boundary(shots, 5.4)


def test_join_at_zero_or_on_a_shot_bound_changes_nothing():
    from shorts.clip import _force_switch

    base = [Shot(0.0, 10.0, "close"), Shot(10.0, 20.0, "wide")]
    assert _force_switch(base, [0.0, 10.0, 10.0 + 1e-9], 4.0) == base


def test_every_join_is_a_boundary_over_random_join_sets():
    import random

    from shorts.clip import _force_switch

    rnd = random.Random(7)
    base = [Shot(0.0, 8.0, "close"), Shot(8.0, 20.0, "wide"), Shot(20.0, 31.0, "close"),
            Shot(31.0, 45.0, "wide")]
    for _ in range(300):
        joins = sorted(round(rnd.uniform(0.2, 44.8), 2) for _ in range(rnd.randint(1, 4)))
        shots = _force_switch(base, joins, 4.0)
        _assert_shot_list_sane(shots, 45.0)
        for k, j in enumerate(joins):
            shot = next(b for b in base if b.start <= j < b.end)
            crowded = sum(shot.start < o < shot.end for o in joins) > 1  # tail of a multi-join shot may be a flash
            gaps = [abs(j - o) for o in [0.0, 45.0, *joins[:k], *joins[k + 1:]]]
            if crowded:
                gaps += [abs(j - shot.end)]
            if min(gaps) >= 1.0:  # the documented exception: a flip that would make a flash is skipped
                assert _is_boundary(shots, j), (joins, shots)


def test_close_zoom_overrides_the_format_zoom():
    w, s, tm = _grid()
    shots = plan_shots(tm, w, s, Span(100, 103), [], [])
    crops = crop_windows(shots, tm, 30, lambda t: 640.0, lambda t: Box(600, 200, 80, 80), 1280, 720,
                         "solo-seated", close_zoom=1.25)
    assert crops[0].h == 576 and crops[0].w == 324      # 720 / 1.25, at 9:16
    assert_in_bounds(crops, 1280, 720)
