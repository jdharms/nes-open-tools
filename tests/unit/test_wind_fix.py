"""Unit tests for the wind fix patch."""

import pytest

from golf.core.patches import PATCH_SPECS, PatchError
from golf.core.patches.wind_fix import (
    FIXED_COS_LOOKUP,
    VANILLA_COS_LOOKUP,
    WIND_FIX_PATCH,
)
from tests.prg_writer import PrgImageWriter

LOOKUP = 0x3E7C3


def vanilla_like_rom() -> PrgImageWriter:
    rom = PrgImageWriter(bytes(16 * 0x4000))
    rom.write_prg(LOOKUP, VANILLA_COS_LOOKUP)
    return rom


def test_it_rewrites_only_the_three_bytes_before_the_shared_entry():
    rom = vanilla_like_rom()
    before = bytes(rom.read_prg(0, 16 * 0x4000))
    WIND_FIX_PATCH.apply(rom)
    after = bytes(rom.read_prg(0, 16 * 0x4000))
    changed = [
        offset for offset in range(len(before)) if before[offset] != after[offset]
    ]
    assert changed == [LOOKUP, LOOKUP + 1, LOOKUP + 2]
    assert after[LOOKUP : LOOKUP + 3] == FIXED_COS_LOOKUP == bytes([0x49, 0x40, 0xEA])


def test_applying_twice_changes_nothing():
    rom = vanilla_like_rom()
    WIND_FIX_PATCH.apply(rom)
    assert WIND_FIX_PATCH.is_applied(rom)
    WIND_FIX_PATCH.apply(rom)
    assert bytes(rom.read_prg(LOOKUP, 3)) == FIXED_COS_LOOKUP


def test_it_refuses_a_rom_without_the_vanilla_lookup():
    rom = PrgImageWriter(bytes(16 * 0x4000))
    assert not WIND_FIX_PATCH.can_apply(rom)
    with pytest.raises(PatchError):
        WIND_FIX_PATCH.apply(rom)


def test_the_eor_is_the_wrapped_add_for_every_half_turn_angle():
    assert all(angle ^ 0x40 == (angle + 0x40) % 0x80 for angle in range(0x80))


def test_it_is_a_patch_type():
    assert "wind_fix" in PATCH_SPECS
