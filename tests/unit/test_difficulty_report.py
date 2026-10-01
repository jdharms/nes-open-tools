"""`golf.difficulty.report`: gathering solves into rows, an archive and tables."""

import json
import tarfile

import pytest

from golf.difficulty.report import (
    expert,
    load,
    markdown,
    new_at_nes_level,
    slim,
    summary,
    write_archive,
)

STATE = {
    "class": 0,
    "x": 10,
    "y": 20,
    "expected": 2.5,
    "visits": 0.4,
    "intent": "7I, medium, aim 0, power 0",
    "played": [{"intent": "7I, medium, aim 0, power 0", "rank": 0}],
}


@pytest.fixture
def solves(tmp_path):
    """NES US 1-2 and Mario Japan 1-3: (par, expected from the tee) each."""
    holes = {
        ("nes_us", "us"): [(4, 4.2), (3, 3.5)],
        ("jp_japan", "jp/jp_japan"): [(4, 4.1), (5, 5.8), (3, 3.2)],
    }
    root, courses = tmp_path / "solves", tmp_path / "courses"
    for (course, folder), values in holes.items():
        (root / course).mkdir(parents=True)
        (courses / folder).mkdir(parents=True)
        for hole, (par, tee) in enumerate(values, 1):
            solve = {"tee": tee, "par": par, "pin": [1, 2], "states": [STATE]}
            if course == "jp_japan":
                solve |= {"unvalued": 0.05, "rounds": 6, "skill": 3.0, "pin_index": 0}
            (root / course / f"hole_{hole:02}.json").write_text(json.dumps(solve))
            meta = {"par": str(par), "distance": str(100 * par), "handicap": str(hole)}
            (courses / folder / f"hole_{hole:02}.json").write_text(json.dumps(meta))
    (root / "jp_japan.log").write_text("round 1: ...\n")
    return root, courses


def test_load_reads_every_solve_with_its_hole(solves):
    results = load(*solves)
    assert [r.lineage for r in results] == [
        "nes_us/01",
        "nes_us/02",
        "jp_japan/01",
        "jp_japan/02",
        "jp_japan/03",
    ]
    mario = results[3]
    assert (mario.par, mario.yards, mario.handicap) == (5, 500, 2)
    assert mario.over_par == pytest.approx(0.8)
    assert (mario.unvalued, mario.rounds, mario.skill, mario.pin) == (0.05, 6, 3.0, 0)
    # Solves written before those were kept leave them unknown.
    assert results[0].unvalued is None and results[0].rounds is None


def test_summary_rows_carry_over_par(solves):
    rows = summary(load(*solves))["holes"]
    assert rows[1]["lineage"] == "nes_us/02"
    assert rows[1]["over_par"] == pytest.approx(0.5)


def test_expert_holes_play_worse_than_every_nes_open_hole(solves):
    results = load(*solves)
    # The worst NES Open hole is +0.5: only Mario Japan 2 (+0.8) is worse.
    assert [r.lineage for r in expert(results)] == ["jp_japan/02"]
    # No NES Open solves, nothing to measure against.
    assert expert([r for r in results if r.mario]) == []


def test_new_holes_leave_out_expert_holes_and_nes_open_families(solves):
    results = load(*solves)
    families = {"twin": ["jp_japan/01", "nes_us/01"], "mario": ["jp_japan/03"]}
    # Mario Japan 1 has a NES Open twin and 2 is expert; 3's family is Mario Open's alone.
    assert [r.lineage for r in new_at_nes_level(results, families)] == ["jp_japan/03"]


def test_slim_keeps_the_play_and_drops_what_was_tried():
    solve = {"tee": 4.0, "par": 4, "skill": 3.0, "states": [STATE]}
    kept = slim(solve)
    assert kept["skill"] == 3.0
    assert kept["states"] == [{k: v for k, v in STATE.items() if k != "played"}]


def test_the_archive_holds_slim_solves_and_logs_and_is_reproducible(solves, tmp_path):
    root, _ = solves
    first, second = tmp_path / "a.tar.xz", tmp_path / "b.tar.xz"
    assert write_archive(root, first) == 6
    write_archive(root, second)
    assert first.read_bytes() == second.read_bytes()
    with tarfile.open(first) as tar:
        assert "jp_japan.log" in tar.getnames()
        member = tar.extractfile("jp_japan/hole_02.json")
        assert member is not None
        assert "played" not in json.loads(member.read())["states"][0]


def test_markdown_lists_expert_and_new_holes_only_against_nes_open(solves):
    results = load(*solves)
    tables = markdown(results, {})
    assert "### Courses" in tables and "### Expert holes" in tables
    assert "| Mario Japan 2 | 5 | 500 | 5.800 | +0.800 |" in tables
    alone = markdown([r for r in results if r.mario], {})
    assert "### Expert holes" not in alone and "### New holes" not in alone
