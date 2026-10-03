"""Feature brush: painting and erasing features in a hole."""

import copy

import numpy as np
import pytest

from golf.algorithms.feature_brush import (
    GROUND_TILES,
    PLACEHOLDER,
    FeatureChange,
    boundary_change,
    brush_grid,
    feature_change,
    fitter_for,
    paint_feature,
    stroke_mask,
)
from golf.algorithms.feature_fit import (
    LOCKED,
    LOCKED_FULL,
    TREES_IN_FEATURE,
    families,
    tile_pixels,
)
from golf.core.palettes import TERRAIN_WIDTH
from tests.synthetic_holes import synthetic_hole

ROUGH = 0xDF
#: a stroke across the middle of the hole
STROKE = [(60 + i, 100 + i // 4) for i in range(48)]


def rough_hole(palette: int = 1):
    hole = synthetic_hole()
    hole.terrain = [[ROUGH] * TERRAIN_WIDTH for _ in range(30)]
    hole.attributes = [[palette] * 11 for _ in range(15)]
    return hole


def drawn(hole) -> np.ndarray:
    """The color-3 pixels of the hole's visible terrain."""
    pixels = tile_pixels() == 3
    rows = np.array(hole.terrain[: hole.terrain_height])
    rows = np.where(rows == PLACEHOLDER, GROUND_TILES[0], rows)
    return pixels[rows].transpose(0, 2, 1, 3).reshape(len(rows) * 8, -1)


def placed(hole) -> set[tuple[int, int]]:
    return {
        (row, col)
        for row in range(hole.terrain_height)
        for col in range(TERRAIN_WIDTH)
        if hole.terrain[row][col] != ROUGH
    }


def test_stroke_mask_is_a_disc_round_each_point():
    hole = rough_hole()
    mask = stroke_mask([(20, 30), (50, 30)], 4, hole)
    assert mask.shape == (240, 176)
    assert mask[30, 20] and mask[30, 24] and mask[26, 50]
    assert not mask[30, 25] and not mask[30, 35]
    assert mask.sum() == 2 * 49


def test_stroke_mask_clips_to_the_visible_terrain():
    hole = rough_hole()
    mask = stroke_mask([(0, 0), (175, 239), (400, 400)], 3, hole)
    assert mask[0, 0] and mask[239, 175]


def test_painting_a_fairway_draws_the_stroke_in_fairway_tiles():
    hole = rough_hole()
    stroke = stroke_mask(STROKE, 9, hole)
    assert paint_feature(hole, 1, stroke) > 0
    fairway = set(families()["fairway"].tiles)
    assert {hole.terrain[row][col] for row, col in placed(hole)} <= fairway
    assert (drawn(hole) != stroke).sum() < 0.15 * stroke.sum()
    assert all(palette == 1 for row in hole.attributes for palette in row)


@pytest.mark.parametrize("palette", [2, 3])
def test_painting_a_hazard_sets_its_palette_and_gives_it_a_lip(palette):
    hole = rough_hole()
    stroke = stroke_mask(STROKE, 9, hole)
    paint_feature(hole, palette, stroke)
    cells = placed(hole)
    assert cells
    assert all(hole.get_attribute(row, col) == palette for row, col in cells)
    pixels = tile_pixels()
    assert any((pixels[hole.terrain[row][col]] == 0).any() for row, col in cells)
    # palettes change only under the hazard
    touched = {(row // 2, col // 2) for row, col in cells}
    for row, line in enumerate(hole.attributes):
        for col, value in enumerate(line):
            assert value == (palette if (row, col) in touched else 1)


def test_water_keeps_a_supertile_that_is_already_water():
    hole = rough_hole(palette=0)
    paint_feature(hole, 3, stroke_mask(STROKE, 9, hole))
    assert all(palette == 0 for row in hole.attributes for palette in row)


def test_new_water_draws_with_palette_3_even_when_the_hud_palette_is_selected():
    hole = rough_hole()
    paint_feature(hole, 0, stroke_mask(STROKE, 9, hole))
    cells = placed(hole)
    assert cells
    assert all(hole.get_attribute(row, col) == 3 for row, col in cells)


def test_erasing_cuts_the_stroke_out():
    hole = rough_hole()
    paint_feature(hole, 1, stroke_mask(STROKE, 9, hole))
    cut = stroke_mask(STROKE[:20], 14, hole)
    assert paint_feature(hole, 1, cut, erase=True) > 0
    assert not drawn(hole)[100, 62]
    assert drawn(hole)[111, 105]


def test_erasing_everything_leaves_ground():
    hole = rough_hole()
    paint_feature(hole, 2, stroke_mask(STROKE, 9, hole))
    paint_feature(hole, 2, stroke_mask(STROKE, 24, hole), erase=True)
    assert not placed(hole)


def test_erased_tiles_become_the_ground_round_them():
    hole = rough_hole()
    for row in hole.terrain:
        row[:] = [0x25] * TERRAIN_WIDTH
    paint_feature(hole, 1, stroke_mask(STROKE, 9, hole))
    paint_feature(hole, 1, stroke_mask(STROKE, 24, hole), erase=True)
    assert {tile for row in hole.terrain for tile in row} == {0x25}
    assert 0x25 in GROUND_TILES


def test_only_cells_near_the_stroke_change():
    hole = rough_hole()
    paint_feature(hole, 1, stroke_mask(STROKE, 9, hole))
    before = copy.deepcopy(hole.terrain)
    bulge = stroke_mask([(110, 112), (118, 116)], 6, hole)
    assert paint_feature(hole, 1, bulge) > 0
    ys, xs = np.nonzero(bulge)
    for row in range(hole.terrain_height):
        for col in range(TERRAIN_WIDTH):
            near = (
                ys.min() // 8 - 1 <= row <= ys.max() // 8 + 1
                and xs.min() // 8 - 1 <= col <= xs.max() // 8 + 1
            )
            if not near:
                assert hole.terrain[row][col] == before[row][col]


def test_trees_are_left_alone():
    hole = rough_hole()
    trees = [(12, 9), (13, 9), (12, 12), (13, 12)]
    for (row, col), tile in zip(trees, (0x9C, 0x9D, 0x9E, 0x9F), strict=True):
        hole.terrain[row][col] = tile
    paint_feature(hole, 1, stroke_mask(STROKE, 9, hole))
    assert [hole.terrain[row][col] for row, col in trees] == [0x9C, 0x9D, 0x9E, 0x9F]
    assert len(placed(hole)) > len(trees)


def test_a_feature_of_another_kind_is_left_alone():
    hole = rough_hole()
    paint_feature(hole, 2, stroke_mask(STROKE[:16], 7, hole))
    bunker = {cell: hole.terrain[cell[0]][cell[1]] for cell in placed(hole)}
    palettes = copy.deepcopy(hole.attributes)
    paint_feature(hole, 1, stroke_mask(STROKE, 9, hole))
    assert all(hole.terrain[row][col] == tile for (row, col), tile in bunker.items())
    for row, col in bunker:
        assert hole.get_attribute(row, col) == palettes[row // 2][col // 2] == 2
    # and no fairway shares a supertile with it
    fairway = placed(hole) - set(bunker)
    assert fairway
    assert all(hole.get_attribute(row, col) == 1 for row, col in fairway)


def test_brush_grid_locks_ground_whose_palette_another_feature_needs():
    hole = rough_hole()
    hole.terrain[10][6] = 0x52
    hole.attributes[5][3] = 2
    fitter = fitter_for(1)
    grid = brush_grid(hole, fitter, 1)
    assert grid[10, 6] == grid[10, 7] == grid[11, 6] == grid[11, 7] == LOCKED
    assert grid[10, 8] == fitter.family.empty
    hazard = fitter_for(2)
    assert brush_grid(hole, hazard, 2)[10, 6] == hazard.family.index[0x52]
    assert brush_grid(hole, hazard, 2)[10, 7] == hazard.family.empty


def test_brush_grid_reads_a_tree_in_a_feature_as_fixed_feature():
    hole = rough_hole()
    hole.terrain[10][6] = 0xBC
    hole.terrain[11][6] = 0xBD
    hole.attributes[5][3] = 2
    fairway, hazard = fitter_for(1), fitter_for(2)
    assert brush_grid(hole, hazard, 2)[10, 6] == brush_grid(hole, hazard, 2)[11, 6]
    assert brush_grid(hole, hazard, 2)[10, 6] == LOCKED_FULL
    # under another kind's palette it is that kind's, and locks its supertile
    assert brush_grid(hole, fairway, 1)[10, 6] == LOCKED
    assert brush_grid(hole, fairway, 1)[10, 7] == LOCKED


def tree_at_fairway_edge():
    """A fairway with a tree standing in it at its right-hand edge."""
    hole = rough_hole()
    paint_feature(hole, 1, stroke_mask([(40 + i, 100) for i in range(40)], 24, hole))
    col = max(col for row, col in placed(hole) if row == 12) - 1
    assert all(hole.terrain[row][col] == 0x27 for row in range(11, 15))
    hole.terrain[12][col], hole.terrain[13][col] = 0xBC, 0xBD
    return hole, col


def edges_against_trees(hole) -> int:
    """Pixels where a tile's edge facing a tree in a feature is not all feature."""
    full = tile_pixels() == 3
    rows, off = hole.terrain_height, 0
    for row in range(rows):
        for col in range(TERRAIN_WIDTH):
            if hole.terrain[row][col] not in TREES_IN_FEATURE:
                continue
            for dy, dx, edge in ((0, 1, np.s_[:, 0]), (0, -1, np.s_[:, 7])):
                tile = hole.terrain[row + dy][col + dx]
                if tile not in TREES_IN_FEATURE:
                    off += int((~full[tile][edge]).sum())
            for dy, edge in ((1, np.s_[0, :]), (-1, np.s_[7, :])):
                tile = hole.terrain[row + dy][col]
                if tile not in TREES_IN_FEATURE:
                    off += int((~full[tile][edge]).sum())
    return off


def test_painting_over_a_tree_in_a_fairway_finds_the_fairway_already_there():
    hole, col = tree_at_fairway_edge()
    assert not feature_change(hole, 1, stroke_mask([(col * 8 + 10, 100)], 5, hole))


@pytest.mark.parametrize(("erase", "offset"), [(False, 16), (True, 14)])
def test_the_border_beside_a_tree_in_a_fairway_meets_it_as_feature(erase, offset):
    hole, col = tree_at_fairway_edge()
    assert edges_against_trees(hole) == 0
    # a dab clear of the tree, pushing out or cutting into the border beside it
    stroke = stroke_mask([(col * 8 + offset, 100)], 5, hole)
    assert paint_feature(hole, 1, stroke, erase) > 0
    assert (hole.terrain[12][col], hole.terrain[13][col]) == (0xBC, 0xBD)
    assert edges_against_trees(hole) == 0


def test_the_editors_placeholder_tile_is_painted_over_like_ground():
    hole = rough_hole()
    for row in hole.terrain:
        row[:] = [PLACEHOLDER] * TERRAIN_WIDTH
    stroke = stroke_mask(STROKE, 9, hole)
    paint_feature(hole, 1, stroke)
    fairway = set(families()["fairway"].tiles)
    painted = {
        (row, col)
        for row in range(hole.terrain_height)
        for col in range(TERRAIN_WIDTH)
        if hole.terrain[row][col] != PLACEHOLDER
    }
    assert painted
    assert {hole.terrain[row][col] for row, col in painted} <= fairway
    assert (drawn(hole) != stroke).sum() < 0.15 * stroke.sum()


def test_a_change_holds_plain_ints():
    hole = rough_hole()
    stroke = stroke_mask(STROKE, 9, hole)
    for change in (feature_change(hole, 2, stroke), boundary_change(hole, stroke)):
        assert change.tiles
        values = [v for entry in change.tiles + change.attributes for v in entry]
        assert all(type(v) is int for v in values)


def test_a_stroke_on_nothing_paintable_changes_nothing():
    hole = rough_hole()
    for row in hole.terrain:
        row[:] = [0xA0] * TERRAIN_WIDTH
    change = feature_change(hole, 1, stroke_mask(STROKE, 9, hole))
    assert not change
    assert change == FeatureChange()


def test_rows_below_the_visible_terrain_are_untouched():
    hole = rough_hole()
    hole.terrain += [[ROUGH] * TERRAIN_WIDTH for _ in range(4)]
    paint_feature(hole, 1, stroke_mask([(80, 236)], 12, hole))
    assert placed(hole)
    assert all(tile == ROUGH for row in hole.terrain[30:] for tile in row)


def test_a_sliver_too_thin_to_draw_is_dropped():
    hole = rough_hole()
    paint_feature(hole, 1, stroke_mask(STROKE, 9, hole))
    # cut all but a strip two pixels deep along the top of the fairway
    top = int(np.nonzero(drawn(hole)[:, 80])[0].min())
    cut = np.zeros_like(drawn(hole))
    cut[top + 2 : top + 30, 72:96] = True
    paint_feature(hole, 1, cut, erase=True)
    # a tile closing the fairway at the cut may round its corner into the next cell
    assert not drawn(hole)[top : top + 2, 80:90].any()


def test_a_painted_stroke_runs_up_to_what_it_cannot_write_and_on_past_it():
    hole = rough_hole()
    for row in range(8, 18):
        hole.terrain[row][12] = 0xA0  # a wall of forest across the stroke's path
    paint_feature(hole, 1, stroke_mask(STROKE, 9, hole))
    shape = drawn(hole)
    assert shape[103, 80]
    assert shape[108, 108]
    assert all(hole.terrain[row][12] == 0xA0 for row in range(8, 18))
    # the fairway may run under the forest's edge in $27, as vanilla fairways do
    fairway = set(families()["fairway"].tiles)
    for row in range(8, 18):
        for col in (11, 13):
            assert hole.terrain[row][col] in fairway | {ROUGH}


def test_another_feature_close_to_the_stroke_is_left_alone():
    hole = rough_hole()
    paint_feature(hole, 1, stroke_mask([(40 + i, 100) for i in range(50)], 7, hole))
    paint_feature(hole, 1, stroke_mask([(40 + i, 130) for i in range(50)], 7, hole))
    lower = copy.deepcopy(hole.terrain[15:])
    assert any(tile != ROUGH for row in lower for tile in row)
    upper = copy.deepcopy(hole.terrain[:15])

    # a bulge on the upper fairway's underside, a tile away from the lower one
    assert paint_feature(hole, 1, stroke_mask([(64, 109)], 5, hole)) > 0
    assert hole.terrain[:15] != upper
    assert hole.terrain[15:] == lower


def test_a_pocket_between_trees_can_be_filled():
    hole = rough_hole()
    for row in range(8, 14):
        hole.terrain[row][8:14] = [0x9E] * 6
    pocket = [(10, 10), (10, 11), (11, 10)]
    for row, col in pocket:
        hole.terrain[row][col] = ROUGH
    # a stroke that spills over the trees all round
    paint_feature(hole, 1, stroke_mask([(86, 85), (92, 85), (85, 91)], 6, hole))
    assert all(hole.terrain[row][col] != ROUGH for row, col in pocket)
    assert sum(tile == 0x9E for row in hole.terrain for tile in row) == 33


def test_a_one_row_bunker_is_extended_along_its_row():
    hole = rough_hole()
    hole.terrain[12][8:12] = [0x52, 0x4A, 0x4A, 0x51]
    for col in (4, 5):
        hole.attributes[6][col] = 2
    # a stroke as tall as the bunker, running left from its end
    stroke = stroke_mask([(66 - i, 100) for i in range(14)], 3, hole)
    paint_feature(hole, 2, stroke)
    assert hole.terrain[12][6:12] == [0x52, 0x4A, 0x4A, 0x4A, 0x4A, 0x51]
    assert placed(hole) == {(12, col) for col in range(6, 12)}


def test_a_fairway_pushed_into_trees_stops_at_them():
    hole = rough_hole()
    paint_feature(hole, 1, stroke_mask([(40, 100 + i) for i in range(20)], 12, hole))
    for row in range(6, 20):
        hole.terrain[row][10] = 0x9E
    paint_feature(hole, 1, stroke_mask([(40 + i, 110) for i in range(70)], 9, hole))
    assert all(tile == ROUGH for row in hole.terrain for tile in row[11:])
