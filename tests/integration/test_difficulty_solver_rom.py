"""
The landing table and the solver's pieces (`golf.difficulty.landing`,
`golf.difficulty.solver`). The table itself takes minutes to build, so these
build a few entries of it.
"""

import math
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from golf.core.rom_reader import RomReader
from golf.difficulty.landing import (
    BASE_AIMS,
    LIE_CLASSES,
    LandingTable,
    LieClass,
    _rest,
    encode,
    intents,
    load,
    power_targets,
    save,
)
from golf.difficulty.player import PERFECT, Hole, Intent, Position, outcomes, swings
from golf.difficulty.solver import (
    GREEN,
    TEE,
    HoleSolver,
    Settings,
    Transition,
    _blur,
    _spread,
    guess,
    pixel_class,
)
from golf.formats.hole_data import HoleData
from golf.physics import (
    Flag,
    HoleGround,
    Lie,
    PhysicsTables,
    ShotInput,
    Spin,
    Terrain,
    UniformGround,
    simulate,
)
from golf.physics.terrain import TerrainTables

ROM_PATH = "nes_open_us.nes"

pytestmark = pytest.mark.skipif(
    not Path(ROM_PATH).exists(), reason=f"{ROM_PATH} not present"
)


@pytest.fixture(scope="module")
def tables() -> PhysicsTables:
    return PhysicsTables.from_rom(RomReader(ROM_PATH))


def _small_table(tables: PhysicsTables, held: list[Intent]) -> LandingTable:
    lie = LIE_CLASSES[0]
    rests = np.array(
        [[_rest(tables, i, lie, aim) for aim in BASE_AIMS] for i in held],
        dtype=np.float32,
    )
    return LandingTable({lie: encode(held)}, {lie: rests})


def _exact(tables: PhysicsTables, intent: Intent, aim: int) -> tuple[float, float]:
    """Where `intent` at `aim` really stops over fairway, from the middle of the playfield."""
    (timing,) = swings(tables, intent, False, PERFECT)
    assert timing is not None
    shot = ShotInput(
        club=intent.club,
        swing_speed=intent.swing_speed,
        power_stop=timing.power_stop,
        accuracy_stop=timing.accuracy_stop,
        hi_lo=intent.hi_lo,
        spin=intent.spin,
        aim=aim,
        rng_state=1,
        x=88,
        y=0x400,
        frames_to_impact=timing.frames_to_impact or 0,
    )
    result = simulate(shot, UniformGround(Terrain(Lie.FAIRWAY)), tables)
    return result.rest.x - 88, result.rest.y - 0x400


@pytest.mark.parametrize(
    ("club", "accuracy", "tolerance"),
    [(0, 0x30, 3.0), (8, 0x30, 3.0), (12, 0x30, 3.0), (4, 0x40, 9.0), (12, 0x20, 9.0)],
)
def test_turned_shots_land_near_where_they_really_do(tables, club, accuracy, tolerance):
    """Straight within 2 pixels, curved within 8 (with a pixel's rounding to spare)."""
    intent = Intent(club, 0, 0x04, accuracy, 1)
    table = _small_table(tables, [intent])
    aims = np.arange(0, 256, 12)
    # Short enough either way to stay on the playfield from its middle.
    offsets = table.offsets(LIE_CLASSES[0], aims.astype(float))[0]
    checked = 0
    for aim, (dx, dy) in zip(aims, offsets, strict=True):
        if abs(math.sin(aim * 2 * math.pi / 256)) > 0.5:
            continue
        exact = _exact(tables, intent, int(aim))
        assert math.hypot(dx - exact[0], dy - exact[1]) < tolerance, aim
        checked += 1
    assert checked > 5


def test_the_table_has_every_club_speed_and_power(tables):
    held = list(intents(tables, 5))
    speeds = {i.swing_speed for i in held}
    assert speeds == {0, 1, 2}
    medium = {i.power_target for i in held if i.swing_speed == 1}
    assert medium == set(power_targets(tables, 1, putting=False))
    assert {i.spin for i in held} == {Spin.NORMAL, Spin.BACK_1, Spin.BACK_2}
    assert {i.hi_lo for i in held} == {-1, 0, 1}
    putter = list(intents(tables, 0x0F))
    assert {(i.hi_lo, i.spin, i.accuracy_target) for i in putter} == {
        (0, Spin.NORMAL, 0x30)
    }


def test_the_table_saves_and_loads(tables, tmp_path):
    held = [Intent(5, 0, 0x04), Intent(12, 0, 0x10, 0x28, 2, 1, Spin.BACK_2)]
    table = _small_table(tables, held)
    full = LandingTable(
        {lie: encode(held) for lie in LIE_CLASSES},
        {lie: table.rests[LIE_CLASSES[0]] for lie in LIE_CLASSES},
    )
    path = tmp_path / "table.npz"
    save(full, path)
    loaded = load(path)
    for lie in LIE_CLASSES:
        np.testing.assert_array_equal(loaded.intents[lie], full.intents[lie])
        assert [loaded.intent(lie, i, 7) for i in range(2)] == [
            replace(intent, aim=7) for intent in held
        ]
        np.testing.assert_array_equal(loaded.rests[lie], full.rests[lie])


def test_pixel_classes():
    assert pixel_class(Lie.GREEN, 0) == GREEN
    assert pixel_class(Lie.TEE, 0) == pixel_class(Lie.FAIRWAY, 0)
    assert pixel_class(Lie.ROUGH, 1) == LIE_CLASSES.index(LieClass(Lie.ROUGH, 1))
    assert pixel_class(Lie.BUNKER, 0, 2) == LIE_CLASSES.index(LieClass(Lie.BUNKER, 2))


def test_spread_fills_from_neighbours_only():
    cells = np.full((5, 5), np.nan)
    cells[2, 2] = 4.0
    once = _spread(cells, 1)
    assert once[1, 1] == once[2, 3] == 4.0
    assert np.isnan(once[0, 0])
    assert _spread(cells, 2)[0, 0] == 4.0


def test_blur_keeps_a_flat_map_flat_and_averages():
    flat = np.full((10, 12), 3.0)
    np.testing.assert_allclose(_blur(flat, 2.0), flat)
    spike = np.zeros((11, 11))
    spike[5, 5] = 1.0
    blurred = _blur(spike, 1.0)
    assert blurred.sum() == pytest.approx(1.0)
    assert blurred[5, 5] < 1.0


def test_guesses_grow_with_distance():
    assert guess(0, GREEN) == pytest.approx(1.0)
    assert guess(50, GREEN) < 2.0
    assert guess(100, 0) < guess(200, 0)
    assert guess(100, 0) < guess(100, pixel_class(Lie.ROUGH, 1))


def test_back_2_is_back_1_where_the_screen_drops_it(tables):
    """
    From around the US 1st's green, BACK 2 plays exactly as BACK 1 for the
    woods and from the rough, as `_usable` assumes, and not for an iron from
    the fairway.
    """
    rom = RomReader(ROM_PATH)
    hole_data = HoleData()
    hole_data.load(Path("courses/us/hole_01.json"))
    ground = HoleGround(hole_data, TerrainTables.from_rom(rom))
    flag = Flag.for_pin(hole_data, 0)
    pin_x, pin_y = flag.x >> 8, flag.y >> 8

    def near(lie: Lie) -> Position:
        for distance in range(20, 60):
            for x in range(pin_x - 8, pin_x + 9):
                y = pin_y + distance
                if ground.classify(x, 0, y, 0).lie == lie:
                    return Position(x, y)
        raise AssertionError(f"no {lie.name} below the green")

    hole = Hole(ground, tables, flag)

    def rests(club: int, position: Position, spin: Spin) -> list:
        aim = round(math.atan2(pin_x - position.x, position.y - pin_y) * 128 / math.pi)
        return [
            outcomes(
                Intent(club, aim % 256, power, spin=spin),
                position,
                hole,
                (0, 0),
                PERFECT,
            )
            for power in range(0, 0x30, 3)
        ]

    rough, fairway = near(Lie.ROUGH), near(Lie.FAIRWAY)
    for club, position in ((0, fairway), (3, fairway), (10, rough), (13, rough)):
        assert rests(club, position, Spin.BACK_1) == rests(
            club, position, Spin.BACK_2
        ), (club, position)
    assert rests(13, fairway, Spin.BACK_1) != rests(13, fairway, Spin.BACK_2)


def test_a_shot_that_can_come_back_is_solved_not_iterated():
    """A quarter of the time it stays (out of bounds, say); else 2 strokes are left."""
    solver = HoleSolver.__new__(HoleSolver)
    here, there = (0, 1, 1), (0, 5, 5)
    solver.expected = {here: 9.0, there: 2.0}
    shot = Transition(Intent(4, 0, 0), [(here, 2, 0.25), (there, 1, 0.75)])
    # V = 0.25 (2 + V) + 0.75 (1 + 2), so V = 2.75 / 0.75, whatever V was.
    assert solver._q(shot, {}, here) == pytest.approx(2.75 / 0.75)
    assert solver._q(shot, {}) == pytest.approx(0.25 * 11 + 0.75 * 3)


def test_a_shot_stays_valued_only_if_it_reaches_no_unplayed_spot_often():
    """Played spots and the hole itself are fine; an unplayed one, only rarely."""
    solver = HoleSolver.__new__(HoleSolver)
    solver.settings = Settings(reach=0.01)
    here, played, unplayed = (0, 1, 1), (0, 5, 5), (0, 9, 9)
    solver.transitions = {here: [], played: []}
    # Two results in the same unplayed cell count together: 0.02 of the shots.
    outcomes = [
        (None, 1, 0.5),
        (played, 1, 0.46),
        (unplayed, 1, 0.01),
        (unplayed, 2, 0.01),
        (here, 2, 0.02),
    ]
    assert solver.stays_valued(outcomes, visits=0.4)
    assert not solver.stays_valued(outcomes, visits=0.5)
    assert solver.stays_valued(outcomes[:2], visits=1.0)


def test_once_no_state_is_added_play_is_kept_among_valued_states():
    """The tee's hop into a cell valued only by borrowing is dropped for the honest shot."""
    solver = HoleSolver.__new__(HoleSolver)
    solver.settings = Settings(reach=0.01)
    solver.height = 32
    solver.flag = Flag(0, 0)
    solver.tee = Position(8, 30)
    played, unplayed = (0, 1, 1), (0, 2, 2)
    honest = Transition(Intent(0, 0, 0), [(played, 2, 1.0)])
    hop = Transition(Intent(13, 0, 0), [(unplayed, 1, 1.0)])
    solver.positions = {TEE: solver.tee, played: Position(4, 4)}
    solver.transitions = {
        TEE: [honest, hop],
        played: [Transition(Intent(4, 0, 0), [(None, 1, 1.0)])],
    }
    solver.expected = {}
    solver.iterate()
    # The unplayed cell borrows the played one's value: the hop looks a stroke better.
    assert solver.policy()[TEE] is hop
    assert solver._set_aside_unvalued(100) == [(TEE, hop.intent)]
    assert solver.policy()[TEE] is honest
    assert solver.expected[TEE] == pytest.approx(3.0)
    # A state's last transition stays, wherever it goes.
    solver.transitions[TEE] = [hop]
    assert solver._set_aside_unvalued(100) == []
