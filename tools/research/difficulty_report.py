#!/usr/bin/env python3
"""
NES Open Tournament Golf - Difficulty Report

Gathers the solves `golf-difficulty` wrote into a directory per course (named as the
catalog names it: nes_us, jp_uk, ...), and writes any of: a summary row per hole, a
slim archive of the solves and their logs for keeping, and the Markdown tables the
results in docs/hole_difficulty.md are made from (to stdout by default).

Examples:
    golf-difficulty-report .cache/difficulty/solves
    golf-difficulty-report .cache/difficulty/solves --summary data/difficulty/holes.json \\
        --archive data/difficulty/solves-skill3-pin0.tar.xz --markdown /tmp/tables.md
"""

import argparse
import json
import sys
from pathlib import Path

from golf.difficulty.report import load, markdown, summary, write_archive
from golf.randomizer.curation import CurationSnapshot


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("solves", type=Path, help="directory of course directories")
    parser.add_argument(
        "--courses", type=Path, default=Path("courses"), help="the dumped courses"
    )
    parser.add_argument("--summary", type=Path, help="write one row per hole here")
    parser.add_argument("--archive", type=Path, help="write the slim .tar.xz here")
    parser.add_argument(
        "--markdown", type=Path, help="write the tables here instead of stdout"
    )
    args = parser.parse_args()

    results = load(args.solves, args.courses)
    if not results:
        sys.exit(f"no solves under {args.solves}")
    print(f"{len(results)} holes", file=sys.stderr)
    if args.summary:
        args.summary.parent.mkdir(parents=True, exist_ok=True)
        args.summary.write_text(json.dumps(summary(results), indent=1) + "\n")
    if args.archive:
        count = write_archive(args.solves, args.archive)
        print(f"{count} files archived in {args.archive}", file=sys.stderr)
    tables = markdown(results, CurationSnapshot.load().families())
    if args.markdown:
        args.markdown.write_text(tables)
    else:
        print(tables)


if __name__ == "__main__":
    main()
