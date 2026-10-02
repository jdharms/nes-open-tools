"""
Integration: the round stats patch against the real ROM.

Every splice's expected original is checked against the vanilla bytes, the patch
applies on top of the course mirrors, and nothing outside its eight writes
changes.
"""

from pathlib import Path

import pytest

from golf.core import rom_utils
from golf.core.patches import COURSE_MIRRORS_PATCH, ROUND_STATS_PATCH, PatchError
from golf.core.patches.byte_patch import BytePatch
from golf.core.patches.round_stats import (
    CODE_BANK,
    CODE_ORIGIN,
    TRAMPOLINE_ORIGIN,
    TRAMPOLINE_VANILLA,
    build_code,
)
from golf.core.rom_writer import RomWriter

ROOT = Path(__file__).resolve().parents[2]
ROM_PATH = str(ROOT / "nes_open_us.nes")
HEADER = 0x10

pytestmark = pytest.mark.skipif(
    not Path(ROM_PATH).exists(), reason=f"{ROM_PATH} not present"
)


def mirrored_writer(out: Path) -> RomWriter:
    writer = RomWriter(ROM_PATH, str(out))
    COURSE_MIRRORS_PATCH.apply(writer)
    return writer


def splices() -> list[BytePatch]:
    return [p for p in ROUND_STATS_PATCH.patches if isinstance(p, BytePatch)]


def test_the_vanilla_rom_has_every_original_the_splices_expect() -> None:
    writer = RomWriter(ROM_PATH, "/dev/null")
    for patch in splices():
        assert patch.can_apply(writer), patch.name


def test_the_trampolines_cover_dead_greens_pointers() -> None:
    writer = RomWriter(ROM_PATH, "/dev/null")
    offset = rom_utils.cpu_to_prg_fixed(TRAMPOLINE_ORIGIN)
    assert writer.read_prg(offset, len(TRAMPOLINE_VANILLA)) == TRAMPOLINE_VANILLA


def test_requires_the_course_mirrors(tmp_path) -> None:
    writer = RomWriter(ROM_PATH, str(tmp_path / "vanilla.nes"))
    with pytest.raises(PatchError, match="requires course_mirrors"):
        ROUND_STATS_PATCH.apply(writer)


def test_applies_once_and_only_where_it_says(tmp_path) -> None:
    mirrored = mirrored_writer(tmp_path / "mirrored.nes")
    mirrored.save()
    before = (tmp_path / "mirrored.nes").read_bytes()

    writer = mirrored_writer(tmp_path / "stats.nes")
    ROUND_STATS_PATCH.apply(writer)
    assert ROUND_STATS_PATCH.is_applied(writer)
    ROUND_STATS_PATCH.apply(writer)  # a second time is a no-op
    writer.save()
    after = (tmp_path / "stats.nes").read_bytes()

    code = build_code().code
    code_offset = HEADER + CODE_BANK * 0x4000 + CODE_ORIGIN - 0x8000
    assert after[code_offset : code_offset + len(code)] == code
    allowed = set(range(code_offset, code_offset + len(code)))
    for patch in splices():
        start = HEADER + patch.prg_offset
        allowed.update(range(start, start + len(patch.patched)))
    changed = {i for i in range(len(before)) if before[i] != after[i]}
    assert changed <= allowed
    for patch in splices():
        start = HEADER + patch.prg_offset
        assert after[start : start + len(patch.patched)] == patch.patched
