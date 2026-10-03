"""The out-of-bounds brush: painting and erasing out-of-bounds ground in a hole."""

import numpy as np

from golf.algorithms.boundary import LINE_TILES, PLACEHOLDER, cell_palettes, line_breaks
from golf.algorithms.feature_brush import (
    boundary_change,
    paint_boundary,
    paint_feature,
    stroke_mask,
)
from golf.algorithms.feature_fit import tile_pixels
from golf.core.palettes import TERRAIN_WIDTH
from tests.synthetic_holes import synthetic_hole

ROUGH = 0xDF
FOREST = 0xA0
#: a stroke across the middle of the hole
STROKE = [(40 + i, 100 + i // 3) for i in range(80)]


def rough_hole(palette: int = 1):
    hole = synthetic_hole()
    hole.terrain = [[ROUGH] * TERRAIN_WIDTH for _ in range(30)]
    hole.attributes = [[palette] * 11 for _ in range(15)]
    return hole


def tiles(hole) -> np.ndarray:
    return np.array(hole.terrain[: hole.terrain_height])


def breaks(hole) -> list:
    return line_breaks(tiles(hole), cell_palettes(hole), tile_pixels())


def test_painting_draws_an_unbroken_line_round_placeholder():
    hole = rough_hole()
    assert paint_boundary(hole, stroke_mask(STROKE, 14, hole)) > 0
    grid = tiles(hole)
    assert (grid == PLACEHOLDER).sum() > 10
    assert np.isin(grid, list(LINE_TILES)).sum() > 10
    assert set(np.unique(grid)) <= {ROUGH, PLACEHOLDER, *LINE_TILES}
    assert breaks(hole) == []


def test_erasing_reshapes_the_line_and_erasing_everything_leaves_ground():
    hole = rough_hole()
    paint_boundary(hole, stroke_mask(STROKE, 14, hole))
    paint_boundary(hole, stroke_mask([(90, 98)], 8, hole), erase=True)
    assert breaks(hole) == []
    paint_boundary(hole, stroke_mask(STROKE, 30, hole), erase=True)
    assert set(np.unique(tiles(hole))) == {ROUGH}


def test_a_second_stroke_reads_unfilled_placeholder_as_out_of_bounds():
    hole = rough_hole()
    paint_boundary(hole, stroke_mask(STROKE, 14, hole))
    inside = tiles(hole) == PLACEHOLDER
    paint_boundary(hole, stroke_mask([(x, 130) for x in range(60, 110)], 10, hole))
    assert (tiles(hole)[inside] == PLACEHOLDER).all()
    assert breaks(hole) == []


def test_forest_beside_a_changed_cell_is_left_for_the_forest_fill():
    hole = rough_hole()
    paint_boundary(hole, stroke_mask(STROKE, 14, hole))
    filled = tiles(hole) == PLACEHOLDER
    for row, col in zip(*np.nonzero(filled), strict=True):
        hole.terrain[row][col] = FOREST
    change = boundary_change(hole, stroke_mask([(120, 96)], 6, hole))
    changed = {(row, col) for row, col, _ in change.tiles}
    assert changed
    for row, col, tile in change.tiles:
        if hole.terrain[row][col] == FOREST and tile == PLACEHOLDER:
            near = {(row - 1, col), (row + 1, col), (row, col - 1), (row, col + 1)}
            assert near & changed
    change.apply(hole)
    # forest well away from the stroke is kept
    assert hole.terrain[13][6] == FOREST


def test_water_is_left_alone_and_may_be_the_boundary():
    hole = rough_hole()
    for row in range(12, 16):
        hole.terrain[row][8:12] = [0x27] * 4
    for row in (6, 7):
        hole.attributes[row][4:6] = [3, 3]
    paint_boundary(hole, stroke_mask([(40 + i, 115) for i in range(80)], 20, hole))
    grid = tiles(hole)
    assert (grid[12:16, 8:12] == 0x27).all()
    assert breaks(hole) == []
    # out-of-bounds ground runs straight up to the water
    assert (grid[12:16, 7] == PLACEHOLDER).any()


def test_the_hud_palette_is_left_where_a_feature_needs_it_and_changed_elsewhere():
    hole = rough_hole(palette=0)
    hole.terrain[14][6] = 0x27  # water in the HUD palette's supertile (7, 3)
    change = boundary_change(hole, stroke_mask(STROKE, 14, hole))
    written = {(row, col) for row, col, _ in change.tiles}
    assert not written & {(14, 6), (14, 7), (15, 6), (15, 7)}
    assert {palette for _, _, palette in change.attributes} == {1}
    assert (7, 3) not in {(row, col) for row, col, _ in change.attributes}


def test_the_feature_brush_still_paints_over_placeholder():
    hole = rough_hole()
    paint_boundary(hole, stroke_mask(STROKE, 14, hole))
    assert paint_feature(hole, 1, stroke_mask([(80, 112)], 10, hole)) > 0


def tree_wall(hole, col: int = 10) -> None:
    for row in range(6, 20):
        hole.terrain[row][col] = 0x9E


def test_a_push_into_trees_stops_at_them():
    hole = rough_hole()
    paint_boundary(hole, stroke_mask([(40, 100 + i) for i in range(20)], 14, hole))
    tree_wall(hole)
    paint_boundary(hole, stroke_mask([(40 + i, 110) for i in range(70)], 10, hole))
    grid = tiles(hole)
    assert set(np.unique(grid[:, 11:])) == {ROUGH}
    assert (grid[6:20, 10] == 0x9E).all()
    assert breaks(hole) == []
    # out-of-bounds ground never sits against the trees; the line runs in front of them
    assert not np.isin(grid[6:20, 9], [PLACEHOLDER]).any()


def test_a_stroke_that_reaches_no_out_of_bounds_starts_a_new_one():
    hole = rough_hole()
    tree_wall(hole)
    paint_boundary(hole, stroke_mask([(40 + i, 110) for i in range(70)], 10, hole))
    grid = tiles(hole)
    assert (grid[:, :10] == PLACEHOLDER).any() and (grid[:, 11:] == PLACEHOLDER).any()
    assert breaks(hole) == []


def test_carving_out_of_placeholder_leaves_deep_rough():
    hole = rough_hole()
    hole.terrain = [[PLACEHOLDER] * TERRAIN_WIDTH for _ in range(30)]
    paint_boundary(
        hole, stroke_mask([(88, 40 + i) for i in range(160)], 24, hole), erase=True
    )
    grid = tiles(hole)
    assert (grid == 0xDF).sum() > 20
    assert not (grid == 0x25).any()
    assert np.isin(grid, list(LINE_TILES)).sum() > 10
    assert breaks(hole) == []


def test_a_fairway_is_left_alone_and_the_line_closes_in_front_of_it():
    hole = rough_hole()
    for row in range(12, 16):
        hole.terrain[row][8:12] = [0x27] * 4
    paint_boundary(hole, stroke_mask([(40 + i, 115) for i in range(80)], 20, hole))
    grid = tiles(hole)
    assert (grid[12:16, 8:12] == 0x27).all()
    assert breaks(hole) == []
    beside = np.concatenate([grid[12:16, 7], grid[12:16, 12], grid[11, 8:12]])
    assert not np.isin(beside, [PLACEHOLDER]).any()
