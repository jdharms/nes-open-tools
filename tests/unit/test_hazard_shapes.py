"""Hazard shapes: enclosed bunkers and water cut out of a hole's terrain."""

import pytest

from golf.algorithms.hazard_shapes import HazardShape, hazard_shapes
from golf.core.palettes import TERRAIN_WIDTH
from golf.formats.hole_data import HoleData
from tests.synthetic_holes import synthetic_hole

ROUGH = 0xDF
#: a round bunker, two tiles each way
POT = ((0x40, 0x41), (0x58, 0x59))
#: the same bunker with a corner tile left out of its bounding box
NOTCHED = ((0x50, None), (0x58, 0x51))


def rough_hole(palette: int = 2) -> HoleData:
    hole = synthetic_hole()
    hole.terrain = [[ROUGH] * TERRAIN_WIDTH for _ in range(30)]
    hole.attributes = [[palette] * 11 for _ in range(15)]
    return hole


def draw(hole: HoleData, tiles, row: int, col: int) -> None:
    for y, tile_row in enumerate(tiles):
        for x, tile in enumerate(tile_row):
            if tile is not None:
                hole.terrain[row + y][col + x] = tile


def test_enclosed_hazard_is_cut_out_with_its_tiles():
    hole = rough_hole()
    draw(hole, POT, 10, 6)
    assert hazard_shapes([hole]) == [HazardShape(POT, 1)]


def test_tiles_outside_the_hazard_are_left_empty():
    hole = rough_hole()
    draw(hole, NOTCHED, 10, 6)
    assert [shape.tiles for shape in hazard_shapes([hole])] == [NOTCHED]


@pytest.mark.parametrize("palette", [0, 2, 3])
def test_sand_and_water_are_the_same_shape(palette):
    hole = rough_hole(palette)
    draw(hole, POT, 10, 6)
    assert [shape.tiles for shape in hazard_shapes([hole])] == [POT]


def test_fairway_is_not_a_hazard():
    hole = rough_hole(palette=1)
    draw(hole, POT, 10, 6)
    assert hazard_shapes([hole]) == []


@pytest.mark.parametrize(
    ("row", "col"), [(0, 6), (29, 6), (10, 0), (10, TERRAIN_WIDTH - 1)]
)
def test_hazard_on_the_edge_of_the_terrain_is_left_out(row, col):
    hole = rough_hole()
    hole.terrain[row][col] = 0x27
    assert hazard_shapes([hole]) == []


def test_rows_below_the_visible_terrain_are_ignored():
    hole = rough_hole()
    hole.terrain += [[ROUGH] * TERRAIN_WIDTH for _ in range(4)]
    draw(hole, POT, 31, 6)
    assert hazard_shapes([hole]) == []


def test_repeated_shape_is_counted_once_per_hazard_across_holes():
    first, second = rough_hole(), rough_hole()
    draw(first, POT, 4, 2)
    draw(first, POT, 12, 14)
    draw(second, POT, 20, 9)
    assert hazard_shapes([first, second]) == [HazardShape(POT, 3)]


def test_shapes_come_smallest_first():
    hole = rough_hole()
    draw(hole, POT, 4, 2)
    draw(hole, NOTCHED, 12, 14)
    assert [shape.tiles for shape in hazard_shapes([hole])] == [NOTCHED, POT]


@pytest.mark.parametrize(
    ("height", "width", "bucket"),
    [
        (1, 1, "tiny"),
        (3, 3, "tiny"),
        (2, 4, "small"),
        (5, 5, "small"),
        (6, 2, "medium"),
        (8, 8, "medium"),
        (9, 3, "large"),
        (31, 18, "large"),
    ],
)
def test_bucket_goes_by_the_longer_side(height, width, bucket):
    shape = HazardShape(tuple((0x27,) * width for _ in range(height)), 1)
    assert shape.bucket == bucket
