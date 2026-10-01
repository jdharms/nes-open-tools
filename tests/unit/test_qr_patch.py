"""
The scorecard QR patch: what it builds, and the patch that disables it.

The patch's job is to put the right bytes in the right three places, with the
credential placeholders left at the fill for `qr_credentials` to finish
(`tests/unit/test_qr_credentials.py`). These tests check the bytes.
"""

import pytest

from golf.core import rom_utils
from golf.core.patches import (
    COURSE_MIRRORS_PATCH,
    QR_DISABLE_PATCH,
    ROUND_STATS_PATCH,
    SCORECARD_QR_PATCH,
    PatchError,
    ScorecardQrPatch,
)
from golf.core.patches.qr_credentials import PLACEHOLDERS, placeholder_offset
from golf.core.patches.scorecard_qr import (
    EXECUTE_FAR_CALL,
    PLACEHOLDER_ADDRESSES,
    QR_BANK,
    SCORECARD_WAIT,
    TRAMPOLINE_CPU_ADDR,
    TRAMPOLINE_ENTRY_BYTES,
    TRAMPOLINE_LIMIT,
    build_trampoline,
)
from golf.qr import port
from golf.qr.port import layout


@pytest.fixture(scope="module")
def patch() -> ScorecardQrPatch:
    return SCORECARD_QR_PATCH


# --------------------------------------------------------------------------
# The image
# --------------------------------------------------------------------------


def test_the_image_is_the_port_as_assembled(patch) -> None:
    assert patch.image == port.rom_bytes()


def test_the_placeholders_are_left_at_the_fill(patch) -> None:
    """An unfinished build must not look like a valid cartridge."""
    program = port.build()
    for _, symbol, length in PLACEHOLDERS:
        start = program.symbol(symbol) - layout.TABLE_ORIGIN
        assert patch.image[start : start + length] == bytes([port.PATCH_FILL]) * length


def test_the_fill_is_zero() -> None:
    """The server rejects an all-zero seed or player ID."""
    assert port.PATCH_FILL == 0x00


def test_the_image_fits_the_reclaimed_region(patch) -> None:
    end = layout.TABLE_ORIGIN + len(patch.image) - 1
    assert layout.REGION_START <= layout.TABLE_ORIGIN
    assert end <= layout.REGION_END
    assert layout.REGION_END - end > 4000  # room left for whatever comes next


# --------------------------------------------------------------------------
# The trampoline and the splice
# --------------------------------------------------------------------------


def test_the_trampoline_waits_then_far_calls(patch) -> None:
    assert patch.trampoline == bytes(
        [
            0x20,
            SCORECARD_WAIT & 0xFF,
            SCORECARD_WAIT >> 8,
            0x20,
            EXECUTE_FAR_CALL & 0xFF,
            EXECUTE_FAR_CALL >> 8,
            QR_BANK,
            patch.entry & 0xFF,
            patch.entry >> 8,
            0x60,
        ]
    )
    assert len(patch.trampoline) == 10


def test_the_trampoline_carries_whatever_entry_point_it_is_given() -> None:
    trampoline = build_trampoline(0xABCD)
    assert trampoline[6:9] == bytes([QR_BANK, 0xCD, 0xAB])
    assert len(trampoline) == 10


def test_the_trampoline_fits_the_dead_greens_pointer_slots(patch) -> None:
    # slots 18-53 of the greens pointer table, up to the par table
    assert TRAMPOLINE_CPU_ADDR == rom_utils.TABLE_GREENS_PTR + 36 == 0xDCBD
    assert TRAMPOLINE_LIMIT == rom_utils.TABLE_PAR == 0xDD05
    assert TRAMPOLINE_CPU_ADDR + len(patch.trampoline) <= TRAMPOLINE_LIMIT


def test_requires_course_mirrors_and_round_stats(patch) -> None:
    """The payload copies the fairway and penalty bytes round_stats keeps."""
    assert list(patch.requires) == [COURSE_MIRRORS_PATCH, ROUND_STATS_PATCH]


def test_the_splice_repoints_the_wait_at_the_trampoline(patch) -> None:
    assert patch.vanilla_splice_bytes == bytes(
        [SCORECARD_WAIT & 0xFF, SCORECARD_WAIT >> 8]
    )
    assert patch.splice_bytes == bytes(
        [TRAMPOLINE_CPU_ADDR & 0xFF, TRAMPOLINE_CPU_ADDR >> 8]
    )


def test_the_offsets_are_where_those_banks_live(patch) -> None:
    assert patch.image_offset == 2 * 0x4000 + (layout.TABLE_ORIGIN - 0x8000)
    assert patch.trampoline_offset == 15 * 0x4000 + (TRAMPOLINE_CPU_ADDR - 0xC000)
    assert patch.splice_offset == 13 * 0x4000 + (0x852E - 0x8000)


def test_a_trampoline_entry_point_is_inside_the_region(patch) -> None:
    assert layout.REGION_START <= patch.entry <= layout.REGION_END
    assert patch.entry == port.build().symbol("QrShowCodes")


def test_an_image_that_would_not_fit_is_refused(monkeypatch) -> None:
    """Moving the origin near the end of the region has to fail loudly."""
    monkeypatch.setattr(layout, "TABLE_ORIGIN", layout.REGION_END - 100)
    with pytest.raises(PatchError):
        ScorecardQrPatch()


# --------------------------------------------------------------------------
# qr_disable
# --------------------------------------------------------------------------


def test_disable_reverts_exactly_the_splice(patch) -> None:
    assert QR_DISABLE_PATCH.name == "qr_disable"
    assert QR_DISABLE_PATCH.prg_offset == patch.splice_offset
    assert QR_DISABLE_PATCH.original == patch.splice_bytes
    assert QR_DISABLE_PATCH.patched == patch.vanilla_splice_bytes


# --------------------------------------------------------------------------
# The finishing contract (ADR 0009)
#
# Everything the finishing patches rely on, as literals. Stored unfinished ROMs
# from every build version under finish ABI 2 have these bytes here, so a change
# to any of them is a finish ABI bump, not a build version bump.
# --------------------------------------------------------------------------


def test_the_placeholders_are_pinned() -> None:
    assert PLACEHOLDER_ADDRESSES == {
        "QrSeedId": 0x8E5F,
        "QrPlayerId": 0x8E67,
        "QrMacKey": 0x8E6F,
    }
    assert [(symbol, length) for _, symbol, length in PLACEHOLDERS] == [
        ("QrSeedId", 8),
        ("QrPlayerId", 8),
        ("QrMacKey", 16),
    ]
    assert port.PATCH_FILL == 0x00


def test_the_port_puts_the_placeholders_at_their_pinned_addresses() -> None:
    program = port.build()
    for symbol, address in PLACEHOLDER_ADDRESSES.items():
        assert program.symbol(symbol) == address, symbol


def test_finishing_writes_at_the_pinned_addresses() -> None:
    for _, symbol, _ in PLACEHOLDERS:
        assert placeholder_offset(symbol) == 2 * 0x4000 + (
            PLACEHOLDER_ADDRESSES[symbol] - 0x8000
        )


def test_a_port_that_moves_a_placeholder_is_refused(monkeypatch) -> None:
    monkeypatch.setitem(PLACEHOLDER_ADDRESSES, "QrMacKey", 0x8E70)
    with pytest.raises(PatchError, match="QrMacKey"):
        ScorecardQrPatch()


def test_the_splice_and_trampoline_shape_are_pinned(patch) -> None:
    assert patch.splice_offset == 0x3452E
    assert patch.splice_bytes == bytes([0xBD, 0xDC])
    assert patch.trampoline_offset == 0x3DCBD
    shape = bytes(patch.trampoline[:7]) + bytes(patch.trampoline[9:])
    assert shape == bytes([0x20, 0xBA, 0x85, 0x20, 0x72, 0xD3, 0x02, 0x60])
    assert list(TRAMPOLINE_ENTRY_BYTES) == [7, 8]


class _Rom:
    """Just enough of a RomWriter for `is_applied`."""

    def __init__(self, contents: dict[int, bytes]) -> None:
        self.contents = contents

    def read_prg(self, offset: int, length: int) -> bytes:
        return self.contents[offset][:length]


def test_applied_does_not_depend_on_where_the_entry_point_is(patch) -> None:
    """A ROM from an earlier build version, whose routine sat elsewhere."""
    moved = build_trampoline(patch.entry + 0x123)
    rom = _Rom(
        {patch.splice_offset: patch.splice_bytes, patch.trampoline_offset: moved}
    )
    assert patch.is_applied(rom)


def test_applied_still_checks_the_trampoline_shape(patch) -> None:
    broken = bytearray(patch.trampoline)
    broken[6] = 0x03  # far call into the wrong bank
    rom = _Rom(
        {
            patch.splice_offset: patch.splice_bytes,
            patch.trampoline_offset: bytes(broken),
        }
    )
    assert not patch.is_applied(rom)
