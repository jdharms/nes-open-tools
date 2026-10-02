"""
NES Open Tournament Golf - Hazard Stamps

Builds the built-in hazard stamps from the hazard shapes found in a set of holes.
"""

import hashlib
from collections.abc import Iterable
from pathlib import Path

from golf.algorithms.hazard_shapes import HazardShape, hazard_shapes
from golf.formats.hole_data import HoleData

from .stamp_data import StampData, StampMetadata

CATEGORY = "hazard"
#: generated stamps carry no timestamp, so that regenerating them changes nothing
CREATED = ""


def _tile_text(shape: HazardShape) -> str:
    return "\n".join(
        " ".join("--" if tile is None else f"{tile:02X}" for tile in row)
        for row in shape.tiles
    )


def hazard_stamp(shape: HazardShape) -> StampData:
    """The stamp for one shape, named by its tiles so the same shape keeps its ID."""
    digest = hashlib.sha1(_tile_text(shape).encode()).hexdigest()[:10]
    stamp = StampData()
    stamp.tiles = [list(row) for row in shape.tiles]
    stamp.width = shape.width
    stamp.height = shape.height
    stamp.mode = "terrain"
    stamp.metadata = StampMetadata(
        stamp_id=f"hazard_{digest}",
        name=f"vanilla ×{shape.count}",
        category=f"{CATEGORY}/{shape.bucket}",
    )
    stamp.metadata.created = CREATED
    return stamp


def hazard_stamps(holes: Iterable[HoleData]) -> list[StampData]:
    """A stamp for every distinct enclosed hazard in `holes`, smallest first."""
    return [hazard_stamp(shape) for shape in hazard_shapes(holes)]


def stamp_path(root: Path, stamp: StampData) -> Path:
    """Where a generated stamp lives under the built-in stamps directory."""
    return root / stamp.metadata.category / f"{stamp.metadata.id}.json"
