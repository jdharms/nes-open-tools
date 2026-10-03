"""The editor's generated hazard stamps, and the order the library lists stamps in."""

from pathlib import Path

from editor.controllers.stamp_library import StampLibrary
from editor.data.hazard_stamps import hazard_stamp, stamp_path
from editor.data.stamp_data import StampData
from golf.algorithms.hazard_shapes import HazardShape

POT = HazardShape(((0x40, 0x41), (0x58, 0x59)), 37)
NOTCHED = HazardShape(((0x50, None), (0x58, 0x51)), 68)
LAKE = HazardShape(tuple((0x27,) * 9 for _ in range(4)), 1)


def test_stamp_carries_the_shape():
    stamp = hazard_stamp(NOTCHED)
    assert stamp.tiles == [[0x50, None], [0x58, 0x51]]
    assert (stamp.width, stamp.height, stamp.mode) == (2, 2, "terrain")
    assert stamp.attributes is None


def test_stamp_is_filed_by_size():
    assert hazard_stamp(POT).metadata.category == "hazard/tiny"
    assert hazard_stamp(LAKE).metadata.category == "hazard/large"


def test_stamp_id_depends_only_on_the_tiles():
    again = HazardShape(POT.tiles, POT.count + 5)
    assert hazard_stamp(POT).metadata.id == hazard_stamp(again).metadata.id
    assert hazard_stamp(POT).metadata.id != hazard_stamp(NOTCHED).metadata.id


def test_stamp_text_is_the_same_every_time():
    assert hazard_stamp(POT).to_json() == hazard_stamp(POT).to_json()


def test_saved_stamp_loads_back(tmp_path):
    stamp = hazard_stamp(NOTCHED)
    path = stamp_path(tmp_path, stamp)
    stamp.save(path)
    assert path == tmp_path / "hazard" / "tiny" / f"{stamp.metadata.id}.json"
    loaded = StampData.load(path)
    assert loaded.tiles == stamp.tiles
    assert loaded.metadata.category == stamp.metadata.category
    assert loaded.to_json() == stamp.to_json()


def test_library_lists_a_category_smallest_first(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    library = StampLibrary()
    library.built_in_path = tmp_path / "built-in"
    for shape in (LAKE, POT, NOTCHED):
        stamp = hazard_stamp(shape)
        stamp.metadata.category = "hazard"
        stamp.save(stamp_path(library.built_in_path, stamp))
    library.load_stamps()
    listed = [stamp.tiles for stamp in library.get_stamps_by_path("hazard")]
    assert listed == [
        [list(row) for row in shape.tiles] for shape in (NOTCHED, POT, LAKE)
    ]
