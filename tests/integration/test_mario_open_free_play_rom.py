"""Execute Mario Open's actual unlock, menu and score checks under py65."""

from pathlib import Path

import pytest
from py65.devices.mpu6502 import MPU

from golf.core.jp_rom_utils import JP_ROM_SHA1
from golf.core.patches import PatchStack, StackError
from golf.core.patches.mario_open_free_play import mario_open_free_play_patch

ROM_PATH = Path(__file__).resolve().parents[2] / "mario_open_jp.nes"
pytestmark = pytest.mark.skipif(not ROM_PATH.exists(), reason="JP ROM not present")


@pytest.fixture(scope="module")
def vanilla():
    return ROM_PATH.read_bytes()


@pytest.fixture(scope="module")
def patched(vanilla):
    return (
        PatchStack([mario_open_free_play_patch()], base_sha1=JP_ROM_SHA1)
        .build(vanilla)
        .rom
    )


def cpu(rom, bank, start):
    mpu = MPU()
    mpu.memory[0x8000:0xC000] = rom[16 + bank * 0x4000 : 16 + (bank + 1) * 0x4000]
    mpu.memory[0xC000:0x10000] = rom[16 + 15 * 0x4000 : 16 + 16 * 0x4000]
    mpu.pc = start
    return mpu


def run_to(mpu, targets):
    for _ in range(200):
        if mpu.pc in targets:
            return mpu.pc
        mpu.step()
    pytest.fail(f"did not reach {targets}: PC=${mpu.pc:04X}")


@pytest.mark.parametrize("progress", range(6))
def test_entry_unlocks_before_menu(patched, progress):
    mpu = cpu(patched, 13, 0x8000)
    mpu.memory[0x6003] = progress
    mpu.memory[0x6004:0x6010] = list(range(12))
    mpu.memory[0x98] = 0x80
    run_to(mpu, {0x8004})
    assert mpu.memory[0x6003] == 5
    assert mpu.memory[0x98] == 0
    assert mpu.memory[0x6004:0x6010] == list(range(12))
    assert mpu.sp == 0xFF


@pytest.mark.parametrize("course", range(6))
@pytest.mark.parametrize("mode", [0, 1])
def test_menu_maps_all_six_courses(patched, course, mode):
    mpu = cpu(patched, 12, 0x89B0)
    mpu.memory[0x6003] = 5
    mpu.memory[0x0608] = course
    mpu.memory[0x0100] = mode
    run_to(mpu, {0x89D1})
    assert mpu.memory[0x0102] == course


@pytest.mark.parametrize("course,limit", enumerate([18, 12, 8, 4, 2, 8]))
@pytest.mark.parametrize("dismissals", [0, 1, 2, 20, 255])
@pytest.mark.parametrize("input_state", [0, 0xC0])
def test_actual_limit_setup(vanilla, course, limit, dismissals, input_state):
    mpu = cpu(vanilla, 12, 0xA264)
    mpu.memory[0x0102] = course
    mpu.memory[0x6028 + course] = dismissals
    mpu.memory[0x15] = input_state
    run_to(mpu, {0xA282})
    bonus = min(dismissals // 2, 10) if input_state == 0xC0 else 0
    assert mpu.memory[0x0658] == limit + bonus


@pytest.mark.parametrize("progress", range(6))
@pytest.mark.parametrize("course", range(6))
def test_vanilla_frontier_completion_advances_progress(vanilla, progress, course):
    mpu = cpu(vanilla, 13, 0x84F6)
    mpu.memory[0x6003] = progress
    mpu.memory[0x0102] = course
    run_to(mpu, {0x8512})
    assert mpu.memory[0x6003] == progress + (progress < 5 and course == progress)


@pytest.mark.parametrize("limit", [18, 12, 8, 4, 2, 8])
@pytest.mark.parametrize("score", [-20, -1, 0, 1, 2, 4, 8, 12, 18, 127, 256, 500])
def test_score_check_continues_past_limit(vanilla, patched, limit, score):
    for rom, expected in [
        (vanilla, 0x847E if score + 1 >= limit else 0x8297),
        (patched, 0x8297),
    ]:
        mpu = cpu(rom, 13, 0x8268)
        mpu.memory[0x011F] = 4
        mpu.memory[0x0109] = 4
        mpu.memory[0x04E6] = score & 0xFF
        mpu.memory[0x04E7] = (score >> 8) & 0xFF
        mpu.memory[0x0658] = limit
        assert run_to(mpu, {0x847E, 0x8297}) == expected


def test_patch_is_idempotent_and_rejects_us(vanilla, patched):
    assert (
        PatchStack([mario_open_free_play_patch()], base_sha1=None).build(patched).rom
        == patched
    )
    us = ROM_PATH.with_name("nes_open_us.nes")
    if us.exists():
        with pytest.raises(StackError):
            PatchStack([mario_open_free_play_patch()], base_sha1=None).build(
                us.read_bytes()
            )
