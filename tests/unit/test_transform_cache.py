"""The transform cache (golf/randomizer/transform_cache.py).

Every transform in the registry gives, through the cache, what its uncached operation
makes, and every memo what it computes, so a new transform or memo is checked here without
a new test; a caller cannot change what the cache keeps; and the key tells apart holes
that `content_hash` does not. The golden digests in `tests/unit/test_transforms.py` pin
what the operations compute; these pin that the cache gives it back unchanged.
"""

import copy

import pytest

from golf.algorithms.features import feature_groups
from golf.algorithms.hazards import hazard_groups
from golf.algorithms.mirror import MirrorError, mirror_hole
from golf.formats.hole_data import HoleData
from golf.randomizer import transform_cache
from golf.randomizer.catalog import DEFAULT_COURSES, Catalog, HoleStore, content_hash
from golf.randomizer.transforms import TRANSFORMS, apply_transforms
from tests.synthetic_holes import mirrorable_hole, synthetic_hole

#: every hole a seed can draw, vanilla and derived
LIVE = {str(entry.id): entry for entry in Catalog.load() if entry.live}

#: every transform in the registry as a manifest names it, a seeded one under two seeds
TEXTS = [
    text
    for name, transform in TRANSFORMS.items()
    for text in ([f"{name}:{seed}" for seed in (0, 7)] if transform.seeded else [name])
]


def uncached(text: str, hole: HoleData) -> HoleData:
    """`text` applied to `hole` by its registry entry's uncached operation."""
    name, _, seed = text.partition(":")
    return TRANSFORMS[name].uncached(hole, int(seed) if seed else None)


def comparable(value):
    return value.to_dict() if isinstance(value, HoleData) else value


@pytest.fixture
def catalog_hole(request, vanilla_courses, vanilla_jp_courses):
    """(id, hole) for the catalog hole named by the parameter. A derived hole builds from
    its vanilla base, so both ROMs' dumps are asked for."""
    return request.param, HoleStore(DEFAULT_COURSES).load(LIVE[request.param])


@pytest.mark.parametrize("catalog_hole", sorted(LIVE), indirect=True)
def test_every_transform_gives_what_its_uncached_operation_makes(catalog_hole):
    """Alone and after `mirror@1`, as generation draws them, once filling the cache and
    once reading it back. Earlier texts fill what later ones read, so a later text's
    first pass may already be a hit."""
    hole_id, hole = catalog_hole
    flipped = uncached("mirror@1", hole)
    for text in TEXTS:
        alone = uncached(text, hole).to_dict()
        after_mirror = uncached(text, flipped).to_dict()
        for _ in ("first", "again"):
            assert apply_transforms(hole, [text]).to_dict() == alone, (hole_id, text)
            assert (
                apply_transforms(hole, ["mirror@1", text]).to_dict() == after_mirror
            ), (hole_id, text)


@pytest.mark.parametrize("catalog_hole", sorted(LIVE), indirect=True)
def test_every_memo_gives_what_it_computes(catalog_hole):
    hole_id, hole = catalog_hole
    for kept in transform_cache.MEMOS:
        try:
            expected = comparable(kept.compute(hole))
        except ValueError:  # a hole the operation refuses, as `mirror_hole` may
            continue
        for _ in ("miss", "hit"):
            assert comparable(kept(hole)) == expected, (hole_id, kept.name)


def test_no_uncached_operation_fills_a_cache():
    for text in TEXTS:
        uncached(text, mirrorable_hole())
        assert not any(transform_cache.sizes().values()), text


def test_a_memo_shares_only_what_cannot_be_changed_in_place():
    for kept in transform_cache.MEMOS:
        value = kept(mirrorable_hole())
        if not kept.copy_out:
            assert not isinstance(value, HoleData), kept.name
            hash(value)  # hashable all the way down: tuples, frozensets, frozen classes


def test_two_memos_cannot_share_a_name():
    before = list(transform_cache.MEMOS)
    with pytest.raises(ValueError, match="mirrors"):
        transform_cache.memo("mirrors", mirror_hole)
    assert before == transform_cache.MEMOS


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
    assert not any(transform_cache.sizes().values())


def test_warm_keeps_a_hole_its_mirror_and_the_groups_of_both():
    hole = mirrorable_hole()
    transform_cache.warm(hole)
    assert transform_cache.sizes()["mirrors"] == 1
    assert transform_cache.sizes()["hazard_groups"] == 2
    flipped = transform_cache.mirrored(hole)
    assert transform_cache.sizes()["mirrors"] == 1
    assert transform_cache.sizes()["hazard_groups"] == 2
    transform_cache.groups(flipped)
    assert transform_cache.sizes()["mirrors"] == 1
    assert transform_cache.sizes()["hazard_groups"] == 2


def test_warm_keeps_only_the_groups_of_a_hole_that_will_not_mirror():
    transform_cache.warm(synthetic_hole())
    assert transform_cache.sizes()["mirrors"] == 0
    assert transform_cache.sizes()["hazard_groups"] == 1


def test_clear_empties_both():
    transform_cache.warm(mirrorable_hole())
    transform_cache.clear()
    assert not any(transform_cache.sizes().values())
