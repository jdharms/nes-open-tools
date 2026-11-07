"""Counts of the checked-in catalog's holes, for tests that pin how many there are.

Each ROM's vanilla holes are a fixed number; the holes derived from them grow as they are
published, and every check that walks a ROM's holes walks those too.
"""

from golf.randomizer.catalog import DERIVED, Catalog

VANILLA_HOLES = {"nes_open_us": 54, "mario_open_jp": 90}


def derived_from(catalog: Catalog, rom: str) -> int:
    """The live derived holes whose base comes from `rom`."""
    return sum(
        1
        for entry in catalog
        if entry.live and entry.kind == DERIVED and entry.rom == rom
    )


def holes_from(catalog: Catalog, rom: str) -> int:
    """What a rehydration of `rom` checks: its vanilla holes and those derived from them."""
    return VANILLA_HOLES[rom] + derived_from(catalog, rom)


def lineages(catalog: Catalog) -> int:
    """The catalog's lineages, each listed once whatever its versions."""
    return len(catalog.newest())
