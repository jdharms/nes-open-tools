"""Redrawing bunkers and water hazards (golf/algorithms/hazards.py)."""

from functools import partial

import pytest

from golf.algorithms.features import Kind, feature_groups
from golf.algorithms.hazards import HAZARD_PALETTE, redraw_hazards, uniform, weighted
from golf.formats.hole_data import HoleData
from tests.synthetic_holes import synthetic_hole
from tests.vanilla_holes import VANILLA_IDS

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


@STYLES
def test_redraws_only_hazard_supertiles(redraw):
    hole = feature_hole()
    outcomes = set()
    for seed in range(40):
        out = redraw(hole, seed)
        assert out.attributes[0][0] == 1  # the fairway is never touched
        outcomes.add((out.attributes[2][2], out.attributes[4][4]))
        changed = {
            (r, c)
            for r in range(15)
            for c in range(11)
            if out.attributes[r][c] != hole.attributes[r][c]
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


@STYLES
@pytest.mark.parametrize("vanilla_hole", VANILLA_IDS, indirect=True)
def test_every_vanilla_hole_redraws_consistently(redraw, vanilla_hole):
    hole_id, hole = vanilla_hole
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


@pytest.mark.parametrize("kind", [Kind.SAND, Kind.WATER])
@pytest.mark.parametrize("size", [1, 256, 1000, 4096])
def test_uniform_ignores_size(kind, size):
    # Exact cutoff, independent of both current kind and area. Seeded PRNG
    # integration is already covered by redraw and golden-output tests.
    assert uniform(kind, size, 0.35 - 1e-9) is Kind.WATER
    assert uniform(kind, size, 0.35) is Kind.SAND
    assert uniform(kind, size, 0.35 + 1e-9) is Kind.SAND


@pytest.mark.parametrize(
    ("kind", "other", "base"),
    [(Kind.SAND, Kind.WATER, 0.3), (Kind.WATER, Kind.SAND, 0.5)],
)
@pytest.mark.parametrize(
    ("size", "factor"),
    [(256, 1.0), (1000, 1.0), (4096, 1000 / 4096)],
)
def test_weighted_flips_large_groups_less_often(kind, other, base, size, factor):
    chance = base * factor
    assert weighted(kind, size, chance - 1e-9) is other
    assert weighted(kind, size, chance) is kind
    assert weighted(kind, size, chance + 1e-9) is kind
