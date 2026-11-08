"""What a hole's transforms compute from the hole alone, kept for the next seed that draws it.

Mirroring a hole refills its forests (`ForestFiller.fill_all`), and redrawing its hazards
first finds its features (`feature_groups`). Neither depends on a seed, and together they
are nearly all of a seed's build time, so both are computed once per hole and kept for
the life of the process. The catalog bounds what they hold: about 42 KB for a hole, its
mirror and the hazard groups of both. See `docs/hole_transforms.md`.

- **Keys** hash the whole hole, not its `content_hash`, which covers only what reaches
  the ROM. Mirroring reads more than that: rows past `terrain_height`, which the fill
  sees, and the metadata it copies.
- **A mirrored hole is copied out**, since callers may change the hole they get. Hazard
  groups are immutable and shared.
- **Threads**: each entry is computed in full before it is stored, and storing is one
  dict assignment, so a reader sees an entry whole or not at all. Two threads that miss
  the same hole at once both compute it and store equal values.

`clear` empties both, which tests do between tests (`tests/conftest.py`).
"""

import copy
import hashlib
import json

from golf.algorithms.forest_fill import ForestFillError
from golf.algorithms.hazards import HazardGroup, hazard_groups
from golf.algorithms.mirror import MirrorError, mirror_hole
from golf.formats.hole_data import HoleData

_mirrors: dict[str, HoleData] = {}
_hazard_groups: dict[str, tuple[HazardGroup, ...]] = {}


def hole_key(hole: HoleData) -> str:
    """SHA-256 over every field of a `HoleData` but the editor's `filepath` and
    `modified`, which no transform reads."""
    whole = {
        "terrain": hole.terrain,
        "terrain_height": hole.terrain_height,
        "attributes": hole.attributes,
        "greens": hole.greens,
        "green_x": hole.green_x,
        "green_y": hole.green_y,
        "metadata": hole.metadata,
    }
    text = json.dumps(whole, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode()).hexdigest()


def mirrored(hole: HoleData) -> HoleData:
    """`mirror_hole(hole)`, as a new hole the caller may change.

    Raises what `mirror_hole` raises, and keeps nothing for a hole it refuses.
    """
    key = hole_key(hole)
    kept = _mirrors.get(key)
    if kept is None:
        kept = mirror_hole(hole)
        _mirrors[key] = kept
    return copy.deepcopy(kept)


def groups(hole: HoleData) -> tuple[HazardGroup, ...]:
    """`hazard_groups(hole)`."""
    key = hole_key(hole)
    kept = _hazard_groups.get(key)
    if kept is None:
        kept = hazard_groups(hole)
        _hazard_groups[key] = kept
    return kept


def warm(hole: HoleData) -> None:
    """Compute what a seed drawing `hole` could ask for: its mirror and the hazard groups
    of it and its mirror, so a hazard redraw after `mirror@1` hits too. A hole that will
    not mirror keeps only its own groups."""
    groups(hole)
    try:
        flipped = mirrored(hole)
    except (MirrorError, ForestFillError):  # no mirror@1 for this hole
        return
    groups(flipped)


def sizes() -> tuple[int, int]:
    """(mirrored holes, hazard group entries) held."""
    return len(_mirrors), len(_hazard_groups)


def clear() -> None:
    _mirrors.clear()
    _hazard_groups.clear()
