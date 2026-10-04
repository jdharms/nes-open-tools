"""Unit tests for .mlb conflict checks, golf-labels, and merging a sidecar."""

import subprocess
import sys
from pathlib import Path

from golf.core.mlb_labels import (
    Label,
    LabelIndex,
    LabelStore,
    check_labels,
    find_conflicts,
    load_labels,
    plan_merge,
    save_labels,
)

ROOT = Path(__file__).resolve().parents[2]


def store(base: list[Label], sidecar: list[Label]) -> LabelStore:
    return LabelStore(LabelIndex(base), LabelIndex(sidecar))


def prg(start: int, name: str, end: int | None = None, comment=None) -> Label:
    return Label("NesPrgRom", start, end, name, comment)


def ram(start: int, name: str, end: int | None = None, comment=None) -> Label:
    return Label("NesInternalRam", start, end, name, comment)


def test_merge_classifies_new_replaced_and_identical_labels():
    kept = prg(0x100, "Kept")
    stub = prg(0x200, "L0_8200")
    same = ram(0x10, "ScrollX", comment="x")
    named = prg(0x200, "DoThing", comment="does the thing")
    new = ram(0x20, "ScrollY")
    plan = plan_merge(
        store([kept, stub, same], [named, ram(0x10, "ScrollX", comment="x"), new])
    )

    assert plan.added == [new]
    assert plan.replaced == [(stub, named)]
    assert [label.name for label in plan.unchanged] == ["ScrollX"]
    assert sorted(label.name for label in plan.merged) == [
        "DoThing",
        "Kept",
        "ScrollX",
        "ScrollY",
    ]
    assert not plan.has_conflicts


def test_same_address_in_another_type_is_not_a_replacement():
    plan = plan_merge(store([prg(0x10, "Code")], [ram(0x10, "Var")]))
    assert len(plan.added) == 1
    assert plan.replaced == []
    assert len(plan.merged) == 2


def test_sidecar_label_inside_a_base_range_is_an_overlap():
    table = ram(0x590, "BallSpeedMagnitude", end=0x592)
    flag = ram(0x592, "PerfectDriveFlag")
    plan = plan_merge(store([table], [flag]))
    assert plan.overlaps == [(flag, table)]
    assert plan.has_conflicts


def test_shrinking_a_replaced_range_clears_the_overlap():
    plan = plan_merge(
        store(
            [ram(0x7E2, "MusicState16", end=0x7E3)],
            [ram(0x7E2, "Pulse1EnvelopeCounter"), ram(0x7E3, "Pulse2EnvelopeCounter")],
        )
    )
    assert plan.overlaps == []


def test_overlap_between_two_sidecar_labels_is_reported_once():
    plan = plan_merge(store([], [prg(0x10, "A", end=0x20), prg(0x18, "B")]))
    assert len(plan.overlaps) == 1


def test_name_moved_by_a_rename_is_not_a_duplicate():
    plan = plan_merge(
        store(
            [ram(0xFF, "MusicRequest")],
            [ram(0xFF, "MusicSuspendFlag"), ram(0xF4, "MusicRequest")],
        )
    )
    assert plan.duplicate_names == {}


def test_name_held_at_two_addresses_is_a_duplicate():
    base = Label("NesSaveRam", 0, 3, "SramMagic")
    side = Label("NesSaveRam", 5, None, "SramMagic")
    plan = plan_merge(store([base], [side]))
    assert plan.duplicate_names == {"SramMagic": [base, side]}


def test_base_only_duplicates_and_empty_names_are_not_reported():
    plan = plan_merge(
        store([prg(0x10, ""), prg(0x20, ""), prg(0x30, "X"), prg(0x40, "X")], [])
    )
    assert plan.duplicate_names == {}


def run_merge(base: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "tools.research.labels", str(base), "merge", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )


def write_pair(tmp_path: Path, base: list[Label], sidecar: list[Label]) -> Path:
    base_path = tmp_path / "golf.mlb"
    save_labels(base_path, base)
    save_labels(tmp_path / "golf.sidecar.mlb", sidecar)
    return base_path


def test_merge_cli_is_a_dry_run_by_default(tmp_path):
    base_path = write_pair(tmp_path, [prg(0x200, "L0_8200")], [prg(0x200, "DoThing")])
    result = run_merge(base_path)
    assert result.returncode == 0, result.stderr
    assert "L0_8200 -> DoThing" in result.stdout
    assert [label.name for label in load_labels(base_path)] == ["L0_8200"]
    assert (tmp_path / "golf.sidecar.mlb").exists()


def test_merge_cli_writes_backups_and_removes_the_sidecar(tmp_path):
    base_path = write_pair(tmp_path, [prg(0x200, "L0_8200")], [prg(0x200, "DoThing")])
    result = run_merge(base_path, "--write")
    assert result.returncode == 0, result.stderr
    assert [label.name for label in load_labels(base_path)] == ["DoThing"]
    assert not (tmp_path / "golf.sidecar.mlb").exists()
    assert [label.name for label in load_labels(f"{base_path}.bak")] == ["L0_8200"]
    backup = tmp_path / "golf.sidecar.mlb.bak"
    assert [label.name for label in load_labels(backup)] == ["DoThing"]


def test_merge_cli_refuses_to_write_conflicts(tmp_path):
    table = ram(0x590, "BallSpeedMagnitude", end=0x592)
    base_path = write_pair(tmp_path, [table], [ram(0x592, "PerfectDriveFlag")])
    result = run_merge(base_path, "--write")
    assert result.returncode == 1
    assert "overlapping ranges" in result.stdout
    assert len(load_labels(base_path)) == 1

    result = run_merge(base_path, "--write", "--allow-conflicts")
    assert result.returncode == 0, result.stderr
    assert len(load_labels(base_path)) == 2


def test_find_conflicts_skips_the_label_being_replaced():
    labels = [ram(0x590, "BallSpeedMagnitude", end=0x592), ram(0x10, "ScrollX")]
    overlapping, same_name = find_conflicts(labels, ram(0x590, "BallSpeed", end=0x591))
    assert overlapping == []
    assert same_name == []


def test_find_conflicts_reports_overlaps_and_names():
    table = ram(0x590, "BallSpeedMagnitude", end=0x592)
    scroll = ram(0x10, "ScrollX")
    overlapping, same_name = find_conflicts([table, scroll], ram(0x592, "ScrollX"))
    assert overlapping == [table]
    assert same_name == [scroll]


def run_labels(base: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "tools.research.labels", str(base), *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )


def test_add_writes_the_label_file_by_default(tmp_path):
    base_path = tmp_path / "golf.mlb"
    save_labels(base_path, [ram(0x10, "ScrollX")])
    result = run_labels(base_path, "add", "ram", "0011", "ScrollY")
    assert result.returncode == 0, result.stderr
    assert [label.name for label in load_labels(base_path)] == ["ScrollX", "ScrollY"]
    assert not (tmp_path / "golf.sidecar.mlb").exists()


def test_add_refuses_a_name_already_in_use(tmp_path):
    base_path = tmp_path / "golf.mlb"
    save_labels(base_path, [ram(0x10, "ScrollX")])
    result = run_labels(base_path, "add", "ram", "0011", "ScrollX")
    assert result.returncode == 1
    assert "already used at NesInternalRam:0010" in result.stderr
    assert len(load_labels(base_path)) == 1


def test_add_warns_about_an_overlapping_range(tmp_path):
    base_path = tmp_path / "golf.mlb"
    save_labels(base_path, [ram(0x590, "BallSpeedMagnitude", end=0x592)])
    result = run_labels(base_path, "add", "ram", "0592", "PerfectDriveFlag")
    assert result.returncode == 0, result.stderr
    assert "overlaps 0590-0592 (BallSpeedMagnitude)" in result.stderr
    assert len(load_labels(base_path)) == 2


def test_edit_refuses_a_rename_to_a_name_in_use(tmp_path):
    base_path = tmp_path / "golf.mlb"
    save_labels(base_path, [ram(0x10, "ScrollX"), ram(0x11, "ScrollY")])
    result = run_labels(base_path, "edit", "ram", "0011", "--name", "ScrollX")
    assert result.returncode == 1
    assert [label.name for label in load_labels(base_path)] == ["ScrollX", "ScrollY"]


def test_check_reports_overlapping_prg_ranges_but_not_places_inside_them():
    table = prg(0x100, "Table", end=0x10F)
    inner = prg(0x104, "PlaceInTable")
    clash = prg(0x10F, "Clash", end=0x112)
    buffer = ram(0x100, "Buffer", end=0x10F)
    nested = ram(0x104, "BufferPart", end=0x107)
    overlaps, duplicates = check_labels([table, inner, clash, buffer, nested])
    assert overlaps == [(table, clash)]
    assert duplicates == {}


def test_check_reports_a_range_overlapped_past_a_shorter_neighbor():
    outer = prg(0x100, "Outer", end=0x1FF)
    short = prg(0x110, "Short", end=0x111)
    late = prg(0x180, "Late", end=0x181)
    overlaps, _ = check_labels([outer, short, late])
    assert overlaps == [(outer, short), (outer, late)]


def test_check_reports_repeated_names_and_ignores_empty_ones():
    first, second = prg(0x10, "Same"), ram(0x20, "Same")
    _, duplicates = check_labels([first, second, prg(0x30, ""), prg(0x40, "")])
    assert duplicates == {"Same": [first, second]}


def test_check_cli_exits_nonzero_on_a_problem(tmp_path):
    path = tmp_path / "golf.mlb"
    save_labels(path, [prg(0x10, "A", end=0x20), prg(0x18, "B", end=0x30)])
    run = [sys.executable, "-m", "tools.research.labels", str(path), "check"]
    result = subprocess.run(run, cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 1
    assert "overlap" in result.stdout
    save_labels(path, [prg(0x10, "A", end=0x20), prg(0x21, "B", end=0x30)])
    result = subprocess.run(run, cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout
