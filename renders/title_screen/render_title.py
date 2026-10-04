"""Rebuild the title screen straight out of the ROM, once per player rank.

Decodes the three bank 5 graphics tables the title loads (bank 12 $8019-$8028),
writes the rank letter the way $8041 does, and draws the background and the 56
sprites of TitleScreenSpriteData with the mid-frame pattern-table switches of
TitleScreenUpdate. See docs/title_screen.md.
"""

import os
import sys

from PIL import Image

sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)

from golf.core.graphics_codec import VideoMemory, load_graphics_table
from golf.core.palettes import NES_SYSTEM_PALETTE
from golf.core.rom_reader import RomReader

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HERE = os.path.dirname(os.path.abspath(__file__))

GRAPHICS_BANK = 5
GRAPHICS_TABLES = (0x8000, 0x8A06, 0x9576)  # sprite CHR, background CHR, nametable
TITLE_BANK = 12
PALETTE = 0x8299  # PaletteDataC8299: what the fade-in ends on
RANK_LETTER_PTRS = 0x828D  # TitleSignpostRankLetterPtrTable, by rank - 1
RANK_LETTER_CHR = 0x1CA0  # tiles $CA-$CD of the $1000 pattern table
SPRITES = 0x8379  # TitleScreenSpriteData: 56 OAM entries
SPRITE_COUNT = 56

# TitleScreenUpdate: the background switches to $1000 just after the sprite-0
# hit; sprites follow after a 160-iteration delay loop, about 800 CPU cycles or
# 7 scanlines. The lines are estimates from cycle counts, not measured.
SPRITE_SWITCH_LINES = 7


def build(rom, rank):
    vram = VideoMemory()
    for table in GRAPHICS_TABLES:
        load_graphics_table(rom, GRAPHICS_BANK, table, vram)
    if rank:
        lo, hi = rom.read_switched(RANK_LETTER_PTRS + 2 * (rank - 1), TITLE_BANK, 2)
        letter = rom.read_switched(lo | hi << 8, TITLE_BANK, 64)
        for i, value in enumerate(letter):
            vram.write(RANK_LETTER_CHR + i, value)
    return vram


def sprite_zero_hit_line(vram, oam):
    """The first scanline where an opaque pixel of sprite 0 meets an opaque
    background pixel - both from table $0000, still in effect above the split."""
    y, tile, attr, x = oam[0:4]
    sprite = vram.tile(tile, 0x0000)
    for row in range(8):
        sy = y + 1 + row
        ty, fine_y = divmod(sy, 8)
        pixels = sprite[7 - row if attr & 0x80 else row]
        for col in range(8):
            sx = x + col
            bg_tile = vram.data[0x2000 + ty * 32 + sx // 8]
            if (
                pixels[7 - col if attr & 0x40 else col]
                and vram.tile(bg_tile, 0x0000)[fine_y][sx % 8]
            ):
                return sy
    raise ValueError("sprite 0 never hits the background")


def render(rom, vram, out_path):
    pal = rom.read_switched(PALETTE, TITLE_BANK, 32)
    oam = rom.read_switched(SPRITES, TITLE_BANK, 4 * SPRITE_COUNT)
    split = sprite_zero_hit_line(vram, oam)

    img = Image.new("RGB", (256, 240))
    px = img.load()
    assert px is not None
    opaque = [[False] * 256 for _ in range(240)]
    for sy in range(240):
        bg_table = 0x1000 if sy > split else 0x0000
        ty, fine_y = divmod(sy, 8)
        for tx in range(32):
            tile = vram.data[0x2000 + ty * 32 + tx]
            attr = vram.data[0x23C0 + (ty // 4) * 8 + (tx // 4)]
            shift = ((ty % 4) // 2) * 4 + ((tx % 4) // 2) * 2
            palette_index = (attr >> shift) & 3
            row = vram.tile(tile, bg_table)[fine_y]
            for x in range(8):
                value = row[x]
                opaque[sy][tx * 8 + x] = value != 0
                nes = pal[0] if value == 0 else pal[palette_index * 4 + value]
                px[tx * 8 + x, sy] = NES_SYSTEM_PALETTE[nes & 0x3F]

    # Sprites, lowest priority first so sprite 0 ends up on top.
    for index in reversed(range(SPRITE_COUNT)):
        y, tile, attr, x = oam[4 * index : 4 * index + 4]
        if y >= 0xEF:
            continue
        for row in range(8):
            sy = y + 1 + row
            if sy >= 240:
                continue
            table = 0x1000 if sy > split + SPRITE_SWITCH_LINES else 0x0000
            pixels = vram.tile(tile, table)[7 - row if attr & 0x80 else row]
            for col in range(8):
                value = pixels[7 - col if attr & 0x40 else col]
                sx = x + col
                if not value or sx >= 256:
                    continue
                if attr & 0x20 and opaque[sy][sx]:
                    continue  # behind an opaque background pixel
                nes = pal[16 + (attr & 3) * 4 + value]
                px[sx, sy] = NES_SYSTEM_PALETTE[nes & 0x3F]

    img.resize((512, 480), Image.Resampling.NEAREST).save(out_path)
    print("wrote", out_path, "split at line", split)


def main():
    rom = RomReader(os.path.join(ROOT, "nes_open_us.nes"))
    for rank in range(4):
        render(rom, build(rom, rank), os.path.join(HERE, f"title_rank{rank}.png"))


if __name__ == "__main__":
    main()
