"""Integration tests: green detail view shortcut against the real vanilla ROM."""

from pathlib import Path

import pytest

from golf.core.patches import (
    COURSE_MIRRORS_PATCH,
    WRAM_EXPANSION_PATCH,
    green_shortcut_patch,
    practice_swing_patch,
    seeded_wind_patch,
)
from golf.core.patches.green_shortcut import (
    CLEAR_ONLY_SPLICES,
    ENTRY_CODE_ADDR,
    ENTRY_SPLICE_PRG_OFFSET,
    POLL_CODE_ADDR,
    POLL_SPLICE_PRG_OFFSET,
    _entry_program,
)
from golf.core.rom_analysis import find_code_references
from golf.core.rom_reader import RomReader
from golf.core.rom_writer import RomWriter

#: bank 13 ShowBallLiePopup
LIE_POPUP_ADDR = 0xA5DE

ROM_PATH = "nes_open_us.nes"

pytestmark = pytest.mark.skipif(
    not Path(ROM_PATH).exists(), reason=f"{ROM_PATH} not present"
)


def test_vanilla_rom_has_expected_bytes_at_every_site(tmp_path):
    writer = RomWriter(ROM_PATH, str(tmp_path / "out.nes"))
    for sub in green_shortcut_patch().patches:
        assert sub.can_apply(writer), sub.name


def test_apply_and_reload(tmp_path):
    out = tmp_path / "green_shortcut.nes"
    writer = RomWriter(ROM_PATH, str(out))
    patch = green_shortcut_patch()
    patch.apply(writer)
    writer.save()

    reloaded = RomWriter(str(out), str(tmp_path / "unused.nes"))
    assert patch.is_applied(reloaded)


def test_applies_on_top_of_wram_expansion(tmp_path):
    """The poll routine lives in the tail of wram_expansion's $CA40 block."""
    writer = RomWriter(ROM_PATH, str(tmp_path / "wram.nes"))
    WRAM_EXPANSION_PATCH.apply(writer)
    assert green_shortcut_patch().can_apply(writer)


def test_coexists_with_seeded_wind_and_course_mirrors(tmp_path):
    """seeded_wind's trampoline at $BFAF sits just below the entry routine."""
    writer = RomWriter(ROM_PATH, str(tmp_path / "combined.nes"))
    COURSE_MIRRORS_PATCH.apply(writer)
    seeded_wind_patch("integration").apply(writer)
    patch = green_shortcut_patch()
    assert patch.can_apply(writer)
    patch.apply(writer)
    assert patch.is_applied(writer)


def test_conflicts_with_practice_swing(tmp_path):
    """Both claim $BFBF, $CAE4 and $05BB, so they are mutually exclusive."""
    writer = RomWriter(ROM_PATH, str(tmp_path / "conflict.nes"))
    green_shortcut_patch().apply(writer)
    assert not practice_swing_patch().can_apply(writer)


def test_practice_swing_first_also_conflicts(tmp_path):
    writer = RomWriter(ROM_PATH, str(tmp_path / "conflict2.nes"))
    practice_swing_patch().apply(writer)
    assert not green_shortcut_patch().can_apply(writer)


def test_patched_rom_reaches_the_new_code_from_every_splice(tmp_path):
    """Each spliced jump lands on the address it is supposed to."""
    out = tmp_path / "spliced.nes"
    writer = RomWriter(ROM_PATH, str(out))
    green_shortcut_patch().apply(writer)
    writer.save()

    reloaded = RomWriter(str(out), str(tmp_path / "unused.nes"))
    clear = _entry_program().symbol("ClearFlagThenLie")

    assert reloaded.read_prg(POLL_SPLICE_PRG_OFFSET, 3) == bytes(
        [0x4C, POLL_CODE_ADDR & 0xFF, POLL_CODE_ADDR >> 8]
    )
    assert reloaded.read_prg(ENTRY_SPLICE_PRG_OFFSET, 3) == bytes(
        [0x4C, ENTRY_CODE_ADDR & 0xFF, ENTRY_CODE_ADDR >> 8]
    )
    for _addr, prg_offset in CLEAR_ONLY_SPLICES.values():
        assert reloaded.read_prg(prg_offset, 3) == bytes(
            [0x20, clear & 0xFF, clear >> 8]
        )


def test_every_lie_panel_call_site_is_spliced(tmp_path):
    """No route into the panel may skip the flag clear.

    A raw byte count of `20 DE A5` over bank 13 finds four hits in vanilla and
    two more that are coincidences, so this asks the reference finder instead -
    it checks instruction boundaries and labeled data ranges.
    """
    reader = RomReader(ROM_PATH)
    vanilla = find_code_references(reader, LIE_POPUP_ADDR, 13).confirmed
    sites = {ref.prg for ref in vanilla}
    assert sites == {ENTRY_SPLICE_PRG_OFFSET} | {
        prg for _addr, prg in CLEAR_ONLY_SPLICES.values()
    }

    out = tmp_path / "all_sites.nes"
    writer = RomWriter(ROM_PATH, str(out))
    green_shortcut_patch().apply(writer)
    writer.save()

    patched = find_code_references(RomReader(str(out)), LIE_POPUP_ADDR, 13)
    remaining = {(ref.kind, ref.cpu) for ref in patched.confirmed}
    # only ClearFlagThenLie's own tail call is left
    program = _entry_program()
    tail_call = program.symbol("ClearFlagThenLie") + 5
    assert remaining == {("JMP", tail_call)}
