#!/usr/bin/env python3
"""
NES Open Tournament Golf - Hole curation editor

Reads and edits `data/catalog/curation.json`, the freely-edited half of the hole catalog
(docs/catalog.md). This pass covers families - the holes a person has judged to be the same
hole in two releases or tee setups. Tags, drawability and display names are still edited by
hand; an existing record keeps them untouched.

  list     every catalog lineage with its family
  show     one hole: its catalog entry, its record, its family and its rangefinder link
  family   list, set, clear and rename families
  suggest  candidate families read out of the hole data, to accept or reject
  check    curated lineages the catalog lacks, and families with one member
"""

import argparse
import sys
from pathlib import Path

from golf.randomizer.catalog import (
    DEFAULT_COURSES,
    DEFAULT_INDEX,
    Catalog,
    CatalogEntry,
    CatalogError,
    DerivedSource,
    HoleStore,
    RomSource,
)
from golf.randomizer.curation import (
    DEFAULT_CURATION,
    CurationSnapshot,
)
from golf.randomizer.twins import Candidate, candidates, signatures, suggested_label

EXAMPLES = """
examples:
  golf-curate list --unfamilied
  golf-curate suggest --limit 5
  golf-curate suggest --review
  golf-curate family set nes_uk_01 nes_uk/01 jp_japan/01
  golf-curate show nes_uk/01
  golf-curate family list
  golf-curate check
"""

RANGEFINDER = "/rangefinder?"


def rangefinder_link(entry: CatalogEntry) -> str:
    """The rangefinder page's deep link for a vanilla hole; no other hole has one.

    A catalog `RomSource`'s course and hole are already the rangefinder's course id and
    hole number, so nothing has to be translated.
    """
    source = entry.source
    if not isinstance(source, RomSource):
        return "-"
    return f"{RANGEFINDER}course={source.course}&hole={source.hole}"


def load(args: argparse.Namespace) -> tuple[Catalog, CurationSnapshot]:
    return Catalog.load(args.catalog), CurationSnapshot.load(args.curation)


def write(snapshot: CurationSnapshot, args: argparse.Namespace) -> None:
    if getattr(args, "dry_run", False):
        print(f"would write {args.curation}")
        return
    snapshot.save(args.curation)
    print(f"wrote {args.curation}")


def row(lineage: str, entry: CatalogEntry, family: str | None) -> str:
    return f"{lineage:<16} par {entry.par}  {entry.distance:>3}y  {family or '-'}"


def cmd_list(args: argparse.Namespace) -> int:
    catalog, curation = load(args)
    shown = 0
    for lineage, entry in sorted(catalog.newest().items()):
        family = curation.for_hole(entry.id).family
        if args.course and not lineage.startswith(f"{args.course}/"):
            continue
        if args.family and family != args.family:
            continue
        if args.par and entry.par != args.par:
            continue
        if args.unfamilied and family is not None:
            continue
        print(row(lineage, entry, family))
        shown += 1
    print(f"\n{shown} hole{'s' if shown != 1 else ''}")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    catalog, curation = load(args)
    entry = catalog[args.lineage]
    lineage = entry.id.lineage
    record = curation.for_hole(entry.id)
    source = entry.source
    if isinstance(source, RomSource):
        where = f"{source.rom} {source.course} hole {source.hole}"
    elif isinstance(source, DerivedSource):
        where = f"{source.base.id} with {source.delta}"
    else:
        where = source.file
    print(lineage)
    print(f"  catalog      par {entry.par}, {entry.distance} yards, {entry.author}")
    print(f"  source       {where}")
    print(f"  family       {record.family or '-'}")
    if record.tags:
        print(f"  tags         {', '.join(sorted(record.tags))}")
    if not record.drawable:
        print("  drawable     no")
    if record.display_name:
        print(f"  display name {record.display_name}")
    if record.family:
        siblings = [one for one in curation.families()[record.family] if one != lineage]
        print(f"  siblings     {', '.join(siblings) or 'none'}")
    print(f"  rangefinder  {rangefinder_link(entry)}")
    return 0


def cmd_family_list(args: argparse.Namespace) -> int:
    catalog, curation = load(args)
    families = curation.families()
    for label, members in sorted(families.items()):
        print(f"{label:<16} {', '.join(members)}")
    in_a_family = sum(len(members) for members in families.values())
    total = len(catalog.newest())
    print(
        f"\n{len(families)} famil{'ies' if len(families) != 1 else 'y'}, "
        f"{in_a_family} of {total} lineages; {total - in_a_family} in no family"
    )
    return 0


def check_lineages(catalog: Catalog, lineages: list[str]) -> None:
    unknown = [one for one in lineages if one not in catalog.newest()]
    if unknown:
        raise CatalogError(
            f"not a drawable lineage in the catalog: {', '.join(sorted(unknown))}"
        )


def cmd_family_set(args: argparse.Namespace) -> int:
    catalog, curation = load(args)
    check_lineages(catalog, args.lineages)
    updated = curation.set_family(args.lineages, args.label, move=args.move)
    print(f"{args.label}: {', '.join(updated.families()[args.label])}")
    write(updated, args)
    return 0


def cmd_family_clear(args: argparse.Namespace) -> int:
    _catalog, curation = load(args)
    updated = curation.clear_family(args.lineages)
    print(f"cleared: {', '.join(args.lineages)}")
    write(updated, args)
    return 0


def cmd_family_rename(args: argparse.Namespace) -> int:
    _catalog, curation = load(args)
    merging = args.new in curation.families()
    updated = curation.rename_family(args.old, args.new)
    verb = "merged into" if merging else "renamed to"
    print(f"{args.old} {verb} {args.new}: {', '.join(updated.families()[args.new])}")
    write(updated, args)
    return 0


def print_candidate(index: int, total: int, candidate: Candidate) -> None:
    print(f"\n[{index}/{total}]  {candidate.evidence}")
    for member in candidate.members:
        query = member.rangefinder_query
        link = f"{RANGEFINDER}{query}" if query else "-"
        print(f"  {member.lineage:<16} {member.distance:>3}y   {link}")


def ask(prompt: str) -> str:
    try:
        return input(prompt).strip().lower()
    except EOFError:
        return "q"


def cmd_suggest(args: argparse.Namespace) -> int:
    catalog, curation = load(args)
    holes = signatures(catalog, HoleStore(args.holes))
    if not holes:
        raise CatalogError(
            f"no hole data under {args.holes}; run golf-rehydrate to dump the vanilla courses"
        )
    found = candidates(holes, curation, args.min_score, args.all)
    if args.limit:
        found = found[: args.limit]
    if not found:
        print("no candidates; every hole the data pairs up is already in a family")
        return 0

    if not args.review:
        for index, candidate in enumerate(found, 1):
            print_candidate(index, len(found), candidate)
            print(f"  -> {suggested_label(candidate.lineages)}")
        print(f"\n{len(found)} candidates; --review to walk them")
        return 0

    print(f"{len(found)} candidates. y accept · n reject · s skip · q save and stop")
    accepted = 0
    for index, candidate in enumerate(found, 1):
        print_candidate(index, len(found), candidate)
        label = suggested_label(candidate.lineages)
        answer = ask(f"  family {label}? [y/n/s/q] ")
        if answer in ("q", "quit"):
            break
        if answer in ("y", "yes"):
            curation = curation.set_family(candidate.lineages, label)
            accepted += 1
            print(f"  -> {label}")
    print(f"\naccepted {accepted} famil{'ies' if accepted != 1 else 'y'}")
    if accepted:
        write(curation, args)
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    catalog, curation = load(args)
    problems = [
        f"{lineage}: curated but not in the catalog"
        for lineage in curation.unknown_lineages(catalog)
    ]
    problems += [
        f"{label}: family of one ({members[0]})"
        for label, members in sorted(curation.families().items())
        if len(members) == 1
    ]
    for problem in problems:
        print(problem, file=sys.stderr)
    if problems:
        return 1
    print(f"{args.curation}: {len(curation.holes)} records, no problems")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(__doc__ or "").strip().splitlines()[2],
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=EXAMPLES,
    )
    parser.add_argument(
        "--curation", type=Path, default=DEFAULT_CURATION, help="curation file"
    )
    parser.add_argument(
        "--catalog", type=Path, default=DEFAULT_INDEX, help="catalog index"
    )
    commands = parser.add_subparsers(dest="command", required=True)

    listing = commands.add_parser("list", help="every catalog lineage with its family")
    listing.add_argument("--course", help="restrict to a lineage prefix, e.g. nes_uk")
    listing.add_argument("--family", help="restrict to one family")
    listing.add_argument("--par", type=int, help="restrict to one par")
    listing.add_argument(
        "--unfamilied", action="store_true", help="only holes in no family"
    )
    listing.set_defaults(func=cmd_list)

    show = commands.add_parser("show", help="one hole in full")
    show.add_argument("lineage", help="a lineage such as nes_uk/01")
    show.set_defaults(func=cmd_show)

    family = commands.add_parser("family", help="list, set, clear and rename families")
    family_commands = family.add_subparsers(dest="family_command", required=True)

    family_list = family_commands.add_parser(
        "list", help="every family and its members"
    )
    family_list.set_defaults(func=cmd_family_list)

    family_set = family_commands.add_parser("set", help="create or extend a family")
    family_set.add_argument("label", help="the family label, e.g. nes_uk_01")
    family_set.add_argument("lineages", nargs="+", help="the holes to put in it")
    family_set.add_argument(
        "--move",
        action="store_true",
        help="allow a hole already in another family to be moved",
    )
    family_set.set_defaults(func=cmd_family_set)

    family_clear = family_commands.add_parser(
        "clear", help="drop the family from each hole"
    )
    family_clear.add_argument("lineages", nargs="+")
    family_clear.set_defaults(func=cmd_family_clear)

    family_rename = family_commands.add_parser(
        "rename", help="rename a family, or merge it into an existing one"
    )
    family_rename.add_argument("old")
    family_rename.add_argument("new")
    family_rename.set_defaults(func=cmd_family_rename)

    suggest = commands.add_parser(
        "suggest", help="candidate families read out of the hole data"
    )
    suggest.add_argument(
        "--review", action="store_true", help="walk them one at a time and record them"
    )
    suggest.add_argument("--limit", type=int, help="show at most this many")
    suggest.add_argument(
        "--min-score",
        type=float,
        default=0.80,
        help="terrain agreement a pair with differing greens needs (default: %(default)s)",
    )
    suggest.add_argument(
        "--all", action="store_true", help="include holes already in a family"
    )
    suggest.add_argument(
        "--holes",
        type=Path,
        default=DEFAULT_COURSES,
        help="hole store root (default: courses/)",
    )
    suggest.set_defaults(func=cmd_suggest)

    check = commands.add_parser(
        "check", help="report problems; exit 1 if there are any"
    )
    check.set_defaults(func=cmd_check)

    for writer in (family_set, family_clear, family_rename, suggest):
        writer.add_argument(
            "--dry-run", action="store_true", help="report without writing"
        )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        return args.func(args)
    except (CatalogError, OSError) as problem:
        print(f"error: {problem}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
