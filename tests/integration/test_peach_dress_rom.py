"""Integration tests: Peach's dress color against the real vanilla ROM."""

from pathlib import Path

import pytest

from golf.core.patches import peach_dress_patch
from golf.core.patches.peach_dress import DRESS_COLOR_ADDR, PALETTE_BANK
from golf.core.rom_reader import RomReader
from golf.core.rom_writer import RomWriter

ROM_PATH = "nes_open_us.nes"

#: bank 13: LoadGreenDetailViewTileset's Load32BytesToBuffer and its inline pointer
PALETTE_LOAD_ADDR = 0x95EB
GREEN_DETAIL_PALETTE_ADDR = 0x95FE

pytestmark = pytest.mark.skipif(
    not Path(ROM_PATH).exists(), reason=f"{ROM_PATH} not present"
)


def test_dress_is_sprite_palette_0_color_1_of_the_green_detail_palette():
    rom = RomReader(ROM_PATH)
    load = rom.read_switched(PALETTE_LOAD_ADDR, PALETTE_BANK, 5)
    assert load == bytes([0x20, 0x0A, 0xD8, 0xFE, 0x95])  # JSR $D80A / .dw $95FE
    palette = rom.read_switched(GREEN_DETAIL_PALETTE_ADDR, PALETTE_BANK, 32)
    assert palette[16:20] == bytes([0x0F, 0x25, 0x36, 0x28])
    assert DRESS_COLOR_ADDR == GREEN_DETAIL_PALETTE_ADDR + 16 + 1


def test_apply_and_reload(tmp_path):
    out = tmp_path / "peach_dress.nes"
    writer = RomWriter(ROM_PATH, str(out))
    patch = peach_dress_patch(0x2A)
    assert patch.can_apply(writer)
    patch.apply(writer)
    writer.save()

    assert RomReader(str(out)).read_switched(DRESS_COLOR_ADDR, PALETTE_BANK) == b"\x2a"
