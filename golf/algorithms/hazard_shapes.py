"""Hazard shapes: the distinct bunkers and water hazards a set of holes draws.

A shape is the tiles one feature (`golf.algorithms.features`) covers, cut out of the
terrain, with the rest of its bounding box left empty. Only enclosed hazards count: one
whose pixels reach the edge of the terrain is a river or a coastline, cut off by the
screen rather than drawn whole. Sand and water are not told apart, since they draw with
the same tiles and differ only in palette.
"""

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass

from golf.core.palettes import TERRAIN_WIDTH
from golf.formats.hole_data import HoleData

from .features import Feature, Kind, find_features

Tiles = tuple[tuple[int | None, ...], ...]

#: the largest side of a shape's bounding box, in tiles, that each bucket takes
SIZE_BUCKETS = (("tiny", 3), ("small", 5), ("medium", 8))
LARGEST_BUCKET = "large"


@dataclass(frozen=True)
class HazardShape:
    #: rows of terrain tiles, None where the bounding box is outside the hazard
    tiles: Tiles
    #: how many hazards in the holes have this shape
    count: int

    @property
    def height(self) -> int:
        return len(self.tiles)

    @property
    def width(self) -> int:
        return len(self.tiles[0])

    @property
    def tile_count(self) -> int:
        return sum(tile is not None for row in self.tiles for tile in row)

    @property
    def bucket(self) -> str:
        side = max(self.height, self.width)
        for name, limit in SIZE_BUCKETS:
            if side <= limit:
                return name
        return LARGEST_BUCKET


def is_enclosed(feature: Feature, hole: HoleData) -> bool:
    """Whether no pixel of the feature is on the edge of the visible terrain."""
    right, bottom = TERRAIN_WIDTH * 8 - 1, hole.terrain_height * 8 - 1
    return all(0 < x < right and 0 < y < bottom for x, y in feature.pixels)


def feature_tiles(feature: Feature, hole: HoleData) -> Tiles:
    """The tiles the feature has pixels in, within its bounding box."""
    cells = {(y // 8, x // 8) for x, y in feature.pixels}
    rows = [row for row, _ in cells]
    cols = [col for _, col in cells]
    return tuple(
        tuple(
            hole.terrain[row][col] if (row, col) in cells else None
            for col in range(min(cols), max(cols) + 1)
        )
        for row in range(min(rows), max(rows) + 1)
    )


def hazard_shapes(holes: Iterable[HoleData]) -> list[HazardShape]:
    """Every distinct enclosed hazard in `holes`, smallest first."""
    counts: Counter[Tiles] = Counter()
    for hole in holes:
        for feature in find_features(hole):
            if feature.kind is not Kind.FAIRWAY and is_enclosed(feature, hole):
                counts[feature_tiles(feature, hole)] += 1
    shapes = [HazardShape(tiles, count) for tiles, count in counts.items()]
    return sorted(
        shapes, key=lambda s: (s.tile_count, s.height, s.width, repr(s.tiles))
    )
