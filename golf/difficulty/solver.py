"""
The expected strokes to hole out, from every spot a hole's play reaches: value
iteration over the player model (`golf.difficulty.player`).

For now one pin (by default the first) and no wind (`docs/hole_difficulty.md`).

**States.** Off the green a state is a cell of a `grid`-pixel grid, split by
the lie class a full swing is played from (`landing.LieClass`); the first real
spot the ball comes to in a cell stands for it. On the green every pixel is its
own state, and the tee is one too.

**Intents.** From each state off the green the landing table screens every
intent it holds for a club in the vanilla bag, at every other aim within a
quarter turn of the pin, against the current value of where each would come to
rest (over plain fairway, or near the pin on the hole itself: `NEAR_PIN`); the
best few are scored again under the player's errors, and the best of
those are played exactly (`player.outcomes`). Where more than `race` are new,
all are first played roughly (one RNG state, few errors a draw), and only the
best of them exactly.

**The green** is solved whole, every pixel of it, from a table of every putt
played once (`golf.difficulty.green`), and valued again at the start of each
round against what the rest of the hole is then worth.

**Rounds.** Only spots play reaches are valued. Each round values the green,
screens every state off it found so far against the current values, plays what is new on the shortlists
(all of it for a new state, the top `refresh` for one screened before and still
visited at least `refresh_reach` times), runs
value iteration, then follows the best play forward from the tee and adds every
state it visits at least `reach` times on average. A spot whose value has
moved `rescreen_move` since it was screened is screened again however rarely
play reaches it: intents chosen against values far off can hop between spots
that all looked better than they were, a loop value iteration only climbs.
After `rounds` no spot is added, and the solve stops only once no spot is due
to be screened again. From the round whose outcomes are no longer added, any
intent the best play chooses that would visit a spot not yet valued as often as
`reach` is set aside, and the values iterated again, until play stays among
valued spots (`HoleSolver.stays_valued`): nothing could value where such an
intent goes, so it would be chosen on borrowed values and guesses alone, and
`guess` is optimistic on long holes. Screening and playing are
separate tasks, so even the first round, the tee alone, is spread over every
core.
A state not yet valued borrows from valued neighbors of the same lie class, or
failing those a guess from its distance to the pin (`guess`).
"""

import math
import multiprocessing
import os
import time
from collections.abc import Callable, Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from golf.core.clubs import VANILLA_CLUBS
from golf.core.rom_reader import RomReader
from golf.difficulty import green
from golf.difficulty.landing import (
    BASE_AIMS,
    COLUMNS,
    LIE_CLASSES,
    LandingTable,
    LieClass,
    _rest_of,
    cache_path,
    lie_class,
    load,
    scatter,
)
from golf.difficulty.player import (
    ERROR_POINTS,
    PERFECT,
    RNG_STATES,
    Hole,
    Intent,
    Position,
    Result,
    Skill,
    errors,
    outcomes,
    rng_states,
    swings,
)
from golf.formats.hole_data import HoleData
from golf.physics.landing import FIRST_SPIN_CLUB
from golf.physics.shot import Flag
from golf.physics.state import Lie, Spin
from golf.physics.tables import PhysicsTables
from golf.physics.terrain import HoleGround, TerrainTables

NO_WIND = (0, 0)

#: Value iteration's sweeps in each round. Values carry over from round to
#: round, so a round need not settle them, and where intents loop among
#: themselves (`Settings.rescreen_move`) they climb until the next round's
#: screen replaces them. The solve ends with a full run.
ROUND_SWEEPS = 300
#: Rounds past `Settings.rounds` that add no states, only screen again those
#: whose values moved, so the solve does not stop on intents that loop. Their
#: best play is kept among valued states (`HoleSolver.stays_valued`).
CLEANUP_ROUNDS = 6

#: Errors a draw when intents are raced (`Settings.race`).
RACE_POINTS = 5
#: Full swings are tried at every other aim up to this far either side of the pin.
SWING_AIMS = 64
#: How many aims the screen scores at once.
AIMS_AT_ONCE = 8
#: From spots within `NEAR_SPOT` pixels of the pin, the intents whose rest over
#: plain fairway, aimed at the pin, stops within `NEAR_PIN` of it are played on
#: the hole in the screen's first pass: the green rolls, and bites backspin,
#: unlike the fairway the table was played on. Farther out few shots stop near
#: the pin, and the table ranks them well enough.
NEAR_PIN = 24
NEAR_SPOT = 40

#: Classes of pixel in the value map: the lie classes, then these.
GREEN = len(LIE_CLASSES)
WATER = GREEN + 1
OUT = GREEN + 2

#: A state: (class, x, y), x and y a grid cell off the green and a pixel on it.
Key = tuple[int, int, int]
#: Per class, what each cell's state is worth or borrows (`HoleSolver._borrowed`),
#: by [y][x].
Borrowed = dict[int, list[list[float]]]
TEE: Key = (-1, 0, 0)


@dataclass(frozen=True)
class Settings:
    grid: int = 4
    """Off the green, the size in pixels of the cells states are made of."""
    shortlist: int = 16
    """Intents played exactly from a spot off the green when it is first screened."""
    refresh: int = 4
    """
    At most this many new intents from the top of a spot's shortlist are
    played in each later round, as the values it was screened against change.
    """
    race: int = 6
    """
    When more intents than this are new on a spot's shortlist, all are first
    played roughly (`RACE_POINTS` errors a draw, one RNG state) and only this
    many, the best that way, are played exactly: 0 plays them all exactly.
    """
    refresh_reach: float = 0.01
    """
    A spot is screened again in later rounds only while the best play visits
    it at least this often: what a spot's play can add to the tee's value is
    its visits times its own improvement.
    """
    rescreen_move: float = 0.5
    """
    A spot is screened again, however rarely play visits it, once its value
    has moved this far since it was last screened: intents chosen against
    values that were far off can loop among themselves (short hops between
    spots that all looked better than they are) and never be replaced.
    """
    tolerance: float = 0.002
    """Stop once no spots are added and the tee's value moves less than this."""
    reach: float = 1e-3
    """A spot is valued once the best play visits it this often on average."""
    blur: float = 2.0
    """The value map is blurred by this many pixels for the screen's first pass."""
    candidates: int = 32
    """
    Off the green, the best intents of this many groups from the first pass
    are scored again under the player's errors, at every aim, before the
    shortlist is taken: 0 keeps the first pass's order.
    """
    rounds: int = 12
    rng_states: int = len(RNG_STATES)
    """How many RNG states each full swing is played from (`player.rng_states`)."""
    scatter_on_hole: bool = True
    """
    The screen's second pass plays each candidate's timing errors on the hole
    from the spot itself, not over plain fairway: an approach rolls out on the
    green, where slope, friction and backspin's bite all differ.
    """
    error_points: int = ERROR_POINTS
    """About how many errors stand for each draw off the green (`player.errors`)."""


@dataclass
class Transition:
    """One intent's outcomes, as states: (next state or None when holed, strokes, probability)."""

    intent: Intent
    outcomes: list[tuple[Key | None, int, float]]
    rank: int = 0
    """Where the screen placed it on its spot's shortlist, 0 first."""
    screened: float = math.nan
    """The screen's estimate of its expected strokes."""


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
    transitions: dict[Key, list[Transition]] = field(default_factory=dict)
    """Every intent played from each state, with where the screen ranked it."""

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
    hole = Hole(ground, tables, flag)
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


def _screen(task: _Task) -> tuple[Key, list[tuple[Intent, float]], float]:
    """The intents worth playing from `task`'s spot, best first, with their scores."""
    context = _context
    assert context is not None
    started = time.perf_counter()
    terrain = context.ground.classify(task.position.x, 0, task.position.y, 0)
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
    results = outcomes(
        intent,
        position,
        context.hole,
        NO_WIND,
        context.skill,
        rng_states(_RNG_COUNT),
        _ERROR_POINTS,
    )
    return key, intent, results, time.perf_counter() - started


def _play_as(
    task: tuple[Key, Position, Intent, int, tuple[int, ...]],
) -> tuple[Key, Intent, dict[Result, float], float]:
    """Play one intent from one spot with the errors and RNG states given."""
    context = _context
    assert context is not None
    started = time.perf_counter()
    key, position, intent, points, states = task
    results = outcomes(
        intent, position, context.hole, NO_WIND, context.skill, states, points
    )
    return key, intent, results, time.perf_counter() - started


def _play_roughly(
    task: tuple[Key, Position, Intent],
) -> tuple[Key, Intent, dict[Result, float], float]:
    """Play one intent from one spot roughly, to race it against others."""
    context = _context
    assert context is not None
    started = time.perf_counter()
    key, position, intent = task
    results = outcomes(
        intent,
        position,
        context.hole,
        NO_WIND,
        context.skill,
        rng_states(1),
        RACE_POINTS,
    )
    return key, intent, results, time.perf_counter() - started


def _green_pixel(
    task: tuple[int, int, int],
) -> tuple[int, int, np.ndarray, np.ndarray, float]:
    """One pixel's putts, for the green's table."""
    context = _context
    assert context is not None
    started = time.perf_counter()
    x, y, center = task
    rests, strokes = green.build_pixel(context.hole, Position(x, y), center)
    return x, y, rests, strokes, time.perf_counter() - started


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


def _screen_swings(
    context: _Context, task: _Task, lie: LieClass
) -> list[tuple[Intent, float]]:
    table = context.table
    assert table is not None
    toward = round(_aim_to(task.position, context.flag) / 2) * 2
    aims = np.arange(toward - SWING_AIMS, toward + SWING_AIMS + 1, 2) % 256
    values = _landing_values(_values(task), task.here, _BLUR)
    height, width = values.shape
    usable = _usable(table, lie)
    best = np.full(len(usable), np.inf)
    best_aim = np.zeros(len(usable), dtype=int)
    # A few aims at a time, keeping each intent's best: all at once is
    # hundreds of megabytes a worker.
    near, rests = _near_pin(context, task, lie, toward, usable)
    for start in range(0, len(aims), AIMS_AT_ONCE):
        chunk = aims[start : start + AIMS_AT_ONCE]
        offsets = table.offsets(lie, chunk.astype(np.float32))  # (intents, aims, 2)
        if len(near):
            angle = chunk * 2 * np.pi / 256
            sin, cos = np.sin(angle)[None], np.cos(angle)[None]
            across, along = rests[:, :1], rests[:, 1:]
            offsets[near, :, 0] = along * sin + across * cos
            offsets[near, :, 1] = -along * cos + across * sin
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
    leaders = leaders[np.isfinite(best[leaders])]
    leaders = leaders[np.argsort(best[leaders])]
    if not _CANDIDATES:
        return [
            (
                table.intent(lie, int(index), int(aims[best_aim[index]])),
                float(best[index]),
            )
            for index in leaders[:_SHORTLIST]
        ]
    rest_values = _landing_values(_values(task), task.here, _SCATTER_BLUR)
    scored = [
        _scattered(
            context,
            task,
            lie,
            int(index),
            int(aims[best_aim[index]]),
            aims,
            rest_values,
        )
        for index in leaders[:_CANDIDATES]
    ]
    return sorted(scored, key=lambda item: item[1])[:_SHORTLIST]


_scatters: dict[tuple, np.ndarray] = {}


def _scattered(
    context: _Context,
    task: _Task,
    lie: LieClass,
    index: int,
    aim: int,
    aims: np.ndarray,
    values: np.ndarray,
) -> tuple[Intent, float]:
    """
    Row `index` of the table scored under the player's errors at each of
    `aims`, at the best of them: timing errors from its scatter, aim errors by
    turning it. The scatter is played on the hole itself from this spot at
    `aim` (`_SCATTER_ON_HOLE`), or over plain fairway at the base aim nearest
    `aim`; either is kept.
    """
    table = context.table
    assert table is not None
    position = task.position
    if _SCATTER_ON_HOLE:
        key = (lie, index, aim, position.x, position.y)
        played = table.intent(lie, index, aim)
        ground, start = context.ground, (position.x, position.y)
    else:
        base = BASE_AIMS[round(aim / 32) % len(BASE_AIMS)]
        key = (lie, index, base)
        played = table.intent(lie, index, base)
        ground, start = None, None
    if key not in _scatters:
        _scatters[key] = scatter(
            context.tables,
            played,
            lie,
            context.skill,
            _ERROR_POINTS,
            ground,
            start,
        )
    rows = _scatters[key]
    turns = errors(context.skill.aim, _ERROR_POINTS)
    turned = np.array([turn for turn, _ in turns], dtype=np.float64)
    weights = np.array([p for _, p in turns])[:, None] * rows[:, 2][None, :]
    angle = (aims[:, None] + turned[None, :]) * 2 * np.pi / 256  # (aims, turns)
    sin, cos = np.sin(angle)[..., None], np.cos(angle)[..., None]
    across, along = rows[:, 0], rows[:, 1]
    x = np.rint(task.position.x + along * sin + across * cos)
    y = np.rint(task.position.y - along * cos + across * sin)
    height, width = values.shape
    missing = np.isnan(x)
    x = np.where(missing, -1, x).astype(np.int32)
    y = np.where(missing, -1, y).astype(np.int32)
    inside = (x >= 0) & (x < width) & (y >= 0) & (y < height)
    # A whiff, or off the hole: a stroke and this spot again.
    score = np.full(x.shape, 1 + task.here)
    score[inside] = values[y[inside], x[inside]]
    expected = (score * weights[None]).sum(axis=(1, 2))
    best = int(expected.argmin())
    return table.intent(lie, index, int(aims[best])), float(expected[best])


def _near_pin(
    context: _Context, task: _Task, lie: LieClass, toward: int, usable: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """
    From a spot within `NEAR_SPOT` of the pin, the usable intents whose perfect
    rest over plain fairway at `toward` stops within `NEAR_PIN` of it, and where
    each really stops on the hole: (indices, (across, along) the aim in pixels).
    """
    table = context.table
    assert table is not None
    position = task.position
    pin_x, pin_y = context.flag.x >> 8, context.flag.y >> 8
    if math.hypot(position.x - pin_x, position.y - pin_y) > NEAR_SPOT:
        return np.zeros(0, dtype=int), np.zeros((0, 2))
    key = (task.key, toward)
    if key in _near_cache:
        return _near_cache[key]
    flat = table.offsets(lie, np.array([toward], dtype=np.float32))[:, 0]
    miss = np.hypot(position.x + flat[:, 0] - pin_x, position.y + flat[:, 1] - pin_y)
    near = np.nonzero(usable & (miss <= NEAR_PIN))[0]
    rests = np.empty((len(near), 2))
    aim = toward % 256
    for row, index in enumerate(near):
        intent = table.intent(lie, int(index), aim)
        (timing,) = swings(context.tables, intent, False, PERFECT)
        rests[row] = _rest_of(
            context.tables,
            intent,
            lie,
            aim,
            timing,
            context.ground,
            (position.x, position.y),
        )
    _near_cache[key] = (near, rests)
    return near, rests


#: `_near_pin`'s answers in this worker, as a spot is screened every round.
_near_cache: dict[tuple, tuple[np.ndarray, np.ndarray]] = {}


_group_cache: dict[tuple, np.ndarray] = {}


def _groups(table: LandingTable, lie: LieClass) -> np.ndarray:
    """Each intent's group: its club, speed, hi/lo and spin."""
    key = (id(table), lie, "groups")
    if key not in _group_cache:
        columns = [COLUMNS.index(c) for c in ("club", "swing_speed", "hi_lo", "spin")]
        _, ids = np.unique(table.intents[lie][:, columns], axis=0, return_inverse=True)
        _group_cache[key] = ids.reshape(-1)
    return _group_cache[key]


def _usable(table: LandingTable, lie: LieClass) -> np.ndarray:
    """
    Which of the table's intents to screen: those with a club in the vanilla
    bag, less BACK 2 wherever it plays exactly as BACK 1 does. The two differ
    only when the first bounce is on the green, for clubs from
    `FIRST_SPIN_CLUB` and shots not played from the rough (`ProcessLanding`).
    """
    key = (id(table), lie, "usable")
    if key not in _group_cache:
        intents = table.intents[lie]
        clubs = intents[:, COLUMNS.index("club")]
        usable = np.isin(clubs, [int(club) for club in VANILLA_CLUBS])
        twin = intents[:, COLUMNS.index("spin")] == Spin.BACK_2
        if lie.lie != Lie.ROUGH:
            twin &= clubs < FIRST_SPIN_CLUB
        _group_cache[key] = usable & ~twin
    return _group_cache[key]


def _landing_values(values: np.ndarray, here: float, blur: float) -> np.ndarray:
    """
    The value of the ball coming to rest on each pixel, blurred: a pixel's own
    class, with water and out of bounds a penalty stroke and this spot again.
    """
    classes = values[-1].astype(int)
    rest = np.take_along_axis(values[:-1], classes[None].clip(0, GREEN), axis=0)[0]
    rest = np.where(classes >= WATER, 1 + here, rest)
    return _blur(rest, blur)


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
_BLUR = Settings.blur
_CANDIDATES = Settings.candidates
_RNG_COUNT = Settings.rng_states
_SCATTER_ON_HOLE = Settings.scatter_on_hole
_ERROR_POINTS = Settings.error_points
#: The value map's blur for the second pass, whose errors are its own.
_SCATTER_BLUR = 1.0


def _configure(settings: Settings) -> None:
    global _SHORTLIST, _BLUR, _CANDIDATES, _RNG_COUNT, _ERROR_POINTS, _SCATTER_ON_HOLE
    _SHORTLIST, _BLUR = settings.shortlist, settings.blur
    _CANDIDATES = settings.candidates
    _RNG_COUNT, _ERROR_POINTS = settings.rng_states, settings.error_points
    _SCATTER_ON_HOLE = settings.scatter_on_hole


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

    def _borrowed(self) -> Borrowed:
        """
        Per class, a grid of values: valued states' own, spread twice to
        neighboring cells of the same class, and NaN beyond (`value` guesses).
        As lists, not arrays: `value` reads single cells, hundreds of thousands
        a sweep, and under PyPy a read from an array costs microseconds.
        """
        grid = self.settings.grid
        rows, columns = -(-self.height // grid), -(-0xB0 // grid)
        filled: Borrowed = {}
        for klass in range(len(LIE_CLASSES)):
            cells = np.full((rows, columns), np.nan)
            for key, value in self.expected.items():
                if key[0] == klass:
                    cells[key[2], key[1]] = value
            filled[klass] = _spread(cells, 2).tolist()
        green = np.full((self.height, 0xB0), np.nan)
        for key, value in self.expected.items():
            if key[0] == GREEN:
                green[key[2], key[1]] = value
        filled[GREEN] = _spread(green, 2).tolist()
        return filled

    def value(self, key: Key, borrowed: Borrowed) -> float:
        if key in self.expected:
            return self.expected[key]
        if key == TEE:
            return guess(self.distance(self.tee), 0)
        klass, x, y = key
        value = borrowed[klass][y][x]
        if math.isnan(value):
            grid = 1 if klass == GREEN else self.settings.grid
            center = Position(x * grid + grid // 2, y * grid + grid // 2)
            value = guess(self.distance(center), klass)
        return value

    def value_map(self) -> np.ndarray:
        """(class..., classes) by (y, x): each class's value at every pixel, then each pixel's class."""
        borrowed = self._borrowed()
        grid = self.settings.grid
        layers = np.zeros((GREEN + 2, self.height, 0xB0))
        ys, xs = np.mgrid[0 : self.height, 0:0xB0]
        distance = np.hypot(xs - (self.flag.x >> 8), ys - (self.flag.y >> 8))
        for klass in range(len(LIE_CLASSES)):
            cells = np.array(borrowed[klass])[ys // grid, xs // grid]
            fallback = np.vectorize(lambda d, k=klass: guess(d, k))(distance)
            layers[klass] = np.where(np.isnan(cells), fallback, cells)
        green = np.array(borrowed[GREEN])
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
                    self._q(transition, borrowed, key)
                    for transition in self.transitions[key]
                )
                change = max(change, abs(best - self.expected[key]))
                self.expected[key] = best
            if sweep % 10 == 9:
                borrowed = self._borrowed()
            if change < tolerance:
                break

    def q(self, transitions: list[Transition], own: Key | None = None) -> list[float]:
        """
        The expected strokes of playing each transition's intent, on the current
        values, from the state `own` when given (`_q`).
        """
        borrowed = self._borrowed()
        return [self._q(transition, borrowed, own) for transition in transitions]

    def _q(
        self,
        transition: Transition,
        borrowed: Borrowed,
        own: Key | None = None,
    ) -> float:
        """
        The expected strokes of a transition. Outcomes back at `own`, the state it
        is played from (a whiff, a drop, out of bounds), are solved rather than
        iterated: playing it until it leaves costs (strokes + the rest) / (1 -
        the chance of staying), which value iteration would only creep towards.
        """
        total = stay = 0.0
        for key, strokes, probability in transition.outcomes:
            total += probability * strokes
            if key is None:
                continue
            if key == own:
                stay += probability
            else:
                total += probability * self.value(key, borrowed)
        return total / (1 - stay) if stay < 1 else math.inf

    def policy(self) -> dict[Key, Transition]:
        borrowed = self._borrowed()
        return {
            key: min(transitions, key=lambda t, key=key: self._q(t, borrowed, key))
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

    def stays_valued(
        self, outcomes: list[tuple[Key | None, int, float]], visits: float
    ) -> bool:
        """
        Whether play from a state visited `visits` times a hole, by a transition
        with these outcomes, would visit no unplayed state `reach` times: the
        test a state passes to be added, so past the last round that adds any,
        a transition that fails it would be valued on borrowed values alone.
        """
        unplayed: dict[Key, float] = {}
        for key, _, probability in outcomes:
            if key is not None and key not in self.transitions:
                unplayed[key] = unplayed.get(key, 0.0) + probability
        return all(visits * p < self.settings.reach for p in unplayed.values())

    def _set_aside_unvalued(self, sweeps: int) -> list[tuple[Key, Intent]]:
        """
        Once states are no longer added: drop each chosen transition that does
        not stay among valued states (`stays_valued`) at the visits play gives
        its state, unless it is the state's last, and iterate again, until the
        best play stays among them. Such a transition is chosen on borrowed
        values and guesses alone, however long ago it was played. What it drops.
        """
        dropped: list[tuple[Key, Intent]] = []
        while True:
            inside, _ = self.visits()
            policy = self.policy()
            failing = [
                (key, transition)
                for key, transition in policy.items()
                if key[0] != GREEN
                and len(self.transitions[key]) > 1
                and not self.stays_valued(transition.outcomes, inside.get(key, 0.0))
            ]
            if not failing:
                return dropped
            for key, transition in failing:
                self.transitions[key] = [
                    t for t in self.transitions[key] if t is not transition
                ]
                dropped.append((key, transition.intent))
            self.iterate(sweeps)

    # --- rounds ---------------------------------------------------------

    def _pool(self, table_path: str | None) -> ProcessPoolExecutor:
        """
        Workers for this hole, started fresh rather than forked: a fork copies
        the whole main process, which grows with every hole solved, and each
        worker's collector soon touches (and so duplicates) all of it.
        """
        return ProcessPoolExecutor(
            self.workers,
            mp_context=multiprocessing.get_context("spawn"),
            initializer=_start,
            initargs=(
                self.rom_path,
                str(self.hole_path),
                self.pin,
                table_path,
                self.skill,
                self.settings,
            ),
        )

    def solve(self) -> Solution:
        settings = self.settings
        pending = {TEE}
        shots = 0
        started = time.perf_counter()
        with self._pool(str(self.table_path)) as pool:
            self.scratch.mkdir(parents=True, exist_ok=True)
            greens = green.GreenSolver(self._green_table(pool), self.tables, self.skill)
            round_number = 0
            previous_tee = math.inf
            inside: dict[Key, float] = {}
            screened_at: dict[Key, float] = {}
            # Intents dropped once states are no longer added, not to play again.
            set_aside: dict[Key, set[Intent]] = {}
            for round_number in range(1, settings.rounds + CLEANUP_ROUNDS + 1):
                # This round's outcomes can still be added as states (below).
                adding = round_number < settings.rounds
                clock = time.perf_counter()
                self._value_green(greens)
                greening = time.perf_counter() - clock
                values = str(self.scratch / f"values-{os.getpid()}-{round_number}.npy")
                np.save(values, self.value_map().astype(np.float32))
                borrowed = self._borrowed()
                keys = sorted(
                    {
                        k
                        for k in set(self.transitions) | pending
                        if k[0] != GREEN
                        and (
                            k not in self.transitions
                            or inside.get(k, 0.0) >= settings.refresh_reach
                            or abs(self.value(k, borrowed) - screened_at[k])
                            >= settings.rescreen_move
                        )
                    },
                    key=lambda k: (self.positions[k].y, self.positions[k].x),
                )
                screens = [
                    _Task(key, self.positions[key], values, self.value(key, borrowed))
                    for key in keys
                ]
                for task in screens:
                    screened_at[task.key] = task.here
                screening = playing = 0.0
                plays: list[tuple[Key, Position, Intent]] = []
                screened: dict[tuple[Key, Intent], tuple[int, float]] = {}
                for key, chosen, seconds in pool.map(_screen, screens, chunksize=4):
                    screening += seconds
                    played = {t.intent for t in self.transitions.get(key, [])}
                    played |= set_aside.get(key, set())
                    fresh = [
                        (rank, intent, score)
                        for rank, (intent, score) in enumerate(chosen)
                        if intent not in played
                    ]
                    if played:
                        fresh = fresh[: settings.refresh]
                    for rank, intent, score in fresh:
                        screened[key, intent] = (rank, score)
                        plays.append((key, self.positions[key], intent))
                # Only the screens read the map.
                Path(values).unlink(missing_ok=True)
                plays, racing = self._race(pool, plays, borrowed)
                # Like shots next to each other, for each worker's caches.
                plays.sort(
                    key=lambda p: (p[2].club, p[2].swing_speed, p[2].aim, p[1].y)
                )
                added = 0
                for key, intent, results, seconds in pool.map(
                    _play, plays, chunksize=4
                ):
                    playing += seconds
                    rank, score = screened[key, intent]
                    self.transitions.setdefault(key, []).append(
                        Transition(intent, self._outcomes(results), rank, score)
                    )
                    added += 1
                shots += added
                pending.clear()
                clock = time.perf_counter()
                self.iterate(ROUND_SWEEPS)
                aside = 0
                if not adding:
                    for key, intent in self._set_aside_unvalued(ROUND_SWEEPS):
                        set_aside.setdefault(key, set()).add(intent)
                        aside += 1
                iterating = time.perf_counter() - clock
                inside, outside = self.visits()
                if adding:
                    for key, mass in outside.items():
                        if mass >= settings.reach:
                            pending.add(key)
                borrowed = self._borrowed()
                due = sum(
                    abs(self.value(k, borrowed) - screened_at[k])
                    >= settings.rescreen_move
                    for k in screened_at
                )
                tee = self.expected[TEE]
                self.log(
                    f"round {round_number}: {len(keys)} of "
                    f"{sum(k[0] != GREEN for k in self.transitions)} states screened, "
                    f"{added} intents played, "
                    + (f"{aside} set aside, " if aside else "")
                    + f"{len(pending)} to add, "
                    f"{due} to screen again, "
                    f"tee {self.expected[TEE]:.3f}, "
                    f"{time.perf_counter() - started:.0f} s "
                    f"({screening:.0f} s screening, {racing:.0f} s racing, "
                    f"{playing:.0f} s playing; here {greening:.0f} s on the green, "
                    f"{iterating:.0f} s iterating)"
                )
                settled = abs(tee - previous_tee) < settings.tolerance
                if not pending and not due and (not added or settled):
                    break
                previous_tee = tee
            # Each round's iteration stopped at ROUND_SWEEPS: settle the values.
            self._value_green(greens)
            self.iterate()
            self._set_aside_unvalued(2000)
        inside, outside = self.visits()
        unvalued = [k for k, mass in outside.items() if mass >= settings.reach]
        if unvalued:
            self.log(
                f"warning: {len(unvalued)} spots the best play visits at least "
                f"{settings.reach} times a hole were never valued "
                f"({sum(outside[k] for k in unvalued):.4f} a hole)"
            )
        policy = self.policy()
        return Solution(
            dict(self.expected),
            {key: t.intent for key, t in policy.items()},
            dict(self.positions),
            inside,
            sum(outside.values()),
            round_number,
            shots,
            {key: list(ts) for key, ts in self.transitions.items()},
        )

    def recheck(
        self, points: int, states: Sequence[int], reach: float = 1e-3
    ) -> tuple[float, int]:
        """
        The tee's value, and the states played again, when the policy `solve`
        chose is played under a finer model: `points` errors a draw and the
        RNG `states`, at every state off the green its play visits at least
        `reach` times, and the green solved again at `points` (every putt is
        in its table already). The other states keep their outcomes. The
        policy is held fixed, so the gap to the solve's own value is how far
        the solve's model flattered its own choices.
        """
        policy = self.policy()
        inside, _ = self.visits()
        keys = [k for k, mass in inside.items() if k[0] != GREEN and mass >= reach]
        tasks = [
            (k, self.positions[k], policy[k].intent, points, tuple(states))
            for k in keys
        ]
        tasks.sort(key=lambda t: (t[2].club, t[2].swing_speed, t[2].aim, t[1].y))
        saved = (dict(self.transitions), dict(self.expected), dict(self.positions))
        with self._pool(None) as pool:
            played = {
                key: results
                for key, _, results, _ in pool.map(_play_as, tasks, chunksize=1)
            }
            greens = green.GreenSolver(
                self._green_table(pool), self.tables, self.skill, points
            )
        try:
            self.transitions = {k: [t] for k, t in policy.items() if k[0] != GREEN}
            for key, results in played.items():
                self.transitions[key] = [
                    Transition(policy[key].intent, self._outcomes(results))
                ]
            previous = math.inf
            for _ in range(50):
                self._value_green(greens)
                self.iterate()
                if abs(self.expected[TEE] - previous) < 1e-6:
                    break
                previous = self.expected[TEE]
            return self.expected[TEE], len(keys)
        finally:
            self.transitions, self.expected, self.positions = saved

    def _race(
        self,
        pool: ProcessPoolExecutor,
        plays: list[tuple[Key, Position, Intent]],
        borrowed: Borrowed,
    ) -> tuple[list[tuple[Key, Position, Intent]], float]:
        """
        The plays worth making exactly: where a spot has more than
        `Settings.race` new intents, the best of them played roughly.
        """
        keep = self.settings.race
        by_key: dict[Key, list[tuple[Key, Position, Intent]]] = {}
        for play in plays:
            by_key.setdefault(play[0], []).append(play)
        raced = [p for ps in by_key.values() if keep and len(ps) > keep for p in ps]
        if not raced:
            return plays, 0.0
        seconds = 0.0
        rough: dict[Key, list[tuple[float, Intent]]] = {}
        for key, intent, results, spent in pool.map(_play_roughly, raced, chunksize=4):
            seconds += spent
            expected = sum(
                p
                * (
                    r.strokes
                    + (0.0 if r.holed else self.value(self.key(r.position), borrowed))
                )
                for r, p in results.items()
            )
            rough.setdefault(key, []).append((expected, intent))
        kept = []
        for key, ps in by_key.items():
            if key not in rough:
                kept.extend(ps)
                continue
            best = {
                intent for _, intent in sorted(rough[key], key=lambda r: r[0])[:keep]
            }
            kept.extend(p for p in ps if p[2] in best)
        return kept, seconds

    def _green_table(self, pool: ProcessPoolExecutor) -> green.GreenTable:
        """The green's table of putts, built on `pool` the first time."""
        path = green.cache_path(
            Path(self.rom_path).read_bytes(),
            self.hole_path.read_bytes(),
            self.pin,
            self.scratch,
        )
        if path.exists():
            return green.load(path)
        started = time.perf_counter()
        flag = (self.flag.x >> 8, self.flag.y >> 8)
        pixels = [(int(x), int(y)) for y, x in np.argwhere(self._classes == GREEN)]
        tasks = [(x, y, green.aim_at(Position(x, y), flag)) for x, y in pixels]
        built = {
            (x, y): (rests, strokes)
            for x, y, rests, strokes, _ in pool.map(_green_pixel, tasks)
        }
        table = green.GreenTable(
            np.array(pixels, dtype=np.int16).reshape(-1, 2),
            np.array([center for _, _, center in tasks], dtype=np.int16),
            np.stack([built[p][0] for p in pixels]),
            np.stack([built[p][1] for p in pixels]),
        )
        green.save(table, path)
        self.log(
            f"green: {len(pixels)} pixels' putts played in "
            f"{time.perf_counter() - started:.0f} s"
        )
        return table

    def _value_green(self, greens: green.GreenSolver) -> None:
        """Solve the green against the current values off it, and take its states."""
        borrowed = self._borrowed()
        outside = np.array(
            [self.value(self.key(leave), borrowed) for leave in greens.leaves]
        )
        values = greens.solve(outside)
        for pixel, putts in enumerate(greens.best()):
            x, y = (int(v) for v in greens.table.pixels[pixel])
            key: Key = (GREEN, x, y)
            self.positions[key] = Position(x, y)
            self.expected[key] = float(values[pixel])
            self.transitions[key] = [
                Transition(intent, self._outcomes(results), rank, value)
                for rank, (intent, results, value) in enumerate(putts)
            ]

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
    """Fill empty cells with the mean of their filled neighbors, `times` over."""
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
