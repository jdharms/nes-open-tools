"""Integration tests: the scene object walk against the real vanilla ROM."""

from collections import Counter
from pathlib import Path

import pytest

from golf.core.object_script import trace_everything
from golf.core.rom_reader import RomReader
from golf.core.rom_trace import OPCODE

ROM_PATH = "nes_open_us.nes"

pytestmark = pytest.mark.skipif(
    not Path(ROM_PATH).exists(), reason=f"{ROM_PATH} not present"
)


@pytest.fixture(scope="module")
def traced():
    return trace_everything(RomReader(ROM_PATH))


def test_every_record_settles_on_one_bank(traced):
    _, _, objects = traced
    # The one known exception: bank 10's $9D65 animation stream ends each branch in a
    # 160-frame hold and a goto that leads nowhere sensible ($F798, $00C8); the scene
    # presumably replaces the object before either goto runs.
    assert [(p.kind, p.bank, p.cpu) for p in objects.problems] == [
        ("stream set by code", 10, 0x9D65)
    ]
    assert len(objects.banks) == len(objects.records)


def test_menus_use_bank_2_and_cutscenes_bank_10(traced):
    _, _, objects = traced
    by_table_bank = Counter(
        (rec.bank, objects.banks[i]) for i, rec in enumerate(objects.records)
    )
    assert {bank for (table, bank) in by_table_bank if table in (9, 11, 14)} == {2}
    assert {bank for (table, bank) in by_table_bank if table == 12} == {10}


def test_no_control_flow_is_left_unresolved(traced):
    result, _, _ = traced
    assert result.unresolved == []


def test_the_scene_callback_reaches_bank_10_code(traced):
    # LF8A2's inline word at bank 12 $B936 is $9B57, run by JMP ($7B11).
    result, _, _ = traced
    assert result.marks[10 * 0x4000 + 0x9B57 - 0x8000] == OPCODE
