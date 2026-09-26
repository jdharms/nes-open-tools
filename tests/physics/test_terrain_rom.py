"""
`HoleGround` against the ROM's own `ClassifyProbePosition`, at every pixel of
every vanilla hole: the NES Open holes on the vanilla ROM, and the Mario Open
holes on one with the `wram_expansion` patch, which the tallest need and the
randomizer plays them all on.

The ROM side loads each hole into RAM the way the game's loader does (terrain
rows, packed attributes, green grid, green position and scroll limit) and runs
the probe under py65. Every field of the result must match, including the green
slope bytes and the tree flags.
"""

from pathlib import Path

import pytest

from golf.core.patches import WRAM_EXPANSION_PATCH
from golf.core.rom_reader import RomReader
from golf.core.rom_writer import RomWriter
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


@pytest.fixture(scope="module")
def expanded_rom(tmp_path_factory) -> RomReader:
    path = tmp_path_factory.mktemp("rom") / "wram_expansion.nes"
    writer = RomWriter(ROM_PATH, str(path))
    WRAM_EXPANSION_PATCH.apply(writer)
    writer.save()
    return RomReader(str(path))


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


@pytest.mark.parametrize("number", range(1, 19))
@pytest.mark.parametrize("course", MARIO_OPEN_COURSES)
def test_mario_open_hole(expanded_rom, vanilla_jp_courses, course, number):
    hole = load_hole(vanilla_jp_courses / "jp", course, number)
    tables = TerrainTables.from_rom(expanded_rom)
    assert_every_pixel_matches(expanded_rom, tables, hole)


def test_tall_holes_need_the_expanded_buffer(tables, vanilla_jp_courses):
    """The vanilla terrain buffer holds 48 rows; the green's buffer follows it."""
    assert tables.terrain_rows == 48
    hole = load_hole(vanilla_jp_courses / "jp", "jp_uk", 14)
    assert hole.terrain_height == 60
    with pytest.raises(ValueError, match="wram_expansion"):
        HoleGround(hole, tables)


def test_expanded_tables(expanded_rom):
    tables = TerrainTables.from_rom(expanded_rom)
    assert tables.terrain_rows == 60
    assert [tables.bottom_y[limit] for limit in (1, 9, 11, 16)] == [
        240,
        368,
        400,
        480,
    ]
