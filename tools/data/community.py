#!/usr/bin/env python3
"""
NES Open Tournament Golf - Community hole publisher

A community hole is a contributor's own hole. Its working copy lives under
courses/community/ and stays theirs to edit; publishing puts a frozen copy beside the
catalog index and an entry naming it, and a changed working copy published again is the
next version (docs/community_holes.md, ADR 0027).

  hole    publish one hole under its author, <author>/<slug>
  course  publish a community course's folder of 18 holes as <course>/01-18
  check   every community hole loads to its hash and takes every transform
"""

import argparse
import sys
from pathlib import Path

from golf.formats.hole_data import HoleData
from golf.randomizer.catalog import DEFAULT_INDEX, Catalog, CatalogError
from golf.randomizer.community import (
    Publication,
    check_community,
    community_entries,
    load_course_folder,
    publish_course,
    publish_hole,
)

EXAMPLES = """
examples:
  golf-community hole courses/community/pinesfan/island_green.json pinesfan/island_green --dry-run
  golf-community course courses/community/georgia_pines georgia_pines --name "Georgia Pines" --author pinesfan --dry-run
  golf-community course courses/community/georgia_pines georgia_pines
  golf-community check
"""


def describe(publication: Publication) -> None:
    for entry in publication.entries:
        print(f"{entry.id}  par {entry.par}, {entry.distance} yards, by {entry.author}")
    if publication.unchanged:
        print(
            f"unchanged: {', '.join(str(hole_id) for hole_id in publication.unchanged)}"
        )
    for note in publication.notes:
        print(f"  note     {note}")


def finish(publication: Publication, args: argparse.Namespace) -> int:
    describe(publication)
    paths = [str(publication.path_for(hole_id)) for hole_id in publication.files]
    if args.dry_run:
        print(f"would write {len(paths)} hole files and {args.catalog}")
        return 0
    publication.write(args.catalog)
    print(
        f"wrote {len(paths)} hole files and {args.catalog} (version "
        f"{publication.catalog.version})"
    )
    return 0


def cmd_hole(args: argparse.Namespace) -> int:
    hole = HoleData()
    hole.load(args.hole)
    publication = publish_hole(
        Catalog.load(args.catalog), hole, args.lineage, root=args.catalog.parent
    )
    return finish(publication, args)


def cmd_course(args: argparse.Namespace) -> int:
    publication = publish_course(
        Catalog.load(args.catalog),
        load_course_folder(args.folder),
        args.slug,
        root=args.catalog.parent,
        name=args.name,
        author=args.author,
    )
    return finish(publication, args)


def cmd_check(args: argparse.Namespace) -> int:
    catalog = Catalog.load(args.catalog)
    problems = check_community(catalog)
    for problem in problems:
        print(problem, file=sys.stderr)
    if problems:
        return 1
    print(
        f"{len(community_entries(catalog))} community holes in "
        f"{len(catalog.courses)} courses and loose, no problems"
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(__doc__ or "").strip().splitlines()[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=EXAMPLES,
    )
    parser.add_argument(
        "--catalog",
        type=Path,
        default=DEFAULT_INDEX,
        help="catalog index; community holes are kept under community/ beside it",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    hole = commands.add_parser("hole", help="publish one hole under its author")
    hole.add_argument("hole", type=Path, help="the hole file, which names its author")
    hole.add_argument(
        "lineage",
        help="<author>/<slug>, e.g. pinesfan/island_green; an existing one gets its "
        "next version",
    )
    hole.add_argument(
        "--dry-run", action="store_true", help="report without writing anything"
    )
    hole.set_defaults(func=cmd_hole)

    course = commands.add_parser("course", help="publish a community course's 18 holes")
    course.add_argument(
        "folder", type=Path, help="the course folder, with hole_01.json-hole_18.json"
    )
    course.add_argument("slug", help="the course's owner, e.g. georgia_pines")
    course.add_argument(
        "--name", help="its display name; needed the first time, corrects it later"
    )
    course.add_argument(
        "--author",
        help="who its holes are credited to unless a hole names its own; needed the "
        "first time, corrects it later",
    )
    course.add_argument(
        "--dry-run", action="store_true", help="report without writing anything"
    )
    course.set_defaults(func=cmd_course)

    check = commands.add_parser(
        "check",
        help="every community hole loads to its hash and takes every transform; exit 1 "
        "otherwise",
    )
    check.set_defaults(func=cmd_check)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        return args.func(args)
    except (CatalogError, OSError, ValueError, KeyError) as problem:
        print(f"error: {problem}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
