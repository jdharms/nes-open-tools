"""Palette-swap experiments: the course intro scene in other seasons.

Only the 16 background palette bytes change; the tiles, nametable and attribute
table are the ROM's.  Each season is rendered on Mario Open's scene (no course
name) and on the NES Open Japan scene with its text box open, into `seasons/`.
See docs/course_intro_scene.md.
"""

import os

from render_scene import (
    COURSES,
    HERE,
    JP_SPLIT_ROW,
    PALETTE,
    ROOT,
    SPLIT_ROW,
    SUNSET_PALETTE,
    build,
    build_jp,
    render_image,
    save,
)

from golf.core.rom_reader import RomReader

# Four background palettes of (shared color 0, then three colors):
#   0  sky: cloud shade, cloud white, sky
#   1  tree line: cloud shade, trees, sky
#   2  far bank: water, shrubs and shadow, sand
#   3  foreground: light grass, shrubs and shadow, sand
# Color 0 is the mid grass, and the lighter half of every tree.
SEASONS = {
    "spring": "1A 35 30 21  1A 35 15 21  1A 21 0A 38  1A 2A 0A 38",
    "spring_fresh": "29 35 30 21  29 35 14 21  29 21 19 38  29 2A 19 38",
    "fall": "18 3C 30 21  18 3C 16 21  18 11 17 37  18 28 17 37",
    "fall_pale": "28 37 30 21  28 37 16 21  28 11 17 37  28 38 17 37",
    "winter": "31 3C 30 21  31 3C 0C 21  31 2C 0C 3D  31 30 0C 3D",
    "winter_overcast": "31 3D 30 10  31 3D 0C 10  31 2C 0C 3D  31 30 0C 3D",
}


def main():
    out_dir = os.path.join(HERE, "seasons")
    os.makedirs(out_dir, exist_ok=True)

    us = RomReader(os.path.join(ROOT, "nes_open_us.nes"))
    palettes = {
        "summer": bytes(us.read_switched(PALETTE[1], PALETTE[0], 16)),
        **{name: bytes.fromhex(text) for name, text in SEASONS.items()},
        "sunset": bytes(us.read_switched(SUNSET_PALETTE[1], SUNSET_PALETTE[0], 16)),
    }
    _, chr_table, nt_table = COURSES[0]
    scenes = [("us", build(us, chr_table, nt_table), SPLIT_ROW)]

    jp_path = os.path.join(ROOT, "mario_open_jp.nes")
    if os.path.exists(jp_path):
        jp = RomReader(jp_path)
        scenes.append(("mario_open", build_jp(jp), JP_SPLIT_ROW))

    for scene, vram, split_row in scenes:
        for name, pal in palettes.items():
            img = render_image(vram, pal, split_row)
            save(img, os.path.join(out_dir, f"{scene}_{name}.png"))


if __name__ == "__main__":
    main()
