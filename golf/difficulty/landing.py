"""
The landing table: where each shot a player might choose comes to rest, from any
spot, roughly and at once, so the solver can screen thousands of intents and
play only the best few exactly.

Each entry is an intent's perfect execution with no wind, played over plain
fairway from each lie a shot can be played from, at 8 base aims. A shot at
another aim is taken from the nearest base aim, turned. Without wind a flight's
shape depends on its aim only through the game's rounding and the uneven hook
and slice terms: a straight shot turned from aim 0 lands within 2 pixels of
where it really does, and a curved one turned by up to 16 steps within 8.

The table depends on nothing but the ROM's physics tables, so it is built once
per ROM and cached (`cache_path`).
"""

import hashlib
import math
import os
from collections.abc import Iterator
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from golf.difficulty.player import PERFECT, Intent, power_press, swings
from golf.physics import meter
from golf.physics.shot import simulate
from golf.physics.state import (
    PERFECT_ACCURACY,
    PUTTER,
    Lie,
    ShotInput,
    Spin,
    Terrain,
    UniformGround,
)
from golf.physics.tables import PhysicsTables

#: The aims each entry is played at: every 32 steps.
BASE_AIMS = tuple(range(0, 256, 32))

#: The accuracy targets tried: straight, and two strengths of hook and slice.
ACCURACY_TARGETS = (
    PERFECT_ACCURACY,
    PERFECT_ACCURACY - 8,
    PERFECT_ACCURACY + 8,
    PERFECT_ACCURACY - 16,
    PERFECT_ACCURACY + 16,
)

#: Spins that play differently (TOP 1 and TOP 2 are NORMAL's twins).
SPINS = (Spin.NORMAL, Spin.BACK_1, Spin.BACK_2)


@dataclass(frozen=True)
class LieClass:
    """What a shot is played from, as far as the launch can tell."""

    lie: Lie
    depth: int = 0
    """The rough's depth, or how buried a ball in sand is."""

    @property
    def terrain(self) -> Terrain:
        if self.lie == Lie.ROUGH:
            return Terrain(Lie.ROUGH, rough_depth=self.depth)
        return Terrain(self.lie)


#: The lies a full swing is played from. The tee plays like the fairway.
LIE_CLASSES = (
    LieClass(Lie.FAIRWAY),
    LieClass(Lie.ROUGH, 0),
    LieClass(Lie.ROUGH, 1),
    LieClass(Lie.BUNKER, 0),
    LieClass(Lie.BUNKER, 1),
    LieClass(Lie.BUNKER, 2),
)


def lie_class(terrain: Terrain, bunker_depth: int) -> LieClass:
    """The class of a spot the ground reports as `terrain`, off the green."""
    if terrain.lie in (Lie.FAIRWAY, Lie.TEE):
        return LieClass(Lie.FAIRWAY)
    if terrain.lie == Lie.ROUGH:
        return LieClass(Lie.ROUGH, terrain.rough_depth)
    if terrain.lie == Lie.BUNKER:
        return LieClass(Lie.BUNKER, bunker_depth)
    raise ValueError(f"no full swing is played from {terrain.lie.name}")


def power_targets(tables: PhysicsTables, speed: int, putting: bool) -> list[int]:
    """The distinct power stops a perfect player can choose at `speed`."""
    stops = {
        _stop(tables, speed, putting, target) for target in range(PERFECT_ACCURACY + 1)
    }
    return sorted(stops)


def _stop(tables: PhysicsTables, speed: int, putting: bool, target: int) -> int:
    return meter.backswing(
        tables, speed, putting, power_press(tables, speed, putting, target)
    ).power_stop


def intents(tables: PhysicsTables, club: int) -> Iterator[Intent]:
    """Every intent the table holds for `club`, at aim 0."""
    putter = club == PUTTER
    for speed in range(3):
        for power in power_targets(tables, speed, putting=False):
            for hi_lo in (0,) if putter else (-1, 0, 1):
                for spin in (Spin.NORMAL,) if putter else SPINS:
                    for accuracy in (PERFECT_ACCURACY,) if putter else ACCURACY_TARGETS:
                        yield Intent(club, 0, power, accuracy, speed, hi_lo, spin)


def _start(aim: int) -> tuple[int, int]:
    """A start far enough from the playfield's edges for any shot at `aim`."""
    return round(88 - 80 * math.sin(aim * 2 * math.pi / 256)), 0x400


def _rest(
    tables: PhysicsTables, intent: Intent, lie: LieClass, aim: int
) -> tuple[float, float]:
    """
    Where a perfect `intent` at `aim` from `lie` stops over plain fairway, as
    (across, along) the aim in pixels: NaN if it leaves the playfield or whiffs.
    """
    (timing,) = swings(tables, intent, False, PERFECT)
    if timing is None:
        return math.nan, math.nan
    x, y = _start(aim)
    shot = ShotInput(
        club=intent.club,
        swing_speed=intent.swing_speed,
        power_stop=timing.power_stop,
        accuracy_stop=timing.accuracy_stop,
        hi_lo=intent.hi_lo,
        spin=intent.spin,
        aim=aim,
        rng_state=1,
        bunker_depth=lie.depth if lie.lie == Lie.BUNKER else 0,
        x=x,
        y=y,
        frames_to_impact=timing.frames_to_impact or 0,
    )
    result = simulate(shot, _FAIRWAY_EVERYWHERE, tables, launch_terrain=lie.terrain)
    if result.ball.lie == Lie.OUT_OF_BOUNDS:
        return math.nan, math.nan
    dx, dy = result.rest.x - x, result.rest.y - y
    angle = aim * 2 * math.pi / 256
    across = dx * math.cos(angle) + dy * math.sin(angle)
    along = dx * math.sin(angle) - dy * math.cos(angle)
    return across, along


_FAIRWAY_EVERYWHERE = UniformGround(Terrain(Lie.FAIRWAY))


#: The columns of `LandingTable.intents`.
COLUMNS = ("club", "power_target", "accuracy_target", "swing_speed", "hi_lo", "spin")


def encode(held: list[Intent]) -> np.ndarray:
    """Intents as rows of `COLUMNS` (their aims are dropped)."""
    return np.array(
        [[int(getattr(intent, column)) for column in COLUMNS] for intent in held],
        dtype=np.int16,
    ).reshape(-1, len(COLUMNS))


@dataclass
class LandingTable:
    """
    For each lie class, its intents and where each comes to rest. The intents
    are rows of `COLUMNS`, not `Intent`s: there are nearly half a million, and
    each worker of the solver holds them all.
    """

    intents: dict[LieClass, np.ndarray]
    """(intents, `COLUMNS`), int16."""
    rests: dict[LieClass, np.ndarray]
    """(intents, base aims, 2): (across, along) the aim, in pixels."""

    def intent(self, lie: LieClass, index: int, aim: int) -> Intent:
        """Row `index` of `lie`'s intents, played at `aim`."""
        club, power, accuracy, speed, hi_lo, spin = (
            int(v) for v in self.intents[lie][index]
        )
        return Intent(club, aim, power, accuracy, speed, hi_lo, Spin(spin))

    def offsets(self, lie: LieClass, aims: np.ndarray) -> np.ndarray:
        """
        (intents, aims, 2): where each intent at each of `aims` comes to rest,
        as (dx, dy) pixels from its start.
        """
        base = np.rint(aims / 32).astype(int) % len(BASE_AIMS)
        rest = self.rests[lie][:, base]  # (intents, aims, 2)
        angle = aims * 2 * np.pi / 256
        sin, cos = np.sin(angle), np.cos(angle)
        across, along = rest[..., 0], rest[..., 1]
        return np.stack(
            (along * sin + across * cos, -along * cos + across * sin), axis=-1
        )


def _build_part(
    args: tuple[PhysicsTables, LieClass, int],
) -> tuple[LieClass, int, list[Intent], list[list[tuple[float, float]]]]:
    tables, lie, club = args
    held = list(intents(tables, club))
    rests = [[_rest(tables, intent, lie, aim) for aim in BASE_AIMS] for intent in held]
    return lie, club, held, rests


def build(tables: PhysicsTables, workers: int | None = None) -> LandingTable:
    """Play every entry: about a million shots, spread over `workers` processes."""
    clubs = [*range(15), PUTTER]
    jobs = [(tables, lie, club) for lie in LIE_CLASSES for club in clubs]
    held: dict[LieClass, list[Intent]] = {lie: [] for lie in LIE_CLASSES}
    rests: dict[LieClass, list[list[tuple[float, float]]]] = {
        lie: [] for lie in LIE_CLASSES
    }
    parts = {}
    with ProcessPoolExecutor(workers or os.cpu_count()) as pool:
        for lie, club, part_intents, part_rests in pool.map(_build_part, jobs):
            parts[(lie, club)] = (part_intents, part_rests)
    for lie in LIE_CLASSES:
        for club in clubs:
            part_intents, part_rests = parts[(lie, club)]
            held[lie].extend(part_intents)
            rests[lie].extend(part_rests)
    return LandingTable(
        {lie: encode(held[lie]) for lie in LIE_CLASSES},
        {lie: np.array(rests[lie], dtype=np.float32) for lie in LIE_CLASSES},
    )


def cache_path(tables: PhysicsTables, root: Path = Path(".cache")) -> Path:
    """Where the table for these physics tables is kept."""
    digest = hashlib.sha256(repr(tables).encode()).hexdigest()[:16]
    return root / "difficulty" / f"landing-{digest}.npz"


def save(table: LandingTable, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    arrays: dict[str, Any] = {}
    for index, lie in enumerate(LIE_CLASSES):
        arrays[f"rests_{index}"] = table.rests[lie]
        arrays[f"intents_{index}"] = table.intents[lie]
    np.savez_compressed(path, **arrays)


def load(path: Path) -> LandingTable:
    data = np.load(path)
    return LandingTable(
        {lie: data[f"intents_{i}"] for i, lie in enumerate(LIE_CLASSES)},
        {lie: data[f"rests_{i}"] for i, lie in enumerate(LIE_CLASSES)},
    )


def load_or_build(tables: PhysicsTables, workers: int | None = None) -> LandingTable:
    """The cached table for `tables`, built first if there is none."""
    path = cache_path(tables)
    if path.exists():
        return load(path)
    table = build(tables, workers)
    save(table, path)
    return table
