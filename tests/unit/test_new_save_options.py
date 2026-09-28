"""Unit tests for the new-save options patch: its bytes, and its routine run under py65."""

import pytest
from py65.devices.mpu6502 import MPU

from golf.core import rom_utils
from golf.core.patches.new_save_options import (
    NEW_SAVE_OPTIONS_PATCH,
    RESUME_ADDR,
    ROUTINE_ADDR,
    ROUTINE_ORIGINAL,
    SPLICE_ADDR,
    SPLICE_ORIGINAL,
    TABLE_ADDR,
    TABLE_OFFSET,
    VANILLA_VALUES,
    BallSpin,
    SwingSpeed,
    new_save_option_values_patch,
    option_values,
)

RETURN = 0x0002  # where the harness's RTS at RESUME_ADDR lands


def run_routine(table: bytes) -> bytes:
    """Run NewSaveOptions over SRAM that is not yet $FF; return $6F98-$6FAF after."""
    routine, _ = NEW_SAVE_OPTIONS_PATCH.patches
    mpu = MPU()
    memory = mpu.memory
    memory[ROUTINE_ADDR : ROUTINE_ADDR + len(routine.patched)] = routine.patched
    memory[TABLE_ADDR : TABLE_ADDR + 4] = table
    memory[0x6F90:0x6FB8] = [0x11] * 0x28
    memory[RESUME_ADDR] = 0x60  # RTS: InitializeSram's magic writes, stubbed
    mpu.sp = 0xFD
    for byte in ((RETURN - 1) >> 8, (RETURN - 1) & 0xFF):
        memory[0x0100 + mpu.sp] = byte
        mpu.sp -= 1
    mpu.pc = ROUTINE_ADDR
    for _ in range(1000):
        if mpu.pc == RETURN:
            break
        mpu.step()
    else:
        pytest.fail("NewSaveOptions did not reach $AD50")
    assert memory[0x6F90:0x6F98] == [0x11] * 8, "wrote below $6F98"
    assert memory[0x6FB0:0x6FB8] == [0x11] * 8, "wrote past $6FAF"
    return bytes(memory[0x6F98:0x6FB0])


def test_the_routine_replaces_only_player_stats_code():
    routine, splice = NEW_SAVE_OPTIONS_PATCH.patches
    assert routine.prg_offset == rom_utils.cpu_to_prg_switched(ROUTINE_ADDR, 9)
    assert routine.original == ROUTINE_ORIGINAL[: len(routine.patched)]
    assert len(routine.patched) == len(routine.original)
    assert splice.prg_offset == rom_utils.cpu_to_prg_switched(SPLICE_ADDR, 9)
    assert splice.original == SPLICE_ORIGINAL
    assert splice.patched[:3] == bytes([0x4C, ROUTINE_ADDR & 0xFF, ROUTINE_ADDR >> 8])
    assert len(splice.patched) == len(splice.original)


def test_the_installed_table_holds_the_vanilla_values():
    routine, _ = NEW_SAVE_OPTIONS_PATCH.patches
    start = TABLE_ADDR - ROUTINE_ADDR
    assert routine.patched[start : start + 4] == VANILLA_VALUES
    assert routine.prg_offset + start == TABLE_OFFSET


def test_the_vanilla_table_reproduces_the_vanilla_fill():
    assert run_routine(VANILLA_VALUES) == bytes([0xFF] * 0x18)


def test_the_table_lands_on_the_four_options():
    values = option_values(False, SwingSpeed.FAST, SwingSpeed.SLOW, BallSpin.BACK2)
    assert run_routine(values) == bytes([0x00, 0x02, 0x00, 0x04]) + bytes([0xFF] * 20)


@pytest.mark.parametrize(
    "arguments, expected",
    [
        ((), b"\xff\xff\xff\xff"),
        ((False,), b"\x00\xff\xff\xff"),
        ((True, SwingSpeed.MEDIUM), b"\xff\x01\xff\xff"),
        ((True, SwingSpeed.OFF, SwingSpeed.FAST), b"\xff\xff\x02\xff"),
        ((True, SwingSpeed.OFF, SwingSpeed.OFF, BallSpin.TOP2), b"\xff\xff\xff\x00"),
        ((True, 2, 1, 3), b"\xff\x02\x01\x03"),
    ],
)
def test_option_values(arguments, expected):
    assert option_values(*arguments) == expected


@pytest.mark.parametrize(
    "arguments", [("on",), (True, 3), (True, SwingSpeed.OFF, 0x80), (True, 0, 0, 5)]
)
def test_values_the_game_does_not_use_are_refused(arguments):
    with pytest.raises(ValueError):
        option_values(*arguments)


def test_the_values_patch_fills_the_installed_table():
    patch = new_save_option_values_patch(spin=BallSpin.NORMAL)
    assert patch.requires == [NEW_SAVE_OPTIONS_PATCH]
    (table,) = patch.patches
    assert table.prg_offset == TABLE_OFFSET
    assert table.original == VANILLA_VALUES
    assert table.patched == b"\xff\xff\xff\x02"
