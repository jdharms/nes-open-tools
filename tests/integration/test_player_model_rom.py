"""The player model (`golf.difficulty.player`), over the physics read from the ROM."""

import random
from pathlib import Path

import pytest

from golf.core.rom_reader import RomReader
from golf.difficulty.player import (
    HOLED,
    PERFECT,
    Hole,
    Intent,
    Position,
    Result,
    Skill,
    accuracy_press,
    errors,
    outcomes,
    power_press,
    swings,
)
from golf.formats.hole_data import HoleData
from golf.physics import (
    PUTTER,
    Flag,
    HoleGround,
    Lie,
    PhysicsTables,
    ShotInput,
    Terrain,
    TerrainTables,
    UniformGround,
    meter,
    play_on,
    simulate,
)

ROM_PATH = "nes_open_us.nes"
CALM = (0x60, 0)

pytestmark = pytest.mark.skipif(
    not Path(ROM_PATH).exists(), reason=f"{ROM_PATH} not present"
)


@pytest.fixture(scope="module")
def tables() -> PhysicsTables:
    return PhysicsTables.from_rom(RomReader(ROM_PATH))


@pytest.fixture(scope="module")
def fairway(tables) -> Hole:
    return Hole(UniformGround(Terrain(Lie.FAIRWAY)), tables, None)


def test_errors():
    assert errors(0) == ((0, 1.0),)
    spread = dict(errors(1.0))
    assert sorted(spread) == list(range(-3, 4))
    assert sum(spread.values()) == pytest.approx(1)
    assert all(spread[k] == pytest.approx(spread[-k]) for k in spread)
    assert spread[0] > spread[1] > spread[2] > spread[3]


@pytest.mark.parametrize("putting", [False, True])
@pytest.mark.parametrize("speed", range(3))
def test_power_press_comes_nearest_the_target(tables, speed, putting):
    def stop(press: int) -> int:
        return meter.backswing(tables, speed, putting, press).power_stop

    for target in range(0x31):
        press = power_press(tables, speed, putting, target)
        miss = abs(stop(press) - target)
        # Nearest of the frames on the way down, which end at the bounce,
        # and the earliest of any equally near.
        for other in range(1, press + 3):
            if other != press and stop(other) <= stop(max(other - 1, 1)):
                assert abs(stop(other) - target) > miss - (other > press)


@pytest.mark.parametrize("speed", range(3))
def test_accuracy_press_comes_nearest_the_target(tables, speed):
    rng = random.Random(speed)
    for _ in range(50):
        power = rng.randrange(5, 30)
        back = meter.backswing(tables, speed, False, power)
        target = rng.randrange(back.power_stop + 1, 0x46)
        gap = accuracy_press(tables, speed, back, target)

        def stop(passes: int, power: int = power) -> int:
            timing = meter.swing(tables, speed, False, power, power + passes)
            assert timing is not None
            return timing.accuracy_stop

        miss = abs(stop(gap) - target)
        if gap > 1:
            assert abs(stop(gap - 1) - target) > miss
        assert abs(stop(gap + 1) - target) >= miss


def test_a_perfect_player_hits_the_targets(tables):
    """Medium speed moves the accuracy meter 2.625 a frame, so one within 1."""
    intent = Intent(club=5, aim=0, power_target=0x08, accuracy_target=0x2C)
    (timing,) = swings(tables, intent, False, PERFECT)
    assert timing is not None
    assert timing.power_stop == 0x08
    assert abs(timing.accuracy_stop - 0x2C) <= 1


def test_outcomes_are_the_physics(tables, fairway):
    """With no error, the outcome is `simulate`'s."""
    intent = Intent(club=5, aim=0x10, power_target=0x04)
    start = Position(88, 0x300)
    results = outcomes(intent, start, fairway, (0x20, 5), PERFECT, [0x1234])
    (timing,) = swings(tables, intent, False, PERFECT)
    assert timing is not None
    shot = ShotInput(
        club=5,
        aim=0x10,
        power_stop=timing.power_stop,
        accuracy_stop=timing.accuracy_stop,
        frames_to_impact=timing.frames_to_impact or 0,
        wind_direction=0x20,
        wind_speed=5,
        rng_state=0x1234,
        x=88,
        y=0x300,
    )
    rest = play_on(shot, simulate(shot, fairway.ground, tables).ball)
    expected = Result(Position(rest.pixel_x, rest.pixel_y), 1, False)
    assert results == {expected: pytest.approx(1)}


def test_error_spreads_the_outcomes(fairway):
    intent = Intent(club=5, aim=0, power_target=0x04)
    start = Position(88, 0x300)
    # One RNG state and a small error keep this to a few hundred shots.
    perfect = outcomes(intent, start, fairway, CALM, PERFECT, [0x1234])
    shaky = outcomes(intent, start, fairway, CALM, Skill.scaled(0.5), [0x1234])
    assert sum(shaky.values()) == pytest.approx(1)
    assert len(perfect) == 1
    assert len(shaky) > 10


def test_a_late_accuracy_press_whiffs(fairway):
    intent = Intent(club=5, aim=0, power_target=0x10, accuracy_target=0x4C)
    start = Position(88, 0x300)
    assert outcomes(intent, start, fairway, CALM, PERFECT) == {
        Result(start, 1, False): pytest.approx(1)
    }


def test_putts_hole_out(tables, vanilla_courses):
    hole_data = HoleData()
    hole_data.load(vanilla_courses / "us" / "hole_01.json")
    flag = Flag.for_pin(hole_data, 0)
    hole = Hole(
        HoleGround(hole_data, TerrainTables.from_rom(RomReader(ROM_PATH))), tables, flag
    )
    # Four pixels short of the pin, putting up the screen at it.
    start = Position(flag.x >> 8, (flag.y >> 8) + 4)
    holed = [
        outcomes(Intent(PUTTER, aim=0, power_target=power), start, hole, CALM, PERFECT)
        for power in range(0x31)
    ]
    assert any(HOLED in results for results in holed)


def test_only_the_putter_on_the_green(tables, vanilla_courses):
    hole_data = HoleData()
    hole_data.load(vanilla_courses / "us" / "hole_01.json")
    flag = Flag.for_pin(hole_data, 0)
    hole = Hole(
        HoleGround(hole_data, TerrainTables.from_rom(RomReader(ROM_PATH))), tables, flag
    )
    start = Position(flag.x >> 8, (flag.y >> 8) + 4)
    with pytest.raises(ValueError):
        outcomes(Intent(12, aim=0, power_target=0x20), start, hole, CALM, PERFECT)
