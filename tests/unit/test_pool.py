"""Unit tests for building a generation pool from the catalog and curation."""

from golf.randomizer.catalog import (
    COMMUNITY,
    DERIVED,
    JP_ROM,
    US_ROM,
    Catalog,
    CatalogEntry,
    DerivedSource,
    FileSource,
    HoleId,
    RomSource,
)
from golf.randomizer.curation import CurationSnapshot
from golf.randomizer.manifest import Settings
from golf.randomizer.pool import build_pool


def entry(
    hole_id: str, par: int = 4, rom: str | None = US_ROM, withdrawn: bool = False
) -> CatalogEntry:
    source = (
        FileSource("community/hole.json")
        if rom is None
        else RomSource(rom, "course", 1)
    )
    return CatalogEntry(
        HoleId.parse(hole_id), source, "0" * 64, par, 400, "Test", withdrawn
    )


def catalog(*entries: CatalogEntry) -> Catalog:
    return Catalog(1, {item.id: item for item in entries})


def pool_keys(pool) -> dict[str, list[str]]:
    return {
        family.key: [str(member.id) for member in family.members]
        for family in pool.families
    }


def test_draws_only_the_newest_version_of_a_lineage():
    pool = build_pool(
        catalog(entry("a/one"), entry("a/one@2")), CurationSnapshot(), Settings()
    )
    assert pool_keys(pool) == {"a/one": ["a/one@2"]}


def test_skips_withdrawn_newest_and_undrawable_lineages():
    holes = catalog(
        entry("a/one"),
        entry("a/one@2", withdrawn=True),
        entry("a/two"),
        entry("a/three"),
    )
    curation = CurationSnapshot.from_json({"a/two": {"drawable": False}})
    assert pool_keys(build_pool(holes, curation, Settings())) == {
        "a/three": ["a/three"]
    }


def derived(hole_id: str, base: CatalogEntry, par: int = 3) -> CatalogEntry:
    return CatalogEntry(
        HoleId.parse(hole_id),
        DerivedSource(base, "derived/hole.json"),
        "1" * 64,
        par,
        190,
        "Test",
    )


def test_a_derived_hole_is_drawn_only_when_its_kind_is_included():
    base = entry("nes_us/12", par=5)
    jp_base = entry("jp_uk/03", par=5, rom=JP_ROM)
    holes = catalog(
        base,
        jp_base,
        derived("jdharms/nes_us_12_short", base),
        derived("jdharms/jp_uk_03_short", jp_base),
        entry("dharms/cliffside", rom=None),
    )
    vanilla = {"jp_uk/03": ["jp_uk/03"], "nes_us/12": ["nes_us/12"]}
    assert pool_keys(build_pool(holes, CurationSnapshot(), Settings())) == vanilla
    with_derived = Settings(include=frozenset({DERIVED}))
    assert pool_keys(build_pool(holes, CurationSnapshot(), with_derived)) == vanilla | {
        "jdharms/jp_uk_03_short": ["jdharms/jp_uk_03_short"],
        "jdharms/nes_us_12_short": ["jdharms/nes_us_12_short"],
    }
    # a derived hole needs its base's ROM
    us_only = Settings(include=frozenset({DERIVED}), sources=frozenset({US_ROM}))
    assert pool_keys(build_pool(holes, CurationSnapshot(), us_only)) == {
        "jdharms/nes_us_12_short": ["jdharms/nes_us_12_short"],
        "nes_us/12": ["nes_us/12"],
    }
    # a community hole needs no ROM at all
    community = Settings(include=frozenset({COMMUNITY}), sources=frozenset({US_ROM}))
    assert pool_keys(build_pool(holes, CurationSnapshot(), community)) == {
        "dharms/cliffside": ["dharms/cliffside"],
        "nes_us/12": ["nes_us/12"],
    }


def test_a_derived_hole_shares_its_bases_family_and_takes_tags():
    base = entry("nes_us/12", par=5)
    holes = catalog(base, derived("jdharms/nes_us_12_short", base))
    curation = CurationSnapshot.from_json(
        {
            "nes_us/12": {"family": "nes_us_12"},
            "jdharms/nes_us_12_short": {"family": "nes_us_12", "tags": ["short"]},
        }
    )
    included = Settings(include=frozenset({DERIVED}))
    pool = build_pool(holes, curation, included)
    assert pool_keys(pool) == {"nes_us_12": ["jdharms/nes_us_12_short", "nes_us/12"]}
    assert pool.families[0].pars == {3, 5}
    no_short = Settings(include=frozenset({DERIVED}), exclude_tags=frozenset({"short"}))
    assert pool_keys(build_pool(holes, curation, no_short)) == {
        "nes_us_12": ["nes_us/12"]
    }


def test_filters_by_source_and_never_draws_community_holes():
    holes = catalog(
        entry("nes_us/01"),
        entry("jp_uk/01", rom=JP_ROM),
        entry("dharms/cliffside", rom=None),
    )
    assert pool_keys(build_pool(holes, CurationSnapshot(), Settings())) == {
        "jp_uk/01": ["jp_uk/01"],
        "nes_us/01": ["nes_us/01"],
    }
    us_only = build_pool(
        holes, CurationSnapshot(), Settings(sources=frozenset({US_ROM}))
    )
    assert pool_keys(us_only) == {"nes_us/01": ["nes_us/01"]}


def test_excludes_tagged_holes():
    holes = catalog(entry("a/one"), entry("a/two"))
    curation = CurationSnapshot.from_json({"a/one": {"tags": ["expert", "dogleg"]}})
    pool = build_pool(holes, curation, Settings(exclude_tags=frozenset({"expert"})))
    assert pool_keys(pool) == {"a/two": ["a/two"]}


def test_groups_families_unless_repeats_are_allowed():
    holes = catalog(
        entry("nes_uk/01"), entry("jp_japan/01", rom=JP_ROM), entry("nes_us/02")
    )
    curation = CurationSnapshot.from_json(
        {"nes_uk/01": {"family": "uk1"}, "jp_japan/01": {"family": "uk1"}}
    )
    assert pool_keys(build_pool(holes, curation, Settings())) == {
        "nes_us/02": ["nes_us/02"],
        "uk1": ["jp_japan/01", "nes_uk/01"],
    }
    repeats = build_pool(holes, curation, Settings(allow_family_repeats=True))
    assert set(pool_keys(repeats)) == {"nes_uk/01", "jp_japan/01", "nes_us/02"}


def test_family_pars_and_members_by_par():
    holes = catalog(entry("a/long", par=5), entry("a/short", par=3))
    curation = CurationSnapshot.from_json(
        {"a/long": {"family": "f"}, "a/short": {"family": "f"}}
    )
    (family,) = build_pool(holes, curation, Settings()).families
    assert family.pars == {3, 5}
    assert [str(member.id) for member in family.with_par(3)] == ["a/short"]
