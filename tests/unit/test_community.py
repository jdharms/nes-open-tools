"""Unit tests for publishing community holes and courses (ADR 0027)."""

import json

import pytest

from golf.formats.hole_data import HoleData
from golf.randomizer import community as community_module
from golf.randomizer.catalog import (
    COMMUNITY,
    Catalog,
    CatalogError,
    CommunityCourse,
    HoleId,
    HoleStore,
    content_hash,
)
from golf.randomizer.community import (
    PublishError,
    check_community,
    load_course_folder,
    publish_course,
    publish_hole,
)
from tests.synthetic_holes import synthetic_hole

AUTHOR = "pinesfan"
LINEAGE = f"{AUTHOR}/island_green"


@pytest.fixture(autouse=True)
def transforms_run(monkeypatch):
    """Made-up holes are not holes a transform can read, so the transforms are stood in for."""
    monkeypatch.setattr(community_module, "transform_problems", lambda hole: [])


def hole(number: int = 1, author: str | None = AUTHOR) -> HoleData:
    """A synthetic hole that passes the checks a build makes."""
    made = synthetic_hole(number)
    made.metadata["scroll_limit"] = 1
    made.metadata["tee"] = {"x": 88, "y": 220}
    made.metadata["handicap"] = (number - 1) % 18 + 1
    if author is not None:
        made.metadata["author"] = author
    return made


def course_holes(author: str | None = None) -> dict[int, HoleData]:
    return {number: hole(number, author) for number in range(1, 19)}


@pytest.fixture
def index(tmp_path):
    path = tmp_path / "catalog" / "holes.json"
    path.parent.mkdir()
    Catalog(version=1).save(path)
    return path


def publish(index, made: HoleData, lineage: str = LINEAGE) -> Catalog:
    publication = publish_hole(Catalog.load(index), made, lineage, root=index.parent)
    publication.write(index)
    return Catalog.load(index)


def publish_whole(index, holes, slug="georgia_pines", **listing) -> Catalog:
    publication = publish_course(
        Catalog.load(index), holes, slug, root=index.parent, **listing
    )
    publication.write(index)
    return Catalog.load(index)


class TestHoleAuthor:
    def test_round_trips(self, tmp_path):
        path = tmp_path / "hole.json"
        hole().save(str(path))
        loaded = HoleData()
        loaded.load(path)
        assert loaded.metadata["author"] == AUTHOR
        assert json.loads(path.read_text())["author"] == AUTHOR

    def test_a_hole_without_one_saves_without_one(self):
        assert "author" not in hole(author=None).to_dict()

    def test_changes_no_content_hash(self):
        assert content_hash(hole()) == content_hash(hole(author=None))


class TestPublishHole:
    def test_writes_a_frozen_copy_beside_the_index(self, index):
        catalog = publish(index, hole())
        entry = catalog[LINEAGE]
        assert entry.kind == COMMUNITY
        assert entry.author == AUTHOR
        assert entry.source.to_json() == {"file": f"community/{LINEAGE}.json"}
        assert (index.parent / "community" / AUTHOR / "island_green.json").exists()
        assert catalog.version == 2

    def test_the_copy_loads_from_any_hole_store(self, index, tmp_path):
        catalog = publish(index, hole())
        loaded = HoleStore(tmp_path / "elsewhere").load(catalog[LINEAGE])
        assert content_hash(loaded) == catalog[LINEAGE].content_hash

    def test_needs_an_author(self, index):
        with pytest.raises(PublishError, match="names no author"):
            publish(index, hole(author=None))

    def test_a_changed_hole_is_the_next_version(self, index):
        publish(index, hole())
        changed = hole()
        changed.terrain[5][5] = 0xA3
        catalog = publish(index, changed)
        assert catalog[f"{LINEAGE}@2"].content_hash == content_hash(changed)
        assert (index.parent / "community" / AUTHOR / "island_green@2.json").exists()
        assert HoleStore().load(catalog[LINEAGE])  # version 1 is still its own file

    def test_an_unchanged_hole_is_refused(self, index):
        publish(index, hole())
        with pytest.raises(PublishError, match="identical to"):
            publish(index, hole())

    def test_a_new_author_corrects_the_entry_in_place(self, index):
        publish(index, hole())
        catalog = publish(index, hole(author="someone_else"))
        assert catalog[LINEAGE].author == "someone_else"
        assert f"{LINEAGE}@2" not in catalog

    def test_a_hole_identical_to_another_lineage_is_refused(self, index):
        publish(index, hole())
        with pytest.raises(PublishError, match="identical to"):
            publish(index, hole(), f"{AUTHOR}/twin")

    @pytest.mark.parametrize("lineage", ["nes_us/island", "jp_hawaii/island"])
    def test_a_vanilla_owner_is_refused(self, index, lineage):
        with pytest.raises(PublishError, match="vanilla course"):
            publish(index, hole(), lineage)

    def test_a_course_owner_is_refused(self, index):
        publish_whole(index, course_holes(), name="Georgia Pines", author=AUTHOR)
        with pytest.raises(PublishError, match="community course"):
            publish(index, hole(19), "georgia_pines/island")

    def test_a_frozen_copy_is_never_overwritten(self, index):
        publication = publish_hole(
            Catalog.load(index), hole(), LINEAGE, root=index.parent
        )
        path = publication.path_for(HoleId(LINEAGE))
        path.parent.mkdir(parents=True)
        path.write_text("{}")
        with pytest.raises(PublishError, match="never overwritten"):
            publication.write(index)


class TestPublishCourse:
    def test_lists_the_course_and_its_18_holes(self, index):
        catalog = publish_whole(
            index, course_holes(), name="Georgia Pines", author=AUTHOR
        )
        assert catalog.courses == {
            "georgia_pines": CommunityCourse("Georgia Pines", AUTHOR)
        }
        assert sorted(str(entry.id) for entry in catalog) == [
            f"georgia_pines/{number:02d}" for number in range(1, 19)
        ]
        assert {entry.author for entry in catalog} == {AUTHOR}
        assert catalog.version == 2

    def test_a_hole_may_name_its_own_author(self, index):
        holes = course_holes()
        holes[7].metadata["author"] = "a_friend"
        catalog = publish_whole(index, holes, name="Georgia Pines", author=AUTHOR)
        assert catalog["georgia_pines/07"].author == "a_friend"
        assert catalog["georgia_pines/08"].author == AUTHOR

    def test_a_new_course_needs_its_name_and_author(self, index):
        with pytest.raises(PublishError, match="name and author"):
            publish_whole(index, course_holes(), name="Georgia Pines")

    def test_a_course_is_holes_1_to_18(self, index):
        holes = course_holes()
        del holes[18]
        with pytest.raises(PublishError, match="holes 1-18"):
            publish_whole(index, holes, name="Georgia Pines", author=AUTHOR)

    def test_only_changed_holes_get_a_new_version(self, index):
        publish_whole(index, course_holes(), name="Georgia Pines", author=AUTHOR)
        holes = course_holes()
        holes[7].terrain[5][5] = 0xA3
        publication = publish_course(
            Catalog.load(index), holes, "georgia_pines", root=index.parent
        )
        assert list(publication.files) == [HoleId("georgia_pines/07", 2)]
        assert len(publication.unchanged) == 17

    def test_an_unchanged_course_is_refused(self, index):
        publish_whole(index, course_holes(), name="Georgia Pines", author=AUTHOR)
        with pytest.raises(PublishError, match="matches its newest version"):
            publish_whole(index, course_holes())

    def test_the_listing_can_be_corrected(self, index):
        publish_whole(index, course_holes(), name="Georgia Pine", author=AUTHOR)
        catalog = publish_whole(index, course_holes(), name="Georgia Pines")
        assert catalog.courses["georgia_pines"].name == "Georgia Pines"

    def test_an_author_owner_cannot_become_a_course(self, index):
        publish(index, hole(19))
        with pytest.raises(PublishError, match="already an author"):
            publish_whole(index, course_holes(), AUTHOR, name="Pines", author=AUTHOR)

    @pytest.mark.parametrize("slug", ["nes_uk", COMMUNITY])
    def test_reserved_owners_are_not_courses(self, index, slug):
        with pytest.raises(PublishError):
            publish_whole(index, course_holes(), slug, name="Pines", author=AUTHOR)

    def test_loads_a_folder_by_its_hole_files(self, tmp_path):
        for number, made in course_holes().items():
            made.save(str(tmp_path / f"hole_{number:02d}.json"))
        (tmp_path / "georgia_pines.json").write_text("{}")  # a recipe beside them
        assert sorted(load_course_folder(tmp_path)) == list(range(1, 19))


class TestIndex:
    def test_courses_round_trip(self, index):
        catalog = publish_whole(
            index, course_holes(), name="Georgia Pines", author=AUTHOR
        )
        assert Catalog.from_json(catalog.to_json(), index.parent) == catalog

    def test_an_index_without_courses_writes_none(self):
        assert "courses" not in Catalog(version=1).to_json()

    def test_a_loose_hole_under_a_course_is_refused(self, index):
        data = publish_whole(
            index, course_holes(), name="Georgia Pines", author=AUTHOR
        ).to_json()
        data["holes"]["georgia_pines/island"] = data["holes"]["georgia_pines/01"]
        with pytest.raises(CatalogError, match="holds only its own holes"):
            Catalog.from_json(data, index.parent)

    @pytest.mark.parametrize("slug", ["nes_us", "community", "Bad Slug"])
    def test_a_reserved_or_malformed_course_is_refused(self, slug):
        data = {
            "version": 1,
            "courses": {slug: {"name": "X", "author": "y"}},
            "holes": {},
        }
        with pytest.raises(CatalogError):
            Catalog.from_json(data)

    @pytest.mark.parametrize("file", ["../holes.json", "/tmp/hole.json", ""])
    def test_a_file_outside_the_index_directory_is_refused(self, file):
        data = {
            "version": 1,
            "holes": {
                LINEAGE: {
                    "source": {"file": file},
                    "content_hash": "0" * 64,
                    "par": 3,
                    "distance": 150,
                    "author": AUTHOR,
                }
            },
        }
        with pytest.raises(CatalogError, match="under the catalog directory"):
            Catalog.from_json(data)


class TestCheck:
    def test_passes_published_holes(self, index):
        catalog = publish_whole(
            index, course_holes(), name="Georgia Pines", author=AUTHOR
        )
        assert check_community(catalog) == []

    def test_names_an_edited_frozen_copy(self, index):
        catalog = publish(index, hole())
        path = index.parent / "community" / AUTHOR / "island_green.json"
        edited = HoleData()
        edited.load(path)
        edited.terrain[5][5] = 0xA3
        edited.save(str(path))
        [problem] = check_community(catalog)
        assert "content hash" in problem
