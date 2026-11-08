"""What a hole's transforms compute from the hole alone, kept for the next seed that draws it.

Mirroring a hole refills its forests (`ForestFiller.fill_all`), and redrawing its hazards
first finds its features (`feature_groups`). Neither depends on a seed, and together they
are nearly all of a seed's build time, so both are computed once per hole and kept for
the life of the process. The catalog bounds what they hold: about 42 KB for a hole, its
mirror and the hazard groups of both. See `docs/hole_transforms.md`.

Each is a `Memo`, made with `memo`, which registers it so `clear` and `sizes` reach
every one; a transform's registry entry (`golf/randomizer/transforms.py`) calls the memo
in place of the operation. A new transform with seedless work to keep adds one line here.

- **Keys** hash the whole hole, not its `content_hash`, which covers only what reaches
  the ROM. Mirroring reads more than that: rows past `terrain_height`, which the fill
  sees, and the metadata it copies.
- **A memo that returns a hole copies it out** (`copy_out`), since callers may change
  the hole they get. One that returns an immutable value, as the hazard groups are,
  shares it.
- **Threads**: each entry is computed in full before it is stored, and storing is one
  dict assignment, so a reader sees an entry whole or not at all. Two threads that miss
  the same hole at once both compute it and store equal values.

`clear` empties every memo, which tests do between tests (`tests/conftest.py`).
"""

import copy
import hashlib
import json
from collections.abc import Callable

from golf.algorithms.forest_fill import ForestFillError
from golf.algorithms.hazards import hazard_groups
from golf.algorithms.mirror import MirrorError, mirror_hole
from golf.formats.hole_data import HoleData


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


class Memo[T]:
    """`compute(hole)`, computed once per `hole_key` and kept.

    Raises what `compute` raises, and keeps nothing for a hole it refuses.
    """

    def __init__(self, name: str, compute: Callable[[HoleData], T], copy_out: bool):
        self.name = name
        self.compute = compute
        self.copy_out = copy_out
        self._kept: dict[str, T] = {}

    def __call__(self, hole: HoleData) -> T:
        key = hole_key(hole)
        kept = self._kept.get(key)
        if kept is None:
            kept = self.compute(hole)
            self._kept[key] = kept
        return copy.deepcopy(kept) if self.copy_out else kept

    def __len__(self) -> int:
        return len(self._kept)

    def clear(self) -> None:
        self._kept.clear()


#: every memo `memo` made, which `clear` and `sizes` walk
MEMOS: list[Memo] = []


def memo[T](
    name: str, compute: Callable[[HoleData], T], *, copy_out: bool = False
) -> Memo[T]:
    """A registered `Memo`. Pass `copy_out` when `compute` returns something mutable."""
    if any(other.name == name for other in MEMOS):
        raise ValueError(f"a transform cache named {name!r} already exists")
    made = Memo(name, compute, copy_out)
    MEMOS.append(made)
    return made


#: `mirror_hole(hole)`, as a new hole the caller may change
mirrored = memo("mirrors", mirror_hole, copy_out=True)
#: `hazard_groups(hole)`, which is immutable
groups = memo("hazard_groups", hazard_groups)


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


def sizes() -> dict[str, int]:
    """How many entries each memo holds, by name."""
    return {kept.name: len(kept) for kept in MEMOS}


def clear() -> None:
    for kept in MEMOS:
        kept.clear()
