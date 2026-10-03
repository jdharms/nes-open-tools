"""The out-of-bounds line tiles."""

import numpy as np
import pytest

from golf.algorithms.boundary import (
    LINE_TILES,
    OPEN_GROUND,
    OUT_SIDES,
    PLACEHOLDER,
    crossings,
    line_breaks,
    line_pixels,
    out_mask,
)
from golf.algorithms.feature_fit import GROUND_TILES, families, tile_pixels


def fairway(tiles: np.ndarray) -> np.ndarray:
    """Every cell in the fairway palette."""
    return np.ones(tiles.shape, int)


EDGES = {
    "up": np.s_[0, :],
    "right": np.s_[:, 7],
    "down": np.s_[7, :],
    "left": np.s_[:, 0],
}


@pytest.mark.parametrize("tile", LINE_TILES)
def test_a_line_tiles_out_sides_are_out_all_along(tile):
    mask = out_mask(tile, tile_pixels()[tile])
    for side in OUT_SIDES[tile]:
        assert mask[EDGES[side]].all()
    assert 0 < mask.sum() < 64


def test_each_tile_holds_one_piece_of_line():
    for tile in LINE_TILES:
        line = line_pixels(tile_pixels()[tile])
        assert 7 <= line.sum() <= 12


def test_the_line_crosses_a_side_only_in_its_middle():
    count = {tile: len(crossings(tile_pixels()[tile])) for tile in LINE_TILES}
    # corner to corner, and along a side
    assert all(count[tile] == 0 for tile in [*range(0x80, 0x84), *range(0x94, 0x98)])
    # the middle of a side to a far corner
    assert all(count[tile] == 1 for tile in range(0x84, 0x94))
    # straight across
    assert all(count[tile] == 2 for tile in range(0x98, 0x9C))


def test_a_straight_line_continues_without_a_seam():
    family = families()["boundary"]
    for across, along in ((0x98, "right"), (0x99, "right"), (0x9A, "down")):
        index = family.index[across]
        seam = family.seam_right if along == "right" else family.seam_below
        assert seam[index, index] == 0


def test_line_breaks_finds_a_line_that_does_not_continue():
    rough = GROUND_TILES[1]
    whole = np.array(
        [
            [rough, rough, rough],
            [0x99, 0x99, 0x99],
            [OPEN_GROUND, PLACEHOLDER, OPEN_GROUND],
        ]
    )
    assert line_breaks(whole, fairway(whole), tile_pixels()) == []
    broken = whole.copy()
    broken[1, 1] = 0x98  # the out-of-bounds side flipped
    assert line_breaks(broken, fairway(broken), tile_pixels())


def test_line_breaks_lets_water_be_the_boundary_but_not_a_fairway():
    tiles = np.array([[OPEN_GROUND, 0x27, GROUND_TILES[0]]])
    water = np.full(tiles.shape, 3)
    assert line_breaks(tiles, water, tile_pixels()) == []
    assert line_breaks(tiles, fairway(tiles), tile_pixels())
    bare = np.array([[OPEN_GROUND, GROUND_TILES[0]]])
    assert line_breaks(bare, fairway(bare), tile_pixels())
