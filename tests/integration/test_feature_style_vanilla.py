"""The feature brush's style table and fit, against the vanilla holes."""

import numpy as np
import pytest

from golf.algorithms.feature_brush import paint_feature, stroke_mask
from golf.algorithms.feature_fit import (
    STYLE_TABLE,
    count_style,
    families,
    grid_blocks,
    load_fitters,
    style_grid,
    style_table_text,
)
from golf.algorithms.features import find_features
from golf.core.palettes import TERRAIN_WIDTH
from golf.formats.hole_data import HoleData
from golf.randomizer.catalog import Catalog, HoleStore, RomSource


@pytest.fixture(scope="module")
def holes(vanilla_courses, vanilla_jp_courses):
    store = HoleStore(vanilla_courses)
    return [
        store.load(entry)
        for entry in Catalog.load().newest().values()
        if isinstance(entry.source, RomSource)
    ]


def test_style_table_is_current(holes):
    counts = [count_style(family, holes) for family in families().values()]
    assert style_table_text(counts) == STYLE_TABLE.read_text(), (
        "run `uv run golf-feature-style`"
    )


def shapes(family, hole):
    """The pixel mask and cells of each feature the family draws whole."""
    grid = style_grid(family, hole)
    for feature in find_features(hole):
        if feature.kind not in family.kinds:
            continue
        cells = {(y // 8, x // 8) for x, y in feature.pixels}
        if any(grid[cell] < 0 for cell in cells):
            continue
        mask = np.zeros((hole.terrain_height * 8, TERRAIN_WIDTH * 8), bool)
        xs, ys = zip(*feature.pixels, strict=True)
        mask[list(ys), list(xs)] = True
        yield mask, cells, grid


def on_edge(mask) -> bool:
    return bool(
        mask[0].any() or mask[-1].any() or mask[:, 0].any() or mask[:, -1].any()
    )


@pytest.mark.parametrize(("name", "least"), [("fairway", 0.92), ("hazard", 0.85)])
def test_a_vanilla_shape_fits_back_to_its_own_tiles(holes, name, least):
    fitter = load_fitters()[name]
    same = total = 0
    for hole in holes[::12]:
        for mask, cells, grid in shapes(fitter.family, hole):
            pick = fitter.fit(mask)
            total += len(cells)
            same += sum(pick[cell] == grid[cell] for cell in cells)
    assert total > 300
    assert same / total >= least


@pytest.mark.parametrize("name", ["fairway", "hazard"])
def test_a_shape_moved_off_the_grid_fits_in_the_vanilla_style(holes, name):
    """Blocks of tiles the vanilla holes use, and an outline close to the one asked for."""
    fitter = load_fitters()[name]
    family = fitter.family
    blocks = seen = wrong = border = 0
    for hole in holes[::12]:
        for mask, _, _ in shapes(family, hole):
            target = np.zeros_like(mask)
            target[5:, 3:] = mask[:-5, :-3]
            if on_edge(target):
                continue
            pick = fitter.fit(target)
            for block, count in grid_blocks(family, pick).items():
                blocks += count
                seen += count * bool(fitter.seen[block])
            cells = target.reshape(pick.shape[0], 8, TERRAIN_WIDTH, 8).transpose(
                0, 2, 1, 3
            )
            border += int((cells.any((2, 3)) & ~cells.all((2, 3))).sum())
            wrong += int((family.render(pick) != target).sum())
    assert blocks > 300
    assert seen / blocks >= 0.9
    assert wrong / border <= 13


def test_a_vanilla_fairway_in_a_pocket_can_be_erased_and_painted_back(
    vanilla_jp_courses,
):
    """Mario Open's Australia 17 has a three-tile fairway between trees and forest."""
    hole = HoleData()
    hole.load(str(vanilla_jp_courses / "jp" / "jp_australia" / "hole_17.json"))
    cells = [(10, 12), (10, 13), (11, 12)]
    vanilla = [hole.terrain[row][col] for row, col in cells]
    assert vanilla == [0x56, 0x5F, 0x55]

    points = [(100, 84), (108, 86), (100, 92)]
    paint_feature(hole, 1, stroke_mask(points, 6, hole), erase=True)
    assert all(hole.terrain[row][col] == 0x25 for row, col in cells)
    paint_feature(hole, 1, stroke_mask(points, 5, hole))
    assert [hole.terrain[row][col] for row, col in cells] == vanilla


@pytest.mark.parametrize(
    ("points", "row"),
    [
        ([(66 - i, 60) for i in range(14)], [0x52, 0x4A, 0x4A, 0x4A, 0x4A, 0x51, 0x25]),
        ([(92 + i, 60) for i in range(10)], [0xDF, 0xDF, 0x52, 0x4A, 0x4A, 0x4A, 0x51]),
    ],
    ids=["left", "right"],
)
def test_a_vanilla_one_row_bunker_is_extended_along_its_row(
    vanilla_jp_courses, points, row
):
    """Mario Open's Australia 17 has the bunker `52 4A 4A 51` on row 7, over a fairway."""
    hole = HoleData()
    hole.load(str(vanilla_jp_courses / "jp" / "jp_australia" / "hole_17.json"))
    assert hole.terrain[7][6:13] == [0xDF, 0xDF, 0x52, 0x4A, 0x4A, 0x51, 0x25]
    others = [list(line) for i, line in enumerate(hole.terrain) if i != 7]
    paint_feature(hole, 2, stroke_mask(points, 3, hole))
    assert hole.terrain[7][6:13] == row
    assert [list(line) for i, line in enumerate(hole.terrain) if i != 7] == others
