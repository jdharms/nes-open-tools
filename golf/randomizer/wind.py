"""
Wind profiles: how a seed's 18 holes get their wind anchors.

A hole's wind is two anchors (`docs/wind.md`): a direction, one of 16 steps of `$10`
clockwise from `$00` (up the screen, a tailwind on every hole), and a speed from 0 to
10 that each swing jitters. A seed has two profiles, one for each, chosen
independently (ADR 0018). The `wind_anchors` patch writes the result into the ROM.

Under the `vanilla` profile a hole keeps the anchor its own wind seed would have dealt,
so a seed with both profiles `vanilla` plays as the unpatched game deals it, the
coupling between direction and speed included.

**Speed.** Anchors fall in three bands. 10 is moderate and 9 strong because of how the
game wraps a jittered speed of 10 or more: anchor 10 plays at 5 on half its swings and
never above 9, while anchor 9 plays at 8-9 on five swings in eight.

Every other speed profile is an *intensity* per hole, from 0 to 1. A hole draws its
band with odds (1-t)^2, 2t(1-t) and t^2 for gentle, moderate and strong, then an anchor
uniformly within the band. Intensity 0 is always gentle and 1 always strong; between
them the bands mix, so a ramp is noisy and need not rise hole by hole. A storm arrives
or clears over `RAMP_HOLES` holes, at a point in the round drawn per seed.

**Direction.** A cone is five neighboring directions drawn with weights 1, 2, 2, 2, 1,
around a center.

See docs/wind_profiles.md.
"""

import random
from collections.abc import Sequence
from fractions import Fraction

HOLES = 18
NINE = 9
VANILLA = "vanilla"

# -- Speed ------------------------------------------------------------------------------------

GENTLE = "gentle"
MODERATE = "moderate"
STRONG = "strong"
STORM_ROLLING_IN = "storm_rolling_in"
DYING_WIND = "dying_wind"
STORM_PASSING = "storm_passing"
BACK_NINE_PRESSURE = "back_nine_pressure"
SPEED_PROFILES = (
    VANILLA,
    GENTLE,
    MODERATE,
    STRONG,
    STORM_ROLLING_IN,
    DYING_WIND,
    STORM_PASSING,
    BACK_NINE_PRESSURE,
)

#: the speed anchors of each band, weakest band first
BANDS: dict[str, tuple[int, ...]] = {
    GENTLE: (0, 1, 2, 3),
    MODERATE: (4, 5, 6, 10),
    STRONG: (7, 8, 9),
}
#: holes a storm takes to arrive or clear, at intensities 1/5, 2/5, 3/5 and 4/5
RAMP_HOLES = 4
#: the holes a storm rolling in can start arriving on, as hole numbers
ONSET_HOLES = range(6, 11)
#: the holes a passing storm can be centered on, as hole numbers: the ones that leave
#: the whole storm inside the round, with a calm 1st and 18th
PEAK_HOLES = range(7, 13)
#: holes a passing storm stays at full strength, centered on its peak hole
PEAK_HOLD = 3

# -- Direction --------------------------------------------------------------------------------

PREVAILING = "prevailing"
OUT_AND_BACK = "out_and_back"
HEADWIND_OUT = "headwind_out"
TAILWIND_OUT = "tailwind_out"
DIRECTION_PROFILES = (VANILLA, PREVAILING, OUT_AND_BACK, HEADWIND_OUT, TAILWIND_OUT)

DIRECTION_STEP = 0x10
DIRECTION_COUNT = 16
#: every hole plays up the screen, so a wind blowing up it is behind the player
TAILWIND = 0x00
HEADWIND = 0x80
#: a cone's directions as steps from its center, each with its weight
CONE = ((-2, 1), (-1, 2), (0, 2), (1, 2), (2, 1))
#: where each direction blows toward, with the top of the screen as north
COMPASS = (
    "N",
    "NNE",
    "NE",
    "ENE",
    "E",
    "ESE",
    "SE",
    "SSE",
    "S",
    "SSW",
    "SW",
    "WSW",
    "W",
    "WNW",
    "NW",
    "NNW",
)


def compass(direction: int) -> str:
    """The compass point a direction anchor blows toward: `$00` N, `$40` E, `$80` S."""
    return COMPASS[direction // DIRECTION_STEP]


def _arriving(first: int) -> list[Fraction]:
    """A storm arriving: 0 before hole index `first`, rising over `RAMP_HOLES`, then 1."""
    steps = RAMP_HOLES + 1
    return [
        Fraction(min(max(hole - first + 1, 0), steps), steps) for hole in range(HOLES)
    ]


def _clearing(last: int) -> list[Fraction]:
    """A storm clearing: 1 up to hole index `last`, falling over `RAMP_HOLES`, then 0."""
    return _arriving(HOLES - 1 - last - RAMP_HOLES)[::-1]


def _passing(peak: int) -> list[Fraction]:
    """A storm that arrives, holds `PEAK_HOLD` holes around index `peak`, and clears."""
    before = PEAK_HOLD // 2
    arriving = _arriving(peak - before - RAMP_HOLES)
    clearing = _clearing(peak - before + PEAK_HOLD - 1)
    return [min(pair) for pair in zip(arriving, clearing, strict=True)]


def intensities(profile: str, rng: random.Random) -> list[Fraction]:
    """The intensity of each hole, 0 to 1, under a speed profile that has one."""
    if profile == GENTLE:
        return [Fraction(0)] * HOLES
    if profile == STRONG:
        return [Fraction(1)] * HOLES
    if profile == STORM_ROLLING_IN:
        return _arriving(rng.choice(ONSET_HOLES) - 1)
    if profile == DYING_WIND:
        return _arriving(rng.choice(ONSET_HOLES) - 1)[::-1]
    if profile == STORM_PASSING:
        return _passing(rng.choice(PEAK_HOLES) - 1)
    if profile == BACK_NINE_PRESSURE:
        return [Fraction(0)] * NINE + [Fraction(1)] * (HOLES - NINE)
    raise ValueError(f"speed profile {profile!r} has no intensity")


def band_weights(intensity: Fraction) -> tuple[int, int, int]:
    """Whole-number odds of gentle, moderate and strong at an intensity."""
    strong, scale = intensity.numerator, intensity.denominator
    gentle = scale - strong
    return gentle * gentle, 2 * gentle * strong, strong * strong


def _weighted[T](rng: random.Random, choices: Sequence[tuple[T, int]]) -> T:
    """One of `choices` by its whole-number weight, with no floating point in the roll."""
    roll = rng.randrange(sum(weight for _, weight in choices))
    for value, weight in choices:
        if roll < weight:
            return value
        roll -= weight
    raise AssertionError("a roll below the total weight always lands")


def draw_speeds(profile: str, vanilla: Sequence[int], rng: random.Random) -> list[int]:
    """Each hole's speed anchor. `vanilla` is what each hole's wind seed deals."""
    if profile not in SPEED_PROFILES:
        raise ValueError(f"unknown wind speed profile {profile!r}")
    if profile == VANILLA:
        return list(vanilla)
    if profile == MODERATE:
        return [rng.choice(BANDS[MODERATE]) for _ in range(HOLES)]
    speeds = []
    for intensity in intensities(profile, rng):
        band = _weighted(rng, list(zip(BANDS, band_weights(intensity), strict=True)))
        speeds.append(rng.choice(BANDS[band]))
    return speeds


def _cone(center: int, rng: random.Random) -> int:
    step = _weighted(rng, CONE)
    return (center + step * DIRECTION_STEP) % (DIRECTION_COUNT * DIRECTION_STEP)


def draw_directions(
    profile: str, vanilla: Sequence[int], rng: random.Random
) -> list[int]:
    """Each hole's direction anchor. `vanilla` is what each hole's wind seed deals."""
    if profile not in DIRECTION_PROFILES:
        raise ValueError(f"unknown wind direction profile {profile!r}")
    if profile == VANILLA:
        return list(vanilla)
    if profile == HEADWIND_OUT:
        out = HEADWIND
    elif profile == TAILWIND_OUT:
        out = TAILWIND
    else:
        out = rng.randrange(DIRECTION_COUNT) * DIRECTION_STEP
    back = out if profile == PREVAILING else out ^ HEADWIND
    return [_cone(out if hole < NINE else back, rng) for hole in range(HOLES)]
