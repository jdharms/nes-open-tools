"""Integration tests: finding text in the real vanilla ROM."""

from pathlib import Path

import pytest

from golf.core.rom_reader import RomReader
from golf.core.rom_text import encodings, find_text, nametable_screens
from golf.core.text_script import script_listing

ROM_PATH = "nes_open_us.nes"

pytestmark = pytest.mark.skipif(
    not Path(ROM_PATH).exists(), reason=f"{ROM_PATH} not present"
)


@pytest.fixture(scope="module")
def rom():
    return RomReader(ROM_PATH)


def where(hits):
    return {(h.encoding, h.where(), h.text) for h in hits}


def test_text_inside_a_compressed_nametable_is_found_decoded(rom):
    hits = find_text(
        rom,
        "select the course",
        list(encodings().values()),
        set(),
        nametable_screens(rom),
    )
    assert where(hits) == {
        ("clubhouse", "bank  7 $AEB2 PPU $20CB", "Please select the course")
    }


def test_the_clubhouse_font_reads_the_clear_data_messages(rom):
    hits = find_text(rom, "1.Clear all player data", [encodings()["clubhouse"]], {14})
    assert [h.where() for h in hits] == ["bank 14 $BC34"]


def test_each_tile_font_is_where_it_was_found(rom):
    known = encodings()
    for name, text, place in [
        ("scorecard", "JAPAN COURSE", "bank  2 $AFCC"),
        ("digits30", "JAPAN COURSE", "bank  2 $BF38"),
        ("stats", "TOURNAMENT STATS", "bank  9 $BE64"),
    ]:
        hits = find_text(rom, text, [known[name]])
        assert place in {h.where() for h in hits}, name


def test_script_listing_follows_branches_and_script_picking_natives(rom):
    listing = "\n".join(script_listing(rom, [0xAA2F]))
    # The promotion offer is behind a branch, the new rank behind a call to a
    # native that picks the name from the $A072 table.
    assert '"Now it is possible for[nl]you to be promoted' in listing
    assert "picks from $A072: $A078, $A080, $A089" in listing
    assert '$A080  "SEMI-PRO"' in listing
    assert "$B7FC  stop" in listing
