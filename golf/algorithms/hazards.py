"""Redrawing a hole's bunkers and water hazards.

A feature's palette is its lie (`golf/algorithms/features.py`), so turning sand into water
changes only the attributes; no terrain tile changes. Features that share a supertile
share its palette, so each group of them is redrawn as one.

`redraw_hazards` does the work every style shares. A style is a `Draw`: given a group's
kind, its size in pixels and a roll in [0, 1), the kind it becomes. Each style is its own
transform (`golf/randomizer/transforms.py`), so one can change without touching seeds
built with another.
"""

import copy
import random
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from golf.formats.hole_data import HoleData

from .features import Kind, Supertile, feature_groups

#: a hazard style: (kind, size in pixels, roll in [0, 1)) -> the kind it becomes
Draw = Callable[[Kind, int, float], Kind]

#: the palettes a redrawn group gets. Vanilla water also uses palette 0, which plays the
#: same, but palette 0's color 2 is the HUD text (`docs/seasonal_terrain.md`)
HAZARD_PALETTE = {Kind.SAND: 2, Kind.WATER: 3}

#: `uniform`: the chance a group comes out water; vanilla's share, 195 of the 548 hazard
#: groups across the US, UK, Japan and Mario Open courses
WATER_CHANCE = 0.35

#: `weighted`: the most likely a group is to change kind, by what it is now
FLIP_CHANCE = {Kind.SAND: 0.3, Kind.WATER: 0.5}
#: `weighted`: groups up to this many pixels flip at the full chance, larger ones at
#: chance * this / size
FULL_CHANCE_PIXELS = 1000


@dataclass(frozen=True)
class HazardGroup:
    """What a redraw reads of a `FeatureGroup`: a small fraction of its memory, since a
    feature keeps every pixel it covers."""

    kinds: frozenset[Kind]
    #: color-3 pixels across the group's features
    size: int
    supertiles: frozenset[Supertile]


def hazard_groups(hole: HoleData) -> tuple[HazardGroup, ...]:
    """`feature_groups(hole)` cut to what `redraw_hazards` reads, in the same order."""
    return tuple(
        HazardGroup(
            group.kinds,
            sum(len(feature.pixels) for feature in group.features),
            group.supertiles,
        )
        for group in feature_groups(hole)
    )


def redraw_hazards(
    hole: HoleData,
    seed: int,
    draw: Draw,
    groups: Sequence[HazardGroup] | None = None,
) -> HoleData:
    """`hole` with each bunker and water group given the kind `draw` picks, as a new hole.

    Each group takes one roll, in the order `feature_groups` gives, from a PRNG seeded
    with `seed`. The roll is taken before deciding whether to skip the group, so a
    skipped group never shifts the rolls of the groups after it. Groups containing
    fairway, or both sand and water, are skipped. A group that changes kind has every
    supertile it covers repainted; one that keeps its kind keeps its palettes.

    `groups` is `hazard_groups(hole)` when the caller already has it, as the transform
    cache does (`golf/randomizer/transform_cache.py`); without it they are found here.
    """
    out = copy.deepcopy(hole)
    rng = random.Random(seed)
    for group in hazard_groups(hole) if groups is None else groups:
        roll = rng.random()
        if len(group.kinds) != 1 or Kind.FAIRWAY in group.kinds:
            continue
        (kind,) = group.kinds
        new = draw(kind, group.size, roll)
        if new is not kind:
            for row, col in group.supertiles:
                out.attributes[row][col] = HAZARD_PALETTE[new]
    return out


def uniform(kind: Kind, size: int, roll: float) -> Kind:
    """Water with `WATER_CHANCE`, sand otherwise, whatever the group was.

    A lake is as likely to dry out as a greenside bunker is to fill.
    """
    return Kind.WATER if roll < WATER_CHANCE else Kind.SAND


def weighted(kind: Kind, size: int, roll: float) -> Kind:
    """The other kind with `FLIP_CHANCE` of this one, scaled down past `FULL_CHANCE_PIXELS`.

    Small hazards are toss-ups; a large lake rarely dries out.
    """
    chance = FLIP_CHANCE[kind] * min(1, FULL_CHANCE_PIXELS / size)
    if roll >= chance:
        return kind
    return Kind.SAND if kind is Kind.WATER else Kind.WATER
