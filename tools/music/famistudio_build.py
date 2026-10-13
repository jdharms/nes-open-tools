"""Build the FamiStudio sound engine and one song into a blob for `famistudio_music`.

A proof of concept: see docs/famistudio_music.md. Takes the engine source from a
FamiStudio release (the directory holding famistudio_ca65.s and NoteTables/) and
a song exported from FamiStudio as "FamiStudio Music Code" in ca65 format, with
no DPCM samples:

    FamiStudio song.fms famistudio-asm-export song.s -famistudio-asm-format:ca65
    golf-famistudio-build --engine SoundEngine/ song.s -o song.fsblob
    golf-patch nes_open_us.nes -p menu_trim -p famistudio_music:blob=song.fsblob -o out.nes

Needs ca65 and ld65 (cc65) on the path.
"""

import argparse
import sys
from pathlib import Path

from golf.core.famistudio_engine import (
    BLOB_BANK,
    BLOB_ORIGIN,
    FamiStudioBuildError,
    build,
)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("song", type=Path, help="the song's ca65 export")
    ap.add_argument(
        "--engine",
        type=Path,
        required=True,
        help="directory holding famistudio_ca65.s and NoteTables/",
    )
    ap.add_argument("-o", "--output", type=Path, required=True, help="blob file")
    args = ap.parse_args(argv)

    try:
        built = build(args.engine, args.song)
    except FamiStudioBuildError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    args.output.write_bytes(built.blob)
    print(
        f"{args.output}: {len(built.blob):,} bytes for bank {BLOB_BANK} "
        f"${BLOB_ORIGIN:04X} (engine {built.code_size:,}, song {built.song_size:,}, "
        f"{built.free:,} free); {built.ram_size} bytes of RAM"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
