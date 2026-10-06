"""Integration: the Mario Open free-play patch, with the patched code run under py65."""

from pathlib import Path

import pytest
from py65.devices.mpu6502 import MPU

from golf.core import rom_utils
from golf.core.patches import PatchError, Recipe, StackError
from golf.core.patches.mario_open_free_play import (
    ALL_COURSES,
    CONTINUE_SHOT_ADDR,
    DISMISSAL_HANDLER_ADDR,
    ENTRY_ADDR,
    PROGRESSION_ADDR,
    ROUND_BANK,
)

ROOT = Path(__file__).resolve().parents[2]
ROM_PATH = ROOT / "mario_open_jp.nes"
US_ROM_PATH = ROOT / "nes_open_us.nes"

pytestmark = pytest.mark.skipif(
    not ROM_PATH.exists(), reason=f"{ROM_PATH.name} not present"
)

# The next-shot score check and what it reads (JP addresses).
SCORE_CHECK_ADDR = 0x8268
HOLE_STROKES = 0x011F
HOLE_PAR = 0x0109
ROUND_SCORE = 0x04E6  # signed 16-bit, relative to par over the finished holes
SCORE_LIMIT = 0x0658


def recipe(**extra) -> Recipe:
    return Recipe.from_dict(
        {"steps": [{"patch": "mario_open_free_play"}], **extra}, ROOT
    )


@pytest.fixture(scope="module")
def vanilla() -> bytes:
    return ROM_PATH.read_bytes()


@pytest.fixture(scope="module")
def patched(vanilla) -> bytes:
    return recipe().stack(vanilla).build(vanilla).rom


def machine(rom: bytes, start: int) -> MPU:
    """A CPU at `start` with bank 13 and the fixed bank mapped."""
    mpu = MPU()
    prg = rom[rom_utils.INES_HEADER_SIZE :]
    for cpu_addr, bank in ((0x8000, ROUND_BANK), (0xC000, 15)):
        offset = bank * 0x4000
        mpu.memory[cpu_addr : cpu_addr + 0x4000] = prg[offset : offset + 0x4000]
    mpu.pc = start
    return mpu


def run_to(mpu: MPU, targets: set[int]) -> int:
    for _ in range(200):
        if mpu.pc in targets:
            return mpu.pc
        mpu.step()
    pytest.fail(f"did not reach {targets}: PC=${mpu.pc:04X}")


@pytest.mark.parametrize("progression", range(ALL_COURSES + 1))
def test_entry_unlocks_every_course(patched, progression):
    mpu = machine(patched, ENTRY_ADDR)
    neighbors = slice(PROGRESSION_ADDR - 3, PROGRESSION_ADDR + 13)
    mpu.memory[neighbors] = [0xA5] * 16
    mpu.memory[PROGRESSION_ADDR] = progression
    mpu.memory[0x98] = 0x80

    run_to(mpu, {ENTRY_ADDR + 4})

    expected = [0xA5] * 16
    expected[3] = ALL_COURSES
    assert mpu.memory[neighbors] == expected
    # what the two instructions the call replaced did
    assert (mpu.a, mpu.memory[0x98]) == (0, 0)
    assert mpu.sp == 0xFF


@pytest.mark.parametrize("score", [-20, 0, 6, 7, 8, 127, 300])
def test_no_score_ends_the_round(vanilla, patched, score):
    """Par 4, four strokes taken, limit +8: vanilla dismisses from +7, the next shot's score."""
    reached = []
    for rom in (vanilla, patched):
        mpu = machine(rom, SCORE_CHECK_ADDR)
        mpu.memory[HOLE_STROKES] = 4
        mpu.memory[HOLE_PAR] = 4
        mpu.memory[ROUND_SCORE : ROUND_SCORE + 2] = list(
            score.to_bytes(2, "little", signed=True)
        )
        mpu.memory[SCORE_LIMIT] = 8
        reached.append(run_to(mpu, {DISMISSAL_HANDLER_ADDR, CONTINUE_SHOT_ADDR}))

    assert reached == [
        DISMISSAL_HANDLER_ADDR if score >= 7 else CONTINUE_SHOT_ADDR,
        CONTINUE_SHOT_ADDR,
    ]


def test_applying_it_again_changes_nothing(patched):
    again = recipe(base_sha1=None)
    assert again.stack(patched).build(patched).rom == patched


@pytest.mark.skipif(not US_ROM_PATH.exists(), reason=f"{US_ROM_PATH.name} not present")
def test_the_us_rom_is_rejected(vanilla):
    us = US_ROM_PATH.read_bytes()
    with pytest.raises(StackError, match="base ROM SHA-1"):
        recipe().stack(us).build(us)
    with pytest.raises(PatchError, match="jp_"):
        recipe(base_sha1=None).stack(us).build(us)
