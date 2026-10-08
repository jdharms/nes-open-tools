#!/usr/bin/env python3
"""
Feature Style - regenerate the tile statistics the editor's feature brush fits with

Counts, over the vanilla holes of both ROMs, how often each pair of feature tiles sits
side by side or stacked and which 2x2 blocks of them occur, once for fairways, once for
bunkers and water, once for the out-of-bounds line and once for a green's fringe, and writes
data/tables/feature_style.json. Needs the courses
`golf-rehydrate` dumps. See docs/feature_brush.md.
"""

import argparse
import sys
from pathlib import Path

from golf.algorithms.feature_fit import (
    STYLE_TABLE,
    count_style,
    families,
    style_table_text,
)
from golf.randomizer.catalog import (
    DEFAULT_COURSES,
    Catalog,
    CatalogError,
    HoleStore,
    RomSource,
)


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
        "--output", type=Path, default=STYLE_TABLE, help="style table to write"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="report without writing; exit 1 if the table would change",
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

    counts = [count_style(family, holes) for family in families().values()]
    text = style_table_text(counts)
    for style in counts:
        print(
            f"{style.family.name}: {len(style.family.tiles)} tiles, "
            f"{len(style.blocks)} distinct blocks from {style.holes} holes"
        )
    if args.check:
        current = args.output.exists() and args.output.read_text() == text
        print(f"{args.output} is {'current' if current else 'stale'}")
        return 0 if current else 1
    args.output.write_text(text)
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
