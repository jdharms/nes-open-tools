"""
The model against the game itself, on real holes.

Each case plays one shot through the game's own frame loop (`RomGameShot`: the
setup panels, the swing, the behind-the-golfer scene, the view switches, trees,
sand and all) from a random lie on a random vanilla hole, then replays it in the
model from the inputs the swing produced, over `HoleGround`, and requires every
register to agree after every frame. The game then plays on into its play
loop, and where it puts the ball for the next shot, and what the shot cost,
must agree with `play_on`.

Random shots rarely reach the cup, so a second set is played at the flag from
close by: putts, and chips with the wedges. The model picks, from swings it
predicts will reach the cup, one with the rarest outcome, and each case names
the outcome the game must produce, so every way of finishing at the cup stays
covered.
"""

import math
import random
from collections.abc import Iterable
from dataclasses import fields, replace
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
    meter,
    play_on,
)
from golf.physics.rom_game import RomGameShot, RomShotRecord, Swing, WhiffError
from golf.physics.shot import VIEW_CUP, Flag, ShotInFlight

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
    "cup_last_x",
    "cup_last_y",
    "cup_entry_y",
)

#: Where each `test_shot_at_the_flag` case must finish (see `outcome`). Seeds
#: found by running it over the first 184; a change to `shot_at_the_flag` or to
#: the model near the cup can move them, and they are found again the same way.
AT_THE_FLAG_CASES = {
    **dict.fromkeys((46, 63, 83, 110, 121), "holed"),
    **dict.fromkeys((7, 25, 32, 37, 47), "rim-in"),
    **dict.fromkeys((0, 4, 6, 23, 29), "lip-out"),
    **dict.fromkeys((101, 148, 183), "flagstick"),
    **dict.fromkeys((2, 5, 20), "past the cup"),
    **dict.fromkeys((1, 3, 8), "missed the cup"),
}

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


def outcome(frames: Iterable[Ball]) -> str:
    """How a shot ended, as far as the cup is concerned."""
    frames = list(frames)
    last = frames[-1]
    if last.holed:
        rim_in = last.cup_drop or last.cup_slow_motion == 1
        return "rim-in" if rim_in else "holed"
    if any(ball.cup_slow_motion == 0xFF for ball in frames):
        return "lip-out"
    if any(ball.flagstick for ball in frames):
        return "flagstick"
    if any(ball.view == VIEW_CUP for ball in frames):
        return "past the cup"
    return "missed the cup"


#: Rarest first: what `shot_at_the_flag` prefers.
OUTCOMES = (
    "rim-in",
    "flagstick",
    "lip-out",
    "holed",
    "past the cup",
    "missed the cup",
)


def replay(record: RomShotRecord, ground: HoleGround, physics: PhysicsTables) -> None:
    """
    Play the game's shot in the model, requiring every frame to agree, and
    then where the next shot is played from.
    """
    flight = ShotInFlight(
        record.shot, ground, physics, scene=record.scene, flag=record.flag
    )
    for name in CARRIED_FROM_LAUNCH:
        setattr(flight.ball, name, getattr(record.frames[0], name))
    assert differences(flight.ball, record.frames[0]) == {}, "launch"
    for frame, rom_ball in enumerate(record.frames[1:], 1):
        flight.step()
        diff = differences(flight.ball, rom_ball)
        assert diff == {}, (
            f"frame {frame} (view ${record.view_modes[frame]:02X}): {diff}"
        )
    after = record.after
    assert after is not None, "the game did not play on after the shot"
    next_shot = play_on(record.shot, flight.ball)
    game = (after.x, after.y, after.bunker_depth, record.strokes, bool(after.holed))
    model = (
        next_shot.x,
        next_shot.y,
        next_shot.bunker_depth,
        next_shot.strokes,
        next_shot.holed,
    )
    assert model == game, "next shot"


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
        record = RomGameShot(rom, course, number).play(shot, swing, follow_through=True)
    except WhiffError:
        assert (
            meter.swing(
                physics, shot.swing_speed, shot.club == PUTTER, *presses(shot, swing)
            )
            is None
        )
        pytest.skip("the swing ran the accuracy meter off the end")
    check_swing(physics, swing, record)
    replay(record, ground, physics)


def presses(shot: ShotInput, swing: Swing) -> tuple[int, int]:
    """
    The backswing passes `RomGameShot` presses A on for `swing`. A putt's
    backswing starts on the swing loop's first pass rather than on a press.
    """
    if shot.club == PUTTER:
        return swing.start + swing.power - 1, swing.start + swing.power - 1
    return swing.power, swing.power + swing.accuracy


def check_swing(physics: PhysicsTables, swing: Swing, record: RomShotRecord) -> None:
    """The meters and the swing animation, against what the game launched."""
    shot = record.shot
    timing = meter.swing(
        physics, shot.swing_speed, shot.club == PUTTER, *presses(shot, swing)
    )
    assert timing is not None, "the model whiffs"
    assert (timing.power_stop, timing.accuracy_stop) == (
        shot.power_stop,
        shot.accuracy_stop,
    )
    if timing.frames_to_impact != shot.frames_to_impact:
        # The game can only count while the shot lasts.
        flight = len(record.frames) - 2
        assert (timing.frames_to_impact or flight) >= flight == shot.frames_to_impact


def shot_at_the_flag(
    rng: random.Random,
    ground: HoleGround,
    flag: Flag,
    physics: PhysicsTables,
) -> tuple[ShotInput, Swing]:
    """
    A putt from the green or a wedge from off it, close to the flag and aimed
    at it, with the swing whose outcome in the model is the rarest. Presses
    come at least 5 frames apart, as the game needs to see each one.
    """
    fx, fy = flag.x >> 8, flag.y >> 8
    putt = rng.random() < 0.6
    while True:
        distance = rng.uniform(3, 20) if putt else rng.uniform(15, 45)
        bearing = rng.uniform(0, 2 * math.pi)
        x = round(fx + distance * math.sin(bearing))
        y = round(fy + distance * math.cos(bearing))
        if not 0 < x < 176 or y <= 0:
            continue
        lie = ground.classify(x, 0, y, 0).lie
        if lie == Lie.GREEN if putt else lie in (Lie.FAIRWAY, Lie.ROUGH):
            break
    to_flag = math.atan2(fx - x, y - fy) * 128 / math.pi
    shot = ShotInput(
        club=PUTTER if putt else rng.randrange(11, 15),
        swing_speed=rng.randrange(3),
        hi_lo=rng.choice([-1, 0, 1]),
        # A putt launches with the spin the setup panels leave, TOP 2.
        spin=Spin.TOP_2 if putt else Spin(rng.randrange(5)),
        aim=round(to_flag + rng.uniform(-2, 2)) & 0xFF,
        wind_direction=rng.randrange(16) * 0x10,
        wind_speed=rng.randrange(3),
        rng_state=rng.randrange(1, 0x10000),
        x=x,
        y=y,
    )
    start = rng.randint(5, 8)

    swings: dict[str, list[Swing]] = {}
    for power in range(5, 200 if putt else 110):
        for accuracy in [5] if putt else range(5, 30):
            swing = Swing(start, power, accuracy)
            timing = meter.swing(physics, shot.swing_speed, putt, *presses(shot, swing))
            if timing is None or abs(timing.accuracy_stop - 0x30) > 3 and not putt:
                continue
            played = replace(
                shot,
                power_stop=timing.power_stop,
                accuracy_stop=timing.accuracy_stop,
                frames_to_impact=timing.frames_to_impact or 0,
            )
            flight = ShotInFlight(played, ground, physics, flag=flag)
            frames = [replace(flight.ball)]
            while not flight.ball.stopped:
                flight.step()
                frames.append(replace(flight.ball))
            swings.setdefault(outcome(frames), []).append(swing)
    rarest = next(kind for kind in OUTCOMES if kind in swings)
    return shot, rng.choice(swings[rarest])


@pytest.mark.parametrize(("seed", "expected"), AT_THE_FLAG_CASES.items())
def test_shot_at_the_flag(rom, tables, vanilla_courses, seed, expected):
    physics, terrain = tables
    rng = random.Random(seed)
    course, number = rng.choice(COURSES), rng.randint(1, 18)
    hole = HoleData()
    hole.load(vanilla_courses / course / f"hole_{number:02}.json")
    ground = HoleGround(hole, terrain)
    game = RomGameShot(rom, course, number)
    shot, swing = shot_at_the_flag(rng, ground, game.flag, physics)

    record = game.play(shot, swing, follow_through=True)
    assert outcome(record.frames) == expected
    check_swing(physics, swing, record)
    replay(record, ground, physics)
