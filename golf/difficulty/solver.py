"""
The expected strokes to hole out, from every spot a hole's play reaches: value
iteration over the player model (`golf.difficulty.player`).

For now one pin (by default the first) and no wind (`docs/planning/hole_difficulty.md`).

**States.** Off the green a state is a cell of a `grid`-pixel grid, split by
the lie class a full swing is played from (`landing.LieClass`); the first real
spot the ball comes to in a cell stands for it. On the green every pixel is its
own state, and the tee is one too.

**Intents.** From each state the landing table screens every intent it holds
for a club in the vanilla bag,
at every other aim within a quarter turn of the pin, against the current value
of where each would come to rest. The best few, one per club, speed, hi/lo and
spin, are played exactly (`player.outcomes`). On the green, every putt within
`PUTT_AIMS` steps of the line to the pin is played once, perfectly, and the
best few are played exactly.

**Rounds.** Only spots play reaches are valued. Each round screens every state
found so far against the current values, plays what is new on the shortlists
(all of it for a new state, the top `refresh` for one screened before), runs
value iteration, then follows the best play forward from the tee and adds every
state it visits at least `reach` times on average. Screening and playing are
separate tasks, so even the first round, the tee alone, is spread over every
core.
A state not yet valued borrows from valued neighbours of the same lie class, or
failing those a guess from its distance to the pin (`guess`).
"""

import math
import os
import time
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from golf.core.clubs import VANILLA_CLUBS
from golf.core.rom_reader import RomReader
from golf.difficulty.landing import (
    COLUMNS,
    LIE_CLASSES,
    LandingTable,
    LieClass,
    cache_path,
    lie_class,
    load,
    power_targets,
)
from golf.difficulty.player import (
    PERFECT,
    RNG_STATES,
    Hole,
    Intent,
    Position,
    Result,
    Skill,
    outcomes,
)
from golf.formats.hole_data import HoleData
from golf.physics.flights import Flights
from golf.physics.shot import Flag
from golf.physics.state import PUTTER, Lie
from golf.physics.tables import PhysicsTables
from golf.physics.terrain import HoleGround, TerrainTables

NO_WIND = (0, 0)

#: Putts are tried at aims up to this many steps either side of the pin,
#: every `PUTT_COARSE`th at first.
PUTT_AIMS = 20
PUTT_COARSE = 4
#: Full swings are tried at every other aim up to this far either side of the pin.
SWING_AIMS = 64
#: How many aims the screen scores at once.
AIMS_AT_ONCE = 8

#: Classes of pixel in the value map: the lie classes, then these.
GREEN = len(LIE_CLASSES)
WATER = GREEN + 1
OUT = GREEN + 2

#: A state: (class, x, y), x and y a grid cell off the green and a pixel on it.
Key = tuple[int, int, int]
TEE: Key = (-1, 0, 0)


@dataclass(frozen=True)
class Settings:
    grid: int = 4
    """Off the green, the size in pixels of the cells states are made of."""
    shortlist: int = 16
    """Intents played exactly from a spot off the green when it is first screened."""
    putts: int = 8
    """Putts played exactly from a spot on the green when it is first screened."""
    refresh: int = 4
    """
    At most this many new intents from the top of a spot's shortlist are
    played in each later round, as the values it was screened against change.
    """
    tolerance: float = 0.002
    """Stop once no spots are added and the tee's value moves less than this."""
    reach: float = 1e-3
    """A spot is valued once the best play visits it this often on average."""
    blur: float = 2.0
    """The value map is blurred by this many pixels for the screen, for execution's spread."""
    rounds: int = 12


@dataclass
class Transition:
    """One intent's outcomes, as states: (next state or None when holed, strokes, probability)."""

    intent: Intent
    outcomes: list[tuple[Key | None, int, float]]


@dataclass
class Solution:
    expected: dict[Key, float]
    """Expected strokes to hole out, by state."""
    policy: dict[Key, Intent]
    positions: dict[Key, Position]
    visits: dict[Key, float]
    """How often the best play from the tee visits each state, on average."""
    unvalued: float
    """How often it visits spots that borrowed their value (reached too rarely to value)."""
    rounds: int
    shots: int
    """Intents played exactly, in all."""

    @property
    def tee(self) -> float:
        return self.expected[TEE]


# --- the context each worker plays shots in ------------------------------------


@dataclass
class _Context:
    hole: Hole
    ground: HoleGround
    table: LandingTable | None
    skill: Skill
    tables: PhysicsTables
    flag: Flag
    height: int


_context: _Context | None = None


def _start_worker(
    rom_path: str, hole_path: str, pin: int, table_path: str | None, skill: Skill
):
    global _context
    _context = _make_context(rom_path, hole_path, pin, table_path, skill)


def _make_context(
    rom_path: str, hole_path: str, pin: int, table_path: str | None, skill: Skill
) -> _Context:
    rom = RomReader(rom_path)
    tables = PhysicsTables.from_rom(rom)
    hole_data = HoleData()
    hole_data.load(Path(hole_path))
    ground = HoleGround(hole_data, TerrainTables.from_rom(rom))
    flag = Flag.for_pin(hole_data, pin)
    hole = Hole(ground, tables, flag, Flights(tables, max_flights=256))
    table = load(Path(table_path)) if table_path else None
    return _Context(hole, ground, table, skill, tables, flag, ground.bottom_y)


@dataclass(frozen=True)
class _Task:
    key: Key
    position: Position
    values: str
    """
    Where the value map is: (class, y, x) of expected strokes from each
    pixel, then each pixel's class (`HoleSolver.value_map`).
    """
    here: float
    """The current expected strokes from this spot."""


def _screen(task: _Task) -> tuple[Key, list[Intent], float]:
    """The intents worth playing from `task`'s spot, best first."""
    context = _context
    assert context is not None
    started = time.perf_counter()
    terrain = context.ground.classify(task.position.x, 0, task.position.y, 0)
    if terrain.lie == Lie.GREEN:
        chosen = _screen_putts(context, task)
    else:
        lie = lie_class(terrain, task.position.bunker_depth)
        chosen = _screen_swings(context, task, lie)
    return task.key, chosen, time.perf_counter() - started


def _play(
    task: tuple[Key, Position, Intent],
) -> tuple[Key, Intent, dict[Result, float], float]:
    """Play one intent from one spot, exactly."""
    context = _context
    assert context is not None
    started = time.perf_counter()
    key, position, intent = task
    # A putt reads the RNG only if it runs into sand or water, so one state
    # stands for all of them on the green.
    putt = context.ground.classify(position.x, 0, position.y, 0).lie == Lie.GREEN
    states = (RNG_STATES[0],) if putt else RNG_STATES
    results = outcomes(intent, position, context.hole, NO_WIND, context.skill, states)
    return key, intent, results, time.perf_counter() - started


_loaded: tuple[str, np.ndarray] | None = None


def _values(task: _Task) -> np.ndarray:
    """The value map, loaded once a round."""
    global _loaded
    if _loaded is None or _loaded[0] != task.values:
        _loaded = (task.values, np.load(task.values))
    return _loaded[1]


def _aim_to(position: Position, flag: Flag) -> float:
    """The aim, in 256ths of a turn, from `position` at the pin."""
    dx = (flag.x >> 8) - position.x
    dy = (flag.y >> 8) - position.y
    return math.atan2(dx, -dy) * 128 / math.pi


def _screen_swings(context: _Context, task: _Task, lie: LieClass) -> list[Intent]:
    table = context.table
    assert table is not None
    toward = round(_aim_to(task.position, context.flag) / 2) * 2
    aims = np.arange(toward - SWING_AIMS, toward + SWING_AIMS + 1, 2) % 256
    values = _landing_values(_values(task), task.here)
    height, width = values.shape
    usable = _in_bag(table, lie)
    best = np.full(len(usable), np.inf)
    best_aim = np.zeros(len(usable), dtype=int)
    # A few aims at a time, keeping each intent's best: all at once is
    # hundreds of megabytes a worker.
    for start in range(0, len(aims), AIMS_AT_ONCE):
        chunk = aims[start : start + AIMS_AT_ONCE]
        offsets = table.offsets(lie, chunk.astype(np.float32))  # (intents, aims, 2)
        x = np.rint(task.position.x + offsets[..., 0])
        y = np.rint(task.position.y + offsets[..., 1])
        missing = np.isnan(x)
        x = np.where(missing, -1, x).astype(np.int32)
        y = np.where(missing, -1, y).astype(np.int32)
        inside = (x >= 0) & (x < width) & (y >= 0) & (y < height)
        # Off the hole is out of bounds: a penalty stroke and this spot again.
        score = np.full(x.shape, 1 + task.here, dtype=np.float32)
        score[inside] = values[y[inside], x[inside]]
        score[missing | ~usable[:, None]] = np.inf
        chunk_best = score.argmin(axis=1)
        chunk_score = score[np.arange(len(score)), chunk_best]
        better = chunk_score < best
        best[better] = chunk_score[better]
        best_aim[better] = start + chunk_best[better]

    groups = _groups(table, lie)
    # The best of each group (club, speed, hi/lo, spin), then the best groups.
    order = np.lexsort((best, groups))
    first = np.ones(len(order), dtype=bool)
    first[1:] = groups[order][1:] != groups[order][:-1]
    leaders = order[first]
    leaders = leaders[np.argsort(best[leaders])][:_SHORTLIST]
    return [
        table.intent(lie, int(index), int(aims[best_aim[index]]))
        for index in leaders
        if np.isfinite(best[index])
    ]


_group_cache: dict[tuple, np.ndarray] = {}


def _groups(table: LandingTable, lie: LieClass) -> np.ndarray:
    """Each intent's group: its club, speed, hi/lo and spin."""
    key = (id(table), lie, "groups")
    if key not in _group_cache:
        columns = [COLUMNS.index(c) for c in ("club", "swing_speed", "hi_lo", "spin")]
        _, ids = np.unique(table.intents[lie][:, columns], axis=0, return_inverse=True)
        _group_cache[key] = ids.reshape(-1)
    return _group_cache[key]


def _in_bag(table: LandingTable, lie: LieClass) -> np.ndarray:
    """Which of the table's intents use a club in the vanilla bag."""
    key = (id(table), lie, "bag")
    if key not in _group_cache:
        clubs = table.intents[lie][:, COLUMNS.index("club")]
        _group_cache[key] = np.isin(clubs, [int(club) for club in VANILLA_CLUBS])
    return _group_cache[key]


def _landing_values(values: np.ndarray, here: float) -> np.ndarray:
    """
    The value of the ball coming to rest on each pixel, blurred: a pixel's own
    class, with water and out of bounds a penalty stroke and this spot again.
    """
    classes = values[-1].astype(int)
    rest = np.take_along_axis(values[:-1], classes[None].clip(0, GREEN), axis=0)[0]
    rest = np.where(classes >= WATER, 1 + here, rest)
    return _blur(rest, _BLUR)


def _blur(values: np.ndarray, sigma: float) -> np.ndarray:
    if sigma <= 0:
        return values
    radius = math.ceil(2 * sigma)
    kernel = np.exp(-0.5 * (np.arange(-radius, radius + 1) / sigma) ** 2)
    kernel /= kernel.sum()
    padded = np.pad(values, radius, mode="edge")
    height, width = values.shape
    rows = np.zeros((padded.shape[0], width))
    for i, k in enumerate(kernel):
        rows += k * padded[:, i : i + width]
    blurred = np.zeros((height, width))
    for i, k in enumerate(kernel):
        blurred += k * rows[i : i + height]
    return blurred


def _screen_putts(context: _Context, task: _Task) -> list[Intent]:
    """
    Every putt near the line, played once perfectly: first at every
    `PUTT_COARSE`th aim, then at every aim and power around the best of those.
    """
    values = _values(task)
    toward = round(_aim_to(task.position, context.flag))
    scores: dict[Intent, float] = {}

    def score(intent: Intent) -> None:
        if intent in scores:
            return
        (result,) = outcomes(
            intent, task.position, context.hole, NO_WIND, PERFECT, (RNG_STATES[0],)
        )
        if result.holed:
            scores[intent] = 1.0
            return
        x, y = result.position.x, result.position.y
        klass = _class_at(context, result.position)
        scores[intent] = result.strokes + float(values[klass, y, x])

    powers = [power_targets(context.tables, speed, putting=True) for speed in range(3)]
    for speed in range(3):
        for power in powers[speed]:
            for aim in range(toward - PUTT_AIMS, toward + PUTT_AIMS + 1, PUTT_COARSE):
                score(Intent(PUTTER, aim % 256, power, swing_speed=speed))
    coarse = sorted(scores, key=scores.__getitem__)[:_PUTTS]
    for best in coarse:
        speed_powers = powers[best.swing_speed]
        at = speed_powers.index(best.power_target)
        for power in speed_powers[max(0, at - 2) : at + 3]:
            for turn in range(-PUTT_COARSE + 1, PUTT_COARSE):
                aim = (best.aim + turn) % 256
                score(Intent(PUTTER, aim, power, swing_speed=best.swing_speed))
    return sorted(scores, key=scores.__getitem__)[:_PUTTS]


def _class_at(context: _Context, position: Position) -> int:
    terrain = context.ground.classify(position.x, 0, position.y, 0)
    return pixel_class(terrain.lie, terrain.rough_depth, position.bunker_depth)


def pixel_class(lie: Lie, rough_depth: int, bunker_depth: int = 0) -> int:
    """The class of a pixel in the value map."""
    if lie == Lie.GREEN:
        return GREEN
    if lie == Lie.WATER:
        return WATER
    if lie == Lie.OUT_OF_BOUNDS:
        return OUT
    if lie == Lie.ROUGH:
        return LIE_CLASSES.index(LieClass(Lie.ROUGH, rough_depth))
    if lie == Lie.BUNKER:
        return LIE_CLASSES.index(LieClass(Lie.BUNKER, bunker_depth))
    return LIE_CLASSES.index(LieClass(Lie.FAIRWAY))


# Set per worker from the settings; module globals keep `_Task` small.
_SHORTLIST = Settings.shortlist
_PUTTS = Settings.putts
_BLUR = Settings.blur


def _configure(settings: Settings) -> None:
    global _SHORTLIST, _PUTTS, _BLUR
    _SHORTLIST, _PUTTS, _BLUR = settings.shortlist, settings.putts, settings.blur


def _start(rom_path, hole_path, pin, table_path, skill, settings) -> None:
    _configure(settings)
    _start_worker(rom_path, hole_path, pin, table_path, skill)


# --- the solver ---------------------------------------------------------------


def guess(distance: float, klass: int) -> float:
    """A rough expected score from `distance` pixels, before anything is known."""
    if klass == GREEN:
        return 2.0 - math.exp(-distance / 8)
    penalty = {1: 0.15, 2: 0.3}.get(klass, 0.4 if 3 <= klass <= 5 else 0.0)
    return 2.0 + distance / 115 + penalty


@dataclass
class HoleSolver:
    rom_path: str
    hole_path: Path
    pin: int = 0
    skill: Skill = field(default_factory=lambda: Skill.scaled(1.0))
    settings: Settings = field(default_factory=Settings)
    workers: int = field(default_factory=lambda: os.cpu_count() or 1)
    log: Callable[[str], None] = field(default=print)
    scratch: Path = Path(".cache/difficulty")
    """Where each round's value map is left for the workers."""

    def __post_init__(self) -> None:
        rom = RomReader(self.rom_path)
        self.tables = PhysicsTables.from_rom(rom)
        self.table_path = cache_path(self.tables)
        if not self.table_path.exists():
            raise FileNotFoundError(
                f"no landing table at {self.table_path}; build it first"
            )
        self.hole = HoleData()
        self.hole.load(self.hole_path)
        self.ground = HoleGround(self.hole, TerrainTables.from_rom(rom))
        self.flag = Flag.for_pin(self.hole, self.pin)
        tee = self.hole.metadata["tee"]
        self.tee = Position(tee["x"], tee["y"])
        self.height = self.ground.bottom_y
        self._classes = np.array(
            [[self._pixel_class(x, y) for x in range(0xB0)] for y in range(self.height)]
        )
        self.positions: dict[Key, Position] = {TEE: self.tee}
        self.transitions: dict[Key, list[Transition]] = {}
        self.expected: dict[Key, float] = {}

    def _pixel_class(self, x: int, y: int) -> int:
        terrain = self.ground.classify(x, 0, y, 0)
        return pixel_class(terrain.lie, terrain.rough_depth)

    def key(self, position: Position) -> Key:
        if (position.x, position.y) == (self.tee.x, self.tee.y):
            return TEE
        terrain = self.ground.classify(position.x, 0, position.y, 0)
        klass = pixel_class(terrain.lie, terrain.rough_depth, position.bunker_depth)
        if klass == GREEN:
            return (GREEN, position.x, position.y)
        grid = self.settings.grid
        return (klass, position.x // grid, position.y // grid)

    def distance(self, position: Position) -> float:
        return math.hypot(
            position.x - (self.flag.x >> 8), position.y - (self.flag.y >> 8)
        )

    # --- values ---------------------------------------------------------

    def _borrowed(self) -> dict[int, np.ndarray]:
        """
        Per class, a grid of values: valued states' own, spread twice to
        neighbouring cells of the same class, and a guess beyond.
        """
        grid = self.settings.grid
        rows, columns = -(-self.height // grid), -(-0xB0 // grid)
        filled: dict[int, np.ndarray] = {}
        for klass in range(len(LIE_CLASSES)):
            cells = np.full((rows, columns), np.nan)
            for key, value in self.expected.items():
                if key[0] == klass:
                    cells[key[2], key[1]] = value
            filled[klass] = _spread(cells, 2)
        green = np.full((self.height, 0xB0), np.nan)
        for key, value in self.expected.items():
            if key[0] == GREEN:
                green[key[2], key[1]] = value
        filled[GREEN] = _spread(green, 2)
        return filled

    def value(self, key: Key, borrowed: dict[int, np.ndarray]) -> float:
        if key in self.expected:
            return self.expected[key]
        if key == TEE:
            return guess(self.distance(self.tee), 0)
        klass, x, y = key
        value = borrowed[klass][y, x]
        if np.isnan(value):
            grid = 1 if klass == GREEN else self.settings.grid
            centre = Position(x * grid + grid // 2, y * grid + grid // 2)
            value = guess(self.distance(centre), klass)
        return float(value)

    def value_map(self) -> np.ndarray:
        """(class..., classes) by (y, x): each class's value at every pixel, then each pixel's class."""
        borrowed = self._borrowed()
        grid = self.settings.grid
        layers = np.zeros((GREEN + 2, self.height, 0xB0))
        ys, xs = np.mgrid[0 : self.height, 0:0xB0]
        distance = np.hypot(xs - (self.flag.x >> 8), ys - (self.flag.y >> 8))
        for klass in range(len(LIE_CLASSES)):
            cells = borrowed[klass][ys // grid, xs // grid]
            fallback = np.vectorize(lambda d, k=klass: guess(d, k))(distance)
            layers[klass] = np.where(np.isnan(cells), fallback, cells)
        green = borrowed[GREEN]
        layers[GREEN] = np.where(
            np.isnan(green), np.vectorize(lambda d: guess(d, GREEN))(distance), green
        )
        layers[GREEN + 1] = self._classes
        return layers

    def iterate(self, sweeps: int = 2000, tolerance: float = 1e-6) -> None:
        """Value iteration over the states played so far, from the green outward."""
        order = sorted(self.transitions, key=lambda k: self.distance(self.positions[k]))
        borrowed = self._borrowed()
        for key in order:
            self.expected.setdefault(key, self.value(key, borrowed))
        for sweep in range(sweeps):
            change = 0.0
            for key in order:
                best = min(
                    self._q(transition, borrowed)
                    for transition in self.transitions[key]
                )
                change = max(change, abs(best - self.expected[key]))
                self.expected[key] = best
            if sweep % 10 == 9:
                borrowed = self._borrowed()
            if change < tolerance:
                break

    def _q(self, transition: Transition, borrowed: dict[int, np.ndarray]) -> float:
        total = 0.0
        for key, strokes, probability in transition.outcomes:
            total += probability * (
                strokes + (0.0 if key is None else self.value(key, borrowed))
            )
        return total

    def policy(self) -> dict[Key, Transition]:
        borrowed = self._borrowed()
        return {
            key: min(transitions, key=lambda t: self._q(t, borrowed))
            for key, transitions in self.transitions.items()
        }

    def visits(self) -> tuple[dict[Key, float], dict[Key, float]]:
        """
        How often the best play from the tee visits each state played so far,
        and each state it reaches that has not been played.
        """
        policy = self.policy()
        inside: dict[Key, float] = {}
        outside: dict[Key, float] = {}
        flow = {TEE: 1.0}
        for _ in range(200):
            next_flow: dict[Key, float] = {}
            for key, mass in flow.items():
                if key not in policy:
                    outside[key] = outside.get(key, 0.0) + mass
                    continue
                inside[key] = inside.get(key, 0.0) + mass
                for target, _, probability in policy[key].outcomes:
                    if target is not None:
                        next_flow[target] = (
                            next_flow.get(target, 0.0) + mass * probability
                        )
            flow = {k: m for k, m in next_flow.items() if m > 1e-9}
            if not flow:
                break
        return inside, outside

    # --- rounds ---------------------------------------------------------

    def solve(self) -> Solution:
        settings = self.settings
        pending = {TEE}
        shots = 0
        started = time.perf_counter()
        with ProcessPoolExecutor(
            self.workers,
            initializer=_start,
            initargs=(
                self.rom_path,
                str(self.hole_path),
                self.pin,
                str(self.table_path),
                self.skill,
                settings,
            ),
        ) as pool:
            self.scratch.mkdir(parents=True, exist_ok=True)
            round_number = 0
            previous_tee = math.inf
            for round_number in range(1, settings.rounds + 1):
                values = str(self.scratch / f"values-{os.getpid()}-{round_number}.npy")
                np.save(values, self.value_map().astype(np.float32))
                borrowed = self._borrowed()
                keys = sorted(
                    set(self.transitions) | pending,
                    key=lambda k: (self.positions[k].y, self.positions[k].x),
                )
                screens = [
                    _Task(key, self.positions[key], values, self.value(key, borrowed))
                    for key in keys
                ]
                busy = 0.0
                plays: list[tuple[Key, Position, Intent]] = []
                for key, chosen, seconds in pool.map(_screen, screens, chunksize=4):
                    busy += seconds
                    played = {t.intent for t in self.transitions.get(key, [])}
                    fresh = [intent for intent in chosen if intent not in played]
                    if played:
                        fresh = fresh[: settings.refresh]
                    plays.extend((key, self.positions[key], intent) for intent in fresh)
                # Like shots next to each other, so a worker's flights are shared.
                plays.sort(
                    key=lambda p: (p[2].club, p[2].swing_speed, p[2].aim, p[1].y)
                )
                added = 0
                for key, intent, results, seconds in pool.map(
                    _play, plays, chunksize=4
                ):
                    busy += seconds
                    self.transitions.setdefault(key, []).append(
                        Transition(intent, self._outcomes(results))
                    )
                    added += 1
                shots += added
                pending.clear()
                self.iterate()
                inside, outside = self.visits()
                for key, mass in outside.items():
                    if mass >= settings.reach:
                        pending.add(key)
                tee = self.expected[TEE]
                self.log(
                    f"round {round_number}: {len(self.transitions)} states, "
                    f"{added} intents played, {len(pending)} to add, "
                    f"tee {self.expected[TEE]:.3f}, "
                    f"{time.perf_counter() - started:.0f} s ({busy:.0f} s of work)"
                )
                settled = abs(tee - previous_tee) < settings.tolerance
                if not pending and (not added or settled):
                    break
                previous_tee = tee
        inside, outside = self.visits()
        policy = self.policy()
        return Solution(
            dict(self.expected),
            {key: t.intent for key, t in policy.items()},
            dict(self.positions),
            inside,
            sum(outside.values()),
            round_number,
            shots,
        )

    def _outcomes(
        self, results: dict[Result, float]
    ) -> list[tuple[Key | None, int, float]]:
        converted = []
        for result, probability in results.items():
            if result.holed:
                converted.append((None, result.strokes, probability))
                continue
            key = self.key(result.position)
            self.positions.setdefault(key, result.position)
            converted.append((key, result.strokes, probability))
        return converted


def _spread(cells: np.ndarray, times: int) -> np.ndarray:
    """Fill empty cells with the mean of their filled neighbours, `times` over."""
    cells = cells.copy()
    for _ in range(times):
        empty = np.isnan(cells)
        if not empty.any():
            break
        padded = np.pad(cells, 1, constant_values=np.nan)
        stack = np.stack(
            [
                padded[
                    1 + dy : 1 + dy + cells.shape[0], 1 + dx : 1 + dx + cells.shape[1]
                ]
                for dy in (-1, 0, 1)
                for dx in (-1, 0, 1)
                if dy or dx
            ]
        )
        count = (~np.isnan(stack)).sum(axis=0)
        total = np.nansum(stack, axis=0)
        mean = np.where(count > 0, total / np.maximum(count, 1), np.nan)
        cells = np.where(empty, mean, cells)
    return cells
