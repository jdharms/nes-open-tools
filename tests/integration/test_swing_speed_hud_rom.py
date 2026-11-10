"""Integration tests: the swing speed HUD patch against the real vanilla ROM."""

from pathlib import Path

import pytest

from golf.core.graphics_codec import load_graphics_table
from golf.core.patches import SWING_SPEED_HUD_PATCH, PatchStack
from golf.core.patches.swing_speed_hud import COMMA_TILE
from golf.core.rom_reader import RomReader
from golf.randomizer.build import unfinished_steps
from golf.randomizer.catalog import US_ROM, Catalog, HoleStore
from golf.randomizer.curation import CurationSnapshot
from golf.randomizer.generate import generate
from golf.randomizer.manifest import Settings
from tests.prg_writer import PrgImageWriter

ROOT = Path(__file__).resolve().parents[2]
ROM_PATH = ROOT / "nes_open_us.nes"

pytestmark = pytest.mark.skipif(
    not ROM_PATH.exists(), reason=f"{ROM_PATH.name} not present"
)

#: the swing view's background tiles, bank 4 `ChrGraphicsTable4A8A4`
TILES_BANK, TILES_ADDR = 4, 0xA8A4
PATTERN_BASE = 0x1000
E_TILE = 0x0D


@pytest.fixture(scope="module")
def vanilla() -> bytes:
    return ROM_PATH.read_bytes()


def decoded_tiles(rom_bytes: bytes):
    return load_graphics_table(RomReader.from_bytes(rom_bytes), TILES_BANK, TILES_ADDR)


def patched(vanilla: bytes) -> bytes:
    writer = PrgImageWriter(vanilla[16:])
    SWING_SPEED_HUD_PATCH.apply(writer)
    return vanilla[:16] + bytes(writer.data)


def test_vanilla_rom_has_the_expected_bytes_at_every_site(vanilla):
    writer = PrgImageWriter(vanilla[16:])
    for sub in SWING_SPEED_HUD_PATCH.patches:
        assert sub.can_apply(writer), sub.name


def test_only_the_comma_tile_changes_and_it_becomes_an_f(vanilla):
    before_table, before = decoded_tiles(vanilla)
    after_table, after = decoded_tiles(patched(vanilla))

    changed = [a for a in range(len(before.data)) if before.data[a] != after.data[a]]
    comma = PATTERN_BASE + COMMA_TILE * 16
    assert changed == list(range(comma + 8, comma + 16))
    assert after_table.compressed_length == before_table.compressed_length

    e = before.tile(E_TILE, PATTERN_BASE)
    f = after.tile(COMMA_TILE, PATTERN_BASE)
    assert f[:5] == e[:5]  # the bar, the arm and the middle bar
    stem_only = [e[5][0]] + [0] * 7
    assert f[5] == f[6] == stem_only
    assert f[7] == [0] * 8


def test_a_randomizer_seed_with_mercy_tap_in_applies_it(vanilla, vanilla_courses):
    catalog = Catalog.load()
    manifest = generate(
        catalog,
        CurationSnapshot.load(),
        Settings(
            prng_seed="swing-speed-hud",
            sources=frozenset({US_ROM}),
            music="nes_us",
            mercy_point=10,
        ),
    )
    steps = unfinished_steps(manifest, catalog, HoleStore(vanilla_courses), vanilla)
    names = [step.name for step in steps]
    assert "mercy_tap_in" in names
    assert "swing_speed_hud" in names
    build = PatchStack(steps).build(vanilla)
    writer = PrgImageWriter(build.rom[16:])
    assert SWING_SPEED_HUD_PATCH.is_applied(writer)
