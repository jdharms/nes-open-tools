"""Derived holes against the real vanilla holes: the catalog's own, and one published here.

A derived hole is built from a vanilla hole, so whether the checked-in ones build to
their content hashes, hold only their own cells and run through every transform can only
be checked where the vanilla holes are dumped.
"""

import json
import shutil
import subprocess
import sys

import pytest

from golf.formats.hole_data import HoleData
from golf.randomizer.build import build_unfinished
from golf.randomizer.catalog import (
    DEFAULT_INDEX,
    DERIVED,
    REPO_ROOT,
    US_ROM,
    Catalog,
    HoleStore,
    content_hash,
)
from golf.randomizer.curation import DEFAULT_CURATION, CurationSnapshot
from golf.randomizer.derive import check_derived, derive
from golf.randomizer.generate import generate
from golf.randomizer.manifest import Settings, required_roms

LINEAGE = "jdharms/nes_us_12_short"
ROM_PATH = REPO_ROOT / "nes_open_us.nes"


def test_every_checked_in_derived_hole_builds_and_takes_every_transform(
    vanilla_courses,
):
    assert check_derived(Catalog.load(), HoleStore(vanilla_courses)) == []


def forward_tee(vanilla_courses, path) -> None:
    """The US 12th, a 40-row par 5, cut to 30 rows with a tee box drawn in its fairway."""
    hole = HoleData()
    hole.load(vanilla_courses / "us" / "hole_12.json")
    # as the editor's row tool leaves it: rows hidden, not deleted
    hole.terrain_height = 30
    hole.metadata["scroll_limit"] = 1
    hole.terrain[28] = list(hole.terrain[38])
    hole.terrain[29] = list(hole.terrain[39])
    hole.terrain[23][14:16] = [0x35, 0x36]
    hole.metadata["par"] = 3
    hole.metadata["distance"] = 190
    hole.metadata["tee"] = {"x": 120, "y": 190}
    hole.save(str(path))


@pytest.fixture
def scratch(tmp_path):
    """A copy of the catalog index and curation file, to publish into."""
    index = tmp_path / "catalog" / "holes.json"
    index.parent.mkdir()
    shutil.copy(DEFAULT_INDEX, index)
    curation = tmp_path / "catalog" / "curation.json"
    shutil.copy(DEFAULT_CURATION, curation)
    return index, curation


def run(index, curation, *args) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.data.derive",
            "--catalog",
            str(index),
            "--curation",
            str(curation),
            *map(str, args),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )


def test_a_forward_tee_is_published_drawn_and_built(vanilla_courses, scratch, tmp_path):
    index, curation = scratch
    edited = tmp_path / "us_12_short.json"
    forward_tee(vanilla_courses, edited)
    before = Catalog.load(index)
    new = ("new", "nes_us/12", edited, LINEAGE, "--author", "jdharms")

    dry = run(index, curation, *new, "--dry-run")
    assert dry.returncode == 0, dry.stderr
    assert "would write" in dry.stdout
    assert Catalog.load(index) == before
    assert not (index.parent / "derived").exists()

    published = run(index, curation, *new)
    assert published.returncode == 0, published.stderr
    assert "par 5 -> 3, 642 -> 190 yards" in published.stdout
    assert "dropped 5 attribute rows" in published.stdout

    catalog = Catalog.load(index)
    entry = catalog[LINEAGE]
    assert catalog.version == before.version + 1
    assert (entry.kind, entry.par, entry.distance) == (DERIVED, 3, 190)
    hole = HoleStore(vanilla_courses).load(entry)
    assert (hole.terrain_height, len(hole.terrain), len(hole.attributes)) == (
        30,
        30,
        15,
    )

    # only the cells that differ are in the repository's half of the hole
    delta = json.loads(
        (index.parent / "derived/jdharms/nes_us_12_short.json").read_text()
    )
    cells = sum(len(cell[2].split()) for cell in delta["terrain"]["cells"])
    assert 0 < cells < 2 * 22 + 3
    assert "greens" not in delta

    records = CurationSnapshot.load(curation)
    assert records.for_hole(LINEAGE).tags == {"short"}
    assert records.for_hole(LINEAGE).family == records.for_hole("nes_us/12").family
    assert records.for_hole(LINEAGE).family is not None

    checked = run(index, curation, "check")
    assert checked.returncode == 0, checked.stderr
    assert run(index, curation, *new).returncode == 1  # identical to version 1

    # no seed draws it unless its settings include derived holes
    seeds = [f"derived-{number}" for number in range(40)]
    plain = [generate(catalog, records, Settings(prng_seed=seed)) for seed in seeds]
    assert not any(
        slot.id == entry.id for manifest in plain for slot in manifest.course.holes
    )
    # the US 12th was in a family already, so nothing about the vanilla draw moved
    assert (
        plain[0].course
        == generate(
            before,
            CurationSnapshot.load(DEFAULT_CURATION),
            Settings(prng_seed=seeds[0]),
        ).course
    )
    with_derived = [
        generate(
            catalog, records, Settings(prng_seed=seed, include=frozenset({DERIVED}))
        )
        for seed in seeds
    ]
    drawn = [
        manifest
        for manifest in with_derived
        if any(slot.id == entry.id for slot in manifest.course.holes)
    ]
    assert drawn
    slot = next(slot for slot in drawn[0].course.holes if slot.id == entry.id)
    assert slot.par == 3
    assert "nes_open_us" in required_roms(drawn[0], catalog)
    family = {"nes_us/12", "jp_france/03"}
    assert not any(str(other.id) in family for other in drawn[0].course.holes)

    # and the course builds, with the hole as published in its slot
    us_only = [
        generate(
            catalog,
            records,
            Settings(
                prng_seed=seed,
                include=frozenset({DERIVED}),
                sources=frozenset({US_ROM}),
                music="nes_us",
            ),
        )
        for seed in seeds
    ]
    manifest = next(
        one for one in us_only if any(slot.id == entry.id for slot in one.course.holes)
    )
    built = build_unfinished(
        manifest, catalog, HoleStore(vanilla_courses), ROM_PATH.read_bytes()
    )
    position = [slot.id for slot in manifest.course.holes].index(entry.id)
    assert content_hash(built.holes[position]) == entry.content_hash
    assert built.ips


def test_a_hole_cropped_at_the_top_is_published_as_an_offset(vanilla_courses, scratch):
    """The US 12th with its top two rows of forest gone, and everything else moved up."""
    index, curation = scratch
    hole = HoleData()
    hole.load(vanilla_courses / "us" / "hole_12.json")
    hole.terrain = hole.terrain[2:]
    hole.terrain_height -= 2
    hole.attributes = hole.attributes[1:]
    hole.metadata["scroll_limit"] -= 1
    hole.green_y -= 16
    hole.metadata["tee"]["y"] -= 16
    hole.terrain[30][3] = 0x35

    catalog = Catalog.load(index)
    store = HoleStore(vanilla_courses)
    derivation = derive(
        catalog,
        CurationSnapshot.load(curation),
        store,
        "nes_us/12",
        hole,
        "community/nes_us_12_short5",
        "jdharms",
        root=index.parent,
    )
    delta = derivation.delta
    assert delta["row_offset"] == 2
    assert delta["terrain"] == {"rows": 38, "cells": [[30, 3, "35"]]}
    assert delta["attributes"] == {"rows": 19, "cells": []}
    assert set(delta["metadata"]) == {"scroll_limit", "green", "tee"}
    assert derivation.terrain_share < 0.01

    derivation.write(index, curation)
    published = Catalog.load(index)
    entry = published["community/nes_us_12_short5"]
    assert content_hash(store.load(entry)) == entry.content_hash
    assert check_derived(published, store) == []
