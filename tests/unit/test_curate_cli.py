"""Unit tests for golf-curate.

Every run passes --curation into tmp_path, so the checked-in curation file is never the
one under test.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from golf.randomizer.catalog import Catalog
from tests.catalog_counts import lineages

ROOT = Path(__file__).resolve().parents[2]


def run(*args) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "tools.data.curate", *map(str, args)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )


@pytest.fixture
def curation(tmp_path) -> Path:
    path = tmp_path / "curation.json"
    path.write_text('{"nes_uk/01": {"family": "nes_uk_01"}}\n')
    return path


def records(path: Path) -> dict:
    return json.loads(path.read_text())


def test_list_covers_every_catalog_lineage(curation):
    completed = run("--curation", curation, "list")
    assert completed.returncode == 0, completed.stderr
    assert "nes_uk/01        par 4  418y  nes_uk_01" in completed.stdout
    count = lineages(Catalog.load())
    assert completed.stdout.rstrip().endswith(f"{count} holes")


def test_list_filters_to_the_unfamilied(curation):
    completed = run(
        "--curation", curation, "list", "--course", "nes_uk", "--unfamilied"
    )
    assert completed.returncode == 0, completed.stderr
    assert "nes_uk/01" not in completed.stdout
    assert "nes_uk/02" in completed.stdout
    assert completed.stdout.rstrip().endswith("17 holes")


def test_show_reports_the_family_and_the_rangefinder_link(curation):
    completed = run("--curation", curation, "show", "nes_uk/01")
    assert completed.returncode == 0, completed.stderr
    assert "family       nes_uk_01" in completed.stdout
    assert "/rangefinder?course=uk&hole=1" in completed.stdout


def test_show_refuses_a_hole_the_catalog_lacks(curation):
    completed = run("--curation", curation, "show", "nes_uk/99")
    assert completed.returncode == 1
    assert completed.stderr.startswith("error:")
    assert "not in the catalog" in completed.stderr


def test_family_set_writes_the_file(curation):
    completed = run("--curation", curation, "family", "set", "nes_uk_01", "jp_japan/01")
    assert completed.returncode == 0, completed.stderr
    assert f"wrote {curation}" in completed.stdout
    assert records(curation) == {
        "jp_japan/01": {"family": "nes_uk_01"},
        "nes_uk/01": {"family": "nes_uk_01"},
    }


def test_family_set_refuses_a_lineage_the_catalog_lacks(curation):
    before = curation.read_text()
    completed = run("--curation", curation, "family", "set", "f", "nes_uk/99")
    assert completed.returncode == 1
    assert "not a drawable lineage" in completed.stderr
    assert curation.read_text() == before


def test_family_set_refuses_to_move_a_hole_without_move(curation):
    before = curation.read_text()
    completed = run("--curation", curation, "family", "set", "other", "nes_uk/01")
    assert completed.returncode == 1
    assert "--move" in completed.stderr
    assert curation.read_text() == before

    completed = run(
        "--curation", curation, "family", "set", "other", "nes_uk/01", "--move"
    )
    assert completed.returncode == 0, completed.stderr
    assert records(curation) == {"nes_uk/01": {"family": "other"}}


def test_dry_run_writes_nothing(curation):
    before = curation.read_text()
    completed = run(
        "--curation", curation, "family", "set", "f", "nes_us/01", "--dry-run"
    )
    assert completed.returncode == 0, completed.stderr
    assert f"would write {curation}" in completed.stdout
    assert curation.read_text() == before


def test_family_clear_drops_an_emptied_record(curation):
    completed = run("--curation", curation, "family", "clear", "nes_uk/01")
    assert completed.returncode == 0, completed.stderr
    assert records(curation) == {}


def test_family_rename_merges_into_an_existing_family(curation):
    assert (
        run("--curation", curation, "family", "set", "b", "nes_us/01").returncode == 0
    )
    completed = run("--curation", curation, "family", "rename", "b", "nes_uk_01")
    assert completed.returncode == 0, completed.stderr
    assert "merged into" in completed.stdout
    assert set(records(curation)) == {"nes_uk/01", "nes_us/01"}


def test_check_passes_on_a_sound_file(curation):
    assert run("--curation", curation, "family", "set", "nes_uk_01", "jp_japan/01")
    completed = run("--curation", curation, "check")
    assert completed.returncode == 0, completed.stderr
    assert "no problems" in completed.stdout


def test_check_reports_a_family_of_one_and_an_unknown_lineage(tmp_path):
    path = tmp_path / "curation.json"
    path.write_text('{"nes_uk/01": {"family": "lonely"}, "made/up": {"tags": ["x"]}}\n')
    completed = run("--curation", path, "check")
    assert completed.returncode == 1
    assert "made/up: curated but not in the catalog" in completed.stderr
    assert "lonely: family of one (nes_uk/01)" in completed.stderr


def test_check_on_the_checked_in_curation_file():
    completed = run("check")
    assert completed.returncode == 0, completed.stderr


def test_argparse_refuses_an_unknown_subcommand(curation):
    completed = run("--curation", curation, "family", "bogus")
    assert completed.returncode == 2
    assert "invalid choice" in completed.stderr
