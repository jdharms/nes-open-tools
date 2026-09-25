"""
The wind the game deals, as probabilities: what `InitHole` ($DA90) and
`WindAdjustmentRoutine` ($DA25) make of the RNG (`docs/seeded_wind.md`).

`InitHole` draws three times: the pin (one of the hole's four), then
`WindDirectionAnchor` and `WindSpeedAnchor`, which hold for the whole hole.
Each shot's setup then draws once more for a speed jitter around the anchor.

The RNG is a 16-bit shift register that moves 11 bits a draw, so neighbouring
draws share bits. That leaves only 64 of the 176 pairs of anchors possible,
each direction with four speeds (`hole_winds`). The pin is independent of the
anchors, and the jitter is independent of both and of every other shot's.

Taking the RNG at hole start as equally likely to be any state on its cycle,
which the vanilla game's title screen and menus make of it, gives these
probabilities. A `seeded_wind` ROM fixes each hole's anchors instead
(`golf.core.rng.predict_hole`).
"""

from collections import Counter
from dataclasses import dataclass
from functools import cache

from golf.core.rng import (
    apply_jitter,
    predict_hole,
    wind_jitter,
)

#: The shift register's other cycle, two states long, which play never enters.
DEGENERATE_STATES = frozenset({0x5555, 0xAAAA})


def _jitter_probabilities() -> dict[int, float]:
    counts = Counter(wind_jitter(bits) for bits in range(8))
    return {jitter: n / 8 for jitter, n in sorted(counts.items())}


#: A shot's speed jitter, with its probability: `WindAdjustmentRoutine` keys it
#: on the draw's low 3 bits.
JITTER = _jitter_probabilities()


@dataclass(frozen=True, order=True)
class WindAnchor:
    """A hole's wind, before each shot's jitter."""

    direction: int
    """`WindDirectionAnchor` ($012F): a multiple of $10, as `ShotInput.wind_direction`."""
    speed: int
    """`WindSpeedAnchor` ($0130): 0-10."""


@cache
def hole_draws() -> dict[tuple[int, WindAnchor], float]:
    """
    Every (pin, anchors) `InitHole` can deal, with its probability: the
    fraction of RNG states on the cycle that lead to it. The pin is 0-3.
    """
    counts: Counter[tuple[int, WindAnchor]] = Counter()
    for state in range(0x10000):
        if state in DEGENERATE_STATES:
            continue
        hole = predict_hole(state, swings=0)
        counts[
            hole.pin_index, WindAnchor(hole.direction_anchor, hole.speed_anchor)
        ] += 1
    total = counts.total()
    return {draw: n / total for draw, n in sorted(counts.items())}


@cache
def hole_winds() -> dict[WindAnchor, float]:
    """The anchors a hole can have, with their probabilities."""
    winds: dict[WindAnchor, float] = {}
    for (_, anchor), probability in hole_draws().items():
        winds[anchor] = winds.get(anchor, 0.0) + probability
    return dict(sorted(winds.items()))


def shot_winds(anchor: WindAnchor) -> dict[tuple[int, int], float]:
    """
    The (`WindDirection`, `WindSpeed`) a shot can be dealt on a hole with
    `anchor`, with their probabilities.
    """
    winds: dict[tuple[int, int], float] = {}
    for jitter, probability in JITTER.items():
        wind = apply_jitter(anchor.direction, anchor.speed, jitter)
        winds[wind] = winds.get(wind, 0.0) + probability
    return dict(sorted(winds.items()))
