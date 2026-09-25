"""
The swing meters and animation (`golf.physics.meter`) against swings played
through the game: every swing speed, putts, backswings long enough to bounce
and to stop by themselves, and accuracy presses late enough to whiff.
"""

import random
from pathlib import Path

import pytest

from golf.core.rom_reader import RomReader
from golf.physics import PUTTER, PhysicsTables, ShotInput, meter
from golf.physics.rom_game import RomGameShot, Swing, WhiffError

ROM_PATH = "nes_open_us.nes"

pytestmark = pytest.mark.skipif(
    not Path(ROM_PATH).exists(), reason=f"{ROM_PATH} not present"
)


@pytest.fixture(scope="module")
def rom() -> RomReader:
    return RomReader(ROM_PATH)


@pytest.fixture(scope="module")
def physics(rom) -> PhysicsTables:
    return PhysicsTables.from_rom(rom)


#: Where the power press comes: on the way down, after the meter bounces off
#: full power, or after it has climbed back to $30 and stopped by itself.
BACKSWINGS = ("putt", "down", "bounced", "stopped itself")


@pytest.mark.parametrize("backswing", BACKSWINGS)
@pytest.mark.parametrize("seed", range(8))
def test_swing(rom, physics, backswing, seed):
    rng = random.Random(seed)
    putting = backswing == "putt"
    game = RomGameShot(rom, "us", 1)
    flag_x, flag_y = game.flag.x >> 8, game.flag.y >> 8
    shot = ShotInput(
        club=PUTTER if putting else rng.randrange(15),
        swing_speed=rng.randrange(3),
        # Beside the pin for a putt; out on the fairway short of it otherwise.
        x=flag_x + 3 if putting else flag_x,
        y=flag_y if putting else flag_y + 60,
    )
    # Frames for the meter to fall from $30 to 0.
    fall = (meter.METER_START << 8) // meter.meter_rate(
        physics, shot.swing_speed, putting
    )
    power = {
        "putt": rng.randint(5, 2 * fall),
        "down": rng.randint(5, fall),
        "bounced": rng.randint(fall + 2, 2 * fall),
        "stopped itself": rng.randint(2 * fall + 2, 2 * fall + 20),
    }[backswing]
    # Presses at least 5 frames apart, so the game sees each one.
    swing = Swing(rng.randint(5, 8), power, rng.randint(5, 25))
    power_press = swing.start + swing.power - 1 if putting else swing.power
    timing = meter.swing(
        physics, shot.swing_speed, putting, power_press, swing.power + swing.accuracy
    )
    try:
        record = game.play(shot, swing)
    except WhiffError:
        assert timing is None
        return
    assert timing is not None
    launched = record.shot
    assert (timing.power_stop, timing.accuracy_stop) == (
        launched.power_stop,
        launched.accuracy_stop,
    )
    if not putting and timing.frames_to_impact != launched.frames_to_impact:
        # The game can only count while the shot lasts.
        assert launched.frames_to_impact == len(record.frames) - 2
