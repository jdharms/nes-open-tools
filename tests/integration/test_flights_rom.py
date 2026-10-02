"""
Shared flights (`golf.physics.flights`) give exactly what `simulate` gives,
from any start, over real holes.
"""

import math
import random
from dataclasses import replace
from pathlib import Path

import pytest

from golf.core.rom_reader import RomReader
from golf.formats.hole_data import HoleData
from golf.physics import (
    PUTTER,
    Ball,
    Flag,
    HoleGround,
    Lie,
    PhysicsTables,
    ShotInput,
    Spin,
    Terrain,
    TerrainTables,
    meter,
    simulate,
)
from golf.physics.flights import Flight, Flights, shareable

ROM_PATH = "nes_open_us.nes"
COURSES = ("japan", "us", "uk")
#: Starts each flight is finished from.
STARTS = 24

pytestmark = pytest.mark.skipif(
    not Path(ROM_PATH).exists(), reason=f"{ROM_PATH} not present"
)


@pytest.fixture(scope="module")
def tables() -> PhysicsTables:
    return PhysicsTables.from_rom(RomReader(ROM_PATH))


@pytest.fixture(scope="module")
def terrain_tables() -> TerrainTables:
    return TerrainTables.from_rom(RomReader(ROM_PATH))


def _hole(vanilla_courses: Path, course: str, number: int) -> HoleData:
    hole = HoleData()
    hole.load(vanilla_courses / course / f"hole_{number:02}.json")
    return hole


def _pixels(ground: HoleGround) -> list[tuple[int, int, Terrain]]:
    return [
        (x, y, ground.classify(x, 0, y, 0))
        for y in range(ground.bottom_y)
        for x in range(0xB0)
    ]


def _shot(rng: random.Random, tables: PhysicsTables, hole: HoleData, x: int, y: int):
    """A random full or part swing, aimed about at the green."""
    speed = rng.randrange(3)
    while True:
        power = rng.randrange(3, 30)
        timing = meter.swing(tables, speed, False, power, power + rng.randrange(3, 25))
        if timing is not None:
            break
    to_green = math.atan2(hole.green_x + 12 - x, y - hole.green_y - 12)
    aim = round(to_green * 128 / math.pi) + rng.randrange(-20, 21)
    return ShotInput(
        club=rng.randrange(15),
        swing_speed=speed,
        power_stop=timing.power_stop,
        accuracy_stop=timing.accuracy_stop,
        frames_to_impact=timing.frames_to_impact or 0,
        hi_lo=rng.choice((-1, 0, 1)),
        spin=Spin(rng.randrange(5)),
        aim=aim & 0xFF,
        wind_direction=rng.randrange(16) << 4,
        wind_speed=rng.randrange(13),
        rng_state=rng.randrange(1, 0x10000),
        x=x,
        y=y,
    )


@pytest.mark.parametrize("number", range(1, 19))
@pytest.mark.parametrize("course", COURSES)
def test_a_flight_finishes_like_simulate(
    course, number, tables, terrain_tables, vanilla_courses
):
    hole = _hole(vanilla_courses, course, number)
    ground = HoleGround(hole, terrain_tables)
    rng = random.Random(f"{course} {number}")
    pixels = _pixels(ground)
    for lie in (Lie.FAIRWAY, Lie.ROUGH, Lie.TEE):
        lies = [p for p in pixels if p[2].lie == lie]
        if not lies:
            continue
        x, y, terrain = rng.choice(lies)
        shot = _shot(rng, tables, hole, x, y)
        flight = Flight(shot, terrain, tables)
        like = [(x, y) for x, y, t in pixels if t == terrain]
        for x, y in rng.sample(like, min(STARTS, len(like))):
            rng_state = (
                shot.rng_state if lie == Lie.ROUGH else rng.randrange(1, 0x10000)
            )
            flag = Flag.for_pin(hole, rng.randrange(4))
            moved = replace(shot, x=x, y=y, rng_state=rng_state)
            want = simulate(moved, ground, tables, flag=flag)
            assert flight.finish(x, y, rng_state, ground, flag) == want, moved


def test_starts_take_whole_shots_or_parts(tables, terrain_tables, vanilla_courses):
    """
    From the US 1st's fairway, a 5-iron straight up the hole. Some starts take
    the whole shot as recorded, some break off during the roll, some take the
    flight but land on or by the green, and some break off in the air, where
    the ball comes down over the green.
    """
    hole = _hole(vanilla_courses, "us", 1)
    ground = HoleGround(hole, terrain_tables)
    flag = Flag.for_pin(hole, 0)
    fairway = [(x, y) for x, y, t in _pixels(ground) if t == Terrain(Lie.FAIRWAY)]
    x, y = fairway[0]
    shot = ShotInput(club=8, aim=0, frames_to_impact=10, wind_speed=4, x=x, y=y)
    flight = Flight(shot, Terrain(Lie.FAIRWAY), tables)
    kinds: dict[str, list[tuple[int, int]]] = {}
    for x, y in fairway:
        shared = flight.shared(x, y, shot.rng_state, ground)
        if shared < flight.air_frames:
            kind = "air"
        elif shared == flight.air_frames:
            kind = "landing"
        else:
            finished = flight.finish(x, y, shot.rng_state, ground, flag)
            kind = "whole" if shared == finished.ball.frames else "roll"
        kinds.setdefault(kind, []).append((x, y))
    assert set(kinds) == {"air", "landing", "roll", "whole"}
    for starts in kinds.values():
        for x, y in starts[:: len(starts) // 3 + 1]:
            moved = replace(shot, x=x, y=y)
            want = simulate(moved, ground, tables, flag=flag)
            assert flight.finish(x, y, shot.rng_state, ground, flag) == want


#: Found by search: the view goes overhead while the ball is still rising,
#: over the green, so the game goes to the green view instead, and the ball is
#: still over the green when it comes down.
RISING_OVER_THE_GREEN = [
    ("japan", 17, ShotInput(14, 0, 3, hi_lo=1, aim=253, wind_direction=0x40,
                            wind_speed=10, x=102, y=101, frames_to_impact=17)),
    ("japan", 1, ShotInput(14, 0, 5, hi_lo=-1, aim=251, wind_direction=0x80,
                           wind_speed=11, x=80, y=82, frames_to_impact=12)),
    ("uk", 4, ShotInput(13, 0, 5, hi_lo=1, aim=250, wind_direction=0x90,
                        wind_speed=12, x=78, y=100, frames_to_impact=19)),
    ("japan", 5, ShotInput(11, 0, 4, hi_lo=1, aim=0, wind_direction=0x80,
                           wind_speed=11, x=126, y=72, frames_to_impact=11)),
]  # fmt: skip


@pytest.mark.parametrize(("course", "number", "shot"), RISING_OVER_THE_GREEN)
def test_the_view_can_go_to_the_green_while_rising(
    course, number, shot, tables, terrain_tables, vanilla_courses
):
    hole = _hole(vanilla_courses, course, number)
    ground = HoleGround(hole, terrain_tables)
    flag = Flag.for_pin(hole, 0)
    shot = replace(shot, rng_state=0x1234)
    # Recorded from elsewhere on the hole, so the start is not the recording's.
    flight = Flight(replace(shot, x=shot.x - 1), Terrain(Lie.FAIRWAY), tables)
    want = simulate(shot, ground, tables, flag=flag)
    assert flight.finish(shot.x, shot.y, shot.rng_state, ground, flag) == want


@pytest.mark.parametrize(
    ("lie", "club"),
    [(Lie.BUNKER, 5), (Lie.GREEN, PUTTER), (Lie.FAIRWAY, PUTTER)],
)
def test_some_shots_are_not_shared(tables, lie, club):
    shot = ShotInput(club=club)
    assert not shareable(shot, Terrain(lie))
    with pytest.raises(ValueError):
        Flight(shot, Terrain(lie), tables)


def test_flights_are_shared_between_starts_and_rng_states(
    tables, terrain_tables, vanilla_courses
):
    hole = _hole(vanilla_courses, "us", 1)
    ground = HoleGround(hole, terrain_tables)
    flag = Flag.for_pin(hole, 0)
    flights = Flights(tables)
    fairway = [
        (x, y)
        for x, y, t in _pixels(ground)
        if t == Terrain(Lie.FAIRWAY) and 150 <= y < 200
    ]
    shot = ShotInput(club=8, aim=0x02, frames_to_impact=10, wind_speed=3)
    for x, y in fairway[::40]:
        for rng_state in (0x0001, 0x4E6C):
            moved = replace(shot, x=x, y=y, rng_state=rng_state)
            assert flights.simulate(moved, ground, flag) == simulate(
                moved, ground, tables, flag=flag
            )
    assert flights.flown == 1
    assert flights.shared == 2 * len(fairway[::40]) - 1


def test_flights_play_what_they_cannot_share(tables, terrain_tables, vanilla_courses):
    hole = _hole(vanilla_courses, "us", 1)
    ground = HoleGround(hole, terrain_tables)
    flag = Flag.for_pin(hole, 0)
    flights = Flights(tables)
    shot = ShotInput(club=PUTTER, x=flag.x >> 8, y=(flag.y >> 8) + 6)
    assert ground.probe(Ball(x=shot.x << 16, y=shot.y << 16)).lie == Lie.GREEN
    assert flights.simulate(shot, ground, flag) == simulate(
        shot, ground, tables, flag=flag
    )
    assert flights.flown == 0
