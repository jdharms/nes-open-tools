"""Contact sheets of the golfers' cutscene poses, decoded from the ROM.

One sheet per set in golf.core.cutscene_sprites.SETS, a row per scene, each
drawn with that scene's own CHR and palette.  See docs/cutscene_sprites.md.
"""

import os
import sys

from PIL import Image, ImageDraw

sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)

from golf.core.cutscene_sprites import FLIP_X, FLIP_Y, SETS, CutsceneSprites
from golf.core.palettes import NES_SYSTEM_PALETTE
from golf.core.rom_reader import RomReader

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HERE = os.path.dirname(os.path.abspath(__file__))
BG = (24, 26, 22)
RULE = (48, 52, 46)


def paint(px, vram, meta, palettes, ox, oy, size):
    w, h = size
    # Lower OAM index wins, so the first sprite listed is in front: paint it last.
    for sprite in reversed(meta.sprites):
        rows = vram.tile(sprite.tile)
        palette = palettes[sprite.attr & 0x03]
        for y in range(8):
            for x in range(8):
                value = rows[7 - y if sprite.attr & FLIP_Y else y][
                    7 - x if sprite.attr & FLIP_X else x
                ]
                if value == 0:
                    continue
                px_x, px_y = ox + sprite.dx + x, oy + sprite.dy + y
                if 0 <= px_x < w and 0 <= px_y < h:
                    px[px_x, px_y] = NES_SYSTEM_PALETTE[palette[value] & 0x3F]


def sheet(sprites, sprite_set, out, scale=3):
    rows = [(scene, sprites.frames(sprite_set, scene)) for scene in sprite_set.scenes]
    boxes = [meta.bounds() for _, frames in rows for _, meta in frames]
    x0, y0 = min(b[0] for b in boxes), min(b[1] for b in boxes)
    x1, y1 = max(b[2] for b in boxes), max(b[3] for b in boxes)
    cw, ch = x1 - x0 + 6, y1 - y0 + 6
    label, header = 110, 14
    columns = max(len(frames) for _, frames in rows)
    size = (label + columns * cw, len(rows) * (header + ch))

    img = Image.new("RGB", size, BG)
    px = img.load()
    draw = ImageDraw.Draw(img)
    for r, (scene, frames) in enumerate(rows):
        top = r * (header + ch)
        vram = sprites.load_chr(scene)
        palettes = sprites.sprite_palettes(scene)
        draw.line([(0, top), (size[0], top)], fill=RULE)
        draw.text((6, top + header + ch // 2 - 4), scene.name, fill=(210, 218, 205))
        for c, (frame, meta) in enumerate(frames):
            draw.text(
                (label + c * cw + 4, top + 2), f"{frame:02X}", fill=(150, 160, 145)
            )
            ox, oy = label + c * cw + 3 - x0, top + header + 3 - y0
            paint(px, vram, meta, palettes, ox, oy, size)

    img.resize((size[0] * scale, size[1] * scale), Image.Resampling.NEAREST).save(out)
    print("wrote", out)


def main():
    sprites = CutsceneSprites(RomReader(os.path.join(ROOT, "nes_open_us.nes")))
    for sprite_set in SETS:
        sheet(
            sprites, sprite_set, os.path.join(HERE, f"cutscene_{sprite_set.name}.png")
        )


if __name__ == "__main__":
    main()
