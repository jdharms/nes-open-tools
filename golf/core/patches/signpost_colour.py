"""
Signpost colour: recolour the brick behind the pre-hole signpost's banner.

`LC_AC2F_DrawSignpostCard` (bank 12) loads its palette with `Load32BytesToBuffer`
from `$ADC4` (`docs/prehole_signpost.md`). The banner sits in background
subpalette 1 - `$30` letters, `$21` sky, `$15` brick on `$0F` - so the brick is the
single byte at `$ADCB`. The HOLE, PAR and yards signs below it are subpalette 0 and
keep their wood colours. On long-drive and nearest-pin contest holes the game writes
`$12` over the same entry at `$AC46`, after this palette load, so those holes show a
blue banner whatever this patch sets.

The byte sits just before the banner bodies `signpost_random_banner` reclaims
(`$ADE4`-`$B01B`), so the two patches stack.

Only the curated colours below are accepted: the non-black NES colours less the
banner's own white and sky, less every colour the white letters are hard to read
against (the whole pale row and the faintest of the `$2x` row), and less one of each
pair that looks the same as another. `SIGNPOST_COLOUR_FAMILIES` groups them by the
colour they read as, so a caller that wants each family equally likely picks a family
first, then a colour within it.
"""

from golf.core import rom_utils
from golf.core.palettes import ColourFamily, family_colours

from .byte_patch import BytePatch

PALETTE_BANK = 12
BANNER_COLOUR_ADDR = 0xADCB  # signpost palette $ADC4 + 7: subpalette 1, colour 3
VANILLA_BANNER_COLOUR = 0x15

#: the curated colours, grouped by the colour each family reads as; pick a family
#: with random.choice, then a colour from its `colours`
SIGNPOST_COLOUR_FAMILIES: tuple[ColourFamily, ...] = (
    ColourFamily("green", (0x0B, 0x19)),
    ColourFamily("blue", (0x01, 0x11, 0x12, 0x22)),
    ColourFamily("purple", (0x03, 0x04, 0x13, 0x14, 0x23)),
    ColourFamily("pink", (0x05, 0x15, 0x24, 0x25)),
    ColourFamily("orange", (0x07, 0x17, 0x27)),
    ColourFamily("teal", (0x0C, 0x1C)),
    ColourFamily("grey", (0x00, 0x2D)),
    ColourFamily("red", (0x06, 0x16, 0x26)),
    ColourFamily("yellow", (0x08, 0x18, 0x28)),
)

#: every curated colour, the families concatenated in order
SIGNPOST_COLOURS = family_colours(SIGNPOST_COLOUR_FAMILIES)


def signpost_colour_patch(colour: int) -> BytePatch:
    """Set the signpost banner's brick to `colour`, one of `SIGNPOST_COLOURS`."""
    if colour not in SIGNPOST_COLOURS:
        raise ValueError(
            f"${colour:02X} is not a curated signpost colour; "
            "see SIGNPOST_COLOUR_FAMILIES"
        )
    return BytePatch(
        name="signpost_colour",
        description=f"Colour the signpost banner's brick ${colour:02X}",
        prg_offset=rom_utils.cpu_to_prg_switched(BANNER_COLOUR_ADDR, PALETTE_BANK),
        original=bytes([VANILLA_BANNER_COLOUR]),
        patched=bytes([colour]),
    )
