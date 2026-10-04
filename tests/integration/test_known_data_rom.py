"""Integration tests: the known data regions measured from the real vanilla ROM."""

from pathlib import Path

import pytest

from golf.core.known_data import known_regions
from golf.core.object_script import trace_everything
from golf.core.rom_reader import RomReader
from golf.core.rom_trace import OPCODE, OPERAND
from golf.core.rom_utils import cpu_to_prg_switched

ROM_PATH = "nes_open_us.nes"

pytestmark = pytest.mark.skipif(
    not Path(ROM_PATH).exists(), reason=f"{ROM_PATH} not present"
)


@pytest.fixture(scope="module")
def measured():
    reader = RomReader(ROM_PATH)
    result, scripts, objects = trace_everything(reader)
    return result, known_regions(reader, result, scripts, objects)


def by_name(regions, name):
    return next(r for r in regions if r.name == name)


def test_regions_do_not_overlap(measured):
    _, regions = measured
    for before, after in zip(regions, regions[1:], strict=False):
        assert before.end < after.start, (before.name, after.name)


def test_no_region_is_traced_code(measured):
    result, regions = measured
    for region in regions:
        assert not any(
            result.marks[p] in (OPCODE, OPERAND)
            for p in range(region.start, region.end + 1)
        ), region.name


@pytest.mark.parametrize(
    ("name", "bank", "next_table"),
    [
        # Each course's terrain stops at the byte before a golfer CHR table:
        # the last hole's attributes are shorter than the 72-byte window.
        ("JapanCourseTerrainData", 0, 0xA238),
        ("USCourseTerrainData", 1, 0xA1E0),
        ("UKCourseTerrainData", 2, 0xA54E),
    ],
)
def test_terrain_ends_where_the_golfer_chr_begins(measured, name, bank, next_table):
    _, regions = measured
    assert by_name(regions, name).end == cpu_to_prg_switched(next_table, bank) - 1


def test_uk_terrain_starts_after_bank_2s_tables(measured):
    _, regions = measured
    assert by_name(regions, "UKCourseTerrainData").cpu == 0x837F


def test_greens_follow_their_decompression_tables(measured):
    _, regions = measured
    assert by_name(regions, "GreensDictionaryTable").cpu == 0x8180
    assert by_name(regions, "GreensCompressedData").cpu == 0x81C0


def test_a_shared_stream_is_its_own_region(measured):
    # Bank 6 $9309 and $930E both decode the stream at $9315.
    _, regions = measured
    shared = by_name(regions, "ChrGraphicsStreams69315")
    assert "$9309" in shared.comment and "$930E" in shared.comment
    assert by_name(regions, "ChrGraphicsTable6930E").length == 7  # header only


def test_the_window_table_ends_where_the_first_dk_script_begins(measured):
    _, regions = measured
    table = by_name(regions, "ScriptWindowGeometryTable")
    assert table.end + 1 == by_name(regions, "TextScriptB9658").start


def test_opponent_shots_fill_bank_3_between_the_replay_code(measured):
    # $A923 follows the replay code; $BEE8 is the next routine.
    _, regions = measured
    shots = sorted((r for r in regions if r.kind == "opponent"), key=lambda r: r.start)
    assert shots[0].cpu == 0xA923
    assert shots[-1].end == cpu_to_prg_switched(0xBEE7, 3)
    for before, after in zip(shots, shots[1:], strict=False):
        assert before.end + 1 == after.start


def test_every_opponent_shot_list_is_a_seed_and_whole_records():
    rom = RomReader(ROM_PATH)
    bank = rom.read_switched(0x8000, 3, 0x4000)

    def word(cpu):
        return bank[cpu - 0x8000] | bank[cpu - 0x7FFF] << 8

    lists, tables = set(), []
    for course in range(3):
        table = bank[0xA923 - 0x8000 + course] | bank[0xA926 - 0x8000 + course] << 8
        tables.append(table)
        lists |= {word(table + 2 * i) for i in range(18 * 4)}
    # Each list runs to the next list or the next course's pointer table.
    bounds = sorted(lists | set(tables) | {0xBEE8})
    for start in sorted(lists):
        end = bounds[bounds.index(start) + 1]
        assert (end - start - 2) % 5 == 0, hex(start)


def test_metasprites_use_their_renderers_format(measured):
    # RenderMetaspriteWithAttr's 3-byte sprites: bank 9's sixteen at $A85F end
    # where the next code starts, and bank 13's six are 13 bytes apart.
    _, regions = measured
    run = by_name(regions, "Metasprites9A85F")
    assert run.end == cpu_to_prg_switched(0xACBB, 9)
    assert by_name(regions, "MetaspritesD9E24").length == 6 * 13


def test_palettes_are_32_bytes_from_load32bytestobuffer(measured):
    _, regions = measured
    palettes = [r for r in regions if r.kind == "palette"]
    assert len(palettes) >= 24
    assert {r.length for r in palettes} == {32}


def test_nametable_descriptors_measure_their_data(measured):
    _, regions = measured
    # 22x5 inline tiles to $20A3 after a 4-byte header.
    assert by_name(regions, "NametableDescriptor3BEF8").length == 4 + 22 * 5
    # Mode 1 (WriteNametableTilesMode1) repeats one tile: header and one byte.
    assert by_name(regions, "NametableDescriptor3BEF3").length == 5
    # A source pointer: the header, the pointer, and the tiles separately.
    assert by_name(regions, "NametableDescriptorB8C46").length == 6
    assert by_name(regions, "NametableSourceDataB8F45").length == 6
