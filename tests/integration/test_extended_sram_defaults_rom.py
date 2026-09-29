"""Integration: extended SRAM defaults on the vanilla ROM, with InitializeSram run under py65."""

from pathlib import Path

import pytest

from golf.core.patches import (
    PatchStack,
    StackError,
    menu_trim_patch,
    sram_defaults_patch,
)
from golf.core.patches.extended_sram_defaults import (
    EXTENDED_SRAM_DEFAULTS_PATCH,
    BallSpin,
    SwingSpeed,
)
from golf.core.patches.sram_defaults import Club, club_bag_bytes
from tests.new_save import new_save

ROM_PATH = Path(__file__).resolve().parents[2] / "nes_open_us.nes"

pytestmark = pytest.mark.skipif(
    not ROM_PATH.exists(), reason=f"{ROM_PATH.name} not present"
)


@pytest.fixture(scope="module")
def vanilla() -> bytes:
    return ROM_PATH.read_bytes()


@pytest.fixture(scope="module")
def installed(vanilla) -> bytes:
    """The routine installed, as the unfinished build leaves it."""
    return (
        PatchStack([menu_trim_patch(), EXTENDED_SRAM_DEFAULTS_PATCH]).build(vanilla).rom
    )


def finish(installed: bytes, *steps) -> bytes:
    """A second stack over the installed routine, as the finisher runs."""
    return PatchStack(list(steps), base_sha1=None).build(installed).rom


def test_the_installed_routine_leaves_a_new_save_as_vanilla(vanilla, installed):
    assert new_save(installed) == new_save(vanilla)


def test_a_new_save_holds_the_chosen_options(installed):
    rom = finish(
        installed,
        sram_defaults_patch(
            "LUIGI",
            [Club.W1, Club.PW],
            False,
            0x5247,
            swing=SwingSpeed.FAST,
            putt=SwingSpeed.MEDIUM,
            spin=BallSpin.BACK1,
        ),
    )
    sram = new_save(rom)
    assert sram[0x0F98:0x0F9C] == bytes([0x00, 0x02, 0x01, 0x03])
    assert sram[0x0F9C:0x0FB0] == bytes([0xFF] * 20)
    assert sram[0x0004:0x000E] == b"LUIGI     "
    bag = club_bag_bytes([Club.W1, Club.PW])
    assert sram[0x0027:0x0035] == bag
    assert sram[0x0035:0x0043] == bag
    assert sram[0x0001:0x0003] == b"\x52\x47"


def test_the_routine_requires_player_stats_out_of_the_club_house(vanilla):
    with pytest.raises(StackError, match="requires menu_trim"):
        PatchStack([EXTENDED_SRAM_DEFAULTS_PATCH]).build(vanilla)


def test_the_values_require_the_routine(vanilla):
    with pytest.raises(StackError, match="requires extended_sram_defaults"):
        PatchStack(
            [
                sram_defaults_patch(
                    bgm=False,
                    swing=SwingSpeed.OFF,
                    putt=SwingSpeed.OFF,
                    spin=BallSpin.OFF,
                )
            ]
        ).build(vanilla)


def test_extended_defaults_can_be_reapplied_after_the_table_changes(installed):
    patch = sram_defaults_patch(
        "LUIGI",
        [Club.W1, Club.PW],
        False,
        0x5247,
        swing=SwingSpeed.FAST,
        putt=SwingSpeed.MEDIUM,
        spin=BallSpin.BACK1,
    )
    finished = finish(installed, patch)
    assert finish(finished, patch) == finished


def test_sram_defaults_bgm_edit_refuses_the_spliced_loop(installed):
    with pytest.raises(StackError, match="sram_defaults_bgm_off"):
        finish(installed, sram_defaults_patch(bgm=False))
