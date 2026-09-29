"""Hole transforms: deterministic, versioned rewrites of a hole applied to a manifest slot.

A transform's name carries its version (`mirror@1`). Once a version ships, its output for a
given hole must never change, since old manifests rebuild through it; a change is a new
version alongside the old one.
"""

import copy
import json
from collections.abc import Callable, Iterable
from functools import cache

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


TRANSFORMS: dict[str, Callable[[HoleData], HoleData]] = {"mirror@1": mirror_hole}


def apply_transforms(hole: HoleData, names: Iterable[str]) -> HoleData:
    """`hole` with each named transform applied in order."""
    for name in names:
        if name not in TRANSFORMS:
            raise TransformError(f"unknown transform {name!r}")
        hole = TRANSFORMS[name](hole)
    return hole
