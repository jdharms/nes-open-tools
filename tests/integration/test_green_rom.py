"""A green solved whole (`golf.difficulty.green`), against the player model."""

from pathlib import Path

import numpy as np
import pytest

from golf.core.rom_reader import RomReader
from golf.difficulty import green
from golf.difficulty.green import GreenSolver, GreenTable, aim_at, build_pixel
from golf.difficulty.player import RNG_STATES, Hole, Position, Skill, outcomes
from golf.formats.hole_data import HoleData
from golf.physics import Flag, HoleGround, Lie, PhysicsTables
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


@pytest.fixture(scope="module")
def table(hole) -> GreenTable:
    """Two pixels of the US 1st's green, some way from the pin, in a narrow window."""
    pin_x, pin_y = _pin(hole)
    pixels = [
        (x, y)
        for x, y in ((pin_x + 6, pin_y + 4), (pin_x - 3, pin_y - 3))
        if hole.ground.classify(x, 0, y, 0).lie == Lie.GREEN
    ]
    assert len(pixels) == 2
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(green, "AIM_WINDOW", 12)
        patch.setattr(green, "AIMS", 25)
        rows = []
        centres = []
        for x, y in pixels:
            centre = aim_at(Position(x, y), _pin(hole))
            rows.append(build_pixel(hole, Position(x, y), centre))
            centres.append(centre)
    return GreenTable(
        np.array(pixels, dtype=np.int16),
        np.array(centres, dtype=np.int16),
        np.stack([r for r, _ in rows]),
        np.stack([s for _, s in rows]),
    )


@pytest.mark.parametrize("scale", [1.0, 3.0])
def test_the_table_gives_what_outcomes_gives(hole, table, scale, monkeypatch):
    monkeypatch.setattr(green, "AIM_WINDOW", 12)
    monkeypatch.setattr(green, "AIMS", 25)
    skill = Skill.scaled(scale)
    solver = GreenSolver(table, hole.tables, skill)
    checked = 0
    for pixel, (x, y) in enumerate(table.pixels):
        for speed in range(3):
            rows = len(solver.frames[speed])
            for row in (0, rows // 3, rows // 2, rows - 1):
                for column in (0, len(solver.offsets) // 2, len(solver.offsets) - 1):
                    intent = solver.intent(pixel, speed, row, column)
                    exact = outcomes(
                        intent,
                        Position(int(x), int(y)),
                        hole,
                        (0, 0),
                        skill,
                        (RNG_STATES[0],),
                    )
                    looked_up = solver._outcomes(pixel, speed, row, column)
                    assert looked_up.keys() == exact.keys(), intent
                    for result, p in exact.items():
                        assert looked_up[result] == pytest.approx(p), (intent, result)
                    checked += 1
    assert checked == 2 * 3 * 4 * 3


def test_putts_feel_no_wind(hole, table):
    """Every putt in the table, played again in a strong wind, stops in the same place."""
    x, y = (int(v) for v in table.pixels[0])
    position = Position(x, y)
    solver = GreenSolver(table, hole.tables, Skill.scaled(1.0))
    for speed in range(3):
        intent = solver.intent(0, speed, len(solver.frames[speed]) // 2, 0)
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
