"""
The wind model against the ROM's own code: `InitHole` dealing the pin and the
wind anchors, and `WindAdjustmentRoutine` dealing each shot's wind.
"""

import random
from pathlib import Path

import pytest

from golf.core.patches.seeded_wind import predict_hole, wind_adjust
from golf.core.rom_reader import RomReader
from golf.formats.hole_data import HoleData
from golf.physics.nes import NesMachine
from golf.physics.rom_game import RomGameShot
from golf.physics.rom_oracle import RNG_STATE, WIND_DIRECTION, WIND_SPEED
from golf.physics.shot import Flag
from golf.physics.wind import DEGENERATE_STATES

ROM_PATH = "nes_open_us.nes"
COURSES = ["japan", "us", "uk"]

WIND_ADJUSTMENT_ROUTINE = 0xDA25
WIND_DIRECTION_ANCHOR = 0x012F
WIND_SPEED_ANCHOR = 0x0130

pytestmark = pytest.mark.skipif(
    not Path(ROM_PATH).exists(), reason=f"{ROM_PATH} not present"
)


@pytest.fixture(scope="module")
def rom() -> RomReader:
    return RomReader(ROM_PATH)


def random_states(rng: random.Random, count: int) -> list[int]:
    states = []
    while len(states) < count:
        state = rng.randrange(0x10000)
        if state not in DEGENERATE_STATES:
            states.append(state)
    return states


@pytest.mark.parametrize("seed", range(6))
def test_init_hole_deals_the_pin_and_anchors(rom, vanilla_courses, seed):
    """
    The pin's flag, the anchors, and the RNG afterwards (so exactly three
    draws), for random starting states.
    """
    rng = random.Random(seed)
    course, number = rng.choice(COURSES), rng.randint(1, 18)
    hole_data = HoleData()
    hole_data.load(vanilla_courses / course / f"hole_{number:02}.json")
    for state in random_states(rng, 12):
        game = RomGameShot(rom, course, number, rng_state=state)
        m = game.machine.memory
        hole = predict_hole(state, swings=0)
        rom_anchors = (m[WIND_DIRECTION_ANCHOR], m[WIND_SPEED_ANCHOR])
        assert rom_anchors == (hole.direction_anchor, hole.speed_anchor)
        assert m[RNG_STATE] | m[RNG_STATE + 1] << 8 == hole.slot_state
        assert game.flag == Flag.for_pin(hole_data, hole.pin_index)


def test_wind_adjustment_routine(rom):
    """Every anchor pair, with RNG states that give every jitter."""
    machine = NesMachine(rom)
    m = machine.memory
    rng = random.Random(0)
    for direction in range(0, 0x100, 0x10):
        for speed in range(11):
            for state in random_states(rng, 16):
                m[WIND_DIRECTION_ANCHOR], m[WIND_SPEED_ANCHOR] = direction, speed
                m[RNG_STATE], m[RNG_STATE + 1] = state & 0xFF, state >> 8
                machine.call(WIND_ADJUSTMENT_ROUTINE)
                game = (
                    m[RNG_STATE] | m[RNG_STATE + 1] << 8,
                    m[WIND_DIRECTION],
                    m[WIND_SPEED],
                )
                assert game == wind_adjust(state, direction, speed), (
                    f"anchors ${direction:02X}/{speed}, state ${state:04X}"
                )
