"""Integration: the compressors' exact output across the whole catalog.

A round trip only proves the output decompresses; this pins the bytes themselves, which
reach every seed's unfinished IPS. A change that alters them needs a new build version.
"""

import hashlib

from golf.core.compressor import GreensCompressor, TerrainCompressor
from golf.randomizer.catalog import Catalog, HoleStore

CATALOG_DIGEST = "a0994881636e39e3ee6e90351afb51948f78a466c43acc263578c09b9193fc2c"


def test_every_catalog_hole_compresses_to_the_pinned_bytes(
    vanilla_courses, vanilla_jp_courses
):
    store = HoleStore(vanilla_courses)
    terrain, greens = TerrainCompressor(), GreensCompressor()
    digest = hashlib.sha256()
    for entry in Catalog.load():
        hole = store.load(entry)
        digest.update(terrain.compress(hole.terrain[: hole.terrain_height]))
        digest.update(greens.compress(hole.greens))
    assert digest.hexdigest() == CATALOG_DIGEST
