"""Signpost banner color patch: the curated colors and the byte it writes."""

import random
from pathlib import Path

import pytest

from golf.core import rom_utils
from golf.core.palettes import NES_BLACK_ENTRIES
from golf.core.patches import (
    SIGNPOST_COLOR_FAMILIES,
    SIGNPOST_COLORS,
    parse_step_arg,
    signpost_color_patch,
)
from golf.core.patches.signpost_color import VANILLA_BANNER_COLOR

WHITE, SKY = {0x20, 0x30}, 0x21


class TestColors:
    def test_flat_list_is_the_families_concatenated(self):
        assert (
            tuple(
                color for family in SIGNPOST_COLOR_FAMILIES for color in family.colors
            )
            == SIGNPOST_COLORS
        )

    def test_no_color_is_in_two_families(self):
        assert len(set(SIGNPOST_COLORS)) == len(SIGNPOST_COLORS) == 28

    def test_family_names_are_unique(self):
        names = [family.name for family in SIGNPOST_COLOR_FAMILIES]
        assert len(set(names)) == len(names)

    def test_vanilla_is_curated(self):
        (pink,) = [f for f in SIGNPOST_COLOR_FAMILIES if f.name == "pink"]
        assert VANILLA_BANNER_COLOR in pink.colors

    def test_no_black_white_sky_or_pale_row(self):
        excluded = NES_BLACK_ENTRIES | WHITE | {SKY} | set(range(0x31, 0x3E))
        assert not set(SIGNPOST_COLORS) & excluded

    def test_random_choice_works_on_both_exports(self):
        rng = random.Random(0)
        family = rng.choice(SIGNPOST_COLOR_FAMILIES)
        assert rng.choice(family.colors) in SIGNPOST_COLORS
        assert rng.choice(SIGNPOST_COLORS) in SIGNPOST_COLORS


class TestPatch:
    def test_writes_the_banner_entry(self):
        patch = signpost_color_patch(0x12)
        assert patch.prg_offset == rom_utils.cpu_to_prg_switched(0xADCB, 12)
        assert patch.original == bytes([0x15])
        assert patch.patched == bytes([0x12])

    @pytest.mark.parametrize("color", [0x0F, 0x30, SKY, 0x2A, 0x10, 0x34, 0x40])
    def test_rejects_uncurated_colors(self, color):
        with pytest.raises(ValueError, match="not a curated signpost color"):
            signpost_color_patch(color)

    def test_inline_step(self):
        step = parse_step_arg("signpost_color:color=0x19", Path("."))
        assert step.params.color == 0x19
