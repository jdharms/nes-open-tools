"""Compare putting in both original ROMs by executing their actual routines.

These are targeted cross-release checks, not a JP port of golf.physics.
"""

from pathlib import Path

import pytest
from py65.devices.mpu6502 import MPU

from golf.core.rom_reader import RomReader

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(
    not all(
        (ROOT / name).exists() for name in ("nes_open_us.nes", "mario_open_jp.nes")
    ),
    reason="both original ROMs required",
)


@pytest.fixture(scope="module")
def roms():
    return tuple(
        RomReader(str(ROOT / name)) for name in ("nes_open_us.nes", "mario_open_jp.nes")
    )


def cpu(rom, start):
    mpu = MPU()
    mpu.memory[0x8000:0xC000] = rom.read_switched(0x8000, 13, 0x4000)
    mpu.memory[0xC000:0x10000] = rom.read_fixed(0xC000, 0x4000)
    mpu.pc = start
    mpu.stPushWord(0x01FF)
    return mpu


def run(mpu, stop=0x0200):
    for _ in range(10000):
        if mpu.pc == stop:
            return
        mpu.step()
    pytest.fail(f"routine did not finish: PC=${mpu.pc:04X}")


def slope(rom, jp, tile, view):
    mpu = cpu(rom, 0xF229 if jp else 0xF300)
    mpu.memory[0x20:0x22] = [0, 3]
    mpu.memory[0x0300] = tile
    mpu.memory[0x97 if jp else 0x98] = view
    run(mpu)
    return bytes(mpu.memory[0xEA:0xF0]), mpu.memory[0xC9 if jp else 0xCA]


def test_slope_and_putting_tables_are_identical(roms):
    us, jp = roms
    assert us.read_fixed(0xF359, 110) == jp.read_fixed(0xF290, 110)
    assert us.read_switched(0xB8B1, 13, 0x97) == jp.read_switched(0xB932, 13, 0x97)
    assert us.read_switched(0xAB46, 13, 6) == jp.read_switched(0xABAF, 13, 6)
    assert us.read_fixed(0xE7CB, 128) == jp.read_fixed(0xE6E2, 128)


@pytest.mark.parametrize("tile", range(256))
@pytest.mark.parametrize("view", [0, 0x40, 0x80, 0xC0])
def test_all_tile_vectors_and_view_modes(roms, tile, view):
    us, jp = (slope(rom, bool(i), tile, view) for i, rom in enumerate(roms))
    expected = bytearray(us[0])
    if view == 0xC0:
        for axis in (0, 3):
            magnitude = int.from_bytes(expected[axis : axis + 2], "little") * 2
            expected[axis : axis + 2] = magnitude.to_bytes(2, "little")
    assert jp == (bytes(expected), us[1])


@pytest.mark.parametrize("speed", range(3))
@pytest.mark.parametrize("power", [0, 1, 5, 10, 20, 30, 40, 48])
@pytest.mark.parametrize("aim", [0, 16, 32, 64, 96, 128, 192, 240])
def test_putter_launch_velocities_match(roms, speed, power, aim):
    results = []
    for i, rom in enumerate(roms):
        jp = bool(i)
        mpu = cpu(rom, 0xAD73 if jp else 0xAD0A)
        # Supply identical green lie; omit the terrain probe's course buffers.
        mpu.memory[0xECD3 if jp else 0xEDBC] = 0x60
        mpu.memory[0xCC if jp else 0xCD] = 15
        mpu.memory[0xCD if jp else 0xCE] = speed
        mpu.memory[0xD5 if jp else 0xD6] = power
        mpu.memory[0xB6 if jp else 0xB7] = aim
        mpu.memory[0xC8 if jp else 0xC9] = 6
        run(mpu)
        base = 0xD9 if jp else 0xDA
        results.append(bytes(mpu.memory[base : base + 14]))
    assert results[0] == results[1]


@pytest.mark.parametrize("tile", [*range(0x30, 0x48), *range(0x88, 0xA0), 0])
@pytest.mark.parametrize(
    "velocity", [(0, 0x4000), (0x4000, 0), (-12345, 6789), (123, -456)]
)
def test_normal_view_green_update_matches(roms, tile, velocity):
    results = []
    for i, rom in enumerate(roms):
        jp = bool(i)
        vector, flags = slope(rom, jp, tile, 0x40)
        mpu = cpu(rom, 0xB256 if jp else 0xB1D5)
        mpu.memory[0xEA:0xF0] = vector
        mpu.memory[0xC9 if jp else 0xCA] = flags
        mpu.memory[0xD7 if jp else 0xD8] = 0xFF
        mpu.memory[0x05C2 if jp else 0x05B0] = 9
        base = 0xD9 if jp else 0xDA
        for axis, value in enumerate(velocity):
            mpu.memory[base + axis * 3 : base + axis * 3 + 3] = (
                value & 0xFFFFFF
            ).to_bytes(3, "little")
        run(mpu)
        results.append(bytes(mpu.memory[base : base + 6]))
    assert results[0] == results[1]


@pytest.mark.parametrize(
    "jp,view,expected",
    [(False, 0xC0, (50, 16271)), (True, 0x40, (50, 16271)), (True, 0xC0, (100, 16221))],
)
def test_cup_view_doubling_changes_the_actual_roll(roms, jp, view, expected):
    rom = roms[int(jp)]
    vector, flags = slope(rom, jp, 0x31, view)
    mpu = cpu(rom, 0xB256 if jp else 0xB1D5)
    mpu.memory[0xEA:0xF0] = vector
    mpu.memory[0xC9 if jp else 0xCA] = flags
    mpu.memory[0xD7 if jp else 0xD8] = 0xFF
    mpu.memory[0x05C2 if jp else 0x05B0] = 9
    base = 0xD9 if jp else 0xDA
    mpu.memory[base + 3 : base + 6] = (0x4000).to_bytes(3, "little")
    run(mpu)
    assert (
        tuple(
            int.from_bytes(mpu.memory[base + axis * 3 : base + axis * 3 + 3], "little")
            for axis in range(2)
        )
        == expected
    )
