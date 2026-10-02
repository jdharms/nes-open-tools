"""The checked-in hazard stamps are what `golf-hazard-stamps` makes of the vanilla holes."""

from pathlib import Path

from editor.data.hazard_stamps import CATEGORY, hazard_stamps, stamp_path
from golf.randomizer.catalog import Catalog, HoleStore, RomSource

BUILT_IN = Path(__file__).resolve().parents[2] / "data" / "stamps" / "built-in"


def test_built_in_hazard_stamps_are_current(vanilla_courses, vanilla_jp_courses):
    store = HoleStore(vanilla_courses)
    holes = [
        store.load(entry)
        for entry in Catalog.load().newest().values()
        if isinstance(entry.source, RomSource)
    ]
    generated = {
        stamp_path(BUILT_IN, stamp): stamp.to_json() for stamp in hazard_stamps(holes)
    }
    checked_in = {
        path: path.read_text() for path in (BUILT_IN / CATEGORY).rglob("*.json")
    }
    assert generated == checked_in, "run `uv run golf-hazard-stamps`"
