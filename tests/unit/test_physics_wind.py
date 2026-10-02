"""The wind's probabilities (`golf.physics.wind`), from the RNG model alone."""

import math

from golf.physics.wind import JITTER, WindAnchor, hole_draws, hole_winds, shot_winds


def test_jitter():
    assert JITTER == {-1: 1 / 8, 0: 1 / 2, 1: 1 / 4, 2: 1 / 8}


def test_only_64_anchor_pairs_occur():
    winds = hole_winds()
    assert len(winds) == 64
    assert math.isclose(sum(winds.values()), 1)
    assert all(math.isclose(p, 1 / 64, rel_tol=1e-3) for p in winds.values())
    speeds: dict[int, set[int]] = {}
    for anchor in winds:
        speeds.setdefault(anchor.direction, set()).add(anchor.speed)
    assert sorted(speeds) == list(range(0, 0x100, 0x10))
    assert all(len(s) == 4 for s in speeds.values())
    # A pure crosswind comes only at these anchors.
    assert speeds[0x40] == speeds[0xC0] == {1, 4, 7, 10}


def test_pin_is_independent_of_the_wind():
    winds = hole_winds()
    for (pin, anchor), probability in hole_draws().items():
        assert pin in range(4)
        assert math.isclose(probability, winds[anchor] / 4, rel_tol=1e-2)


def test_shot_winds():
    calm = shot_winds(WindAnchor(0x60, 0))
    # A jitter of -1 turns a calm hole's wind round at speed 1.
    assert calm == {
        (0x60, 0): 1 / 2,
        (0x60, 1): 1 / 4,
        (0x60, 2): 1 / 8,
        (0xE0, 1): 1 / 8,
    }
    strong = shot_winds(WindAnchor(0x40, 10))
    # 10 and more come down by 5.
    assert strong == {
        (0x40, 5): 1 / 2,
        (0x40, 6): 1 / 4,
        (0x40, 7): 1 / 8,
        (0x40, 9): 1 / 8,
    }
