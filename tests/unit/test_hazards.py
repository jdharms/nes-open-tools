"""Redrawing bunkers and water hazards (golf/algorithms/hazards.py)."""

from functools import partial

import pytest

from golf.algorithms.features import Kind, feature_groups
from golf.algorithms.hazards import HAZARD_PALETTE, redraw_hazards, uniform, weighted
from golf.formats.hole_data import HoleData
from tests.synthetic_holes import synthetic_hole
from tests.vanilla_holes import vanilla_holes

STYLES = pytest.mark.parametrize(
    "redraw",
    [partial(redraw_hazards, draw=uniform), partial(redraw_hazards, draw=weighted)],
    ids=["uniform", "weighted"],
)


def feature_hole(sand_palette: int = 2, water_palette: int = 3) -> HoleData:
    """Deep rough with a fairway, a bunker and a pond, each one supertile of `$27`."""
    hole = synthetic_hole()
    hole.terrain = [[0xDF] * 22 for _ in range(30)]
    for row, col in ((0, 0), (2, 2), (4, 4)):
        for dy in (0, 1):
            for dx in (0, 1):
                hole.terrain[row * 2 + dy][col * 2 + dx] = 0x27
    hole.attributes = [[1] * 11 for _ in range(15)]
    hole.attributes[2][2] = sand_palette
    hole.attributes[4][4] = water_palette
    return hole


def lake_hole() -> HoleData:
    """Deep rough with one 4 x 4 supertile lake, 4096 pixels, in supertiles (8-11, 0-3)."""
    hole = feature_hole()
    hole.terrain = [[0xDF] * 22 for _ in range(30)]
    for row in range(16, 24):
        for col in range(8):
            hole.terrain[row][col] = 0x27
    for row in range(8, 12):
        for col in range(4):
            hole.attributes[row][col] = 3
    return hole


@STYLES
def test_redraws_only_hazard_supertiles(redraw):
    outcomes = set()
    for seed in range(40):
        out = redraw(feature_hole(), seed)
        assert out.attributes[0][0] == 1  # the fairway is never touched
        outcomes.add((out.attributes[2][2], out.attributes[4][4]))
        changed = {
            (r, c)
            for r in range(15)
            for c in range(11)
            if out.attributes[r][c] != feature_hole().attributes[r][c]
        }
        assert changed <= {(2, 2), (4, 4)}
    assert outcomes == {(2, 2), (2, 3), (3, 2), (3, 3)}


@STYLES
def test_keeps_the_palette_of_water_that_stays_water(redraw):
    for seed in range(40):
        out = redraw(feature_hole(water_palette=0), seed)
        assert out.attributes[4][4] in (0, 2)


@STYLES
def test_is_deterministic(redraw):
    assert redraw(feature_hole(), 7).to_dict() == redraw(feature_hole(), 7).to_dict()


@STYLES
def test_leaves_the_original_alone(redraw):
    hole = feature_hole()
    before = hole.to_dict()
    redraw(hole, 3)
    assert hole.to_dict() == before


@pytest.fixture(scope="module")
def every_vanilla_hole(vanilla_courses, vanilla_jp_courses):
    return list(vanilla_holes())


@STYLES
def test_every_vanilla_hole_redraws_consistently(redraw, every_vanilla_hole):
    for hole_id, hole in every_vanilla_hole:
        hazard = {
            supertile
            for group in feature_groups(hole)
            if Kind.FAIRWAY not in group.kinds
            for supertile in group.supertiles
        }
        for seed in (0, 1, 2):
            out = redraw(hole, seed)
            assert out.terrain == hole.terrain, hole_id
            for r, row in enumerate(hole.attributes):
                for c, palette in enumerate(row):
                    new = out.attributes[r][c]
                    if (r, c) not in hazard:
                        assert new == palette, hole_id
                    elif new != palette:
                        assert new in HAZARD_PALETTE.values(), hole_id
            # every group still reads as one kind of feature
            for group in feature_groups(out):
                assert len(group.kinds) == 1, hole_id


def dried_out(draw, hole: HoleData, supertile: tuple[int, int]) -> float:
    """How often, over 400 seeds, `draw` turns the water at `supertile` to sand."""
    row, col = supertile
    return (
        sum(
            redraw_hazards(hole, seed, draw).attributes[row][col] == 2
            for seed in range(400)
        )
        / 400
    )


def test_uniform_ignores_size():
    # 1 - 0.35 for the lake and the one-supertile pond alike
    assert 0.58 < dried_out(uniform, lake_hole(), (8, 0)) < 0.72
    assert 0.58 < dried_out(uniform, feature_hole(), (4, 4)) < 0.72


def test_weighted_flips_large_groups_less_often():
    # 0.5 * 1000 / 4096, about 12%, against 50% for the pond
    assert 0.08 < dried_out(weighted, lake_hole(), (8, 0)) < 0.17
    assert 0.42 < dried_out(weighted, feature_hole(), (4, 4)) < 0.58
