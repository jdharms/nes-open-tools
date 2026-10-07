"""
Write Mario Open Golf's course intro sky as the image the `course_intro_sky` patch reads.

The patch draws the top eight tile rows of an image over the course name on the NES
Open course intro scene. The checked-in image is Mario Open's own sky, and this
regenerates it from that ROM:

    golf-intro-sky mario_open_jp.nes

See docs/course_intro_scene.md, **The sky patch**.
"""

import argparse
import hashlib
import sys
from pathlib import Path

from golf.core.jp_rom_utils import JP_ROM_SHA1
from golf.core.patches.course_intro_sky import (
    MARIO_OPEN_SKY_IMAGE,
    read_mario_open_sky,
    write_sky_image,
)
from golf.core.rom_reader import RomReader


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("rom", type=Path, help="the vanilla Mario Open Golf ROM")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=MARIO_OPEN_SKY_IMAGE,
        help="the image to write (default: the checked-in one)",
    )
    args = parser.parse_args()

    data = args.rom.read_bytes()
    if hashlib.sha1(data).hexdigest() != JP_ROM_SHA1:
        sys.exit(f"{args.rom} is not the vanilla Mario Open Golf ROM")
    sky = read_mario_open_sky(RomReader.from_bytes(data))
    write_sky_image(sky, args.output)
    print(f"wrote {args.output}: {len(set(sky.cells))} distinct tiles")


if __name__ == "__main__":
    main()
