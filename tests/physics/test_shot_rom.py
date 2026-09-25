"""
The Python shot model against the ROM's own shot loop, frame by frame.

Each case plays one shot twice, in `golf.physics` and in bank 13's
`CalcLaunchVector` under py65, over the same ground, and requires every
physics register to agree after every frame.
"""

import random
from dataclasses import dataclass, fields
from pathlib import Path

import pytest

from golf.core.rom_reader import RomReader
from golf.physics import (
    PUTTER,
    Ball,
    Lie,
    PhysicsTables,
    ShotInput,
    Slope,
    Spin,
    Terrain,
    UniformGround,
)
from golf.physics.launch import hi_lo_offset
from golf.physics.rom_oracle import RomShot
from golf.physics.shot import ShotInFlight

ROM_PATH = "nes_open_us.nes"

pytestmark = pytest.mark.skipif(
    not Path(ROM_PATH).exists(), reason=f"{ROM_PATH} not present"
)


@pytest.fixture(scope="module")
def rom() -> RomReader:
    return RomReader(ROM_PATH)


@pytest.fixture(scope="module")
def tables(rom) -> PhysicsTables:
    return PhysicsTables.from_rom(rom)


@dataclass(frozen=True)
class StripedGround:
    """Bands of terrain across the screen, so a shot crosses lie changes."""

    bands: tuple[Terrain, ...]
    band_height: int

    def classify(self, x: int, x_fraction: int, y: int, y_fraction: int) -> Terrain:
        return self.bands[(y // self.band_height) % len(self.bands)]

    def probe(self, ball: Ball) -> Terrain:
        return self.classify(ball.pixel_x, 0, ball.pixel_y, 0)


def random_terrain(rng: random.Random, lie: Lie) -> Terrain:
    if lie == Lie.ROUGH:
        return Terrain(lie, rough_depth=rng.randrange(2))
    if lie == Lie.GREEN:
        return Terrain(
            lie,
            green_flags=rng.choice([0x00, 0x40, 0x80, 0xC0]),
            slope=Slope.of(
                rng.choice([0, 10, 20, 30, 0x40]),
                rng.random() < 0.5,
                rng.choice([0, 10, 20, 30, 0x40]),
                rng.random() < 0.5,
            ),
        )
    return Terrain(lie)


LANDING_LIES = [
    Lie.FAIRWAY,
    Lie.ROUGH,
    Lie.BUNKER,
    Lie.WATER,
    Lie.GREEN,
    Lie.OUT_OF_BOUNDS,
]
LAUNCH_LIES = [Lie.TEE, Lie.FAIRWAY, Lie.ROUGH, Lie.BUNKER, Lie.GREEN]


def random_case(seed: int):
    rng = random.Random(seed)
    club = rng.choice([*range(15), PUTTER])
    shot = ShotInput(
        club=club,
        swing_speed=rng.randrange(3),
        power_stop=rng.choice([0, 0, 1, 5, 9, 10, rng.randrange(0x31)]),
        accuracy_stop=rng.choice([0x30, 0x30, rng.randrange(0x4C)]),
        hi_lo=rng.choice([-1, 0, 1]),
        spin=Spin(rng.randrange(5)),
        aim=rng.randrange(256),
        wind_direction=rng.choice([rng.randrange(16) * 0x10, rng.randrange(256)]),
        wind_speed=rng.randrange(10),
        rng_state=rng.randrange(1, 0x10000),
        bunker_depth=rng.randrange(3),
        x=rng.randrange(40, 136),
        y=rng.randrange(0x200, 0x400),
    )
    launch = random_terrain(rng, rng.choice(LAUNCH_LIES))
    if rng.random() < 0.5:
        ground = UniformGround(random_terrain(rng, rng.choice(LANDING_LIES)))
    else:
        bands = tuple(
            random_terrain(rng, rng.choice(LANDING_LIES))
            for _ in range(rng.randint(2, 4))
        )
        ground = StripedGround(bands, rng.choice([8, 24, 64]))
    return shot, ground, launch


def differences(model: Ball, rom: Ball) -> dict:
    return {
        f.name: (getattr(model, f.name), getattr(rom, f.name))
        for f in fields(Ball)
        if f.compare and getattr(model, f.name) != getattr(rom, f.name)
    }


def play_both(rom, tables, shot, ground, launch):
    # The oracle runs CalcLaunchVector alone, in the overhead view ($98 = 0).
    flight = ShotInFlight(shot, ground, tables, launch, view=0)
    oracle = RomShot(rom, shot, ground, launch, hi_lo_offset(shot, tables))
    oracle.step_frame()  # the ROM's first frame is the launch
    assert differences(flight.ball, oracle.ball()) == {}, "launch"
    while not flight.ball.stopped:
        flight.step()
        oracle.step_frame()
        diff = differences(flight.ball, oracle.ball())
        assert diff == {}, f"frame {flight.ball.frames}: {diff}"
    assert oracle.stopped


@pytest.mark.parametrize("club", [*range(15), PUTTER])
@pytest.mark.parametrize("launch_lie", [Lie.TEE, Lie.FAIRWAY, Lie.ROUGH, Lie.GREEN])
def test_full_power_straight_shot(rom, tables, club, launch_lie):
    shot = ShotInput(club=club, rng_state=0x1234)
    ground = UniformGround(Terrain(Lie.FAIRWAY))
    play_both(rom, tables, shot, ground, Terrain(launch_lie))


@pytest.mark.parametrize("seed", range(400))
def test_random_shot(rom, tables, seed):
    shot, ground, launch = random_case(seed)
    play_both(rom, tables, shot, ground, launch)
