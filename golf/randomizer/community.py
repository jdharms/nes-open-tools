"""
Publishing community holes: a frozen copy of a contributor's hole beside the catalog
index, and the catalog entry that names it (ADR 0027).

The working copy, under `courses/community/`, stays the contributor's to edit; the
randomizer reads only the copy published here, which is never edited. Publishing a
changed working copy makes the lineage's next version. A community course's holes are
`<course>/01`-`<course>/18` and are published together from its folder; any other hole is
published under its author, `<author>/<slug>`. `golf-community` (tools/data/community.py)
is the CLI on top. See docs/community_holes.md.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path

from golf.core import rom_utils
from golf.formats.hole_data import HoleData

from .catalog import (
    COMMUNITY,
    OWNER_PATTERN,
    VANILLA_OWNERS,
    Catalog,
    CatalogEntry,
    CatalogError,
    CommunityCourse,
    FileSource,
    HoleId,
    HoleStore,
    content_hash,
    course_lineage,
)
from .derive import check_hole, transform_problems, visible

#: where an index keeps its community holes, relative to its own directory
COMMUNITY_DIR = "community"
#: a course folder's hole files, as the dump tools name them
_HOLE_FILE = re.compile(r"hole_(\d\d)\.json")


class PublishError(CatalogError):
    """A community hole or course that cannot be published."""


@dataclass(frozen=True)
class Publication:
    """What publishing would write: nothing is on disk until `write`."""

    catalog: Catalog
    #: each new version's frozen file, by the entry that names it
    files: Mapping[HoleId, HoleData]
    #: the course's holes whose working copy matches their newest version
    unchanged: tuple[HoleId, ...] = ()
    #: what was done or noticed along the way, for the person publishing
    notes: tuple[str, ...] = ()

    @property
    def entries(self) -> list[CatalogEntry]:
        return [self.catalog[hole_id] for hole_id in sorted(self.files)]

    def path_for(self, hole_id: HoleId) -> Path:
        source = self.catalog[hole_id].source
        assert isinstance(source, FileSource)
        return source.path

    def write(self, index: Path) -> None:
        """Write each frozen file, then the index that names them."""
        paths = [self.path_for(hole_id) for hole_id in self.files]
        for path in paths:
            if path.exists():
                raise PublishError(
                    f"{path} already exists; community holes are never overwritten"
                )
        for hole_id, path in zip(self.files, paths, strict=True):
            path.parent.mkdir(parents=True, exist_ok=True)
            self.files[hole_id].save(str(path))
        self.catalog.save(index)


def community_file(hole_id: HoleId) -> str:
    """`community/georgia_pines/07.json`, or `...@2.json` for a later version."""
    owner, slug = hole_id.lineage.split("/")
    suffix = "" if hole_id.version == 1 else f"@{hole_id.version}"
    return f"{COMMUNITY_DIR}/{owner}/{slug}{suffix}.json"


def _check_owner(owner: str) -> None:
    if not OWNER_PATTERN.fullmatch(owner):
        raise PublishError(f"owner {owner!r} must match {OWNER_PATTERN.pattern}")
    if owner in VANILLA_OWNERS:
        raise PublishError(f"{owner} names a vanilla course")


@dataclass(frozen=True)
class _Prepared:
    entry: CatalogEntry
    #: the frozen copy, or None when the newest version already holds this content
    frozen: HoleData | None
    notes: tuple[str, ...]


def _prepare(
    catalog: Catalog, hole: HoleData, lineage: str, author: str, root: Path
) -> _Prepared:
    """The entry `hole` publishes as under `lineage`: its next version, or its newest
    when the content is unchanged. Raises PublishError."""
    published, notes = visible(hole)
    check_hole(published)
    problems = transform_problems(published)
    if problems:
        raise PublishError(
            f"{lineage}: a transform cannot run on the hole: " + "; ".join(problems)
        )
    digest = content_hash(published)

    versions = [entry for entry in catalog if entry.id.lineage == lineage]
    for entry in versions:
        if entry.kind != COMMUNITY:
            raise PublishError(f"{lineage} is already {entry.id}, a {entry.kind} hole")
    newest = versions[-1] if versions else None
    if newest is not None and newest.content_hash == digest and not newest.withdrawn:
        if newest.author == author:
            return _Prepared(newest, None, tuple(notes))
        corrected = replace(newest, author=author)
        return _Prepared(
            corrected,
            None,
            (*notes, f"credited {newest.id} to {author}, was {newest.author}"),
        )

    hole_id = HoleId(lineage, (newest.id.version if newest else 0) + 1)
    for other in catalog:
        # an older version's content may come back as a new version, which is how a
        # version is undone (docs/catalog.md); a withdrawn version's may not
        restores = other.id.lineage == lineage and not other.withdrawn
        if other.content_hash == digest and not restores:
            raise PublishError(f"{lineage}: the hole is identical to {other.id}")

    published.metadata["hole"] = hole.metadata.get("hole", 1)
    entry = CatalogEntry(
        id=hole_id,
        source=FileSource(community_file(hole_id), root),
        content_hash=digest,
        par=published.metadata["par"],
        distance=published.metadata["distance"],
        author=author,
    )
    return _Prepared(entry, published, tuple(notes))


def publish_hole(
    catalog: Catalog, hole: HoleData, lineage: str, *, root: Path
) -> Publication:
    """Publish one hole under its author, `<author>/<slug>`, or under `community`.

    The credit is the hole's own `author`. `root` is the directory of the index the
    entry will be written to. Raises PublishError.
    """
    owner = HoleId(lineage).lineage.split("/")[0]
    _check_owner(owner)
    if owner in catalog.courses:
        raise PublishError(
            f"{owner} is a community course; publish its holes from its folder"
        )
    author = hole.metadata.get("author")
    if not author:
        raise PublishError(f"{lineage}: the hole names no author")
    prepared = _prepare(catalog, hole, lineage, author, root)
    if prepared.frozen is None and prepared.entry == catalog[prepared.entry.id]:
        raise PublishError(f"the hole is identical to {prepared.entry.id}")
    entries = {**catalog.entries, prepared.entry.id: prepared.entry}
    files = {} if prepared.frozen is None else {prepared.entry.id: prepared.frozen}
    return Publication(
        replace(catalog, version=catalog.version + 1, entries=entries),
        files,
        notes=prepared.notes,
    )


def load_course_folder(folder: Path) -> dict[int, HoleData]:
    """A course folder's holes by number, from its `hole_NN.json` files."""
    holes = {}
    for path in sorted(Path(folder).iterdir()):
        match = _HOLE_FILE.fullmatch(path.name)
        if match:
            hole = HoleData()
            hole.load(path)
            holes[int(match[1])] = hole
    return holes


def publish_course(
    catalog: Catalog,
    holes: Mapping[int, HoleData],
    slug: str,
    *,
    root: Path,
    name: str | None = None,
    author: str | None = None,
) -> Publication:
    """Publish a community course's 18 holes as `<slug>/01`-`<slug>/18`.

    A course is listed the first time it is published, which needs its `name` and
    `author`; later they correct its listing in place. A hole is credited to its own
    `author`, or to the course's. Holes whose working copy matches their newest version
    are left as they are. Raises PublishError.
    """
    _check_owner(slug)
    if slug == COMMUNITY:
        raise PublishError(f"{COMMUNITY} is not a course")
    numbers = sorted(holes)
    expected = list(range(1, rom_utils.HOLES_PER_COURSE + 1))
    if numbers != expected:
        raise PublishError(
            f"a course is holes 1-{rom_utils.HOLES_PER_COURSE}, got {numbers}"
        )
    listed = catalog.courses.get(slug)
    if listed is None:
        others = [
            entry.id for entry in catalog if entry.id.lineage.startswith(f"{slug}/")
        ]
        if others:
            raise PublishError(f"{slug} is already an author, of {others[0]}")
        if not (name and author):
            raise PublishError(f"{slug} is a new course; give its name and author")
        course = CommunityCourse(name, author)
    else:
        course = CommunityCourse(name or listed.name, author or listed.author)
    courses = {**catalog.courses, slug: course}
    notes = []
    if listed is None:
        notes.append(f"listed {slug}, {course.name!r} by {course.author}")
    elif listed != course:
        notes.append(
            f"corrected {slug}'s listing to {course.name!r} by {course.author}"
        )

    entries = dict(catalog.entries)
    files: dict[HoleId, HoleData] = {}
    unchanged = []
    with_course = replace(catalog, courses=courses)
    for number in numbers:
        lineage = course_lineage(slug, number)
        hole = holes[number]
        credit = hole.metadata.get("author") or course.author
        prepared = _prepare(with_course, hole, lineage, credit, root)
        notes += [f"{lineage}: {note}" for note in prepared.notes]
        entries[prepared.entry.id] = prepared.entry
        if prepared.frozen is None:
            unchanged.append(prepared.entry.id)
        else:
            files[prepared.entry.id] = prepared.frozen

    changed = bool(files) or entries != dict(catalog.entries) or listed != course
    if not changed:
        raise PublishError(f"every hole of {slug} matches its newest version")
    return Publication(
        Catalog(catalog.version + 1, entries, courses),
        files,
        tuple(unchanged),
        tuple(notes),
    )


def community_entries(catalog: Catalog) -> list[CatalogEntry]:
    return [entry for entry in catalog if entry.kind == COMMUNITY]


def check_community(catalog: Catalog) -> list[str]:
    """Every problem with the catalog's live community holes.

    Each one must load to its content hash from where publishing puts it, and be a hole
    a seed could be built with, through every transform.
    """
    store = HoleStore()
    problems = []
    for entry in community_entries(catalog):
        if not entry.live:
            continue
        source = entry.source
        assert isinstance(source, FileSource)
        if source.file != community_file(entry.id):
            problems.append(
                f"{entry.id}: {source.file} is not where publishing puts it, "
                f"{community_file(entry.id)}"
            )
        try:
            hole = store.load(entry)
            check_hole(hole)
        except CatalogError as problem:
            problems.append(f"{entry.id}: {problem}")
            continue
        problems += [f"{entry.id}: {problem}" for problem in transform_problems(hole)]
    return problems
