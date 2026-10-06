"""Unit tests for the wind anchors patch and the model of it in `predict_hole`."""

import pytest

from golf.core.patches import COURSE_MIRRORS_PATCH, PATCH_SPECS, PatchError
from golf.core.patches.wind_anchors import (
    ANCHOR_TABLE_CPU_ADDR,
    anchor_table_bytes,
    wind_anchors_patch,
    wind_anchors_patches,
)
from golf.core.rng import predict_hole
from tests.prg_writer import PrgImageWriter

ANCHORS = [((hole * 0x30) & 0xF0, hole % 11) for hole in range(18)]
TABLE = 0x3C000 + ANCHOR_TABLE_CPU_ADDR - 0xC000
DRAW = 0x3DBA0


def vanilla_like_rom(mirrored: bool = True) -> PrgImageWriter:
    rom = PrgImageWriter(bytes(16 * 0x4000))
    for patch in wind_anchors_patches(ANCHORS):
        rom.write_prg(patch.prg_offset, patch.original)
    for mirror in COURSE_MIRRORS_PATCH.patches:
        rom.write_prg(
            mirror.prg_offset, mirror.patched if mirrored else mirror.original
        )
    return rom


def test_the_table_is_two_bytes_a_hole_direction_then_speed():
    table = anchor_table_bytes(ANCHORS)
    assert len(table) == 36
    assert [(table[n], table[n + 1]) for n in range(0, 36, 2)] == ANCHORS


def test_the_table_fills_the_rest_of_the_dead_flag_block():
    """$E00B-$E02E: after seeded_wind's 36-byte seed table, up to GreenFlagYTable."""
    assert ANCHOR_TABLE_CPU_ADDR == 0xDFE7 + 36
    assert ANCHOR_TABLE_CPU_ADDR + 36 == 0xE02F


@pytest.mark.parametrize(
    "anchors",
    [
        ANCHORS[:17],
        [*ANCHORS, (0, 0)],
        [(0x08, 3), *ANCHORS[1:]],
        [(0x100, 3), *ANCHORS[1:]],
        [(0x40, 11), *ANCHORS[1:]],
        [(0x40, -1), *ANCHORS[1:]],
    ],
)
def test_anchors_the_table_cannot_hold_are_refused(anchors):
    with pytest.raises(ValueError, match="wind"):
        anchor_table_bytes(anchors)


def test_it_writes_the_table_and_the_read_and_nothing_else():
    rom = vanilla_like_rom()
    before = bytes(rom.read_prg(0, 16 * 0x4000))
    wind_anchors_patch(ANCHORS).apply(rom)
    after = bytes(rom.read_prg(0, 16 * 0x4000))
    changed = {
        offset for offset in range(len(before)) if before[offset] != after[offset]
    }
    assert changed <= {*range(TABLE, TABLE + 36), *range(DRAW, DRAW + 22)}
    assert after[TABLE : TABLE + 36] == anchor_table_bytes(ANCHORS)
    assert after[DRAW : DRAW + 22].hex() == (
        "209cd2"  # jsr LSFR_RNG_ALGO
        "209cd2"  # jsr LSFR_RNG_ALGO
        "a631"  # ldx TempX
        "bd0be0"  # lda WindAnchorTable,x
        "8d2f01"  # sta WindDirectionAnchor
        "bd0ce0"  # lda WindAnchorTable+1,x
        "8d3001"  # sta WindSpeedAnchor
        "eaea"
    )


def test_it_requires_course_mirrors():
    assert wind_anchors_patch(ANCHORS).requires == [COURSE_MIRRORS_PATCH]
    with pytest.raises(PatchError, match="requires course_mirrors"):
        wind_anchors_patch(ANCHORS).apply(vanilla_like_rom(mirrored=False))


def test_it_is_a_patch_type():
    assert "wind_anchors" in PATCH_SPECS


@pytest.mark.parametrize("seed", [0x0001, 0x1234, 0xBEEF, 0xFFFE])
def test_table_anchors_leave_the_pin_and_the_rng_where_the_seed_puts_them(seed):
    dealt = predict_hole(seed, swings=6)
    given = predict_hole(seed, swings=6, anchors=(0x80, 10))
    assert (given.direction_anchor, given.speed_anchor) == (0x80, 10)
    assert (given.pin_index, given.slot_state) == (dealt.pin_index, dealt.slot_state)
    assert all(direction in (0x80, 0x00) for direction, _ in given.winds)
    again = predict_hole(
        seed, swings=6, anchors=(dealt.direction_anchor, dealt.speed_anchor)
    )
    assert again == dealt
