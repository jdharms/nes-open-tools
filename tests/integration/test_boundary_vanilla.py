"""The out-of-bounds line and its fit, against the vanilla holes."""

import copy
from collections import Counter, defaultdict

import numpy as np
import pytest

from golf.algorithms.boundary import (
    FOREST_TILES,
    LINE_TILES,
    OPEN_GROUND,
    OUT_SIDES,
    cell_palettes,
    line_breaks,
)
from golf.algorithms.feature_brush import boundary_change, paint_boundary, stroke_mask
from golf.algorithms.feature_fit import (
    GROUND_TILES,
    LOCKED,
    grid_blocks,
    load_fitters,
    style_grid,
    tile_pixels,
)
from golf.formats.hole_data import HoleData
from golf.randomizer.catalog import Catalog, HoleStore, RomSource

SIDES = {"up": (-1, 0), "right": (0, 1), "down": (1, 0), "left": (0, -1)}


@pytest.fixture(scope="module")
def holes(vanilla_courses, vanilla_jp_courses):
    store = HoleStore(vanilla_courses)
    return [
        store.load(entry)
        for entry in Catalog.load().newest().values()
        if isinstance(entry.source, RomSource)
    ]


def terrain(hole) -> np.ndarray:
    return np.array(hole.terrain[: hole.terrain_height])


def as_tiles(family, pick, hole) -> np.ndarray:
    """The hole with a fitted grid written into it."""
    tiles = terrain(hole).copy()
    for index, tile in enumerate(family.tiles):
        tiles[pick == index] = tile
    tiles[pick == family.empty] = GROUND_TILES[1]
    return tiles


def test_out_sides_are_where_the_vanilla_holes_put_forest(holes):
    out = {OPEN_GROUND, *FOREST_TILES}
    beside = defaultdict(Counter)
    for hole in holes:
        tiles = terrain(hole)
        rows, cols = tiles.shape
        for row, col in zip(*np.nonzero(np.isin(tiles, list(LINE_TILES))), strict=True):
            for side, (dy, dx) in SIDES.items():
                if 0 <= row + dy < rows and 0 <= col + dx < cols:
                    near = int(tiles[row + dy, col + dx])
                    if near in out:
                        beside[int(tiles[row, col]), side]["out"] += 1
                    elif near in GROUND_TILES:
                        beside[int(tiles[row, col]), side]["in"] += 1
    for tile in LINE_TILES:
        for side in OUT_SIDES[tile]:
            assert beside[tile, side]["out"] > 3 * beside[tile, side]["in"]


def test_the_vanilla_line_is_almost_never_broken(holes):
    breaks = sum(
        len(line_breaks(terrain(hole), cell_palettes(hole), tile_pixels()))
        for hole in holes
    )
    assert breaks <= 40


def test_a_vanilla_boundary_fits_back_to_its_own_tiles_unbroken(holes):
    fitter = load_fitters()["boundary"]
    family = fitter.family
    same = total = breaks = 0
    for hole in holes[::3]:
        grid = style_grid(family, hole)
        pick = fitter.fit(
            family.render(grid),
            start=np.where(grid < 0, grid, family.empty),
            free=grid >= 0,
        )
        line = (grid > family.full) & (grid < family.empty)
        total += int(line.sum())
        same += int((pick[line] == grid[line]).sum())
        tiles = as_tiles(family, np.where(grid < 0, LOCKED, pick), hole)
        breaks += len(line_breaks(tiles, cell_palettes(hole), tile_pixels()))
    assert total > 2000
    assert same / total >= 0.9
    assert breaks <= 2


def test_a_boundary_moved_off_the_grid_and_painted_back_stays_unbroken(holes):
    """Each hole's out of bounds cleared to rough, then painted 3 right and 5 down."""
    fitter = load_fitters()["boundary"]
    family = fitter.family
    out = {OPEN_GROUND, *FOREST_TILES, *LINE_TILES}
    painted = breaks = blocks = seen = 0
    for hole in holes[::4]:
        shape = family.render(style_grid(family, hole))
        stroke = np.zeros_like(shape)
        stroke[5:, 3:] = shape[:-5, :-3]
        cleared = copy.deepcopy(hole)
        for line in cleared.terrain[: cleared.terrain_height]:
            line[:] = [GROUND_TILES[1] if tile in out else tile for tile in line]
        boundary_change(cleared, stroke).apply(cleared)
        painted += 1
        breaks += len(
            line_breaks(terrain(cleared), cell_palettes(cleared), tile_pixels())
        )
        for block, count in grid_blocks(family, style_grid(family, cleared)).items():
            blocks += count
            seen += count * bool(fitter.seen[block])
    assert breaks <= 0.1 * painted
    assert seen / blocks >= 0.95


def test_a_vanilla_boundary_pushed_into_trees_stops_at_them(vanilla_jp_courses):
    """Mario Open's Australia 17 has trees on the rough against its top right forest."""
    hole = HoleData()
    hole.load(str(vanilla_jp_courses / "jp" / "jp_australia" / "hole_17.json"))
    assert hole.terrain[4][19:21] == [0x9F, 0x83]
    before = line_breaks(terrain(hole), cell_palettes(hole), tile_pixels())
    # straight into the trees: nothing to change
    stroke = stroke_mask([(170 - i, 44 - i) for i in range(18)], 6, hole)
    assert not boundary_change(hole, stroke)
    # past them into open rough beyond: the line wraps the near side and goes no further
    paint_boundary(hole, stroke_mask([(150 - i, 46) for i in range(30)], 6, hole))
    assert line_breaks(terrain(hole), cell_palettes(hole), tile_pixels()) == before
    assert all(
        hole.terrain[row][col] in (0x25, 0xDF, 0x9E, 0x9F)
        for row, col in [(4, 16), (5, 16), (6, 16), (6, 17)]
    )
