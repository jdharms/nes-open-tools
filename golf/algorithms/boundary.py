"""The out-of-bounds line: the tiles that draw where the out-of-bounds ground ends.

Out of bounds is speckled ground, usually under forest, edged with a solid black line.
The line is drawn by `$80`-`$9B`, each of which holds one piece of it running between two
points on the tile's edge: a corner, or the middle of a side. The 28 tiles are every such
piece - corner to opposite corner, the middle of a side to either far corner, straight
across from side to side, and along a side from corner to corner - each with the
out-of-bounds ground on one side of it or the other. So two line tiles side by side
continue the line only if it crosses their shared side at the same point.

Inside the line is forest (`$A0`-`$BB`) or bare out-of-bounds ground (`$3F`). The vanilla
holes put the edge of a water hazard straight against them as well, with no line
between: the water's black lip is then the boundary. They never do that with a fairway,
and with a bunker only twice.

See `docs/feature_brush.md`.
"""

import numpy as np

from golf.core.palettes import TERRAIN_WIDTH
from golf.formats.hole_data import HoleData

from .features import KIND_OF_PALETTE, TEE_BOX, Kind

LINE_TILES = range(0x80, 0x9C)
#: bare out-of-bounds ground, with no trees and no line
OPEN_GROUND = 0x3F
FOREST_TILES = range(0xA0, 0xBC)

#: the sides of each line tile that are out of bounds all along, from where the vanilla
#: holes put forest beside it; the line meets the other sides, or crosses them
OUT_SIDES = {
    0x80: ("up", "left"),
    0x81: ("up", "right"),
    0x82: ("down", "left"),
    0x83: ("right", "down"),
    0x84: ("up", "left"),
    0x85: ("up",),
    0x86: ("up",),
    0x87: ("up", "right"),
    0x88: ("left",),
    0x89: ("up", "left"),
    0x8A: ("up", "right"),
    0x8B: ("right",),
    0x8C: ("down", "left"),
    0x8D: ("down",),
    0x8E: ("down",),
    0x8F: ("right", "down"),
    0x90: ("left",),
    0x91: ("down", "left"),
    0x92: ("right", "down"),
    0x93: ("right",),
    0x94: ("up", "right", "left"),
    0x95: ("right", "down", "left"),
    0x96: ("up", "right", "down"),
    0x97: ("up", "down", "left"),
    0x98: ("up",),
    0x99: ("down",),
    0x9A: ("left",),
    0x9B: ("right",),
}

_STEPS_8 = [(dy, dx) for dy in (-1, 0, 1) for dx in (-1, 0, 1) if dy or dx]
_STEPS_4 = [(-1, 0), (1, 0), (0, -1), (0, 1)]


def _components(mask: np.ndarray, steps: list[tuple[int, int]]) -> np.ndarray:
    """Each set pixel labeled by its connected part, from 1; unset pixels are 0."""
    labels = np.zeros(mask.shape, int)
    count = 0
    for y, x in zip(*np.nonzero(mask), strict=True):
        if labels[y, x]:
            continue
        count += 1
        labels[y, x] = count
        stack = [(y, x)]
        while stack:
            cy, cx = stack.pop()
            for dy, dx in steps:
                ny, nx = cy + dy, cx + dx
                if (
                    0 <= ny < mask.shape[0]
                    and 0 <= nx < mask.shape[1]
                    and mask[ny, nx]
                    and not labels[ny, nx]
                ):
                    labels[ny, nx] = count
                    stack.append((ny, nx))
    return labels


def line_pixels(pixels: np.ndarray) -> np.ndarray:
    """The line in one line tile's pixels: its largest connected run of black.

    The speckle of the out-of-bounds ground is black too, but in single pixels.
    """
    labels = _components(pixels == 0, _STEPS_8)
    sizes = np.bincount(labels.ravel())
    sizes[0] = 0
    return labels == int(sizes.argmax())


def out_mask(tile: int, pixels: np.ndarray) -> np.ndarray:
    """The pixels of a line tile that are out of bounds, the line itself included."""
    line = line_pixels(pixels)
    parts = _components(~line, _STEPS_4)
    edges = {
        "up": parts[0],
        "right": parts[:, 7],
        "down": parts[7],
        "left": parts[:, 0],
    }
    out = {int(part) for side in OUT_SIDES[tile] for part in edges[side] if part}
    return np.isin(parts, list(out)) | line


def line_masks(tile_pixels: np.ndarray) -> np.ndarray:
    """`[i, y, x]`: the out-of-bounds pixels of `LINE_TILES[i]`, from every tile's pixels."""
    return np.array([out_mask(tile, tile_pixels[tile]) for tile in LINE_TILES])


def crossings(pixels: np.ndarray) -> frozenset[str]:
    """The sides of a line tile the line crosses in the middle, rather than at a corner."""
    line = line_pixels(pixels)
    sides = {"up": line[0], "right": line[:, 7], "down": line[7], "left": line[:, 0]}
    crossed = set()
    for side, edge in sides.items():
        touched = set(np.nonzero(edge)[0].tolist())
        if touched & {3, 4} and not touched & {0, 7}:
            crossed.add(side)
    return frozenset(crossed)


#: the editor's placeholder, which the forest fill fills: out of bounds to the line
PLACEHOLDER = 0x100


def side_states(tile_pixels: np.ndarray) -> dict[tuple[int, str], str]:
    """For each line tile and side: "out" of bounds all along, "in" bounds, or "cross"ed
    by the line in the middle."""
    states = {}
    for tile in LINE_TILES:
        crossed = crossings(tile_pixels[tile])
        for side in ("up", "right", "down", "left"):
            states[tile, side] = (
                "cross"
                if side in crossed
                else "out"
                if side in OUT_SIDES[tile]
                else "in"
            )
    return states


def cell_palettes(hole: HoleData) -> np.ndarray:
    """Each visible terrain cell's palette."""
    return np.array(
        [
            [hole.get_attribute(row, col) for col in range(TERRAIN_WIDTH)]
            for row in range(hole.terrain_height)
        ]
    )


def line_breaks(
    tiles: np.ndarray, palettes: np.ndarray, tile_pixels: np.ndarray
) -> list[tuple[int, int, str]]:
    """Where the out-of-bounds line is broken: (row, column, "right" or "down") for each
    pair of neighbors that disagree about where it runs.

    `palettes` is each cell's palette. Forest, bare out-of-bounds ground and the
    placeholder are out of bounds all round. A water hazard's tiles suit any neighbor,
    since its edge may be the boundary; anything else - rough, fairways, bunkers, trees,
    the tee box - is in bounds.
    """
    states = side_states(tile_pixels)
    out = {OPEN_GROUND, PLACEHOLDER, *FOREST_TILES}
    feature = (tile_pixels == 3).any((1, 2))

    def state(tile: int, palette: int, side: str) -> str | None:
        if tile in out:
            return "out"
        if tile in LINE_TILES:
            return states[tile, side]
        water = KIND_OF_PALETTE[palette] is Kind.WATER
        if water and tile < len(feature) and feature[tile] and tile not in TEE_BOX:
            return None
        return "in"

    breaks = []
    rows, cols = tiles.shape
    for row in range(rows):
        for col in range(cols):
            for (dy, dx), side, facing in (
                ((0, 1), "right", "left"),
                ((1, 0), "down", "up"),
            ):
                if row + dy >= rows or col + dx >= cols:
                    continue
                a = state(int(tiles[row, col]), int(palettes[row, col]), side)
                b = state(
                    int(tiles[row + dy, col + dx]),
                    int(palettes[row + dy, col + dx]),
                    facing,
                )
                if a is not None and b is not None and a != b:
                    breaks.append((row, col, side))
    return breaks
