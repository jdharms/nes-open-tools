"""Hole transforms: deterministic, versioned rewrites of a hole applied to a manifest slot.

A transform's name carries its version (`mirror@1`), and a transform that takes an
argument writes it after a colon (`hazards@1:1234`). Once a version ships, its output for
a given hole and argument must never change, since old manifests rebuild through it; a
change is a new version alongside the old one.
"""

import copy
import json
import random
from collections.abc import Callable, Iterable
from functools import cache

from golf.algorithms.features import Kind, feature_groups
from golf.algorithms.forest_fill import (
    ALL_FOREST_TILES,
    PLACEHOLDER_TILE,
    BetterForestFiller,
)
from golf.core.palettes import GREENS_WIDTH, TERRAIN_WIDTH
from golf.formats.hole_data import HoleData

from .catalog import REPO_ROOT

MIRROR_TABLE = REPO_ROOT / "data" / "tables" / "mirror_tiles.json"

#: the hole's width in course pixels; pixel x mirrors to `TERRAIN_PIXELS - 1 - x`
TERRAIN_PIXELS = TERRAIN_WIDTH * 8
#: flag offsets are in eighths of a course pixel across the 24-pixel green box
FLAG_UNITS = GREENS_WIDTH * 8


class TransformError(ValueError):
    pass


@cache
def mirror_tables() -> tuple[dict[int, int], dict[int, int]]:
    """The terrain and greens tile maps of `mirror@1`."""
    data = json.loads(MIRROR_TABLE.read_text())
    return tuple(
        {int(t, 16): int(m, 16) for t, m in data[kind].items()}
        for kind in ("terrain", "greens")
    )  # type: ignore[return-value]


def _mirror_rows(
    rows: list[list[int]], table: dict[int, int], what: str, keep: frozenset[int]
) -> list[list[int]]:
    out = []
    for y, row in enumerate(rows):
        mirrored = []
        for x, tile in enumerate(reversed(row)):
            if tile in keep:
                mirrored.append(PLACEHOLDER_TILE)
            elif tile in table:
                mirrored.append(table[tile])
            else:
                raise TransformError(
                    f"{what} tile ${tile:02X} at row {y}, column {len(row) - 1 - x} "
                    "has no mirror"
                )
        out.append(mirrored)
    return out


def _refill_forests(terrain: list[list[int]]) -> None:
    """Replace every placeholder with forest, in place."""
    filler = BetterForestFiller()
    for region in filler.detect_regions(terrain):
        for (row, col), tile in filler.fill_region(terrain, region).items():
            terrain[row][col] = tile
    for y, row in enumerate(terrain):
        if PLACEHOLDER_TILE in row:
            raise TransformError(f"forest fill left row {y} incomplete")


def mirror_hole(hole: HoleData) -> HoleData:
    """`mirror@1`: the hole flipped left to right.

    Every tile is swapped for its partner in `data/tables/mirror_tiles.json`, except tiles
    with trees in a forest, which are removed and the forest refilled
    (`docs/forest_notes.md`), because the fill pattern only runs one way.
    """
    terrain_table, greens_table = mirror_tables()
    out = HoleData()
    out.terrain = _mirror_rows(hole.terrain, terrain_table, "terrain", ALL_FOREST_TILES)
    _refill_forests(out.terrain)
    out.terrain_height = hole.terrain_height
    out.attributes = [list(reversed(row)) for row in hole.attributes]
    out.greens = _mirror_rows(hole.greens, greens_table, "greens", frozenset())
    out.green_x = TERRAIN_PIXELS - GREENS_WIDTH - hole.green_x
    out.green_y = hole.green_y
    out.metadata = copy.deepcopy(hole.metadata)
    tee = out.metadata["tee"]
    tee["x"] = TERRAIN_PIXELS - 1 - tee["x"]
    for flag in out.metadata["flag_positions"]:
        flag["x_offset"] = FLAG_UNITS - 1 - flag["x_offset"]
    return out


#: the palettes the hazard transforms write. Vanilla water also uses palette 0, which plays
#: the same
HAZARD_PALETTE = {Kind.SAND: 2, Kind.WATER: 3}
MAX_HAZARD_SEED = 0xFFFF_FFFF

#: `hazards@1`: the chance any group comes out water; about vanilla's share (195 of 548)
HAZARD_WATER_CHANCE = 0.35

#: `hazards-weighted@1`: the most likely a group is to change type, by what it is now
HAZARD_FLIP_CHANCE = {Kind.SAND: 0.3, Kind.WATER: 0.5}
#: groups up to this many pixels flip at the full chance; larger ones at chance * this / size
HAZARD_FULL_CHANCE_PIXELS = 1000


def _redraw_hazards(
    hole: HoleData, seed: int, draw: Callable[[Kind, int, float], Kind]
) -> HoleData:
    """`hole` with each bunker and water group given the kind `draw` picks.

    Features that share a supertile share its palette, so each group of them
    (`golf.algorithms.features`) takes one roll, in order, from a PRNG seeded with `seed`;
    `draw` gets the group's kind, its size in pixels and the roll. A group that changes has
    every supertile it covers repainted; one that stays keeps its palettes. Groups
    containing fairway, or both sand and water, are left alone.
    """
    out = copy.deepcopy(hole)
    rng = random.Random(seed)
    for group in feature_groups(hole):
        roll = rng.random()
        if len(group.kinds) != 1 or Kind.FAIRWAY in group.kinds:
            continue
        (kind,) = group.kinds
        size = sum(len(feature.pixels) for feature in group.features)
        new = draw(kind, size, roll)
        if new is not kind:
            for row, col in group.supertiles:
                out.attributes[row][col] = HAZARD_PALETTE[new]
    return out


def hazards_hole(hole: HoleData, seed: int) -> HoleData:
    """`hazards@1:<seed>`: every bunker and water hazard redrawn, whatever it was.

    Each group comes out water with `HAZARD_WATER_CHANCE` and sand otherwise, so a lake is
    as likely to dry out as a greenside bunker is to fill.
    """

    def draw(kind: Kind, size: int, roll: float) -> Kind:
        return Kind.WATER if roll < HAZARD_WATER_CHANCE else Kind.SAND

    return _redraw_hazards(hole, seed, draw)


def hazards_weighted_hole(hole: HoleData, seed: int) -> HoleData:
    """`hazards-weighted@1:<seed>`: bunkers and water hazards turned into each other.

    A group flips with `HAZARD_FLIP_CHANCE` of its kind, scaled down in proportion to its
    size past `HAZARD_FULL_CHANCE_PIXELS`: small hazards are toss-ups, a large lake rarely
    dries out.
    """

    def draw(kind: Kind, size: int, roll: float) -> Kind:
        chance = HAZARD_FLIP_CHANCE[kind] * min(1, HAZARD_FULL_CHANCE_PIXELS / size)
        if roll >= chance:
            return kind
        return Kind.SAND if kind is Kind.WATER else Kind.WATER

    return _redraw_hazards(hole, seed, draw)


def _seeded(
    transform: Callable[[HoleData, int], HoleData], name: str
) -> Callable[[str | None], Callable[[HoleData], HoleData]]:
    def build(argument: str | None) -> Callable[[HoleData], HoleData]:
        if (
            argument is None
            or not argument.isdecimal()
            or int(argument) > MAX_HAZARD_SEED
        ):
            raise TransformError(
                f"{name} takes a seed from 0 to {MAX_HAZARD_SEED}, as {name}:<seed>"
            )
        seed = int(argument)
        return lambda hole: transform(hole, seed)

    return build


def _no_argument(transform: Callable[[HoleData], HoleData], name: str):
    def build(argument: str | None) -> Callable[[HoleData], HoleData]:
        if argument is not None:
            raise TransformError(f"{name} takes no argument")
        return transform

    return build


#: each transform's name, and how to build it from the argument after the colon
TRANSFORMS: dict[str, Callable[[str | None], Callable[[HoleData], HoleData]]] = {
    "mirror@1": _no_argument(mirror_hole, "mirror@1"),
    "hazards@1": _seeded(hazards_hole, "hazards@1"),
    "hazards-weighted@1": _seeded(hazards_weighted_hole, "hazards-weighted@1"),
}


def parse_transform(text: str) -> Callable[[HoleData], HoleData]:
    """The transform `text` names, with its argument bound."""
    name, colon, argument = text.partition(":")
    if name not in TRANSFORMS:
        raise TransformError(f"unknown transform {text!r}")
    return TRANSFORMS[name](argument if colon else None)


def apply_transforms(hole: HoleData, names: Iterable[str]) -> HoleData:
    """`hole` with each named transform applied in order."""
    for name in names:
        hole = parse_transform(name)(hole)
    return hole
