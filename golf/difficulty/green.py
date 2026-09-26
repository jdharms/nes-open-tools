"""
A green solved whole: the expected strokes from every pixel of it, at any
skill, from one table of putts each played once.

A putt from the green reads the RNG only if it runs into sand or water, and
feels no wind: wind acts on air frames alone, a putt never leaves the ground,
and on the green the probe writes the slope over the wind registers
(`Ball.observe`). So a putt's result depends on nothing but the pixel it starts
from, the putt speed, the power stop and the aim, and the frame A is pressed on
decides the stop (`meter.swing`). `build_pixel` plays every speed, every stop
and every aim within `AIM_WINDOW` steps of the pin line from one pixel, and
the player's errors, a few frames either way on the press and a few steps on
the aim, are other entries of the same table.

`GreenSolver` then values the green by value iteration over lookups alone:
E(p) is the least, over every speed, aimed press and aim, of the average over
the errors of strokes + E(where the putt stops), with E = 0 in the cup. Where a
putt leaves the green, the caller says what the rest of the hole is worth.
"""

import hashlib
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import numpy as np

from golf.difficulty.landing import power_targets
from golf.difficulty.player import (
    EVERY_UNIT,
    HOLED,
    RNG_STATES,
    Hole,
    Intent,
    Position,
    Result,
    Skill,
    errors,
    power_press,
    shot_result,
)
from golf.physics import meter
from golf.physics.state import PERFECT_ACCURACY, PUTTER, ShotInput, Spin
from golf.physics.tables import PhysicsTables

#: Putts are played at every aim up to this many steps either side of the pin
#: line. Intents stay far enough inside it for their aim errors to fit.
AIM_WINDOW = 48
AIMS = 2 * AIM_WINDOW + 1
#: Power stops, 0 (full) to $30 (none).
STOPS = PERFECT_ACCURACY + 1
SPEEDS = 3
#: Presses are followed this many frames past the latest a player aims for,
#: for late presses (the meter bounces and climbs again).
FRAME_MARGIN = 40
#: How many of the best intents from each pixel are handed back.
KEPT = 3

#: `GreenTable.strokes` for a putt that drops, and for a stop no press reaches.
IN_CUP = 0
UNREACHED = -1


@cache
def aimed_frames(tables: PhysicsTables, speed: int) -> tuple[int, ...]:
    """The presses a player can aim for at `speed`: one for each power stop."""
    return tuple(
        sorted(
            {
                power_press(tables, speed, True, target)
                for target in power_targets(tables, speed, True)
            }
        )
    )


@cache
def frame_stops(tables: PhysicsTables, speed: int) -> tuple[int, ...]:
    """The power stop a press on each frame gives, frame 1 first."""
    last = aimed_frames(tables, speed)[-1] + FRAME_MARGIN
    stops = []
    for frame in range(1, last + 1):
        timing = meter.swing(tables, speed, True, frame)
        assert timing is not None, "a putt cannot whiff"
        stops.append(timing.power_stop)
    return tuple(stops)


def reachable(tables: PhysicsTables, speed: int) -> frozenset[int]:
    return frozenset(frame_stops(tables, speed))


def aim_at(position: Position, pin: tuple[int, int]) -> int:
    """The aim, in 256ths of a turn, from `position` at the pin, rounded."""
    dx, dy = pin[0] - position.x, pin[1] - position.y
    return round(np.arctan2(dx, -dy) * 128 / np.pi)


@dataclass
class GreenTable:
    """Every putt from every pixel of one green, to one pin."""

    pixels: np.ndarray
    """(pixels, 2): x, y."""
    centres: np.ndarray
    """(pixels,): the aim at the pin from each, the middle of its window."""
    rests: np.ndarray
    """(pixels, speeds, stops, aims, 3): x, y and bunker depth where each putt leaves the ball."""
    strokes: np.ndarray
    """(pixels, speeds, stops, aims): what each cost, `IN_CUP` or `UNREACHED`."""


def build_pixel(
    hole: Hole, position: Position, centre: int
) -> tuple[np.ndarray, np.ndarray]:
    """One pixel's rows of a `GreenTable`: (rests, strokes)."""
    rests = np.zeros((SPEEDS, STOPS, AIMS, 3), dtype=np.int16)
    strokes = np.full((SPEEDS, STOPS, AIMS), UNREACHED, dtype=np.int8)
    for speed in range(SPEEDS):
        for stop in sorted(reachable(hole.tables, speed)):
            for column in range(AIMS):
                shot = ShotInput(
                    club=PUTTER,
                    swing_speed=speed,
                    power_stop=stop,
                    accuracy_stop=stop,
                    spin=Spin.TOP_2,
                    aim=(centre - AIM_WINDOW + column) & 0xFF,
                    rng_state=RNG_STATES[0],
                    x=position.x,
                    y=position.y,
                )
                result = shot_result(shot, hole)
                if result.holed:
                    strokes[speed, stop, column] = IN_CUP
                    continue
                strokes[speed, stop, column] = result.strokes
                rest = result.position
                rests[speed, stop, column] = (rest.x, rest.y, rest.bunker_depth)
    return rests, strokes


def cache_path(rom: bytes, hole_json: bytes, pin: int, directory: Path) -> Path:
    """Where in `directory` the table for this ROM, hole and pin is kept."""
    digest = hashlib.sha256()
    settings = f"{pin} {AIM_WINDOW} {FRAME_MARGIN} {RNG_STATES[0]} v1"
    for part in (rom, hole_json, settings.encode()):
        digest.update(part)
    return directory / f"green-{digest.hexdigest()[:16]}.npz"


def save(table: GreenTable, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        path,
        pixels=table.pixels,
        centres=table.centres,
        rests=table.rests,
        strokes=table.strokes,
    )


def load(path: Path) -> GreenTable:
    data = np.load(path)
    return GreenTable(data["pixels"], data["centres"], data["rests"], data["strokes"])


class GreenSolver:
    """The green's values under one skill, from its table."""

    def __init__(
        self,
        table: GreenTable,
        tables: PhysicsTables,
        skill: Skill,
        points: int = EVERY_UNIT,
    ) -> None:
        """
        `points` is about how many errors stand for each draw (`errors`): by
        default every unit, as the green is lookups alone.
        """
        self.table = table
        count = len(table.pixels)
        rests = table.rests
        strokes = table.strokes
        played = strokes > IN_CUP

        # Where each putt leaves the ball: a pixel of the green, or a spot off
        # it, numbered in `leaves` for the caller to value.
        width = int(max(table.pixels[:, 0].max(), rests[..., 0].max())) + 1
        height = int(max(table.pixels[:, 1].max(), rests[..., 1].max())) + 1
        on_green = np.full((height, width), -1, dtype=np.int32)
        on_green[table.pixels[:, 1], table.pixels[:, 0]] = np.arange(count)
        x, y, depth = (rests[..., i].astype(np.int64) for i in range(3))
        landed = np.where(depth == 0, on_green[y, x], -1)
        self.next = np.where(played, landed, -1).astype(np.int32)
        off = played & (self.next < 0)
        # One number per spot: np.unique over rows is slow.
        codes = (x[off] << 20) | (y[off] << 4) | depth[off]
        spots, numbers = np.unique(codes, return_inverse=True)
        self.leave = np.full(strokes.shape, -1, dtype=np.int32)
        self.leave[off] = numbers.reshape(-1)
        self.leaves = [
            Position(int(c) >> 20, int(c) >> 4 & 0xFFFF, int(c) & 0xF) for c in spots
        ]
        self.cost = np.where(strokes == IN_CUP, 1.0, np.maximum(strokes, 0)).astype(
            np.float64
        )
        self.valid = strokes != UNREACHED

        # The press errors, as each aimed press's chance of each stop.
        power = errors(skill.power, points)
        self.frames = [aimed_frames(tables, speed) for speed in range(SPEEDS)]
        self.stop_of = [frame_stops(tables, speed) for speed in range(SPEEDS)]
        self.power = []
        for speed in range(SPEEDS):
            weights = np.zeros((len(self.frames[speed]), STOPS))
            stops = self.stop_of[speed]
            for row, frame in enumerate(self.frames[speed]):
                for error, p in power:
                    pressed = min(max(1, frame + error), len(stops))
                    weights[row, stops[pressed - 1]] += p
            self.power.append(weights)
        # The aim errors, and the aims intended, far enough inside the window.
        self.aim = errors(skill.aim, points)
        reach = max(abs(error) for error, _ in self.aim)
        if reach >= AIM_WINDOW:
            raise ValueError(f"aim errors reach {reach} steps, past the table's window")
        self.offsets = np.arange(-AIM_WINDOW + reach, AIM_WINDOW - reach + 1)
        self.expected = np.zeros(count)
        self._outside = np.zeros(strokes.shape)

    def solve(
        self, outside: np.ndarray, tolerance: float = 1e-9, sweeps: int = 1000
    ) -> np.ndarray:
        """
        The expected strokes from each pixel, `outside` being the value of each
        of `leaves`. Starts from the last solution, so later calls are quick.
        """
        self._outside = np.where(self.leave >= 0, outside[self.leave], 0.0)
        for _ in range(sweeps):
            best = self._intents().reshape(len(self.expected), -1).min(axis=1)
            change = np.abs(best - self.expected).max()
            self.expected = best
            if change < tolerance:
                break
        return self.expected

    def _costs(self) -> np.ndarray:
        """Strokes + value of where each putt, played exactly, leaves the ball."""
        on = np.where(self.next >= 0, self.expected[self.next], 0.0)
        return np.where(self.valid, self.cost + on + self._outside, 0.0)

    def _intents(self) -> np.ndarray:
        """(pixels, speeds, most aimed presses, intended aims): each intent's expected strokes."""
        costs = self._costs()
        aimed = np.zeros(costs.shape[:3] + (len(self.offsets),))
        for error, p in self.aim:
            aimed += p * costs[..., AIM_WINDOW + self.offsets + error]
        most = max(len(f) for f in self.frames)
        values = np.full((len(self.expected), SPEEDS, most, len(self.offsets)), np.inf)
        for speed in range(SPEEDS):
            weights = self.power[speed]
            values[:, speed, : len(weights)] = np.einsum(
                "fk,pkj->pfj", weights, aimed[:, speed]
            )
        return values

    def best(
        self, kept: int = KEPT
    ) -> list[list[tuple[Intent, dict[Result, float], float]]]:
        """
        For each pixel, its `kept` best intents, each with its outcomes and
        expected strokes, as `player.outcomes` would give them.
        """
        values = self._intents()
        count, _, most, aims = values.shape
        flat = values.reshape(count, -1)
        chosen = np.argsort(flat, axis=1)[:, :kept]
        best = []
        for pixel in range(count):
            putts = []
            for flat_index in chosen[pixel]:
                speed, row, column = np.unravel_index(
                    int(flat_index), (SPEEDS, most, aims)
                )
                intent = self.intent(pixel, int(speed), int(row), int(column))
                putts.append(
                    (
                        intent,
                        self._outcomes(pixel, int(speed), int(row), int(column)),
                        float(flat[pixel, flat_index]),
                    )
                )
            best.append(putts)
        return best

    def intent(self, pixel: int, speed: int, row: int, column: int) -> Intent:
        frame = self.frames[speed][row]
        aim = int(self.table.centres[pixel]) + int(self.offsets[column])
        return Intent(
            PUTTER, aim & 0xFF, self.stop_of[speed][frame - 1], swing_speed=speed
        )

    def _outcomes(
        self, pixel: int, speed: int, row: int, column: int
    ) -> dict[Result, float]:
        results: dict[Result, float] = {}
        weights = self.power[speed][row]
        for stop in np.nonzero(weights)[0]:
            for error, p in self.aim:
                at = (
                    pixel,
                    speed,
                    int(stop),
                    AIM_WINDOW + int(self.offsets[column]) + error,
                )
                strokes = int(self.table.strokes[at])
                if strokes == IN_CUP:
                    result = HOLED
                else:
                    x, y, depth = (int(v) for v in self.table.rests[at])
                    result = Result(Position(x, y, depth), strokes, False)
                results[result] = results.get(result, 0.0) + float(weights[stop]) * p
        return results
