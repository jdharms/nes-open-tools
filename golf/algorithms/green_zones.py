"""The zones of a green: the rough, the fringe and the putting surface, pixel by pixel.

A green is 24x24 tiles drawn in three colors: 1 is the putting surface, 3 the rough, and
the fringe between them is a checkerboard of 1 and 2. The fringe is a band four to six
pixels wide all the way round the putting surface, and 56 tiles (`FRINGE_TILES`) draw it:
each is a different cut of a tile into rough, fringe and putting surface, by where the
band crosses it. Inside the band are the flat tile and the slopes; outside it the rough,
which is a checkerboard of two tiles, each with four variants that carry a one-pixel
strip of fringe for the side of a fringe tile whose band begins at the tile's edge.

So a green's fringe follows from its putting surface alone (`fringe_zones`), and the
tiles that draw it from where its two edges cross each cell: the Green Brush fits them
(`golf.algorithms.feature_fit`, as the family `green`).

See `docs/feature_brush.md`.
"""

from pathlib import Path

import numpy as np

GREENS_TILESET = Path(__file__).resolve().parents[2] / "data" / "green-ram.bin"

#: the zones, in order from outside the green to inside it
ROUGH, FRINGE, GREEN = 0, 1, 2

FRINGE_TILES = (*range(0x48, 0x70), *range(0x74, 0x84))
#: the putting surface with no slope
FLAT_TILE = 0xB0
#: tiles from here up are the putting surface or the fringe; below, the rough
FIRST_GREEN_TILE = 0x30
#: the editor's placeholder, which Green Fix fills
PLACEHOLDER = 0x100

#: the rough's two tiles, checkered, each followed by its variants with a strip of
#: fringe along the right, bottom, top and left side
ROUGH_FAMILIES = (
    (0x29, 0x70, 0x71, 0x72, 0x73),
    (0x2C, 0x84, 0x85, 0x86, 0x87),
)
ROUGH_TILES = frozenset(tile for family in ROUGH_FAMILIES for tile in family)
#: (variant, row step, column step, the fringe tile there that wants the strip), first
#: match first: `$66` on the right, `$64` below, `$67` on the left, `$65` above
_STRIPS = ((1, 0, 1, 0x66), (2, 1, 0, 0x64), (4, 0, -1, 0x67), (3, -1, 0, 0x65))

#: how far, in pixels, the fringe reaches from the putting surface
FRINGE_WIDTH = 4.5


def _closed(mask: np.ndarray) -> np.ndarray:
    """The mask with its pinholes filled: grown by a pixel all round, then shrunk."""
    out = mask
    for grow in (True, False):
        padded = np.pad(out, 1, mode="edge")
        windows = [
            padded[dy : dy + mask.shape[0], dx : dx + mask.shape[1]]
            for dy in range(3)
            for dx in range(3)
        ]
        out = np.any(windows, 0) if grow else np.all(windows, 0)
    return out


def fringe_tile_zones(pixels: np.ndarray) -> np.ndarray:
    """One fringe tile's pixels as zones.

    The rough is color 3 and the specks in it. Of the rest, the fringe is color 2 and
    the pixels of color 1 checkered with it: those with color 2 or rough on two sides or
    more. What is left is the putting surface.
    """
    rough = _closed(pixels == 3)
    dither = np.pad((pixels == 2) | rough, 1, mode="reflect").astype(int)
    sides = dither[:-2, 1:-1] + dither[2:, 1:-1] + dither[1:-1, :-2] + dither[1:-1, 2:]
    zones = np.full(pixels.shape, GREEN)
    zones[(pixels == 2) | (sides >= 2)] = FRINGE
    zones[rough] = ROUGH
    return zones


def tile_zones(tile_pixels: np.ndarray) -> np.ndarray:
    """`[tile, y, x]`: every greens tile's zones, from every tile's pixels.

    A rough tile is all rough, its strip of fringe included, and a slope all putting
    surface.
    """
    zones = np.full(tile_pixels.shape, GREEN)
    zones[:FIRST_GREEN_TILE] = ROUGH
    zones[list(ROUGH_TILES)] = ROUGH
    for tile in FRINGE_TILES:
        zones[tile] = fringe_tile_zones(tile_pixels[tile])
    return zones


def fringe_zones(green: np.ndarray, width: float = FRINGE_WIDTH) -> np.ndarray:
    """The zones of a green whose putting surface is the pixel mask `green`: fringe
    within `width` pixels of it, and rough beyond."""
    rows, cols = green.shape
    reach = int(width)
    padded = np.pad(green, reach)
    near = np.zeros_like(green)
    for dy in range(-reach, reach + 1):
        for dx in range(-reach, reach + 1):
            if dy * dy + dx * dx <= width * width:
                near |= padded[
                    reach + dy : reach + dy + rows, reach + dx : reach + dx + cols
                ]
    return np.where(green, GREEN, np.where(near, FRINGE, ROUGH))


def rough_phase(greens: list[list[int]]) -> int:
    """Which way a green's rough is checkered: 0 if `$29` and its variants are where row
    plus column is even, as in most greens, and 1 if they are where it is odd."""
    votes = [0, 0]
    for row, tiles in enumerate(greens):
        for col, tile in enumerate(tiles):
            for family, members in enumerate(ROUGH_FAMILIES):
                if tile in members:
                    votes[(row + col + family) % 2] += 1
    return int(votes[1] > votes[0])


def rough_tile(greens: list[list[int]], row: int, col: int, phase: int = 0) -> int:
    """The rough tile for a cell: its place in the checkerboard, with the strip of
    fringe a fringe tile beside it wants."""
    family = ROUGH_FAMILIES[(row + col + phase) % 2]
    for variant, dy, dx, fringe in _STRIPS:
        near_row, near_col = row + dy, col + dx
        if (
            0 <= near_row < len(greens)
            and 0 <= near_col < len(greens[near_row])
            and greens[near_row][near_col] == fringe
        ):
            return family[variant]
    return family[0]
