#!/usr/bin/env python3
"""
Hazard Stamps - regenerate the editor's built-in hazard stamps from the vanilla courses

Finds every enclosed bunker and water hazard in the vanilla holes of both ROMs, keeps one
of each distinct shape, and writes them as stamps under data/stamps/built-in/hazard/,
filed by size. Replaces whatever that directory held. Needs the courses `golf-rehydrate`
dumps.
"""

import argparse
import shutil
import sys
from pathlib import Path

from editor.data.hazard_stamps import CATEGORY, hazard_stamps, stamp_path
from golf.randomizer.catalog import (
    DEFAULT_COURSES,
    REPO_ROOT,
    Catalog,
    CatalogError,
    HoleStore,
    RomSource,
)

DEFAULT_OUTPUT = REPO_ROOT / "data" / "stamps" / "built-in"


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(__doc__ or "").strip().splitlines()[0]
    )
    parser.add_argument(
        "courses_root",
        nargs="?",
        type=Path,
        default=DEFAULT_COURSES,
        help="directory holding the dumped courses, with Mario Open under jp/ (default: courses/)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="built-in stamps directory to write hazard/ under",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="report without writing; exit 1 if anything would change",
    )
    args = parser.parse_args()

    store = HoleStore(args.courses_root)
    try:
        holes = [
            store.load(entry)
            for entry in Catalog.load().newest().values()
            if isinstance(entry.source, RomSource)
        ]
    except CatalogError as error:
        print(f"{error}\nrun `uv run golf-rehydrate` first", file=sys.stderr)
        return 1

    stamps = hazard_stamps(holes)
    target = args.output / CATEGORY
    wanted = {stamp_path(args.output, stamp): stamp for stamp in stamps}
    existing = set(target.rglob("*.json")) if target.exists() else set()

    if args.check:
        changed = [
            path
            for path, stamp in wanted.items()
            if path in existing and path.read_text() != stamp.to_json()
        ]
        missing, stale = wanted.keys() - existing, existing - wanted.keys()
        for verb, paths in (
            ("missing", missing),
            ("changed", changed),
            ("stale", stale),
        ):
            for path in sorted(paths):
                print(f"{verb}: {path}")
        print(f"{len(stamps)} stamps from {len(holes)} holes")
        return 1 if missing or changed or stale else 0

    if target.exists():
        shutil.rmtree(target)
    for path, stamp in wanted.items():
        stamp.save(path)
    print(f"wrote {len(stamps)} stamps from {len(holes)} holes under {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
