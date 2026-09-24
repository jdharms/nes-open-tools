"""
`HoleGround` against the ROM's own `ClassifyProbePosition`, at every pixel of
every vanilla hole.

The ROM side loads each hole into RAM the way the game's loader does (terrain
rows, packed attributes, green grid, green position and scroll limit) and runs
the probe under py65. Every field of the result must match, including the green
slope bytes and the tree flags.
"""

import random
from pathlib import Path

import pytest

from golf.core.rom_reader import RomReader
from golf.formats.hole_data import HoleData
from golf.physics.rom_oracle import RomTerrainProbe
from golf.physics.terrain import HoleGround, TerrainTables

ROM_PATH = "nes_open_us.nes"
NES_OPEN_COURSES = ["japan", "us", "uk"]
MARIO_OPEN_COURSES = ["jp_japan", "jp_australia", "jp_france", "jp_hawaii", "jp_uk"]

pytestmark = pytest.mark.skipif(
    not Path(ROM_PATH).exists(), reason=f"{ROM_PATH} not present"
)


@pytest.fixture(scope="module")
def rom() -> RomReader:
    return RomReader(ROM_PATH)


@pytest.fixture(scope="module")
def tables(rom) -> TerrainTables:
    return TerrainTables.from_rom(rom)


def assert_every_pixel_matches(rom, tables, hole: HoleData) -> None:
    ground = HoleGround(hole, tables)
    oracle = RomTerrainProbe(rom, hole)
    # Past the right edge and the bottom too, where both should say out of bounds.
    for y in range(hole.terrain_height * 8 + 8):
        for x in range(0xB4):
            model = ground.classify(x, 0x80, y, 0x80)
            assert model == oracle.classify(x, 0x80, y, 0x80), (x, y)


def load_hole(courses: Path, course: str, number: int) -> HoleData:
    hole = HoleData()
    hole.load(courses / course / f"hole_{number:02}.json")
    return hole


@pytest.mark.parametrize("number", range(1, 19))
@pytest.mark.parametrize("course", NES_OPEN_COURSES)
def test_nes_open_hole(rom, tables, vanilla_courses, course, number):
    assert_every_pixel_matches(rom, tables, load_hole(vanilla_courses, course, number))


def test_mario_open_holes_sampled(rom, tables, vanilla_jp_courses):
    """Mario Open holes that fit the vanilla ROM's 48 rows, at random pixels."""
    rng = random.Random(0)
    checked = 0
    for course in MARIO_OPEN_COURSES:
        for number in range(1, 19):
            hole = load_hole(vanilla_jp_courses / "jp", course, number)
            if hole.metadata["scroll_limit"] >= len(tables.bottom_y):
                continue
            ground = HoleGround(hole, tables)
            oracle = RomTerrainProbe(rom, hole)
            for _ in range(500):
                args = (
                    rng.randrange(0xB0),
                    rng.randrange(256),
                    rng.randrange(hole.terrain_height * 8),
                    rng.randrange(256),
                )
                assert ground.classify(*args) == oracle.classify(*args), (
                    course,
                    number,
                    args,
                )
            checked += 1
    assert checked
