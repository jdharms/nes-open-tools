"""
The pool: the holes a seed may draw, grouped into the families a draw chooses between.

A hole is in the pool when its lineage's newest version is not withdrawn, curation leaves
it drawable, its source ROM is one the settings allow, and it has none of the excluded
tags. Community holes have no source ROM and are never in the pool until the settings
gain a way to ask for them.

Holes a curator put in one family form one `Family`; every other hole is a family of its
own, and so is every hole when the settings allow family repeats. Generation draws a
family per slot and then a member of it, so a hole with a twin is no likelier than a hole
without one. The pool also names its expert holes, the ones curation tags `expert`, for
the draw rule that caps them. See docs/manifest.md.
"""

from dataclasses import dataclass, field

from .catalog import Catalog, CatalogEntry, HoleId, RomSource
from .curation import EXPERT_TAG, CurationSnapshot
from .manifest import Settings


@dataclass(frozen=True)
class Family:
    key: str
    members: tuple[CatalogEntry, ...]
    pars: frozenset[int] = field(init=False)

    def __post_init__(self):
        object.__setattr__(
            self, "pars", frozenset(member.par for member in self.members)
        )

    def with_par(self, par: int) -> tuple[CatalogEntry, ...]:
        return tuple(member for member in self.members if member.par == par)


@dataclass(frozen=True)
class Pool:
    """Families sorted by key, members sorted by id, so seeded draws are reproducible."""

    families: tuple[Family, ...]
    #: the pool's holes curation tags `expert`, which the expert-cap draw rule counts
    experts: frozenset[HoleId] = frozenset()

    def families_with_par(self, par: int) -> int:
        return sum(par in family.pars for family in self.families)


def source_rom(entry: CatalogEntry) -> str | None:
    """The vanilla ROM a hole comes from, or None for a community hole."""
    return entry.source.rom if isinstance(entry.source, RomSource) else None


def build_pool(
    catalog: Catalog, curation: CurationSnapshot, settings: Settings
) -> Pool:
    groups: dict[str, list[CatalogEntry]] = {}
    experts = set()
    for lineage, entry in sorted(catalog.newest().items()):
        record = curation.for_hole(entry.id)
        if not record.drawable or source_rom(entry) not in settings.sources:
            continue
        if record.tags & settings.exclude_tags:
            continue
        key = (
            lineage
            if settings.allow_family_repeats or record.family is None
            else record.family
        )
        groups.setdefault(key, []).append(entry)
        if EXPERT_TAG in record.tags:
            experts.add(entry.id)
    return Pool(
        tuple(Family(key, tuple(members)) for key, members in sorted(groups.items())),
        frozenset(experts),
    )
