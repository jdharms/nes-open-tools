"""
Peach's dress: recolour the Princess Peach sprite in the putting view's left panel.

`DrawPeachPanel` (bank 13 `$BE0B`) draws her only while putting, from
`PeachBodyMetaspriteData` (`$BEF2`): the dress is the first chunk's 12 sprites, all in
sprite palette 0, and it uses only colour 1 of that palette. `LoadGreenDetailViewTileset`
copies `GreenDetailPaletteData` (`$95FE`, 32 bytes) into `PaletteBuffer` whenever the
green detail view is drawn, so the dress is the single byte at `$960F`, vanilla `$25`.
Nothing else on the putting screen uses that palette entry: the flag and ball are
palette 3.

Only the curated colours below are accepted. They are the 54 non-black NES colours less
her skin (`$36`) and hair (`$28`), and less one of each pair that looks the same as
another on her sprite, judged by CIEDE2000 distance under Mesen's default palette and by
eye. `DRESS_COLOUR_FAMILIES` groups them by the colour they read as. Green has the most
entries because three of the NES's twelve hue columns read as green, so a caller that
wants each family equally likely picks a family first, then a colour within it.
"""

from golf.core import rom_utils
from golf.core.palettes import ColourFamily, family_colours

from .byte_patch import BytePatch

PALETTE_BANK = 13
DRESS_COLOUR_ADDR = 0x960F  # GreenDetailPaletteData + $11: sprite palette 0, colour 1
VANILLA_DRESS_COLOUR = 0x25

#: the curated colours, grouped by the colour each family reads as; pick a family
#: with random.choice, then a colour from its `colours`
DRESS_COLOUR_FAMILIES: tuple[ColourFamily, ...] = (
    ColourFamily("green", (0x0B, 0x19, 0x29, 0x2A, 0x2B, 0x39, 0x3B)),
    ColourFamily("blue", (0x01, 0x11, 0x12, 0x21, 0x22, 0x31, 0x32)),
    ColourFamily("purple", (0x03, 0x04, 0x13, 0x14, 0x23, 0x33)),
    ColourFamily("pink", (0x05, 0x15, 0x24, 0x25, 0x35)),
    ColourFamily("orange", (0x07, 0x17, 0x27, 0x37)),
    ColourFamily("teal", (0x0C, 0x1C, 0x2C, 0x3C)),
    ColourFamily("grey", (0x00, 0x2D, 0x3D, 0x30)),
    ColourFamily("red", (0x06, 0x16, 0x26)),
    ColourFamily("yellow", (0x08, 0x18, 0x38)),
)

#: every curated colour, the families concatenated in order
DRESS_COLOURS = family_colours(DRESS_COLOUR_FAMILIES)


def peach_dress_patch(colour: int) -> BytePatch:
    """Set Peach's dress to `colour`, one of `DRESS_COLOURS`."""
    if colour not in DRESS_COLOURS:
        raise ValueError(
            f"${colour:02X} is not a curated dress colour; see DRESS_COLOUR_FAMILIES"
        )
    return BytePatch(
        name="peach_dress",
        description=f"Colour Peach's dress ${colour:02X} in the putting view",
        prg_offset=rom_utils.cpu_to_prg_switched(DRESS_COLOUR_ADDR, PALETTE_BANK),
        original=bytes([VANILLA_DRESS_COLOUR]),
        patched=bytes([colour]),
    )
