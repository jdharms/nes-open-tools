"""The family candidates the real hole data yields, over the whole catalog.

Needs both vanilla ROMs rehydrated: the twins are cross-release, so the Mario Open dump is
half of every pair.
"""

from golf.randomizer.catalog import VANILLA, Catalog, HoleStore
from golf.randomizer.curation import CurationSnapshot
from golf.randomizer.twins import candidates, signatures, suggested_label


def test_every_catalog_hole_has_a_signature(vanilla_courses, vanilla_jp_courses):
    catalog = Catalog.load()
    holes = signatures(catalog, HoleStore(vanilla_courses))
    assert len(holes) == len(catalog.newest())


def test_the_shared_greens_pair_the_vanilla_holes_up(
    vanilla_courses, vanilla_jp_courses
):
    catalog = Catalog.load()
    # a derived hole shares its base's green; the twins counted here are vanilla pairs
    holes = [
        one
        for one in signatures(catalog, HoleStore(vanilla_courses))
        if catalog[one.lineage].kind == VANILLA
    ]
    found = candidates(holes, CurationSnapshot(), include_familied=True)

    greens = [one for one in found if one.greens_match]
    assert len(greens) == 39
    assert all(len(one.members) == 2 for one in greens)
    # every pair is one NES Open hole and one Mario Open hole
    for candidate in greens:
        assert len({one.lineage.startswith("nes_") for one in candidate.members}) == 2

    # terrain corroborates all but two of them, and finds three pairs the greens miss
    assert sum(one.terrain_score > 0.80 for one in greens) == 37
    assert min(one.terrain_score for one in greens) > 0.70
    assert len(found) - len(greens) == 3


def test_the_curated_family_is_among_the_candidates(
    vanilla_courses, vanilla_jp_courses
):
    holes = signatures(Catalog.load(), HoleStore(vanilla_courses))
    found = candidates(holes, CurationSnapshot(), include_familied=True)
    pair = next(one for one in found if "nes_uk/01" in one.lineages)
    assert pair.lineages == ("jp_japan/01", "nes_uk/01")
    assert pair.terrain_score == 1.0
    assert suggested_label(pair.lineages) == "nes_uk_01"


def test_holes_already_curated_drop_out(vanilla_courses, vanilla_jp_courses):
    holes = signatures(Catalog.load(), HoleStore(vanilla_courses))
    curation = CurationSnapshot.load()
    found = candidates(holes, curation)
    curated = set(curation.families().get("nes_uk_01", []))
    assert curated
    assert not any(curated & set(one.lineages) for one in found)
