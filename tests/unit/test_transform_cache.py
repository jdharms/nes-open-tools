"""The transform cache (golf/randomizer/transform_cache.py).

A hit is the hole a miss computes, and both are what the uncached operations compute; a
caller cannot change what the cache keeps; and the key tells apart holes that
`content_hash` does not. The golden digests in `tests/unit/test_transforms.py` pin what a
miss computes; these pin that the cache gives it back unchanged.
"""

import copy

import pytest

from golf.algorithms import hazards
from golf.algorithms.features import feature_groups
from golf.algorithms.hazards import hazard_groups, redraw_hazards
from golf.algorithms.mirror import MirrorError, mirror_hole
from golf.randomizer import transform_cache
from golf.randomizer.catalog import DEFAULT_COURSES, Catalog, HoleStore, content_hash
from golf.randomizer.transforms import apply_transforms
from tests.synthetic_holes import mirrorable_hole, synthetic_hole

#: every hole a seed can draw, vanilla and derived
LIVE = {str(entry.id): entry for entry in Catalog.load() if entry.live}

STYLES = {"hazards@1": hazards.uniform, "hazards-weighted@1": hazards.weighted}


@pytest.fixture
def catalog_hole(request, vanilla_courses, vanilla_jp_courses):
    """(id, hole) for the catalog hole named by the parameter. A derived hole builds from
    its vanilla base, so both ROMs' dumps are asked for."""
    return request.param, HoleStore(DEFAULT_COURSES).load(LIVE[request.param])


@pytest.mark.parametrize("catalog_hole", sorted(LIVE), indirect=True)
def test_every_catalog_hole_comes_back_as_the_uncached_operations_make_it(
    catalog_hole,
):
    hole_id, hole = catalog_hole
    flipped = mirror_hole(hole)
    for _ in ("miss", "hit"):
        assert transform_cache.mirrored(hole).to_dict() == flipped.to_dict(), hole_id
        for target in (hole, flipped):
            assert transform_cache.groups(target) == hazard_groups(target), hole_id
    # through the registry, as a build applies them, with the cache now holding all three
    for name, draw in STYLES.items():
        for seed in (0, 7):
            alone = redraw_hazards(hole, seed, draw).to_dict()
            after_mirror = redraw_hazards(flipped, seed, draw).to_dict()
            for _ in range(2):
                assert apply_transforms(hole, [f"{name}:{seed}"]).to_dict() == alone
                assert (
                    apply_transforms(hole, ["mirror@1", f"{name}:{seed}"]).to_dict()
                    == after_mirror
                ), hole_id


@pytest.mark.parametrize("catalog_hole", sorted(LIVE), indirect=True)
def test_hazard_groups_keep_what_a_redraw_reads_of_feature_groups(catalog_hole):
    hole_id, hole = catalog_hole
    for target in (hole, mirror_hole(hole)):
        full = feature_groups(target)
        cut = hazard_groups(target)
        assert len(cut) == len(full), hole_id
        for group, kept in zip(full, cut, strict=True):
            assert kept.kinds == group.kinds, hole_id
            assert kept.size == sum(len(f.pixels) for f in group.features), hole_id
            assert kept.supertiles == group.supertiles, hole_id


def test_changing_a_mirrored_hole_leaves_what_the_cache_keeps_alone():
    hole = mirrorable_hole()
    expected = mirror_hole(hole).to_dict()
    first = transform_cache.mirrored(hole)
    first.terrain[0][0] = 0x00
    first.attributes[0][0] = 3
    first.greens[0][0] = 0x00
    first.metadata["tee"]["x"] = 0
    first.metadata["flag_positions"][0]["x_offset"] = 0
    assert transform_cache.mirrored(hole).to_dict() == expected


def test_each_call_gets_its_own_copy():
    hole = mirrorable_hole()
    first, second = transform_cache.mirrored(hole), transform_cache.mirrored(hole)
    assert first is not second
    assert first.terrain is not second.terrain
    assert first.metadata is not second.metadata


def test_mirroring_through_the_cache_leaves_the_original_alone():
    hole = mirrorable_hole()
    before = hole.to_dict()
    transform_cache.mirrored(hole)
    transform_cache.mirrored(hole)
    assert hole.to_dict() == before


def test_terrain_past_the_visible_height_is_its_own_key():
    hole = mirrorable_hole()
    taller = copy.deepcopy(hole)
    taller.terrain.append(list(taller.terrain[0]))
    # what reaches the ROM is the same, but the fill sees the extra row
    assert content_hash(taller) == content_hash(hole)
    assert transform_cache.hole_key(taller) != transform_cache.hole_key(hole)
    assert transform_cache.mirrored(taller).terrain == mirror_hole(taller).terrain
    assert transform_cache.mirrored(hole).terrain == mirror_hole(hole).terrain


def test_metadata_off_the_rom_is_its_own_key():
    hole = mirrorable_hole()
    signed = copy.deepcopy(hole)
    signed.metadata["author"] = "someone"
    assert content_hash(signed) == content_hash(hole)
    assert transform_cache.hole_key(signed) != transform_cache.hole_key(hole)
    assert transform_cache.mirrored(hole).metadata == mirror_hole(hole).metadata
    assert transform_cache.mirrored(signed).metadata["author"] == "someone"


def test_a_changed_hole_is_a_new_key():
    hole = mirrorable_hole()
    transform_cache.mirrored(hole)
    hole.metadata["tee"]["x"] += 1
    assert transform_cache.mirrored(hole).to_dict() == mirror_hole(hole).to_dict()


def test_the_key_ignores_editor_state():
    hole = mirrorable_hole()
    edited = copy.deepcopy(hole)
    edited.filepath, edited.modified = "elsewhere.json", True
    assert transform_cache.hole_key(edited) == transform_cache.hole_key(hole)


def test_a_hole_that_will_not_mirror_keeps_nothing_and_raises_each_time():
    for _ in ("first", "again"):
        with pytest.raises(MirrorError):
            transform_cache.mirrored(synthetic_hole())
    assert transform_cache.sizes() == (0, 0)


def test_warm_keeps_a_hole_its_mirror_and_the_groups_of_both():
    hole = mirrorable_hole()
    transform_cache.warm(hole)
    assert transform_cache.sizes() == (1, 2)
    flipped = transform_cache.mirrored(hole)
    assert transform_cache.sizes() == (1, 2)
    transform_cache.groups(flipped)
    assert transform_cache.sizes() == (1, 2)


def test_warm_keeps_only_the_groups_of_a_hole_that_will_not_mirror():
    transform_cache.warm(synthetic_hole())
    assert transform_cache.sizes() == (0, 1)


def test_clear_empties_both():
    transform_cache.warm(mirrorable_hole())
    transform_cache.clear()
    assert transform_cache.sizes() == (0, 0)
