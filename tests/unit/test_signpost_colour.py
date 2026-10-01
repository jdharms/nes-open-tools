"""Signpost banner colour patch: the curated colours and the byte it writes."""

import random
from pathlib import Path

import pytest

from golf.core import rom_utils
from golf.core.palettes import NES_BLACK_ENTRIES
from golf.core.patches import (
    SIGNPOST_COLOUR_FAMILIES,
    SIGNPOST_COLOURS,
    parse_step_arg,
    signpost_colour_patch,
)
from golf.core.patches.signpost_colour import VANILLA_BANNER_COLOUR

WHITE, SKY = {0x20, 0x30}, 0x21


class TestColours:
    def test_flat_list_is_the_families_concatenated(self):
        assert (
            tuple(
                colour
                for family in SIGNPOST_COLOUR_FAMILIES
                for colour in family.colours
            )
            == SIGNPOST_COLOURS
        )

    def test_no_colour_is_in_two_families(self):
        assert len(set(SIGNPOST_COLOURS)) == len(SIGNPOST_COLOURS) == 28

    def test_family_names_are_unique(self):
        names = [family.name for family in SIGNPOST_COLOUR_FAMILIES]
        assert len(set(names)) == len(names)

    def test_vanilla_is_curated(self):
        (pink,) = [f for f in SIGNPOST_COLOUR_FAMILIES if f.name == "pink"]
        assert VANILLA_BANNER_COLOUR in pink.colours

    def test_no_black_white_sky_or_pale_row(self):
        excluded = NES_BLACK_ENTRIES | WHITE | {SKY} | set(range(0x31, 0x3E))
        assert not set(SIGNPOST_COLOURS) & excluded

    def test_random_choice_works_on_both_exports(self):
        rng = random.Random(0)
        family = rng.choice(SIGNPOST_COLOUR_FAMILIES)
        assert rng.choice(family.colours) in SIGNPOST_COLOURS
        assert rng.choice(SIGNPOST_COLOURS) in SIGNPOST_COLOURS


class TestPatch:
    def test_writes_the_banner_entry(self):
        patch = signpost_colour_patch(0x12)
        assert patch.prg_offset == rom_utils.cpu_to_prg_switched(0xADCB, 12)
        assert patch.original == bytes([0x15])
        assert patch.patched == bytes([0x12])

    @pytest.mark.parametrize("colour", [0x0F, 0x30, SKY, 0x2A, 0x10, 0x34, 0x40])
    def test_rejects_uncurated_colours(self, colour):
        with pytest.raises(ValueError, match="not a curated signpost colour"):
            signpost_colour_patch(colour)

    def test_inline_step(self):
        step = parse_step_arg("signpost_colour:colour=0x19", Path("."))
        assert step.params.colour == 0x19
