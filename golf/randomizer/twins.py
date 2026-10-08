"""
Twins: holes that are the same hole in two releases, proposed from the hole data itself.

A family is a person's judgment (see `golf.randomizer.curation`), but the judgment is not
hard to make well-informed. Across the vanilla set a shared putting green is the strongest
single signal: 39 greens layouts appear exactly twice and none more often, every one of
them pairing an NES Open hole with a Mario Open one. Terrain is the second: 37 of those 39
pairs also agree on better than 80% of their terrain cells, and terrain catches three more
pairs whose greens were redrawn between releases.

So a candidate group is holes with a byte-identical `greens` layout, plus any remaining
pair whose terrain agrees above a threshold, ranked greens-first so a curator can walk
them. Neither signal subsumes the other, and neither decides anything: nothing here writes
curation. See docs/catalog.md.
"""

import hashlib
import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from itertools import combinations

from golf.formats.hole_data import HoleData

from .catalog import Catalog, CatalogEntry, HoleStore, RomSource
from .curation import CurationSnapshot

#: terrain agreement below which a pair is not worth showing, when the greens differ
MIN_TERRAIN_SCORE = 0.80

NES_OPEN_PREFIX = "nes_"


@dataclass(frozen=True)
class HoleSignature:
    """The parts of a hole that say whether two holes are the same hole."""

    lineage: str
    par: int
    distance: int
    greens_hash: str
    terrain: tuple[tuple[int, ...], ...]
    course: str | None = None
    hole: int | None = None

    @property
    def rangefinder_query(self) -> str | None:
        """`course=uk&hole=1`, the rangefinder page's deep link, or None for a file hole."""
        if self.course is None or self.hole is None:
            return None
        return f"course={self.course}&hole={self.hole}"


def _canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def signature(entry: CatalogEntry, hole: HoleData) -> HoleSignature:
    data = hole.to_dict()
    source = entry.source
    vanilla = source if isinstance(source, RomSource) else None
    return HoleSignature(
        lineage=entry.id.lineage,
        par=entry.par,
        distance=entry.distance,
        greens_hash=hashlib.sha256(_canonical(data["greens"]).encode()).hexdigest(),
        terrain=tuple(
            tuple(row) for row in data["terrain"]["rows"][: hole.terrain_height]
        ),
        course=vanilla.course if vanilla else None,
        hole=vanilla.hole if vanilla else None,
    )


def signatures(catalog: Catalog, store: HoleStore) -> list[HoleSignature]:
    """A signature per drawable lineage whose hole data is present under the store.

    Entries whose data is absent are skipped, so a checkout without the JP dump still
    works.
    """
    found = []
    for entry in catalog.newest().values():
        if not store.has(entry):
            continue
        found.append(signature(entry, store.load(entry)))
    return found


def terrain_similarity(left: HoleSignature, right: HoleSignature) -> float:
    """Share of terrain cells the two holes agree on, counting a height difference against."""
    shared = min(len(left.terrain), len(right.terrain))
    if shared == 0:
        return 0.0
    same = 0
    total = 0
    for a, b in zip(left.terrain[:shared], right.terrain[:shared], strict=True):
        # rows of unequal width agree only where both have a cell, but the wider row's
        # width is what the pair is scored out of
        same += sum(1 for x, y in zip(a, b, strict=False) if x == y)
        total += max(len(a), len(b))
    tallest = max(left.terrain, key=len, default=())
    total += abs(len(left.terrain) - len(right.terrain)) * max(len(tallest), 1)
    return same / total if total else 0.0


@dataclass(frozen=True)
class Candidate:
    """Holes the data says are probably one hole, with the evidence for it."""

    members: tuple[HoleSignature, ...]
    greens_match: bool
    terrain_score: float

    @property
    def lineages(self) -> tuple[str, ...]:
        return tuple(member.lineage for member in self.members)

    @property
    def evidence(self) -> str:
        greens = "identical greens" if self.greens_match else "different greens"
        pars = {member.par for member in self.members}
        par = f"par {pars.pop()}" if len(pars) == 1 else "par differs"
        return f"{greens} · terrain {self.terrain_score:.0%} · {par}"


def _worst_pair_score(members: Sequence[HoleSignature]) -> float:
    return min(
        (terrain_similarity(a, b) for a, b in combinations(members, 2)), default=1.0
    )


def suggested_label(lineages: Iterable[str]) -> str:
    """`nes_uk/01` -> `nes_uk_01`, naming a family after its NES Open hole by convention."""
    ordered = sorted(lineages)
    named = next(
        (one for one in ordered if one.startswith(NES_OPEN_PREFIX)), ordered[0]
    )
    return named.replace("/", "_")


def candidates(
    holes: Sequence[HoleSignature],
    curation: CurationSnapshot,
    min_score: float = MIN_TERRAIN_SCORE,
    include_familied: bool = False,
) -> list[Candidate]:
    """Groups worth a curator's attention, best evidence first.

    Holes already in a family are left out unless `include_familied`, since a hole is in at
    most one family and the interesting question is about the ones still unmapped.
    """
    pool = [
        hole
        for hole in holes
        if include_familied or curation.for_hole(hole.lineage).family is None
    ]
    by_greens: dict[str, list[HoleSignature]] = {}
    for hole in pool:
        by_greens.setdefault(hole.greens_hash, []).append(hole)

    found: list[Candidate] = []
    grouped: set[str] = set()
    for members in by_greens.values():
        if len(members) < 2:
            continue
        members = sorted(members, key=lambda hole: hole.lineage)
        found.append(Candidate(tuple(members), True, _worst_pair_score(members)))
        grouped.update(hole.lineage for hole in members)

    for left, right in combinations(sorted(pool, key=lambda hole: hole.lineage), 2):
        if left.lineage in grouped or right.lineage in grouped:
            continue
        score = terrain_similarity(left, right)
        if score >= min_score:
            found.append(Candidate((left, right), False, score))

    return sorted(
        found,
        key=lambda one: (not one.greens_match, -one.terrain_score, one.lineages),
    )
