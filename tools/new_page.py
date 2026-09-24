#!/usr/bin/env python3
"""Create a Markdown page, or an entry of a collection page, for the randomizer website."""

import argparse
import json
import re
import sys
import unicodedata
from datetime import date
from pathlib import Path

from server.pages import (
    DEFAULT_ENABLED,
    DEFAULT_LISTED,
    DEFAULT_ORDER,
    INDEX_NAME,
    PAGES_DIR,
    SLUG,
)


def slug_from_title(title: str) -> str:
    """Turn a human-written page title into a valid page slug."""
    ascii_title = (
        unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode("ascii")
    )
    return re.sub(r"[^a-z0-9]+", "-", ascii_title.lower()).strip("-")


def toml_string(value: str) -> str:
    """Quote a string using escapes shared by JSON and TOML basic strings."""
    return json.dumps(value, ensure_ascii=False)


def page_source(title: str) -> str:
    """A new page with every optional frontmatter value written explicitly."""
    quoted = toml_string(title)
    return (
        "+++\n"
        f"title = {quoted}\n"
        f"nav_title = {quoted}\n"
        f"order = {DEFAULT_ORDER}\n"
        f"enabled = {str(DEFAULT_ENABLED).lower()}\n"
        f"listed = {str(DEFAULT_LISTED).lower()}\n"
        "+++\n\n"
    )


def entry_source(title: str, day: date) -> str:
    """A new collection entry dated ``day``, with its optional value written explicitly."""
    return (
        "+++\n"
        f"title = {toml_string(title)}\n"
        f"date = {day.isoformat()}\n"
        f"enabled = {str(DEFAULT_ENABLED).lower()}\n"
        "+++\n\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Create a Markdown page in the randomizer site's pages directory, "
        "or with --entry an entry of a collection page there, dated today."
    )
    parser.add_argument(
        "name", metavar="TITLE", help="human-written page or entry title"
    )
    parser.add_argument(
        "--entry",
        metavar="PAGE",
        help="create an entry of the collection page PAGE instead of a page",
    )
    parser.add_argument(
        "--slug",
        help="URL (or entry anchor) and filename stem (default: derived from TITLE)",
    )
    parser.add_argument(
        "--dir",
        type=Path,
        default=PAGES_DIR,
        help="page directory (default: server/content/pages)",
    )
    args = parser.parse_args(argv)

    title = args.name.strip()
    if not title:
        print("error: TITLE must not be empty", file=sys.stderr)
        return 2
    slug = args.slug if args.slug is not None else slug_from_title(title)
    if not SLUG.fullmatch(slug):
        print(
            "error: slug must contain only lowercase letters, digits, and single hyphens",
            file=sys.stderr,
        )
        return 2
    if not args.dir.is_dir():
        print(f"error: page directory does not exist: {args.dir}", file=sys.stderr)
        return 2

    if args.entry is None:
        if (args.dir / slug).is_dir():
            print(f"error: a collection page is named {slug}", file=sys.stderr)
            return 2
        path = args.dir / f"{slug}.md"
        source = page_source(title)
    else:
        collection = args.dir / args.entry
        if not SLUG.fullmatch(args.entry) or not (collection / INDEX_NAME).is_file():
            print(
                f"error: no collection page {args.entry}: {collection / INDEX_NAME} "
                "does not exist",
                file=sys.stderr,
            )
            return 2
        path = collection / f"{slug}.md"
        source = entry_source(title, date.today())

    try:
        with path.open("x", encoding="utf-8") as handle:
            handle.write(source)
    except FileExistsError:
        what = "page" if args.entry is None else "entry"
        print(f"error: {what} already exists: {path}", file=sys.stderr)
        return 2

    print(f"created {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
