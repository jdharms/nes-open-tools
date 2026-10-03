"""Every vanilla hole in the catalog, for tests that run something over all of them.

Ask for the `vanilla_courses` and `vanilla_jp_courses` fixtures first: they skip or fail
when the dumped courses are missing.
"""

from collections.abc import Iterator

from golf.formats.hole_data import HoleData
from golf.randomizer.catalog import DEFAULT_COURSES, Catalog, HoleStore, RomSource


def vanilla_holes() -> Iterator[tuple[str, HoleData]]:
    """(id, hole) for every vanilla hole, in id order."""
    store = HoleStore(DEFAULT_COURSES)
    for entry in Catalog.load():
        if isinstance(entry.source, RomSource) and not entry.withdrawn:
            yield str(entry.id), store.load(entry)
