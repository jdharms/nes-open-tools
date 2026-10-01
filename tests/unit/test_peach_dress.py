"""Peach's dress colour patch: the curated colours and the byte it writes."""

from pathlib import Path

import pytest

from golf.core import rom_utils
from golf.core.palettes import NES_BLACK_ENTRIES
from golf.core.patches import (
    DRESS_COLOUR_FAMILIES,
    DRESS_COLOURS,
    parse_step_arg,
    peach_dress_patch,
)
from golf.core.patches.peach_dress import VANILLA_DRESS_COLOUR

HAIR, SKIN = 0x28, 0x36


class TestColours:
    def test_no_colour_is_in_two_families(self):
        total = sum(len(family) for family in DRESS_COLOUR_FAMILIES.values())
        assert total == len(DRESS_COLOURS) == 43

    def test_vanilla_is_curated(self):
        assert VANILLA_DRESS_COLOUR in DRESS_COLOUR_FAMILIES["pink"]

    def test_no_black_hair_or_skin(self):
        assert not DRESS_COLOURS & (NES_BLACK_ENTRIES | {HAIR, SKIN})

    def test_every_colour_is_an_nes_colour(self):
        assert all(0 <= colour <= 0x3F for colour in DRESS_COLOURS)


class TestPatch:
    def test_writes_the_dress_entry(self):
        patch = peach_dress_patch(0x16)
        assert patch.prg_offset == rom_utils.cpu_to_prg_switched(0x960F, 13)
        assert patch.original == bytes([0x25])
        assert patch.patched == bytes([0x16])

    @pytest.mark.parametrize("colour", [0x0F, 0x0D, HAIR, SKIN, 0x0A, 0x40])
    def test_rejects_uncurated_colours(self, colour):
        with pytest.raises(ValueError, match="not a curated dress colour"):
            peach_dress_patch(colour)

    def test_inline_step(self):
        assert (
            parse_step_arg("peach_dress:colour=0x2A", Path(".")).params.colour == 0x2A
        )
