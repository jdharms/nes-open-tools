#!/usr/bin/env python3
"""
NES Open Tournament Golf - Derived hole publisher

A derived hole is a vanilla hole with a delta applied: a forward tee that makes a par 5 a
par 3, or a variant with a dogleg redrawn. Edit a copy of the vanilla hole in the editor,
then publish it here. The repository gets the cells and metadata that differ, a catalog
entry and a curation record, and never the hole itself (docs/derived_holes.md).

  new     publish an edited hole as a derived hole, or as a new version of one
  export  write a derived hole out as a hole file, to edit toward its next version
  show    one derived hole: its base, its delta and what the delta changes
  check   every derived hole builds, holds only its own cells, and takes every transform
"""

import argparse
import json
import sys
from pathlib import Path

from golf.formats.hole_data import HoleData
from golf.randomizer import delta as hole_delta
from golf.randomizer.catalog import (
    DEFAULT_COURSES,
    DEFAULT_INDEX,
    Catalog,
    CatalogError,
    DerivedSource,
    HoleStore,
    canonical_dict,
)
from golf.randomizer.curation import DEFAULT_CURATION, CurationSnapshot
from golf.randomizer.derive import (
    Derivation,
    check_derived,
    derive,
    derived_entries,
    format_delta,
)

EXAMPLES = """
examples:
  cp courses/us/hole_12.json courses/scratch/us_12_forward3.json
  golf-editor courses/scratch/us_12_forward3.json
  golf-derive new nes_us/12 courses/scratch/us_12_forward3.json community/nes_us_12_forward3 --author jdharms --dry-run
  golf-derive new nes_us/12 courses/scratch/us_12_forward3.json community/nes_us_12_forward3 --author jdharms
  golf-derive show community/nes_us_12_forward3
  golf-derive export community/nes_us_12_forward3 -o courses/scratch/us_12_forward3.json
  golf-derive check
"""


def comma_list(text: str) -> list[str]:
    return [item.strip() for item in text.split(",") if item.strip()]


def describe(derivation: Derivation) -> None:
    entry, delta = derivation.entry, derivation.delta
    source = entry.source
    assert isinstance(source, DerivedSource)
    base = source.base
    print(f"{entry.id}  from {base.id}, by {entry.author}")
    print(f"  par {base.par} -> {entry.par}, {base.distance} -> {entry.distance} yards")
    describe_delta(delta, derivation.terrain_share)
    record = derivation.curation.for_hole(entry.id)
    print(f"  family   {record.family or '-'}")
    print(f"  tags     {', '.join(sorted(record.tags)) or '-'}")
    for note in derivation.notes:
        print(f"  note     {note}")


def describe_delta(delta: dict, terrain_share: float | None = None) -> None:
    offset = delta.get("row_offset", 0)
    if offset:
        moved = (
            f"{offset} rows cropped from the top"
            if offset > 0
            else f"{-offset} rows added at the top"
        )
        print(f"  rows     {moved}")
    for key, value in delta.get("metadata", {}).items():
        print(f"  {key:<8} {json.dumps(value)}")
    for name in hole_delta.GRIDS:
        if name not in delta:
            continue
        grid = delta[name]
        cells = sum(len(text.split(" ")) for _, _, text in grid["cells"])
        share = (
            f", {terrain_share:.0%} of the shared terrain"
            if name == "terrain" and terrain_share is not None
            else ""
        )
        print(f"  {name:<8} {grid['rows']} rows, {cells} cells changed{share}")


def cmd_new(args: argparse.Namespace) -> int:
    catalog = Catalog.load(args.catalog)
    curation = CurationSnapshot.load(args.curation)
    edited = HoleData()
    edited.load(args.hole)
    derivation = derive(
        catalog,
        curation,
        HoleStore(args.holes),
        args.base,
        edited,
        args.lineage,
        args.author,
        root=args.catalog.parent,
        tags=None if args.tags is None else frozenset(comma_list(args.tags)),
        family=args.family,
        allow_large=args.allow_large,
    )
    describe(derivation)
    if args.dry_run:
        print(f"would write {derivation.delta_path}, {args.catalog}, {args.curation}")
        return 0
    derivation.write(args.catalog, args.curation)
    print(
        f"wrote {derivation.delta_path}, {args.catalog} (version "
        f"{derivation.catalog.version}) and {args.curation}"
    )
    return 0


def derived_entry(catalog: Catalog, hole_id: str):
    entry = catalog[hole_id]
    if not isinstance(entry.source, DerivedSource):
        raise CatalogError(f"{entry.id} is not a derived hole")
    return entry, entry.source


def cmd_export(args: argparse.Namespace) -> int:
    catalog = Catalog.load(args.catalog)
    entry, _ = derived_entry(catalog, args.id)
    hole = HoleStore(args.holes).load(entry, even_withdrawn=True)
    if args.output.exists() and not args.force:
        raise CatalogError(f"{args.output} exists; pass --force to overwrite it")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    hole.save(str(args.output))
    print(f"wrote {entry.id} to {args.output}")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    catalog = Catalog.load(args.catalog)
    curation = CurationSnapshot.load(args.curation)
    entry, source = derived_entry(catalog, args.id)
    delta = json.loads(source.path.read_text())
    base = source.base
    print(f"{entry.id}  from {base.id}, by {entry.author}")
    print(f"  par {base.par} -> {entry.par}, {base.distance} -> {entry.distance} yards")
    print(f"  delta    {source.path}")
    share = None
    store = HoleStore(args.holes)
    if store.path_for(base).exists():
        share = hole_delta.changed_share(
            canonical_dict(store.load(base, even_withdrawn=True)), delta, "terrain"
        )
    describe_delta(delta, share)
    record = curation.for_hole(entry.id)
    print(f"  family   {record.family or '-'}")
    print(f"  tags     {', '.join(sorted(record.tags)) or '-'}")
    if args.delta:
        print(format_delta(delta), end="")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    catalog = Catalog.load(args.catalog)
    problems = check_derived(catalog, HoleStore(args.holes))
    for problem in problems:
        print(problem, file=sys.stderr)
    if problems:
        return 1
    print(f"{len(derived_entries(catalog))} derived holes, no problems")
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
        help="catalog index; deltas are kept under derived/ beside it",
    )
    parser.add_argument(
        "--curation", type=Path, default=DEFAULT_CURATION, help="curation file"
    )
    parser.add_argument(
        "--holes",
        type=Path,
        default=DEFAULT_COURSES,
        help="hole store the vanilla holes are dumped in (default: courses/)",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    new = commands.add_parser(
        "new", help="publish an edited hole as a derived hole, or a new version of one"
    )
    new.add_argument("base", help="the vanilla hole it was edited from, e.g. nes_us/12")
    new.add_argument("hole", type=Path, help="the edited hole file")
    new.add_argument(
        "lineage",
        help="the lineage to publish under, <owner>/<slug>, e.g. "
        "community/nes_us_12_forward3; an existing one gets its next version",
    )
    new.add_argument("--author", required=True, help="who the hole is credited to")
    new.add_argument(
        "--tags",
        help="comma-separated curation tags, or '' for none (default: 'short' when "
        "the par is lower than the base's; a later version keeps the lineage's tags)",
    )
    new.add_argument(
        "--family",
        help="curation family (default: the base's, created and named after the base "
        "if it has none; a later version keeps the lineage's family)",
    )
    new.add_argument(
        "--allow-large",
        action="store_true",
        help="publish a delta that rewrites most of the terrain the two holes share",
    )
    new.add_argument(
        "--dry-run", action="store_true", help="report without writing anything"
    )
    new.set_defaults(func=cmd_new)

    export = commands.add_parser(
        "export", help="write a derived hole out as a hole file"
    )
    export.add_argument("id", help="a derived hole's id")
    export.add_argument("-o", "--output", type=Path, required=True)
    export.add_argument("--force", action="store_true", help="overwrite the output")
    export.set_defaults(func=cmd_export)

    show = commands.add_parser(
        "show", help="one derived hole and what its delta changes"
    )
    show.add_argument("id", help="a derived hole's id")
    show.add_argument("--delta", action="store_true", help="print the delta file too")
    show.set_defaults(func=cmd_show)

    check = commands.add_parser(
        "check",
        help="every derived hole builds, holds only its own cells and takes every "
        "transform; exit 1 otherwise",
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
