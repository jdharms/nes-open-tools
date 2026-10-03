"""Mirroring a hole left to right.

Every terrain and greens tile is swapped for its partner in
`data/tables/mirror_tiles.json`, except forest tiles with trees: the forest fill pattern
only runs one way, so those are replaced with placeholders and the forest is filled
again (`golf/algorithms/forest_fill.py`). Terrain (22 tiles) and greens (24) are both an
even number of tiles wide, so reversing each attribute row keeps every supertile over
its own tiles.

The partners are chosen for how a tile plays and looks, not as pixel-exact flips, which
the tileset often lacks (`docs/hole_transforms.md`).
"""

import copy
import json
from functools import cache
from pathlib import Path
from typing import NamedTuple

from golf.core.palettes import GREENS_WIDTH, TERRAIN_WIDTH
from golf.formats.hole_data import HoleData

from .forest_fill import ALL_FOREST_TILES, PLACEHOLDER_TILE, ForestFiller

MIRROR_TABLE = (
    Path(__file__).resolve().parents[2] / "data" / "tables" / "mirror_tiles.json"
)

#: the hole's width in course pixels
TERRAIN_PIXELS = TERRAIN_WIDTH * 8
#: `InitHole` starts the ball at the tee's x with fraction $80, the middle of the pixel
#: (bank 13 $8173), and centers the tee blocks on it ($8F18), so x mirrors to this minus x
TEE_MIRROR = TERRAIN_PIXELS - 1
#: a flag offset `o` puts the pin `o / 8 + $28 / 256` pixels into the green box ($DB3F),
#: and this minus `o` keeps every pin in the mirrored pixel column
FLAG_MIRROR = 189


class MirrorError(ValueError):
    pass


class MirrorTiles(NamedTuple):
    """Each tile's left-right partner. Both maps are their own inverse."""

    terrain: dict[int, int]
    greens: dict[int, int]


@cache
def mirror_tiles() -> MirrorTiles:
    data = json.loads(MIRROR_TABLE.read_text())
    terrain, greens = (
        {int(tile, 16): int(partner, 16) for tile, partner in data[kind].items()}
        for kind in ("terrain", "greens")
    )
    return MirrorTiles(terrain, greens)


def _mirror_rows(
    rows: list[list[int]],
    partners: dict[int, int],
    what: str,
    refill: frozenset[int] = frozenset(),
) -> list[list[int]]:
    out = []
    for y, row in enumerate(rows):
        mirrored = []
        for x, tile in enumerate(reversed(row)):
            if tile in refill:
                mirrored.append(PLACEHOLDER_TILE)
            elif tile in partners:
                mirrored.append(partners[tile])
            else:
                raise MirrorError(
                    f"{what} tile ${tile:02X} at row {y}, column {len(row) - 1 - x} "
                    "has no mirror"
                )
        out.append(mirrored)
    return out


def mirror_hole(hole: HoleData) -> HoleData:
    """`hole` flipped left to right, as a new hole.

    The y coordinates, distance, scroll limit and the rest of the metadata stay as they
    are.
    """
    tiles = mirror_tiles()
    out = HoleData()
    out.terrain = _mirror_rows(hole.terrain, tiles.terrain, "terrain", ALL_FOREST_TILES)
    ForestFiller().fill_all(out.terrain)
    out.terrain_height = hole.terrain_height
    out.attributes = [list(reversed(row)) for row in hole.attributes]
    out.greens = _mirror_rows(hole.greens, tiles.greens, "greens")
    out.green_x = TERRAIN_PIXELS - GREENS_WIDTH - hole.green_x
    out.green_y = hole.green_y
    out.metadata = copy.deepcopy(hole.metadata)
    tee = out.metadata["tee"]
    tee["x"] = TEE_MIRROR - tee["x"]
    for flag in out.metadata["flag_positions"]:
        flag["x_offset"] = FLAG_MIRROR - flag["x_offset"]
    return out
