"""The golf-transform CLI."""

import subprocess
import sys
from pathlib import Path

from golf.formats.hole_data import HoleData
from golf.randomizer.transforms import apply_transforms
from tests.synthetic_holes import synthetic_hole, write_courses

ROOT = Path(__file__).resolve().parents[2]


def run(*args) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "tools.transform", *map(str, args)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )


def test_a_course_directory_transforms_every_hole(tmp_path):
    source = write_courses(tmp_path / "in", "course") / "course"
    (source / "course.json").write_text("{}")
    completed = run(source, tmp_path / "out", "hazards@1:5")
    assert completed.returncode == 0, completed.stderr
    for number in (1, 18):
        written = HoleData()
        written.load(tmp_path / "out" / f"hole_{number:02d}.json")
        expected = apply_transforms(synthetic_hole(number), ["hazards@1:5"])
        assert written.to_dict() == expected.to_dict()
    assert (tmp_path / "out" / "course.json").read_text() == "{}"


def test_list_names_every_transform():
    completed = run("--list")
    assert completed.returncode == 0
    assert "mirror@1 " in completed.stdout
    assert "hazards-weighted@1:<seed>" in completed.stdout


def test_a_bad_transform_writes_nothing(tmp_path):
    source = write_courses(tmp_path / "in", "course") / "course"
    completed = run(source, tmp_path / "out", "hazards@1")
    assert completed.returncode == 2
    assert "takes a seed" in completed.stderr
    assert not (tmp_path / "out").exists()
