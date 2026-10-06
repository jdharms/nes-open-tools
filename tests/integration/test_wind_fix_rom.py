"""Integration: the wind fix on the vanilla ROM, with the game's own routines run under py65."""

from pathlib import Path

import pytest
from py65.devices.mpu6502 import MPU

from golf.core.patches import WIND_FIX_PATCH, PatchStack

ROM_PATH = Path(__file__).resolve().parents[2] / "nes_open_us.nes"

pytestmark = pytest.mark.skipif(
    not ROM_PATH.exists(), reason=f"{ROM_PATH.name} not present"
)

HEADER = 0x10
BANK = 0x4000
PHYSICS_BANK = 13
COS_LOOKUP = 0xE7C3  # LE7C3
TRIG_TABLE = 0xE7CB
APPLY_WIND_EFFECT = 0xB4FF
#: `ApplyWindEffect` has both components in $EA-$EF by here, and has moved nothing yet
WIND_VECTOR_DONE = 0xB590
WIND_DIRECTION = 0x96
WIND_SPEED = 0x97
BALL_HEIGHT = 0xB6
#: where the harness's return address lands when a routine returns
RETURN = 0x0002
DIRECTIONS = range(0x00, 0x100, 0x10)


@pytest.fixture(scope="module")
def vanilla() -> bytes:
    return ROM_PATH.read_bytes()


@pytest.fixture(scope="module")
def fixed(vanilla) -> bytes:
    return PatchStack([WIND_FIX_PATCH]).build(vanilla).rom


def machine(rom: bytes) -> MPU:
    """Bank 13 at $8000 and the fixed bank at $C000, all the wind code needs."""
    mpu = MPU()
    start = HEADER + PHYSICS_BANK * BANK
    mpu.memory[0x8000:0xC000] = rom[start : start + BANK]
    mpu.memory[0xC000:0x10000] = rom[HEADER + 15 * BANK : HEADER + 16 * BANK]
    mpu.sp = 0xFD
    for byte in ((RETURN - 1) >> 8, (RETURN - 1) & 0xFF):
        mpu.memory[0x0100 + mpu.sp] = byte
        mpu.sp -= 1
    return mpu


def run(mpu: MPU, start: int, stop: int) -> None:
    mpu.pc = start
    for _ in range(10_000):
        if mpu.pc == stop:
            return
        mpu.step()
    raise AssertionError(f"${start:04X} never reached ${stop:04X}")


def cos_lookup(rom: bytes, angle: int) -> int:
    mpu = machine(rom)
    mpu.a = angle
    run(mpu, COS_LOOKUP, RETURN)
    return mpu.a


def signed24(memory, address: int) -> int:
    value = memory[address] | memory[address + 1] << 8 | memory[address + 2] << 16
    return value - (1 << 24) if value & 0x800000 else value


def wind_vector(rom: bytes, direction: int, speed: int = 9) -> tuple[int, int]:
    """The push `ApplyWindEffect` computes, as signed ($EA-$EC, $ED-$EF)."""
    mpu = machine(rom)
    mpu.memory[WIND_DIRECTION] = direction
    mpu.memory[WIND_SPEED] = speed
    mpu.memory[BALL_HEIGHT] = 0x20
    run(mpu, APPLY_WIND_EFFECT, WIND_VECTOR_DONE)
    return signed24(mpu.memory, 0xEA), signed24(mpu.memory, 0xED)


def test_the_lookup_wraps_within_the_table(vanilla, fixed):
    table = vanilla[HEADER + 15 * BANK + TRIG_TABLE - 0xC000 :][:0x80]
    for angle in range(0x80):
        assert cos_lookup(fixed, angle) == table[(angle + 0x40) % 0x80], hex(angle)


def test_angles_below_a_quarter_turn_read_what_vanilla_reads(vanilla, fixed):
    """The launch angle, the lookup's other caller, never reaches $40."""
    for angle in range(0x40):
        assert cos_lookup(fixed, angle) == cos_lookup(vanilla, angle), hex(angle)


def test_vanilla_reads_past_the_table_from_a_quarter_turn(vanilla):
    """The bug the patch fixes: a pure crosswind's Y component is not zero."""
    assert cos_lookup(vanilla, 0x40) == 0xA2
    assert wind_vector(vanilla, 0x40)[1] != 0


def test_the_wind_blows_the_same_on_the_directions_vanilla_gets_right(vanilla, fixed):
    for direction in (*range(0x00, 0x40, 0x10), *range(0x80, 0xC0, 0x10)):
        assert wind_vector(fixed, direction) == wind_vector(vanilla, direction)


def test_a_quarter_turn_swaps_the_components(fixed):
    """|Y| of a direction is |X| of the direction a quarter turn on, as cos is of sin."""
    for direction in DIRECTIONS:
        _, y = wind_vector(fixed, direction)
        x, _ = wind_vector(fixed, (direction + 0x40) & 0xFF)
        assert abs(y) == abs(x), hex(direction)


def test_opposite_directions_push_opposite_ways(fixed):
    for direction in DIRECTIONS:
        x, y = wind_vector(fixed, direction)
        assert wind_vector(fixed, direction ^ 0x80) == (-x, -y), hex(direction)


def test_each_direction_pushes_toward_its_own_quadrant(fixed):
    """$00 is up the screen, $40 right, $80 down, $C0 left; positive Y is down."""

    def sign(value: int) -> int:
        return (value > 0) - (value < 0)

    for direction in DIRECTIONS:
        x, y = wind_vector(fixed, direction)
        expected_x = 0 if direction in (0x00, 0x80) else (1 if direction < 0x80 else -1)
        expected_y = (
            0
            if direction in (0x40, 0xC0)
            else (-1 if (direction + 0x40) & 0x80 == 0 else 1)
        )
        assert (sign(x), sign(y)) == (expected_x, expected_y), hex(direction)
