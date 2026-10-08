"""The zones of the greens tiles, the fringe round a putting surface, and the rough."""

import numpy as np

from golf.algorithms.feature_fit import tile_pixels
from golf.algorithms.green_zones import (
    FLAT_TILE,
    FRINGE,
    FRINGE_TILES,
    GREEN,
    GREENS_TILESET,
    ROUGH,
    ROUGH_TILES,
    fringe_zones,
    rough_phase,
    rough_tile,
    tile_zones,
)
from tests.synthetic_holes import synthetic_hole


def zones() -> np.ndarray:
    return tile_zones(tile_pixels(GREENS_TILESET))


def test_rough_slopes_and_the_flat_tile_are_one_zone():
    all_zones = zones()
    for tile in ROUGH_TILES:
        assert (all_zones[tile] == ROUGH).all()
    for tile in (FLAT_TILE, 0x30, 0x47, 0x88, 0xA7):
        assert (all_zones[tile] == GREEN).all()


def test_every_fringe_tile_has_fringe_and_no_rough_against_putting_surface():
    all_zones = zones()
    for tile in FRINGE_TILES:
        tile_zone = all_zones[tile]
        assert (tile_zone == FRINGE).sum() >= 8
        for a, b in (
            (tile_zone[:, :-1], tile_zone[:, 1:]),
            (tile_zone[:-1], tile_zone[1:]),
        ):
            assert (np.abs(a - b) <= 1).all(), f"${tile:02X}"


def test_the_straight_tiles_cut_the_cell_where_their_band_runs():
    all_zones = zones()
    # $64: fringe above putting surface, the band beginning at the tile's top edge
    assert (all_zones[0x64][:3] == FRINGE).all()
    assert (all_zones[0x64][4:] == GREEN).all()
    # $62: the band two rows down, with rough above it and no putting surface to speak of
    assert (all_zones[0x62][:2] == ROUGH).all()
    assert (all_zones[0x62][3:5] == FRINGE).all()
    # $66: fringe left of putting surface
    assert (all_zones[0x66][:, :3] == FRINGE).all()
    assert (all_zones[0x66][:, 4:] == GREEN).all()


def test_the_fringe_is_a_band_round_the_putting_surface():
    green = np.zeros((40, 40), bool)
    green[15:25, 15:25] = True
    made = fringe_zones(green)
    assert (made[green] == GREEN).all()
    assert (made[15:25, 11:15] == FRINGE).all()
    assert (made[15:25, 10] == ROUGH).all()
    # round at the corners: 4 pixels out diagonally is past the band
    assert made[11, 11] == ROUGH and made[12, 12] == FRINGE
    assert (fringe_zones(np.zeros((16, 16), bool)) == ROUGH).all()


def test_rough_is_checkered_and_takes_a_strip_beside_the_fringe_tiles_that_want_one():
    greens = synthetic_hole().greens
    assert rough_tile(greens, 4, 4) == 0x29
    assert rough_tile(greens, 4, 5) == 0x2C
    assert rough_tile(greens, 4, 4, phase=1) == 0x2C
    for (row, col), fringe, even, odd in (
        ((4, 5), 0x66, 0x70, 0x84),  # right of the cell
        ((5, 4), 0x64, 0x71, 0x85),  # below it
        ((3, 4), 0x65, 0x72, 0x86),  # above it
        ((4, 3), 0x67, 0x73, 0x87),  # left of it
    ):
        greens = synthetic_hole().greens
        greens[row][col] = fringe
        assert rough_tile(greens, 4, 4) == even
        assert rough_tile(greens, 4, 4, phase=1) == odd
    # any other fringe tile wants none
    greens[4][3] = 0x62
    assert rough_tile(greens, 4, 4) == 0x29


def test_rough_phase_follows_the_rough_that_is_there():
    hole = synthetic_hole()
    assert rough_phase(hole.greens) == 0
    flipped = [[0x29 + 0x2C - tile for tile in row] for row in hole.greens]
    assert rough_phase(flipped) == 1
    assert rough_phase([[FLAT_TILE] * 24 for _ in range(24)]) == 0
