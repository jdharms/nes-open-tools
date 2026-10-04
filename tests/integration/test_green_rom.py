"""A green solved whole (`golf.difficulty.green`), against the player model."""

from pathlib import Path

import numpy as np
import pytest

from golf.core.rom_reader import RomReader
from golf.difficulty import green
from golf.difficulty.green import GreenSolver, GreenTable, aim_at, build_pixel
from golf.difficulty.player import (
    EVERY_UNIT,
    RNG_STATES,
    Hole,
    Intent,
    Position,
    Skill,
    outcomes,
)
from golf.formats.hole_data import HoleData
from golf.physics import Flag, HoleGround, Lie, PhysicsTables
from golf.physics.state import PUTTER
from golf.physics.terrain import TerrainTables

ROM_PATH = "nes_open_us.nes"

pytestmark = pytest.mark.skipif(
    not Path(ROM_PATH).exists(), reason=f"{ROM_PATH} not present"
)


@pytest.fixture(scope="module")
def hole() -> Hole:
    rom = RomReader(ROM_PATH)
    tables = PhysicsTables.from_rom(rom)
    data = HoleData()
    data.load(Path("courses/us/hole_01.json"))
    ground = HoleGround(data, TerrainTables.from_rom(rom))
    return Hole(ground, tables, Flag.for_pin(data, 0))


def _pin(hole: Hole) -> tuple[int, int]:
    assert hole.flag is not None
    return hole.flag.x >> 8, hole.flag.y >> 8


@pytest.fixture(params=[(6, 4), (-3, -3)], ids=["below-pin", "above-pin"])
def position(hole, request) -> Position:
    pin_x, pin_y = _pin(hole)
    dx, dy = request.param
    return Position(pin_x + dx, pin_y + dy)


@pytest.fixture(params=range(3), ids=["slow", "medium", "fast"])
def speed(request) -> int:
    return request.param


@pytest.fixture
def table(hole, position, speed, monkeypatch) -> GreenTable:
    """Build the tested pixel/speed only; the other speeds stay UNREACHED.

    Each case still plays every reachable stop and all 25 aims at its speed.
    Narrowing the build lets xdist distribute six independent pieces of work.
    """
    x, y = position.x, position.y
    assert hole.ground.classify(x, 0, y, 0).lie == Lie.GREEN
    monkeypatch.setattr(green, "AIM_WINDOW", 12)
    monkeypatch.setattr(green, "AIMS", 25)
    reachable = green.reachable
    monkeypatch.setattr(
        green,
        "reachable",
        lambda tables, at: reachable(tables, at) if at == speed else frozenset(),
    )
    center = aim_at(position, _pin(hole))
    rests, strokes = build_pixel(hole, position, center)
    return GreenTable(
        np.array([(x, y)], dtype=np.int16),
        np.array([center], dtype=np.int16),
        rests[np.newaxis],
        strokes[np.newaxis],
    )


def test_the_table_gives_what_outcomes_gives(hole, table, speed):
    # Both skills share the table built in this worker; parametrizing skills as
    # separate tests would build the expensive table again on another worker.
    checked = 0
    for scale in (1.0, 3.0):
        skill = Skill.scaled(scale)
        solver = GreenSolver(table, hole.tables, skill)
        for pixel, (x, y) in enumerate(table.pixels):
            rows = len(solver.frames[speed])
            for row in (0, rows // 3, rows // 2, rows - 1):
                for column in (
                    0,
                    len(solver.offsets) // 2,
                    len(solver.offsets) - 1,
                ):
                    intent = solver.intent(pixel, speed, row, column)
                    exact = outcomes(
                        intent,
                        Position(int(x), int(y)),
                        hole,
                        (0, 0),
                        skill,
                        (RNG_STATES[0],),
                        EVERY_UNIT,
                    )
                    looked_up = solver._outcomes(pixel, speed, row, column)
                    assert looked_up.keys() == exact.keys(), intent
                    for result, p in exact.items():
                        assert looked_up[result] == pytest.approx(p), (
                            intent,
                            result,
                        )
                    checked += 1
    assert checked == 2 * 4 * 3


def test_putts_feel_no_wind(hole):
    """A putt at each speed, played in strong winds, stops in the same place."""
    pin_x, pin_y = _pin(hole)
    position = Position(pin_x + 6, pin_y + 4)
    for speed in range(3):
        frames = green.aimed_frames(hole.tables, speed)
        frame = frames[len(frames) // 2]
        stop = green.frame_stops(hole.tables, speed)[frame - 1]
        intent = Intent(
            PUTTER,
            (aim_at(position, _pin(hole)) - 10) & 0xFF,
            stop,
            swing_speed=speed,
        )
        calm = outcomes(intent, position, hole, (0, 0), Skill.scaled(1.0))
        for wind in ((0, 15), (64, 15), (160, 9)):
            assert outcomes(intent, position, hole, wind, Skill.scaled(1.0)) == calm


def test_value_iteration_on_a_made_up_green():
    """
    Three pixels in a row: from the first every putt stops on the second,
    from the second every putt drops, and the third only ever leaves the
    green for a spot worth 2.5 strokes.
    """
    tables = PhysicsTables.from_rom(RomReader(ROM_PATH))
    shape = (3, green.SPEEDS, green.STOPS, green.AIMS)
    strokes = np.ones(shape, dtype=np.int8)
    rests = np.zeros(shape + (3,), dtype=np.int16)
    rests[0, ..., 0] = 1  # the first pixel's putts stop on the second, (1, 0)
    strokes[1] = green.IN_CUP
    rests[2, ..., 0] = 9  # off the green
    rests[2, ..., 1] = 9
    table = GreenTable(
        np.array([(0, 0), (1, 0), (2, 0)], dtype=np.int16),
        np.zeros(3, dtype=np.int16),
        rests,
        strokes,
    )
    solver = GreenSolver(table, tables, Skill.scaled(1.0))
    assert solver.leaves == [Position(9, 9)]
    values = solver.solve(np.array([2.5]))
    np.testing.assert_allclose(values, [2.0, 1.0, 3.5])
    (intent, results, value), *_ = solver.best()[0]
    assert value == pytest.approx(2.0)
    assert set(results) == {green.Result(Position(1, 0), 1, False)}
