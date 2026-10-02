"""Build the standalone Practice Greens ROM and its local allocation manifest."""

import argparse
import json
from pathlib import Path

from golf.core.patches.practice_greens import build_practice_greens


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("rom", nargs="?", type=Path, default=Path("nes_open_us.nes"))
    parser.add_argument("--courses", type=Path, default=Path("courses"))
    parser.add_argument(
        "-o", "--output", type=Path, default=Path("practice_greens.nes")
    )
    parser.add_argument(
        "--keep-signposts",
        action="store_true",
        help="Keep the per-hole signpost cards instead of skipping them",
    )
    args = parser.parse_args()
    result = build_practice_greens(
        args.rom.read_bytes(), args.courses, skip_signposts=not args.keep_signposts
    )
    args.output.write_bytes(result.rom)
    manifest_path = args.output.with_suffix(".build.json")
    manifest_path.write_text(json.dumps(result.manifest, indent=2) + "\n")
    print(
        f"Built {args.output}: {result.manifest['unique_greens']} unique greens from "
        f"{result.manifest['vanilla_holes']} holes; manifest: {manifest_path}"
    )


if __name__ == "__main__":
    main()
