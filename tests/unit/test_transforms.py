"""Hole transforms (golf/randomizer/transforms.py)."""

import pytest

from golf.algorithms.features import Kind, feature_groups
from golf.algorithms.forest_fill import ALL_FOREST_TILES
from golf.formats.hole_data import HoleData
from golf.randomizer.catalog import HoleId
from golf.randomizer.manifest import Slot
from golf.randomizer.transforms import (
    TransformError,
    apply_transforms,
    hazards_hole,
    hazards_weighted_hole,
    mirror_hole,
    mirror_tables,
    parse_transform,
)
from tests.synthetic_holes import synthetic_hole


def mappable_hole() -> HoleData:
    hole = synthetic_hole()
    hole.terrain[0][0] = 0xA0  # synthetic_hole marks it with the hole number
    return hole


@pytest.mark.parametrize("kind", [0, 1], ids=["terrain", "greens"])
def test_tables_are_their_own_inverse(kind):
    table = mirror_tables()[kind]
    assert all(table[table[tile]] == tile for tile in table)


def test_forest_trees_are_refilled_not_mapped():
    assert not ALL_FOREST_TILES & mirror_tables()[0].keys()


def test_mirror_flips_greens_attributes_and_positions():
    hole = mappable_hole()
    hole.attributes[0] = list(range(11))
    hole.greens[3][0] = 0x31  # slopes right; $33 is the same slope to the left
    mirrored = mirror_hole(hole)
    assert mirrored.attributes[0] == list(range(10, -1, -1))
    assert mirrored.greens[3][23] == 0x33
    # The rough checkerboard keeps its phase: every square changes column parity
    assert mirrored.greens[0][0] == 0x29
    assert mirrored.green_x == 176 - 24 - 100
    assert mirrored.metadata["tee"] == {"x": 87, "y": 300}
    assert [f["x_offset"] for f in mirrored.metadata["flag_positions"]] == [
        127,
        126,
        125,
        124,
    ]


def test_mirror_leaves_the_original_alone():
    hole = mappable_hole()
    before = hole.to_dict()
    mirror_hole(hole)
    assert hole.to_dict() == before


def test_mirror_refills_forests():
    mirrored = mirror_hole(mappable_hole())
    assert all(
        tile in ALL_FOREST_TILES | {0x3F} for row in mirrored.terrain for tile in row
    )


def test_unmapped_tile_is_an_error():
    with pytest.raises(TransformError, match=r"\$01 at row 0, column 0"):
        mirror_hole(synthetic_hole())


def test_unknown_transform_is_an_error():
    with pytest.raises(TransformError, match="unknown transform"):
        apply_transforms(mappable_hole(), ["spin@1"])


def test_slot_round_trips_a_transform():
    slot = Slot(HoleId("nes_us/01"), 4, 0, ("mirror@1",))
    assert Slot.from_json(slot.to_json()) == slot


def test_every_nes_open_hole_mirrors_back(vanilla_courses):
    for path in sorted(vanilla_courses.glob("*/hole_*.json")):
        hole = HoleData()
        hole.load(path)
        twice = mirror_hole(mirror_hole(hole))
        assert twice.greens == hole.greens, path
        assert twice.attributes == hole.attributes, path
        assert twice.metadata == hole.metadata, path
        assert twice.green_x == hole.green_x, path
        for row, back in zip(hole.terrain, twice.terrain, strict=True):
            for tile, returned in zip(row, back, strict=True):
                if tile not in ALL_FOREST_TILES:
                    assert returned == tile, path


def feature_hole(sand_palette: int = 2, water_palette: int = 3) -> HoleData:
    """Deep rough with a fairway, a bunker and a pond, each one supertile of `$27`."""
    hole = mappable_hole()
    hole.terrain = [[0xDF] * 22 for _ in range(30)]
    for row, col in ((0, 0), (2, 2), (4, 4)):
        for dy in (0, 1):
            for dx in (0, 1):
                hole.terrain[row * 2 + dy][col * 2 + dx] = 0x27
    hole.attributes = [[1] * 11 for _ in range(15)]
    hole.attributes[2][2] = sand_palette
    hole.attributes[4][4] = water_palette
    return hole


HAZARDS = pytest.mark.parametrize(
    "shuffle", [hazards_hole, hazards_weighted_hole], ids=["uniform", "weighted"]
)


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


@HAZARDS
def test_hazards_redraws_only_hazard_supertiles(shuffle):
    outcomes = set()
    for seed in range(40):
        out = shuffle(feature_hole(), seed)
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


@HAZARDS
def test_hazards_keeps_the_palette_of_water_that_stays_water(shuffle):
    for seed in range(40):
        out = shuffle(feature_hole(water_palette=0), seed)
        assert out.attributes[4][4] in (0, 2)


@HAZARDS
def test_hazards_is_deterministic(shuffle):
    assert shuffle(feature_hole(), 7).to_dict() == shuffle(feature_hole(), 7).to_dict()


@HAZARDS
def test_hazards_leaves_the_original_alone(shuffle):
    hole = feature_hole()
    before = hole.to_dict()
    shuffle(hole, 3)
    assert hole.to_dict() == before


@pytest.mark.parametrize("name", ["hazards@1", "hazards-weighted@1"])
@pytest.mark.parametrize("argument", ["", ":", ":-1", ":x", ":4294967296"])
def test_hazards_needs_a_seed(name, argument):
    with pytest.raises(TransformError, match=f"{name} takes a seed"):
        parse_transform(name + argument)


def test_mirror_takes_no_argument():
    with pytest.raises(TransformError, match="takes no argument"):
        parse_transform("mirror@1:3")


def test_slot_round_trips_an_argument():
    slot = Slot(
        HoleId("nes_us/01"), 4, 0, ("hazards@1:99", "hazards-weighted@1:5", "mirror@1")
    )
    assert Slot.from_json(slot.to_json()) == slot


@HAZARDS
def test_every_nes_open_hole_shuffles_consistently(shuffle, vanilla_courses):
    for path in sorted(vanilla_courses.glob("*/hole_*.json")):
        hole = HoleData()
        hole.load(path)
        groups = feature_groups(hole)
        hazard = {
            s for g in groups if Kind.FAIRWAY not in g.kinds for s in g.supertiles
        }
        for seed in (0, 1, 2):
            out = shuffle(hole, seed)
            assert out.terrain == hole.terrain, path
            for r, row in enumerate(hole.attributes):
                for c, palette in enumerate(row):
                    if (r, c) not in hazard:
                        assert out.attributes[r][c] == palette, path
            # every group still reads as one kind of feature
            for group in feature_groups(out):
                assert len(group.kinds) == 1, path


def dried_out(shuffle, hole: HoleData, supertile: tuple[int, int]) -> float:
    """How often, over 400 seeds, `shuffle` turns the water at `supertile` to sand."""
    row, col = supertile
    return (
        sum(shuffle(hole, seed).attributes[row][col] == 2 for seed in range(400)) / 400
    )


def test_uniform_hazards_ignore_size():
    # 1 - 0.35 for the lake and the one-supertile pond alike
    assert 0.58 < dried_out(hazards_hole, lake_hole(), (8, 0)) < 0.72
    assert 0.58 < dried_out(hazards_hole, feature_hole(), (4, 4)) < 0.72


def test_weighted_hazards_flip_large_groups_less_often():
    # 0.5 * 1000 / 4096, about 12%, against 50% for the pond
    assert 0.08 < dried_out(hazards_weighted_hole, lake_hole(), (8, 0)) < 0.17
    assert 0.42 < dried_out(hazards_weighted_hole, feature_hole(), (4, 4)) < 0.58
