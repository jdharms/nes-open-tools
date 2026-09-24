"""Checked-in Markdown pages served by the randomizer website.

A page is either one Markdown file directly under the pages directory, or a collection:
a directory there holding an `_index.md` with the page's frontmatter and an optional
intro, and one Markdown file per entry, each shown as a card, newest date first.
"""

import re
import tomllib
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path

from markdown_it import MarkdownIt
from markupsafe import Markup

HERE = Path(__file__).resolve().parent
PAGES_DIR = HERE / "content" / "pages"
FRONTMATTER_DELIMITER = "+++"
FIELDS = frozenset({"title", "nav_title", "order", "enabled", "listed"})
ENTRY_FIELDS = frozenset({"title", "date", "enabled"})
INDEX_NAME = "_index.md"
SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
DEFAULT_ORDER = 100
DEFAULT_ENABLED = True
DEFAULT_LISTED = True


class PageError(ValueError):
    """A malformed page or page catalog."""


@dataclass(frozen=True)
class PageEntry:
    """One card of a collection page; its slug is the card's anchor id."""

    slug: str
    title: str
    date: date
    body_html: Markup


@dataclass(frozen=True)
class ContentPage:
    slug: str
    title: str
    nav_title: str
    order: int
    enabled: bool
    listed: bool
    #: the page's body, or a collection's intro above its cards
    body_html: Markup
    collection: bool = False
    #: a collection's enabled entries, newest first
    entries: tuple[PageEntry, ...] = ()


@dataclass(frozen=True)
class PageCatalog:
    """The Markdown pages known to the site, including disabled ones."""

    pages: tuple[ContentPage, ...]

    @classmethod
    def load(cls, directory: Path = PAGES_DIR) -> "PageCatalog":
        """Load and validate every page and collection directly under ``directory``."""
        if not directory.is_dir():
            raise PageError(f"page directory does not exist: {directory}")

        pages: list[ContentPage] = []
        for path in sorted(directory.iterdir()):
            if path.is_dir():
                pages.append(_load_collection(directory, path))
            elif path.suffix == ".md":
                pages.append(_load_page(directory, path))

        slugs = [page.slug for page in pages]
        duplicates = sorted({slug for slug in slugs if slugs.count(slug) > 1})
        if duplicates:
            raise PageError(
                f"both a page file and a collection directory are named {duplicates}"
            )
        return cls(tuple(pages))

    def get(self, slug: str) -> ContentPage | None:
        """Return an enabled page by slug; disabled and unknown pages are absent."""
        return next((page for page in self.enabled if page.slug == slug), None)

    @property
    def enabled(self) -> tuple[ContentPage, ...]:
        """Every enabled page, listed or not, in catalog order."""
        return tuple(page for page in self.pages if page.enabled)

    @property
    def listed(self) -> tuple[ContentPage, ...]:
        """Enabled pages that should appear in navigation, in display order."""
        return tuple(
            sorted(
                (page for page in self.pages if page.enabled and page.listed),
                key=lambda page: (page.order, page.nav_title.casefold(), page.slug),
            )
        )


def _render(body: str) -> Markup:
    renderer = MarkdownIt("commonmark", {"html": False}).enable("table")
    return Markup(renderer.render(body))


def _read(name: str, path: Path, fields: frozenset[str]) -> tuple[dict, str]:
    """A file's validated frontmatter table and its Markdown body."""
    frontmatter, body = _split_frontmatter(name, path.read_text(encoding="utf-8"))
    try:
        metadata = tomllib.loads(frontmatter)
    except tomllib.TOMLDecodeError as problem:
        raise PageError(f"{name}: invalid TOML frontmatter: {problem}") from None

    extra = metadata.keys() - fields
    if extra:
        raise PageError(f"{name}: unknown frontmatter fields: {sorted(extra)}")
    return metadata, body


def _split_frontmatter(name: str, source: str) -> tuple[str, str]:
    lines = source.splitlines(keepends=True)
    if not lines or lines[0].strip() != FRONTMATTER_DELIMITER:
        raise PageError(f"{name}: first line must be {FRONTMATTER_DELIMITER!r}")
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == FRONTMATTER_DELIMITER:
            return "".join(lines[1:index]), "".join(lines[index + 1 :])
    raise PageError(f"{name}: missing closing {FRONTMATTER_DELIMITER!r}")


def _string_field(
    name: str, metadata: dict, field: str, default: str | None = None
) -> str:
    value = metadata.get(field, default)
    if not isinstance(value, str) or not value.strip():
        raise PageError(f"{name}: {field} must be a nonempty string")
    return value.strip()


def _bool_field(name: str, metadata: dict, field: str, default: bool) -> bool:
    value = metadata.get(field, default)
    if type(value) is not bool:
        raise PageError(f"{name}: {field} must be a boolean")
    return value


def _check_slug(name: str, stem: str, what: str) -> None:
    if not SLUG.fullmatch(stem):
        raise PageError(
            f"{name}: {what} must contain only lowercase letters, digits, and hyphens"
        )


def _load_page(root: Path, path: Path, slug: str | None = None) -> ContentPage:
    """A page file, or with ``slug`` a collection's ``_index.md``."""
    name = path.relative_to(root).as_posix()
    if slug is None:
        _check_slug(name, path.stem, "filename")
        slug = path.stem
    metadata, body = _read(name, path, FIELDS)

    title = _string_field(name, metadata, "title")
    nav_title = _string_field(name, metadata, "nav_title", title)
    order = metadata.get("order", DEFAULT_ORDER)
    if type(order) is not int:
        raise PageError(f"{name}: order must be an integer")
    enabled = _bool_field(name, metadata, "enabled", DEFAULT_ENABLED)
    listed = _bool_field(name, metadata, "listed", DEFAULT_LISTED)
    if listed and not enabled:
        raise PageError(f"{name}: a disabled page cannot be listed")

    return ContentPage(
        slug=slug,
        title=title,
        nav_title=nav_title,
        order=order,
        enabled=enabled,
        listed=listed,
        body_html=_render(body),
    )


def _load_collection(root: Path, directory: Path) -> ContentPage:
    _check_slug(directory.name, directory.name, "directory name")
    index = directory / INDEX_NAME
    if not index.is_file():
        raise PageError(f"{directory.name}: a collection needs {INDEX_NAME}")

    entries: list[tuple[PageEntry, bool]] = []
    for path in sorted(directory.iterdir()):
        name = path.relative_to(root).as_posix()
        if path.is_dir():
            raise PageError(f"{name}: collections cannot contain directories")
        if path.suffix != ".md" or path.name == INDEX_NAME:
            continue
        entries.append(_load_entry(name, path))

    visible = sorted(
        (entry for entry, enabled in entries if enabled),
        key=lambda entry: (entry.date, entry.slug),
        reverse=True,
    )
    page = _load_page(root, index, slug=directory.name)
    return replace(page, collection=True, entries=tuple(visible))


def _load_entry(name: str, path: Path) -> tuple[PageEntry, bool]:
    """An entry and whether it is enabled; disabled entries are validated all the same."""
    _check_slug(name, path.stem, "filename")
    metadata, body = _read(name, path, ENTRY_FIELDS)
    title = _string_field(name, metadata, "title")
    # A TOML datetime loads as a datetime, which is also a date.
    when = metadata.get("date")
    if type(when) is not date:
        raise PageError(f"{name}: date must be a TOML date such as 2026-10-01")
    enabled = _bool_field(name, metadata, "enabled", DEFAULT_ENABLED)
    return PageEntry(path.stem, title, when, _render(body)), enabled
