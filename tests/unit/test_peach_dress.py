"""Peach's dress colour patch: the curated colours and the byte it writes."""

import random
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
    def test_flat_list_is_the_families_concatenated(self):
        assert (
            tuple(
                colour for family in DRESS_COLOUR_FAMILIES for colour in family.colours
            )
            == DRESS_COLOURS
        )

    def test_no_colour_is_in_two_families(self):
        assert len(set(DRESS_COLOURS)) == len(DRESS_COLOURS) == 43

    def test_family_names_are_unique(self):
        names = [family.name for family in DRESS_COLOUR_FAMILIES]
        assert len(set(names)) == len(names)

    def test_vanilla_is_curated(self):
        (pink,) = [f for f in DRESS_COLOUR_FAMILIES if f.name == "pink"]
        assert VANILLA_DRESS_COLOUR in pink.colours

    def test_no_black_hair_or_skin(self):
        assert not set(DRESS_COLOURS) & (NES_BLACK_ENTRIES | {HAIR, SKIN})

    def test_random_choice_works_on_both_exports(self):
        rng = random.Random(0)
        assert rng.choice(rng.choice(DRESS_COLOUR_FAMILIES).colours) in DRESS_COLOURS
        assert rng.choice(DRESS_COLOURS) in DRESS_COLOURS

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
