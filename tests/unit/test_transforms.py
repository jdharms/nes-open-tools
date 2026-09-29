"""Hole transforms (golf/randomizer/transforms.py)."""

import pytest

from golf.algorithms.forest_fill import ALL_FOREST_TILES
from golf.formats.hole_data import HoleData
from golf.randomizer.catalog import HoleId
from golf.randomizer.manifest import Slot
from golf.randomizer.transforms import (
    TransformError,
    apply_transforms,
    mirror_hole,
    mirror_tables,
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
