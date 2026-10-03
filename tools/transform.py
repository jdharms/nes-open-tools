"""Apply hole transforms to a hole or a course directory, writing new hole JSON."""

import argparse
import shutil
import sys
from pathlib import Path

from golf.formats.hole_data import HoleData
from golf.randomizer.transforms import (
    TRANSFORMS,
    TransformError,
    apply_transforms,
    parse_transform,
)


class ListTransforms(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        for name, transform in TRANSFORMS.items():
            usage = f"{name}:<seed>" if transform.seeded else name
            print(f"{usage:28} {transform.summary}")
        parser.exit()


def transform_file(source: Path, output: Path, transforms: list[str]) -> None:
    hole = HoleData()
    hole.load(source)
    try:
        transformed = apply_transforms(hole, transforms)
    except TransformError as problem:
        raise SystemExit(f"{source}: {problem}") from None
    transformed.save(str(output))
    print(f"Wrote {output}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        epilog="""\
Examples:
  golf-transform courses/us/hole_05.json mirrored.json mirror@1
  golf-transform courses/uk/ courses/uk-wet/ hazards@1:42 mirror@1
  golf-transform --list

Transforms run in the order given. A directory transforms every hole_*.json in it
with the same transforms and seed, and copies course.json alongside.""",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--list", action=ListTransforms, nargs=0, help="list the transforms and exit"
    )
    parser.add_argument("source", type=Path, help="a hole JSON or course directory")
    parser.add_argument("output", type=Path, help="the JSON or directory to write")
    parser.add_argument(
        "transforms", nargs="+", help="transform names, as --list prints"
    )
    args = parser.parse_args()

    for name in args.transforms:
        try:
            parse_transform(name)
        except TransformError as problem:
            parser.error(f"{problem}; see --list")

    if args.source.is_dir():
        holes = sorted(args.source.glob("hole_*.json"))
        if not holes:
            sys.exit(f"{args.source}: no hole_*.json files")
        args.output.mkdir(parents=True, exist_ok=True)
        for path in holes:
            transform_file(path, args.output / path.name, args.transforms)
        if (args.source / "course.json").exists():
            shutil.copy(args.source / "course.json", args.output / "course.json")
    else:
        transform_file(args.source, args.output, args.transforms)


if __name__ == "__main__":
    main()
