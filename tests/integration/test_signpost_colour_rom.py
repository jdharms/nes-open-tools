"""Integration tests: the signpost banner colour against the real vanilla ROM."""

from pathlib import Path

import pytest

from golf.core.patches import signpost_colour_patch
from golf.core.patches.signpost_colour import BANNER_COLOUR_ADDR, PALETTE_BANK
from golf.core.patches.signpost_random_banner import BODY_REGION_START
from golf.core.rom_reader import RomReader
from golf.core.rom_writer import RomWriter

ROM_PATH = "nes_open_us.nes"

#: bank 12: LC_AC2F_DrawSignpostCard's Load32BytesToBuffer and its inline pointer
PALETTE_LOAD_ADDR = 0xAC41
SIGNPOST_PALETTE_ADDR = 0xADC4

pytestmark = pytest.mark.skipif(
    not Path(ROM_PATH).exists(), reason=f"{ROM_PATH} not present"
)


def test_banner_is_background_subpalette_1_colour_3():
    rom = RomReader(ROM_PATH)
    load = rom.read_switched(PALETTE_LOAD_ADDR, PALETTE_BANK, 5)
    assert load == bytes([0x20, 0x0A, 0xD8, 0xC4, 0xAD])  # JSR $D80A / .dw $ADC4
    palette = rom.read_switched(SIGNPOST_PALETTE_ADDR, PALETTE_BANK, 16)
    assert palette[4:8] == bytes([0x0F, 0x30, 0x21, 0x15])
    assert BANNER_COLOUR_ADDR == SIGNPOST_PALETTE_ADDR + 4 + 3


def test_clear_of_the_banner_bodies_the_random_banner_reclaims():
    assert BANNER_COLOUR_ADDR < BODY_REGION_START


def test_apply_and_reload(tmp_path):
    out = tmp_path / "signpost_colour.nes"
    writer = RomWriter(ROM_PATH, str(out))
    patch = signpost_colour_patch(0x19)
    assert patch.can_apply(writer)
    patch.apply(writer)
    writer.save()

    assert (
        RomReader(str(out)).read_switched(BANNER_COLOUR_ADDR, PALETTE_BANK) == b"\x19"
    )
