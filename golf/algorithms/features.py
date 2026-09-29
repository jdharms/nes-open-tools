"""Course features: the fairways, bunkers and water hazards of a hole's terrain.

The four terrain palettes differ only in colour 3, and only feature tiles (`$27`, the
lips and borders `$40`-`$7F`, the tree-edge tiles `$BC`-`$BF`) and the tee box draw with
it. So a feature is a 4-connected area of colour-3 pixels, and the black outlines inside
the border tiles keep neighbouring features apart even when they share a tile.

A feature's palette is also its lie (`LEFA7` in the fixed bank): 1 plays as fairway, 2 as
a bunker, and 0 or 3 as water. Features that share a supertile share its palette, so they
change type together; `feature_groups` collects them.
"""

from collections import Counter
from dataclasses import dataclass
from enum import Enum
from functools import cache
from pathlib import Path

from golf.core.chr_tile import TilesetData
from golf.formats.hole_data import HoleData

TERRAIN_TILESET = Path(__file__).resolve().parents[2] / "data" / "chr-ram.bin"

#: tee box tiles draw with colour 3 but are not a feature
TEE_BOX = frozenset(range(0x35, 0x3D))

Supertile = tuple[int, int]  # (row, col) in the attribute grid


class Kind(Enum):
    FAIRWAY = "fairway"
    SAND = "sand"
    WATER = "water"


KIND_OF_PALETTE = {0: Kind.WATER, 1: Kind.FAIRWAY, 2: Kind.SAND, 3: Kind.WATER}


@dataclass(frozen=True)
class Feature:
    #: colour-3 pixels in course coordinates, (x, y)
    pixels: frozenset[tuple[int, int]]
    #: pixel count per supertile the feature covers
    supertiles: dict[Supertile, int]
    #: the palette covering most of its pixels decides what it is
    kind: Kind


@dataclass(frozen=True)
class FeatureGroup:
    """Features tied together by shared supertiles: one palette choice covers them all."""

    features: tuple[Feature, ...]
    supertiles: frozenset[Supertile]

    @property
    def kinds(self) -> frozenset[Kind]:
        return frozenset(f.kind for f in self.features)


@cache
def colour_3_pixels() -> tuple[frozenset[tuple[int, int]], ...]:
    """For each terrain tile, the (x, y) pixels drawn in colour 3."""
    tileset = TilesetData(str(TERRAIN_TILESET))
    out = []
    for tile in range(256):
        rows = tileset.decode_tile(tile)
        out.append(
            frozenset(
                (x, y)
                for y, row in enumerate(rows)
                for x, c in enumerate(row)
                if c == 3
            )
        )
    return tuple(out)


def find_features(hole: HoleData) -> list[Feature]:
    """Every feature in the visible terrain, in reading order of its first pixel."""
    shapes = colour_3_pixels()
    pixels = set()
    for ty in range(hole.terrain_height):
        for tx, tile in enumerate(hole.terrain[ty]):
            if tile not in TEE_BOX:
                pixels.update((tx * 8 + x, ty * 8 + y) for x, y in shapes[tile])
    features = []
    seen: set[tuple[int, int]] = set()
    for start in sorted(pixels, key=lambda p: (p[1], p[0])):
        if start in seen:
            continue
        seen.add(start)
        stack, area = [start], []
        while stack:
            x, y = stack.pop()
            area.append((x, y))
            for n in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if n in pixels and n not in seen:
                    seen.add(n)
                    stack.append(n)
        per_supertile = Counter((y // 16, x // 16) for x, y in area)
        by_kind = Counter()
        for (row, col), n in per_supertile.items():
            by_kind[KIND_OF_PALETTE[hole.attributes[row][col]]] += n
        features.append(
            Feature(frozenset(area), dict(per_supertile), by_kind.most_common(1)[0][0])
        )
    return features


def feature_groups(hole: HoleData) -> list[FeatureGroup]:
    """Features merged wherever they share a supertile, in order of their first feature."""
    features = find_features(hole)
    parent = list(range(len(features)))

    def root(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    owner: dict[Supertile, int] = {}
    for i, feature in enumerate(features):
        for supertile in feature.supertiles:
            if supertile in owner:
                a, b = root(owner[supertile]), root(i)
                parent[max(a, b)] = min(a, b)
            else:
                owner[supertile] = i
    members: dict[int, list[Feature]] = {}
    for i, feature in enumerate(features):
        members.setdefault(root(i), []).append(feature)
    return [
        FeatureGroup(tuple(group), frozenset(s for f in group for s in f.supertiles))
        for _, group in sorted(members.items())
    ]
