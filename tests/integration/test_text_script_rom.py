"""Integration tests: the text script walker against the real vanilla ROM."""

from pathlib import Path

import pytest

from golf.core.rom_reader import RomReader
from golf.core.rom_trace import OPCODE, OPERAND
from golf.core.text_script import (
    CALL_NATIVE_SITE,
    RESUME_CALLBACK_SITE,
    SCRIPT_BANK,
    trace_with_scripts,
)

ROM_PATH = "nes_open_us.nes"

pytestmark = pytest.mark.skipif(
    not Path(ROM_PATH).exists(), reason=f"{ROM_PATH} not present"
)


@pytest.fixture(scope="module")
def walked():
    return trace_with_scripts(RomReader(ROM_PATH))


def prg(cpu: int) -> int:
    return SCRIPT_BANK * 0x4000 + cpu - 0x8000


def test_every_script_decodes(walked):
    _, walk = walked
    assert walk.problems == []


def test_the_documented_entry_points_are_found(walked):
    # docs/course_intro_scene.md and docs/prize_money.md
    _, walk = walked
    for cpu in (0x9658, 0xA0EE, 0xA2D5, 0xA33C, 0xA8A2, 0xAA2F, 0xB8DD, 0xBC7D):
        assert cpu in walk.entries


def test_native_calls_reach_the_prize_money_routines(walked):
    result, walk = walked
    for cpu in (0x94DC, 0x9511, 0x9554, 0x956B, 0x95D5):
        assert cpu in walk.native
        assert result.marks[prg(cpu)] == OPCODE


def test_script_bytes_are_not_code(walked):
    result, walk = walked
    assert not any(result.marks[prg(c)] in (OPCODE, OPERAND) for c in walk.covered)


def test_the_script_driven_jumps_are_answered(walked):
    result, _ = walked
    sites = {prg(CALL_NATIVE_SITE), prg(RESUME_CALLBACK_SITE)}
    assert not sites & {f.prg for f in result.unresolved}


def test_the_scripts_use_four_windows(walked):
    _, walk = walked
    assert walk.windows == {0, 1, 2, 3}
