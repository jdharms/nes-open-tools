"""Unit tests for the wind profiles: the bands, the intensity ramps and the cones."""

import random
from collections import Counter
from fractions import Fraction

import pytest

from golf.randomizer.wind import (
    BACK_NINE_PRESSURE,
    BANDS,
    DIRECTION_PROFILES,
    DYING_WIND,
    GENTLE,
    HEADWIND,
    HEADWIND_OUT,
    MODERATE,
    ONSET_HOLES,
    OUT_AND_BACK,
    PEAK_HOLES,
    PREVAILING,
    SPEED_PROFILES,
    STORM_PASSING,
    STORM_ROLLING_IN,
    STRONG,
    TAILWIND,
    TAILWIND_OUT,
    VANILLA,
    band_weights,
    draw_directions,
    draw_speeds,
    intensities,
)

DEALT_SPEEDS = [n % 11 for n in range(18)]
DEALT_DIRECTIONS = [(n * 0x30) & 0xF0 for n in range(18)]
SEEDS = range(200)


def speeds(profile: str, seed: int) -> list[int]:
    return draw_speeds(profile, DEALT_SPEEDS, random.Random(seed))


def directions(profile: str, seed: int) -> list[int]:
    return draw_directions(profile, DEALT_DIRECTIONS, random.Random(seed))


def band_of(speed: int) -> str:
    return next(band for band, anchors in BANDS.items() if speed in anchors)


def steps_from(direction: int, center: int) -> int:
    """How many direction steps `direction` is from `center`, from -8 to 7."""
    return ((direction - center) // 0x10 + 8) % 16 - 8


def test_the_profiles_a_seed_can_name():
    assert SPEED_PROFILES == (
        "vanilla",
        "gentle",
        "moderate",
        "strong",
        "storm_rolling_in",
        "dying_wind",
        "storm_passing",
        "back_nine_pressure",
    )
    assert DIRECTION_PROFILES == (
        "vanilla",
        "prevailing",
        "out_and_back",
        "headwind_out",
        "tailwind_out",
    )


def test_the_bands_hold_every_anchor_once_with_ten_moderate_and_nine_strong():
    assert BANDS == {GENTLE: (0, 1, 2, 3), MODERATE: (4, 5, 6, 10), STRONG: (7, 8, 9)}
    assert sorted(anchor for band in BANDS.values() for anchor in band) == list(
        range(11)
    )


def test_vanilla_keeps_what_the_wind_seeds_deal():
    assert speeds(VANILLA, 0) == DEALT_SPEEDS
    assert directions(VANILLA, 0) == DEALT_DIRECTIONS


@pytest.mark.parametrize("profile", [*SPEED_PROFILES])
def test_a_speed_draw_is_eighteen_anchors_and_repeats_for_its_seed(profile):
    drawn = speeds(profile, 7)
    assert len(drawn) == 18 and all(speed in range(11) for speed in drawn)
    assert speeds(profile, 7) == drawn


@pytest.mark.parametrize("profile", [*DIRECTION_PROFILES])
def test_a_direction_draw_is_eighteen_steps_and_repeats_for_its_seed(profile):
    drawn = directions(profile, 7)
    assert len(drawn) == 18
    assert all(direction in range(0, 0x100, 0x10) for direction in drawn)
    assert directions(profile, 7) == drawn


@pytest.mark.parametrize("band", [GENTLE, MODERATE, STRONG])
def test_a_band_profile_draws_every_anchor_of_its_band_and_no_other(band):
    seen = Counter(speed for seed in SEEDS for speed in speeds(band, seed))
    assert set(seen) == set(BANDS[band])
    # uniform within the band: no anchor far from its share of 3,600 draws
    share = 18 * len(SEEDS) / len(BANDS[band])
    assert all(abs(count - share) < share * 0.15 for count in seen.values())


@pytest.mark.parametrize(
    ("intensity", "weights"),
    [
        (Fraction(0), (1, 0, 0)),
        (Fraction(1), (0, 0, 1)),
        (Fraction(1, 2), (1, 2, 1)),
        (Fraction(1, 4), (9, 6, 1)),
        (Fraction(10, 13), (9, 60, 100)),
    ],
)
def test_band_weights_are_the_squares_of_an_intensity(intensity, weights):
    assert band_weights(intensity) == weights


RAMP = [Fraction(step, 5) for step in range(1, 5)]


def storm(profile: str, seed: int) -> tuple[list[Fraction], list[str]]:
    """A profile's intensity curve and the bands it drew, for one seed.

    The curve's position is the profile's first draw, so the same seed gives the curve
    the speeds were drawn from.
    """
    curve = intensities(profile, random.Random(seed))
    return curve, [band_of(speed) for speed in speeds(profile, seed)]


def test_a_storm_rolls_in_over_four_holes_starting_on_hole_six_to_ten():
    starts = set()
    for seed in SEEDS:
        curve, drawn = storm(STORM_ROLLING_IN, seed)
        start = curve.index(RAMP[0])
        starts.add(start + 1)
        assert curve == [0] * start + RAMP + [1] * (18 - start - 4)
        assert drawn[:start] == [GENTLE] * start
        assert drawn[start + 4 :] == [STRONG] * (18 - start - 4)
        assert drawn[:5] == [GENTLE] * 5 and drawn[13:] == [STRONG] * 5
    assert starts == set(ONSET_HOLES) == {6, 7, 8, 9, 10}


def test_a_storms_arrival_is_noisy():
    """The bands mix on the ramp, so the wind need not rise hole by hole."""
    order = {GENTLE: 0, MODERATE: 1, STRONG: 2}
    rounds = [
        [order[band] for band in storm(STORM_ROLLING_IN, seed)[1]] for seed in SEEDS
    ]
    assert any(drawn != sorted(drawn) for drawn in rounds)
    assert any(MODERATE in storm(STORM_ROLLING_IN, seed)[1] for seed in SEEDS)


def test_a_dying_wind_is_a_storm_reversed():
    starts = set()
    for seed in SEEDS:
        curve, drawn = storm(DYING_WIND, seed)
        assert curve == sorted(curve, reverse=True)
        assert [value for value in curve if 0 < value < 1] == RAMP[::-1]
        starts.add(curve.index(RAMP[-1]) + 1)
        assert drawn[:5] == [STRONG] * 5 and drawn[13:] == [GENTLE] * 5
    # the mirror of a storm arriving: it starts to clear on holes 6-10 too
    assert starts == {6, 7, 8, 9, 10}


def test_back_nine_pressure_is_a_gentle_nine_then_a_strong_one():
    for seed in SEEDS:
        drawn = [band_of(speed) for speed in speeds(BACK_NINE_PRESSURE, seed)]
        assert drawn == [GENTLE] * 9 + [STRONG] * 9


def test_a_passing_storm_builds_for_four_holds_for_three_and_clears_for_four():
    centers = set()
    for seed in SEEDS:
        curve, drawn = storm(STORM_PASSING, seed)
        first = curve.index(Fraction(1))
        center = first + 1
        centers.add(center + 1)
        assert curve[first : first + 3] == [1, 1, 1] and curve.count(Fraction(1)) == 3
        # the whole storm fits in the round, between a calm 1st and a calm 18th
        calm_after = 18 - (first - 4) - 11
        assert curve == (
            [0] * (first - 4) + RAMP + [1, 1, 1] + RAMP[::-1] + [0] * calm_after
        )
        assert drawn[0] == drawn[-1] == GENTLE
        assert drawn[first : first + 3] == [STRONG] * 3
        assert all(
            band == GENTLE
            for band, value in zip(drawn, curve, strict=True)
            if value == 0
        )
    assert centers == set(PEAK_HOLES) == set(range(7, 13))


def test_a_passing_storm_leaves_seven_holes_calm():
    for seed in SEEDS:
        curve, _ = storm(STORM_PASSING, seed)
        assert curve.count(Fraction(0)) == 7


def cone_center(drawn: list[int]) -> int:
    """The one center every direction in `drawn` is within two steps of."""
    centers = [
        center
        for center in range(0, 0x100, 0x10)
        if all(abs(steps_from(direction, center)) <= 2 for direction in drawn)
    ]
    assert centers, f"no cone holds {[hex(d) for d in drawn]}"
    return centers[len(centers) // 2]


def test_a_prevailing_wind_stays_in_one_cone_all_round():
    centers = set()
    for seed in SEEDS:
        drawn = directions(PREVAILING, seed)
        centers.add(cone_center(drawn))
        assert max(abs(steps_from(a, b)) for a in drawn for b in drawn) <= 4, (
            "a cone is five directions wide"
        )
    assert len(centers) == 16


def test_out_and_back_turns_the_cone_round_at_the_turn():
    outward = set()
    for seed in SEEDS:
        drawn = directions(OUT_AND_BACK, seed)
        # the back nine, turned half a circle, sits in the front nine's cone
        turned = drawn[:9] + [direction ^ 0x80 for direction in drawn[9:]]
        outward.add(cone_center(turned))
    assert len(outward) == 16


@pytest.mark.parametrize(
    ("profile", "out", "back"),
    [(HEADWIND_OUT, HEADWIND, TAILWIND), (TAILWIND_OUT, TAILWIND, HEADWIND)],
)
def test_a_forced_out_and_back_centers_on_headwind_and_tailwind(profile, out, back):
    assert (HEADWIND, TAILWIND) == (0x80, 0x00)
    for seed in SEEDS:
        drawn = directions(profile, seed)
        assert all(abs(steps_from(direction, out)) <= 2 for direction in drawn[:9])
        assert all(abs(steps_from(direction, back)) <= 2 for direction in drawn[9:])


def test_a_cone_draws_its_ends_half_as_often_as_the_rest():
    steps = Counter(
        steps_from(direction, HEADWIND)
        for seed in range(900)
        for direction in directions(HEADWIND_OUT, seed)[:9]
    )
    total = sum(steps.values())
    assert set(steps) == {-2, -1, 0, 1, 2}
    for step, weight in [(-2, 1), (-1, 2), (0, 2), (1, 2), (2, 1)]:
        assert abs(steps[step] / total - weight / 8) < 0.02


def test_an_unknown_profile_is_refused():
    with pytest.raises(ValueError, match="speed profile"):
        speeds("hurricane", 0)
    with pytest.raises(ValueError, match="direction profile"):
        directions("swirling", 0)
