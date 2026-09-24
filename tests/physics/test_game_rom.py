"""
The model against the game itself, on real holes.

Each case plays one shot through the game's own frame loop (`RomGameShot`: the
setup panels, the swing, the behind-the-golfer scene, the view switches, trees,
sand and all) from a random lie on a random vanilla hole, then replays it in the
model from the inputs the swing produced, over `HoleGround`, and requires every
register to agree after every frame.

A shot that reaches the cup, which the model does not port yet, must match up
to the frame the model refuses on.
"""

import math
import random
from dataclasses import fields
from pathlib import Path

import pytest

from golf.core.rom_reader import RomReader
from golf.formats.hole_data import HoleData
from golf.physics import (
    PUTTER,
    Ball,
    HoleGround,
    Lie,
    PhysicsTables,
    ShotInput,
    Spin,
    TerrainTables,
    UnportedBehaviourError,
)
from golf.physics.rom_game import RomGameShot, Swing, WhiffError
from golf.physics.shot import ShotInFlight

ROM_PATH = "nes_open_us.nes"
COURSES = ["japan", "us", "uk"]
PLAYABLE = (Lie.FAIRWAY, Lie.TEE, Lie.ROUGH, Lie.BUNKER, Lie.GREEN)

#: Registers the game leaves over from before the shot, which the model cannot
#: know: scratch bytes other code uses, and readouts not yet recomputed.
CARRIED_FROM_LAUNCH = (
    "wind_x",
    "wind_y",
    "rough_depth",
    "green_flags",
    "shot_distance",
    "scene_depth",
    "tree_hit",
    "tree_hit_seen",
)

pytestmark = pytest.mark.skipif(
    not Path(ROM_PATH).exists(), reason=f"{ROM_PATH} not present"
)


@pytest.fixture(scope="module")
def rom() -> RomReader:
    return RomReader(ROM_PATH)


@pytest.fixture(scope="module")
def tables(rom) -> tuple[PhysicsTables, TerrainTables]:
    return PhysicsTables.from_rom(rom), TerrainTables.from_rom(rom)


def differences(model: Ball, rom: Ball) -> dict:
    return {
        f.name: (getattr(model, f.name), getattr(rom, f.name))
        for f in fields(Ball)
        if f.compare and getattr(model, f.name) != getattr(rom, f.name)
    }


def random_shot(rng: random.Random, hole: HoleData, ground: HoleGround):
    """A shot from a random playable spot, aimed roughly at the green."""
    while True:
        x = rng.randrange(8, 168)
        y = rng.randrange(8, hole.terrain_height * 8 - 8)
        lie = ground.classify(x, 0, y, 0).lie
        if lie in PLAYABLE:
            break
    to_green = math.atan2(hole.green_x + 12 - x, y - hole.green_y - 12)
    aim = round(to_green * 128 / math.pi + rng.uniform(-40, 40)) & 0xFF
    shot = ShotInput(
        club=PUTTER if lie == Lie.GREEN else rng.randrange(15),
        swing_speed=rng.randrange(3),
        hi_lo=rng.choice([-1, 0, 1]),
        spin=Spin(rng.randrange(5)),
        aim=aim,
        wind_direction=rng.randrange(16) * 0x10,
        wind_speed=rng.randrange(10),
        rng_state=rng.randrange(1, 0x10000),
        bunker_depth=rng.randrange(3),
        x=x,
        y=y,
    )
    swing = Swing(rng.randint(2, 8), rng.randint(15, 45), rng.randint(6, 18))
    return shot, swing


@pytest.mark.parametrize("seed", range(64))
def test_random_shot_on_a_real_hole(rom, tables, vanilla_courses, seed):
    physics, terrain = tables
    rng = random.Random(seed)
    course, number = rng.choice(COURSES), rng.randint(1, 18)
    hole = HoleData()
    hole.load(vanilla_courses / course / f"hole_{number:02}.json")
    ground = HoleGround(hole, terrain)
    shot, swing = random_shot(rng, hole, ground)

    try:
        record = RomGameShot(rom, course, number).play(shot, swing)
    except WhiffError:
        pytest.skip("the swing ran the accuracy meter off the end")

    flight = ShotInFlight(
        record.shot, ground, physics, scene=record.scene, flag=record.flag
    )
    for name in CARRIED_FROM_LAUNCH:
        setattr(flight.ball, name, getattr(record.frames[0], name))
    assert differences(flight.ball, record.frames[0]) == {}, "launch"
    try:
        for frame, rom_ball in enumerate(record.frames[1:], 1):
            flight.step()
            diff = differences(flight.ball, rom_ball)
            assert diff == {}, (
                f"frame {frame} (view ${record.view_modes[frame]:02X}): {diff}"
            )
    except UnportedBehaviourError as error:
        assert "cup" in str(error)
