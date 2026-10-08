"""The checked-in deltas and the derived holes of the catalog agree with each other.

Every derived entry's delta is in the repository and names the entry's base, no delta is
left without an entry, and no derived hole takes a vanilla course's lineage. Whether each
one builds to its content hash needs the vanilla holes, so that check is in
`tests/integration/test_derived_holes.py`. See docs/derived_holes.md.
"""

import json

from golf.randomizer.catalog import DEFAULT_INDEX, Catalog, DerivedSource
from golf.randomizer.delta import FORMAT
from golf.randomizer.derive import (
    DELTA_DIR,
    VANILLA_OWNERS,
    delta_file,
    derived_entries,
)

CATALOG = Catalog.load()
CATALOG_ROOT = DEFAULT_INDEX.parent


def test_every_derived_hole_has_its_delta_where_golf_derive_writes_it():
    problems = []
    for entry in derived_entries(CATALOG):
        source = entry.source
        assert isinstance(source, DerivedSource)
        if source.delta != delta_file(entry.id):
            problems.append(
                f"{entry.id}: delta is {source.delta}, not {delta_file(entry.id)}"
            )
        elif not source.path.is_file():
            problems.append(f"{entry.id}: {source.path} is missing")
        else:
            delta = json.loads(source.path.read_text())
            if delta.get("format") != FORMAT or delta.get("base") != str(
                source.base.id
            ):
                problems.append(
                    f"{entry.id}: {source.path} is not a format {FORMAT} delta for "
                    f"{source.base.id}"
                )
    assert not problems, "\n".join(problems)


def test_no_delta_is_left_without_an_entry():
    directory = CATALOG_ROOT / DELTA_DIR
    named = {
        entry.source.path
        for entry in derived_entries(CATALOG)
        if isinstance(entry.source, DerivedSource)
    }
    stray = sorted(
        str(path)
        for path in directory.rglob("*")
        if path.is_file() and path not in named and path.name != ".gitkeep"
    )
    assert not stray, "deltas no catalog entry names:\n" + "\n".join(stray)


def test_no_derived_hole_takes_a_vanilla_lineage():
    taken = [
        str(entry.id)
        for entry in derived_entries(CATALOG)
        if entry.id.lineage.split("/")[0] in VANILLA_OWNERS
    ]
    assert not taken
