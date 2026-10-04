"""Mirroring a hole left to right (golf/algorithms/mirror.py)."""

import pytest

from golf.algorithms.features import TEE_BOX
from golf.algorithms.forest_fill import ALL_FOREST_TILES, INNER_BORDER
from golf.algorithms.mirror import MirrorError, mirror_hole, mirror_tiles
from golf.formats.hole_data import HoleData
from golf.physics import Flag
from golf.physics.terrain import FIRST_GREEN_TILE, GREEN_SIZE
from tests.synthetic_holes import synthetic_hole
from tests.vanilla_holes import VANILLA_IDS


def mappable_hole() -> HoleData:
    hole = synthetic_hole()
    hole.terrain[0][0] = 0xA0  # synthetic_hole marks it with the hole number
    return hole


@pytest.mark.parametrize("kind", ["terrain", "greens"])
def test_tables_are_their_own_inverse(kind):
    partners = getattr(mirror_tiles(), kind)
    assert all(partners[partners[tile]] == tile for tile in partners)


def test_forest_trees_are_refilled_not_mapped():
    assert not ALL_FOREST_TILES & mirror_tiles().terrain.keys()


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
        125,
        124,
        123,
        122,
    ]


def test_mirror_leaves_the_original_alone():
    hole = mappable_hole()
    before = hole.to_dict()
    mirror_hole(hole)
    assert hole.to_dict() == before


def test_mirror_refills_forests():
    mirrored = mirror_hole(mappable_hole())
    assert all(
        tile in ALL_FOREST_TILES | {INNER_BORDER}
        for row in mirrored.terrain
        for tile in row
    )


def test_unmapped_tile_is_an_error():
    with pytest.raises(MirrorError, match=r"\$01 at row 0, column 0"):
        mirror_hole(synthetic_hole())


@pytest.mark.parametrize("vanilla_hole", VANILLA_IDS, indirect=True)
def test_every_vanilla_hole_mirrors_back_and_places_tees_and_pins(vanilla_hole):
    hole_id, hole = vanilla_hole
    mirrored = mirror_hole(hole)
    twice = mirror_hole(mirrored)
    assert twice.greens == hole.greens, hole_id
    assert twice.attributes == hole.attributes, hole_id
    assert twice.metadata == hole.metadata, hole_id
    assert twice.green_x == hole.green_x, hole_id
    for row, back in zip(hole.terrain, twice.terrain, strict=True):
        for tile, returned in zip(row, back, strict=True):
            if tile not in ALL_FOREST_TILES:
                assert returned == tile, hole_id
    tee = mirrored.metadata["tee"]
    assert mirrored.terrain[tee["y"] // 8][tee["x"] // 8] in TEE_BOX, hole_id
    for pin in range(4):
        column, row = pin_pixel(hole, pin)
        assert pin_pixel(mirrored, pin) == (GREEN_SIZE - 1 - column, row), hole_id
        assert mirrored.greens[row][GREEN_SIZE - 1 - column] >= FIRST_GREEN_TILE


def pin_pixel(hole: HoleData, pin: int) -> tuple[int, int]:
    """The column and row of the green box the pin is in."""
    flag = Flag.for_pin(hole, pin)
    return (flag.x >> 8) - hole.green_x, (flag.y >> 8) - hole.green_y
