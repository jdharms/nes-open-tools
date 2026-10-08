"""The helpers in server/views.py that templates call directly."""

from markupsafe import Markup, escape

from golf.randomizer.catalog import (
    US_ROM,
    Catalog,
    CatalogEntry,
    DerivedSource,
    HoleId,
    RomSource,
)
from golf.randomizer.curation import CurationSnapshot
from golf.randomizer.manifest import Slot
from golf.randomizer.roms import vanilla_rom
from server.views import _hole_view, timestamp


def test_timestamp_is_a_time_element_holding_the_utc_minute():
    assert timestamp("2026-09-23T15:51:09Z") == Markup(
        '<time datetime="2026-09-23T15:51:09Z">2026-09-23 15:51 UTC</time>'
    )


def test_timestamp_survives_being_passed_into_a_string_as_a_value():
    stamp = timestamp("2026-09-23T15:51:09Z")
    assert Markup("created {}").format(stamp) == Markup("created ") + stamp
    assert escape(stamp) == stamp


def test_a_hole_view_names_a_source_rom_for_a_vanilla_hole_only():
    base = CatalogEntry(
        HoleId("nes_us/12"), RomSource(US_ROM, "us", 12), "0" * 64, 5, 642, "Nintendo"
    )
    short = CatalogEntry(
        HoleId("jdharms/nes_us_12_short"),
        DerivedSource(base, "derived/jdharms/nes_us_12_short.json"),
        "1" * 64,
        3,
        190,
        "jdharms",
    )
    catalog = Catalog(1, {base.id: base, short.id: short})

    vanilla = _hole_view(1, Slot(base.id, 5, 0), catalog, CurationSnapshot())
    assert (vanilla.rom_title, vanilla.source_hole) == (vanilla_rom(US_ROM).title, 12)
    assert vanilla.course

    derived = _hole_view(2, Slot(short.id, 3, 0), catalog, CurationSnapshot())
    assert (derived.rom_title, derived.course, derived.source_hole) == (None,) * 3
    assert (derived.author, derived.par, derived.distance) == ("jdharms", 3, 190)
