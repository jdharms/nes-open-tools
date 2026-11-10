"""Unit tests for the swing speed HUD patch, on a bare PRG image."""

import pytest

from golf.core import rom_utils
from golf.core.patches import PATCH_SPECS, SWING_SPEED_HUD_PATCH, PatchError
from golf.core.patches.swing_speed_hud import (
    BLANK_TILE,
    CLUB_SPLICE_ADDR,
    COMMA_TILE,
    HOOK_ADDR,
    MID_COMMA_ADDRS,
    _hook_program,
)
from tests.prg_writer import PrgImageWriter


def bank13(addr: int) -> int:
    return rom_utils.cpu_to_prg_switched(addr, 13)


def vanilla_like_rom() -> PrgImageWriter:
    rom = PrgImageWriter(bytes(16 * 0x4000))
    for sub in SWING_SPEED_HUD_PATCH.patches:
        rom.write_prg(sub.prg_offset, sub.original)
    return rom


def test_the_hook_draws_the_letter_then_finishes_like_the_vanilla_routine():
    program = _hook_program()
    table = program.symbol("SpeedTiles")
    assert program.code == bytes(
        [
            0xA6, 0xCE,  # LDX SwingSpeed
            0xBD, table & 0xFF, table >> 8,  # LDA SpeedTiles,X
            0x8D, 0x19, 0x04,  # STA $0419, column 5 of the club box
            0x20, 0x84, 0xCE, 0x10, 0x04,  # JSR WriteNametableTiles / .dw $0410
            0x4C, 0x70, 0xA1,  # JMP ShowDistanceToPin
            0x17, 0x13, COMMA_TILE,  # S, M, and the comma redrawn as F
        ]
    )  # fmt: skip
    assert table == HOOK_ADDR + 16


def test_the_club_splice_moves_both_tiles_left_and_jumps_to_the_hook():
    rom = vanilla_like_rom()
    SWING_SPEED_HUD_PATCH.apply(rom)
    assert bytes(rom.read_prg(bank13(CLUB_SPLICE_ADDR), 17)) == bytes(
        [
            0xA6, 0xCD,
            0xBD, 0x5D, 0xA5,
            0x8D, 0x16, 0x04,
            0xBD, 0x6D, 0xA5,
            0x8D, 0x17, 0x04,
            0x4C, HOOK_ADDR & 0xFF, HOOK_ADDR >> 8,
        ]
    )  # fmt: skip


def test_it_writes_only_its_own_sites():
    rom = vanilla_like_rom()
    before = bytes(rom.data)
    SWING_SPEED_HUD_PATCH.apply(rom)
    sites = {
        offset
        for sub in SWING_SPEED_HUD_PATCH.patches
        for offset in range(sub.prg_offset, sub.prg_offset + len(sub.patched))
    }
    changed = {i for i in range(len(before)) if before[i] != rom.data[i]}
    assert changed <= sites
    for addr in MID_COMMA_ADDRS:
        assert rom.data[bank13(addr)] == BLANK_TILE


def test_applying_twice_changes_nothing():
    rom = vanilla_like_rom()
    SWING_SPEED_HUD_PATCH.apply(rom)
    once = bytes(rom.data)
    assert SWING_SPEED_HUD_PATCH.is_applied(rom)
    SWING_SPEED_HUD_PATCH.apply(rom)
    assert bytes(rom.data) == once


def test_it_refuses_a_rom_without_the_vanilla_bytes():
    rom = PrgImageWriter(bytes(16 * 0x4000))
    assert not SWING_SPEED_HUD_PATCH.can_apply(rom)
    with pytest.raises(PatchError):
        SWING_SPEED_HUD_PATCH.apply(rom)


def test_it_is_a_patch_type():
    assert "swing_speed_hud" in PATCH_SPECS
