"""
The player: the shot they mean to play, how their execution scatters around
it, and where that leaves the ball.

A shot is meant as meter targets, not frames: the power stop the player wants,
and the accuracy stop, where $30 is straight and either side hooks or slices on
purpose. The meters move 1-3 steps a frame, so a target may fall between two
frames: the player means to press on the frame that comes nearest, and misses
that frame by a timing error: normal in frames, rounded to whole
frames, one draw for each press. The accuracy press is aimed at its target on
the meter as the swing actually went, so a late power press does not also
spoil the accuracy. The aim misses by a normal error in aim steps.

The wind is the shot's own: the game deals it at shot setup, before the player
chooses, so the player plays to it (the solver averages over the winds a hole
deals, `golf.physics.wind`). What does vary behind the player's back is the RNG
the physics draws on, sampled at a few fixed states.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from functools import cache

from golf.physics import meter
from golf.physics.flights import Flights
from golf.physics.rules import play_on
from golf.physics.shot import Flag
from golf.physics.state import (
    PERFECT_ACCURACY,
    PUTTER,
    Ground,
    Lie,
    ShotInput,
    Spin,
)
from golf.physics.tables import PhysicsTables

#: Errors are drawn out to this many standard deviations, and renormalised.
ERROR_REACH = 2.0

#: The RNG states each shot is played from, standing for all of them. Two of
#: each parity, as the fairway's first bounce reads the low bit.
RNG_STATES = (0x0001, 0x4E6C, 0x9A3B, 0xD5C2)

#: How much each error is, per unit of skill: a stated assumption, which the
#: calibration's sensitivity runs vary (`docs/planning/hole_difficulty.md`).
POWER_FRAMES_PER_SKILL = 1.0
ACCURACY_FRAMES_PER_SKILL = 1.0
AIM_STEPS_PER_SKILL = 1.0


@dataclass(frozen=True)
class Skill:
    """How far a player's execution scatters, as standard deviations."""

    power: float
    """Of the power press, in frames."""
    accuracy: float
    """Of the accuracy press, in frames."""
    aim: float
    """Of the aim, in aim steps (1/256 of a turn)."""

    @classmethod
    def scaled(cls, scale: float) -> "Skill":
        """One number for all three, in the fixed ratios above; 0 is perfect."""
        return cls(
            scale * POWER_FRAMES_PER_SKILL,
            scale * ACCURACY_FRAMES_PER_SKILL,
            scale * AIM_STEPS_PER_SKILL,
        )


PERFECT = Skill(0.0, 0.0, 0.0)


@dataclass(frozen=True)
class Intent:
    """The shot the player means to play."""

    club: int
    aim: int
    power_target: int
    """The power stop they want: 0 is full power, $30 none."""
    accuracy_target: int = PERFECT_ACCURACY
    """The accuracy stop they want: $30 straight, either side to curve it. Ignored on a putt."""
    swing_speed: int = 1
    """The swing speed, or the putt speed for the putter."""
    hi_lo: int = 0
    spin: Spin = Spin.NORMAL


@dataclass(frozen=True)
class Position:
    """Where a shot is played from."""

    x: int
    """Pixel."""
    y: int
    """Pixel."""
    bunker_depth: int = 0


@dataclass(frozen=True)
class Hole:
    """What a shot on one hole is played against."""

    ground: Ground
    tables: PhysicsTables
    flag: Flag | None
    flights: Flights | None = field(default=None, compare=False, repr=False)
    """
    Flights shared between the shots played here, and with any other hole
    given the same `Flights` (they depend on neither the hole nor the pin).
    Each hole gets its own when none is given.
    """

    def __post_init__(self) -> None:
        if self.flights is None:
            object.__setattr__(self, "flights", Flights(self.tables))


@dataclass(frozen=True)
class Result:
    """How one shot turned out, as the solver needs it."""

    position: Position
    """Where the next shot is played from; meaningless once holed."""
    strokes: int
    """What the shot cost: 1, or 2 with a penalty."""
    holed: bool


HOLED = Result(Position(0, 0), 1, True)


@cache
def errors(deviation: float) -> tuple[tuple[int, float], ...]:
    """A normal error, rounded to whole units, as (error, probability)."""
    if deviation <= 0:
        return ((0, 1.0),)
    reach = math.ceil(ERROR_REACH * deviation)

    def below(x: float) -> float:
        return 0.5 * (1 + math.erf(x / (deviation * math.sqrt(2))))

    weights = [(k, below(k + 0.5) - below(k - 0.5)) for k in range(-reach, reach + 1)]
    total = sum(w for _, w in weights)
    return tuple((k, w / total) for k, w in weights)


def power_press(
    tables: PhysicsTables, swing_speed: int, putting: bool, target: int
) -> int:
    """
    The backswing pass on which the falling power meter shows the stop
    nearest `target`, the earlier of two equally near.
    """

    def stop(press: int) -> int:
        return meter.backswing(tables, swing_speed, putting, press).power_stop

    press = 1
    while stop(press) > target:
        press += 1
    if press > 1 and stop(press - 1) - target <= target - stop(press):
        press -= 1
    return press


def accuracy_press(
    tables: PhysicsTables, swing_speed: int, backswing: meter.Backswing, target: int
) -> int:
    """
    How many passes after the power press the rising accuracy meter shows
    the stop nearest `target`, the earlier of two equally near.
    """
    step = 2 * meter.meter_rate(tables, swing_speed, putting=False)

    def stop(passes: int) -> int:
        return (backswing.power + passes * step) >> 8

    passes = max(1, -(-((target << 8) - backswing.power) // step))
    if passes > 1 and target - stop(passes - 1) <= stop(passes) - target:
        passes -= 1
    return passes


def swings(
    tables: PhysicsTables, intent: Intent, putting: bool, skill: Skill
) -> dict[meter.SwingTiming | None, float]:
    """
    Every swing the player's timing can produce, with its probability. None
    is a whiff: the accuracy meter ran off the end before the second press.
    """
    speed = intent.swing_speed
    aimed_power = power_press(tables, speed, putting, intent.power_target)
    results: dict[meter.SwingTiming | None, float] = {}
    # A putt's backswing starts by itself; any other starts on a press, which
    # the power press must come far enough after to be seen.
    earliest = 1 if putting else meter.MIN_PRESS_GAP
    for power_error, p_power in errors(skill.power):
        pressed = max(earliest, aimed_power + power_error)
        if putting:
            timing = meter.swing(tables, speed, True, pressed)
            results[timing] = results.get(timing, 0.0) + p_power
            continue
        back = meter.backswing(tables, speed, False, pressed)
        aimed = accuracy_press(tables, speed, back, intent.accuracy_target)
        for accuracy_error, p_accuracy in errors(skill.accuracy):
            # The game ignores a press too soon after the last: pressed any
            # sooner, the player's press is the first one it would see.
            gap = max(meter.MIN_PRESS_GAP, aimed + accuracy_error)
            timing = meter.swing(tables, speed, False, pressed, pressed + gap)
            results[timing] = results.get(timing, 0.0) + p_power * p_accuracy
    return results


def outcomes(
    intent: Intent,
    position: Position,
    hole: Hole,
    wind: tuple[int, int],
    skill: Skill,
    rng_states: Sequence[int] = RNG_STATES,
) -> dict[Result, float]:
    """
    Everything `intent` can come to from `position` in `wind`, the
    (`WindDirection`, `WindSpeed`) the shot was dealt, with its probability.
    """
    start = hole.ground.classify(position.x, 0, position.y, 0)
    putting = start.lie == Lie.GREEN
    if putting and intent.club != PUTTER:
        # The setup panels hand the player the putter on the green ($88AE).
        raise ValueError("only the putter can be played from the green")
    shot = ShotInput(
        club=intent.club,
        swing_speed=intent.swing_speed,
        hi_lo=0 if intent.club == PUTTER else intent.hi_lo,
        # The setup panels skip spin on the green; the game launches TOP 2.
        spin=Spin.TOP_2 if putting else intent.spin,
        bunker_depth=position.bunker_depth,
        x=position.x,
        y=position.y,
        wind_direction=wind[0],
        wind_speed=wind[1],
    )
    results: dict[Result, float] = {}

    def add(result: Result, probability: float) -> None:
        results[result] = results.get(result, 0.0) + probability

    for timing, p_timing in swings(hole.tables, intent, putting, skill).items():
        if timing is None:
            # A whiff costs a stroke and leaves the ball where it was.
            add(Result(position, 1, False), p_timing)
            continue
        for aim_error, p_aim in errors(skill.aim):
            aimed = replace(
                shot,
                aim=(intent.aim + aim_error) & 0xFF,
                power_stop=timing.power_stop,
                accuracy_stop=timing.accuracy_stop,
                frames_to_impact=timing.frames_to_impact or 0,
            )
            p = p_timing * p_aim / len(rng_states)
            for rng_state in rng_states:
                add(_result(replace(aimed, rng_state=rng_state), hole), p)
    return results


def _result(shot: ShotInput, hole: Hole) -> Result:
    assert hole.flights is not None
    finished = hole.flights.simulate(shot, hole.ground, hole.flag)
    next_shot = play_on(shot, finished.ball)
    if next_shot.holed:
        return HOLED
    position = Position(next_shot.pixel_x, next_shot.pixel_y, next_shot.bunker_depth)
    return Result(position, next_shot.strokes, False)
