"""Feature fit: choosing the border tiles that draw a shape."""

import numpy as np
import pytest

from golf.algorithms.feature_fit import (
    FULL_TILE,
    LOCKED,
    StyleCounts,
    count_style,
    families,
    grid_blocks,
    load_fitters,
    outline_distance,
    style_grid,
    tile_pixels,
)
from golf.core.palettes import TERRAIN_WIDTH
from tests.synthetic_holes import synthetic_hole

ROUGH = 0xDF
#: a round bunker, two tiles each way, as the vanilla holes draw it
POT = ((0x40, 0x41), (0x58, 0x59))


def rough_hole(palette: int = 2):
    hole = synthetic_hole()
    hole.terrain = [[ROUGH] * TERRAIN_WIDTH for _ in range(30)]
    hole.attributes = [[palette] * 11 for _ in range(15)]
    return hole


def disc(rows: int, cols: int, x: float, y: float, radius: float) -> np.ndarray:
    ys, xs = np.mgrid[: rows * 8, : cols * 8]
    return (xs - x) ** 2 + (ys - y) ** 2 <= radius * radius


def test_fairways_draw_without_the_outlined_tiles():
    fairway, hazard = families()["fairway"], families()["hazard"]
    pixels = tile_pixels()
    assert fairway.tiles[0] == hazard.tiles[0] == FULL_TILE
    assert not any((pixels[tile] == 0).any() for tile in fairway.tiles)
    assert hazard.tiles == [FULL_TILE, *range(0x40, 0x80)]
    assert set(fairway.tiles) < set(hazard.tiles)


def test_every_tile_of_a_family_draws_a_different_shape():
    for family in families().values():
        shapes = {family.masks[i].tobytes() for i in range(family.size)}
        assert len(shapes) == family.size


def test_seam_counts_the_pixels_that_disagree():
    family = families()["hazard"]
    full, empty = family.full, family.empty
    assert family.seam_right[full, full] == family.seam_right[empty, empty] == 0
    assert family.seam_right[full, empty] == family.seam_below[empty, full] == 8


def test_outline_distance_is_one_beside_the_outline_and_capped():
    mask = np.zeros((16, 16), bool)
    mask[:, 8:] = True
    distance = outline_distance(mask)
    assert distance[0, 7] == distance[0, 8] == 1
    assert distance[0, 5] == distance[0, 10] == 3
    assert distance[0, 0] == distance[0, 15] == 5


def test_style_grid_marks_features_ground_and_everything_else():
    hole = rough_hole()
    for y, row in enumerate(POT):
        hole.terrain[10 + y][6 : 6 + len(row)] = row
    hole.terrain[4][4] = 0x35  # tee box: draws color 3 but is no feature
    hazard, fairway = families()["hazard"], families()["fairway"]
    grid = style_grid(hazard, hole)
    assert grid[10, 6] == hazard.index[0x40]
    assert grid[11, 7] == hazard.index[0x59]
    assert grid[0, 0] == hazard.empty
    assert grid[4, 4] == LOCKED
    # a bunker is no part of the fairway family's style
    assert style_grid(fairway, hole)[10, 6] == LOCKED


def test_counts_pairs_and_blocks():
    hole = rough_hole()
    for y, row in enumerate(POT):
        hole.terrain[10 + y][6 : 6 + len(row)] = row
    family = families()["hazard"]
    counts = count_style(family, [hole, hole])
    index = family.index
    assert counts.holes == 2
    assert counts.right[index[0x40], index[0x41]] == 2
    assert counts.below[index[0x41], index[0x59]] == 2
    assert counts.right[family.empty, index[0x40]] == 2
    assert counts.right[family.empty, family.empty] == 0
    assert counts.blocks[tuple(index[t] for row in POT for t in row)] == 2
    # the pot and the eight blocks that overlap its edge
    assert len(counts.blocks) == 9


def test_blocks_skip_locked_cells_and_plain_ground():
    family = families()["hazard"]
    grid = np.full((3, 3), family.empty)
    assert not grid_blocks(family, grid)
    grid[1, 1] = family.index[0x52]
    assert sum(grid_blocks(family, grid).values()) == 4
    grid[0, 0] = LOCKED
    assert sum(grid_blocks(family, grid).values()) == 3


def test_counts_survive_the_style_table():
    hole = rough_hole()
    for y, row in enumerate(POT):
        hole.terrain[10 + y][6 : 6 + len(row)] = row
    family = families()["hazard"]
    counts = count_style(family, [hole])
    again = StyleCounts.from_json(family, counts.to_json())
    assert again.holes == counts.holes
    assert (again.right == counts.right).all()
    assert (again.below == counts.below).all()
    assert again.blocks == counts.blocks


def test_style_table_for_other_tiles_is_refused():
    family = families()["fairway"]
    data = StyleCounts(family).to_json()
    data["tiles"] = "27 40"
    with pytest.raises(ValueError, match="other tiles"):
        StyleCounts.from_json(family, data)


@pytest.mark.parametrize("name", ["fairway", "hazard"])
def test_fit_draws_the_shape_with_the_family_s_tiles(name):
    fitter = load_fitters()[name]
    family = fitter.family
    target = disc(10, 10, 38, 41, 22)
    pick = fitter.fit(target)
    assert pick.shape == (10, 10)
    assert pick.min() >= 0
    assert pick[5, 4] == family.full
    assert pick[0, 0] == family.empty
    wrong = (family.render(pick) != target).sum()
    assert wrong < 0.1 * target.sum()


def test_fairway_and_hazard_differ_in_their_lips():
    target = disc(10, 10, 38, 41, 22)
    pixels = tile_pixels()

    def outlined(name: str) -> int:
        fitter = load_fitters()[name]
        tiles = [
            fitter.family.tiles[i]
            for i in fitter.fit(target).flat
            if i < fitter.family.empty
        ]
        return sum(bool((pixels[tile] == 0).any()) for tile in tiles)

    assert outlined("fairway") == 0
    assert outlined("hazard") > 0


def test_fit_from_a_start_only_changes_free_cells_and_never_locked_ones():
    fitter = load_fitters()["fairway"]
    family = fitter.family
    start = fitter.fit(disc(10, 10, 38, 41, 22))
    start[4, 9] = LOCKED
    free = np.zeros((10, 10), bool)
    free[3:7, 6:10] = True
    target = family.render(start) | disc(10, 10, 62, 40, 12)
    pick = fitter.fit(target, start=start, free=free)
    assert (pick[~free] == start[~free]).all()
    assert pick[4, 9] == LOCKED
    assert (pick != start).any()
    # the bulge is drawn
    assert family.render(pick)[40, 64]


def test_settled_cells_keep_their_tiles_when_nothing_calls_for_a_change():
    fitter = load_fitters()["hazard"]
    start = fitter.fit(disc(10, 10, 38, 41, 22))
    free = np.ones((10, 10), bool)
    target = fitter.family.render(start)
    again = fitter.fit(target, start=start, free=free, settled=free)
    assert (again == start).all()
