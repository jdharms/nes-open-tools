"""The seed builder: where it finds the vanilla ROM, refusing to build without it, and
prewarming the transform caches without getting in a build's way."""

import threading
from dataclasses import replace
from pathlib import Path

import pytest

from golf.randomizer import transform_cache
from golf.randomizer.catalog import Catalog, HoleStore
from golf.randomizer.curation import CurationSnapshot
from golf.randomizer.manifest import Settings
from server.builder import BuilderUnavailableError, SeedBuilder
from server.config import Config
from tests.synthetic_holes import mirrorable_hole


@pytest.fixture(scope="module")
def catalog() -> Catalog:
    return Catalog.load()


@pytest.fixture(scope="module")
def curation() -> CurationSnapshot:
    return CurationSnapshot.load()


def builder(catalog, curation, rom_path: Path) -> SeedBuilder:
    return SeedBuilder(catalog, curation, HoleStore(), rom_path)


def test_from_config_reads_the_rom_and_holes_directories(tmp_path):
    made = SeedBuilder.from_config(
        Config(rom_dir=tmp_path / "roms", holes_dir=tmp_path / "holes")
    )
    assert made.rom_path == tmp_path / "roms" / "nes_open_us.nes"
    assert made.store.root == tmp_path / "holes"
    assert len(made.catalog) > 0


def test_generate_uses_the_catalog_and_curation(catalog, curation, tmp_path):
    manifest = builder(catalog, curation, tmp_path / "missing.nes").generate(
        Settings(prng_seed="builder")
    )
    assert manifest.catalog_version == catalog.version
    assert manifest.curation_stamp == curation.stamp


def test_a_missing_rom_makes_the_builder_unavailable(catalog, curation, tmp_path):
    seeds = builder(catalog, curation, tmp_path / "missing.nes")
    manifest = seeds.generate(Settings(prng_seed="builder"))
    with pytest.raises(BuilderUnavailableError, match="cannot read"):
        seeds.build(manifest)


def test_a_rom_that_is_not_vanilla_makes_the_builder_unavailable(
    catalog, curation, tmp_path
):
    rom = tmp_path / "nes_open_us.nes"
    rom.write_bytes(b"NES\x1a" + bytes(100))
    seeds = builder(catalog, curation, rom)
    with pytest.raises(BuilderUnavailableError, match="not the vanilla US ROM"):
        seeds.vanilla()


def test_warm_refuses_a_missing_rom(catalog, curation, tmp_path):
    with pytest.raises(BuilderUnavailableError, match="cannot read"):
        builder(catalog, curation, tmp_path / "missing.nes").warm()


# -- Prewarming the transform caches -------------------------------------------------------


class MirrorableStore(HoleStore):
    """Loads every entry as the same made-up hole, so prewarming needs no dumped course."""

    def load(self, entry, *, even_withdrawn=False):
        return mirrorable_hole()


def prewarmer(catalog, curation, tmp_path) -> SeedBuilder:
    return SeedBuilder(catalog, curation, MirrorableStore(), tmp_path / "missing.nes")


def in_thread(target, *args) -> threading.Thread:
    thread = threading.Thread(target=target, args=args, daemon=True)
    thread.start()
    return thread


def test_prewarm_fills_the_caches_for_each_entry(catalog, curation, tmp_path):
    seeds = prewarmer(catalog, curation, tmp_path)
    entries = [entry for entry in catalog if entry.live][:2]
    assert seeds.prewarm(threading.Event(), entries, pause=0) == 2
    # both entries load the same hole, so it holds one hole, one mirror, both their groups
    assert transform_cache.sizes() == (1, 2)


def test_prewarm_skips_withdrawn_holes_by_default(catalog, curation, tmp_path):
    seeds = prewarmer(catalog, curation, tmp_path)
    first, second = list(catalog)[:2]
    seeds.catalog = [first, replace(second, withdrawn=True)]  # type: ignore[assignment]
    assert seeds.prewarm(threading.Event(), pause=0) == 1


def test_prewarm_stops_when_told(catalog, curation, tmp_path):
    stop = threading.Event()
    stop.set()
    seeds = prewarmer(catalog, curation, tmp_path)
    assert seeds.prewarm(stop, list(catalog), pause=0) == 0
    assert transform_cache.sizes() == (0, 0)


def test_prewarm_never_runs_beside_a_build(catalog, curation, tmp_path):
    seeds = prewarmer(catalog, curation, tmp_path)
    entries = [entry for entry in catalog if entry.live][:1]
    seeds._builds.acquire()  # a build in progress
    thread = in_thread(seeds.prewarm, threading.Event(), entries, 0)
    thread.join(0.3)
    assert thread.is_alive()
    assert transform_cache.sizes() == (0, 0)
    seeds._builds.release()
    thread.join(5)
    assert not thread.is_alive()
    assert transform_cache.sizes() == (1, 2)


def test_prewarm_gives_way_while_a_build_waits(catalog, curation, tmp_path):
    seeds = prewarmer(catalog, curation, tmp_path)
    entries = [entry for entry in catalog if entry.live][:1]
    seeds._waiting = 1  # a build queued for the semaphore, which is free
    thread = in_thread(seeds.prewarm, threading.Event(), entries, 0.01)
    thread.join(0.3)
    assert thread.is_alive()
    assert transform_cache.sizes() == (0, 0)
    seeds._waiting = 0
    thread.join(5)
    assert not thread.is_alive()
    assert transform_cache.sizes() == (1, 2)


def test_a_build_counts_itself_waiting_until_it_has_the_semaphore(
    catalog, curation, tmp_path, monkeypatch
):
    seeds = builder(catalog, curation, tmp_path / "missing.nes")
    monkeypatch.setattr(seeds, "vanilla", lambda: b"not a rom")
    manifest = seeds.generate(Settings(prng_seed="builder"))
    seeds._builds.acquire()
    failures = []

    def build():
        try:
            seeds.build(manifest)
        except Exception as problem:  # the made-up ROM fails the build's check
            failures.append(problem)

    thread = in_thread(build)
    for _ in range(100):
        if seeds._waiting:
            break
        thread.join(0.01)
    assert seeds._waiting == 1
    seeds._builds.release()
    thread.join(5)
    assert seeds._waiting == 0
    assert failures, "the build should have run once it had the semaphore"
