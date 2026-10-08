"""The yardage books' render cache: each image once, under its hole's content hash."""

import json

import pytest
from PIL import Image

from golf.randomizer.catalog import canonical_json, content_hash
from golf.rendering import hole_renders
from golf.rendering.hole_renders import HoleRenders
from golf.rendering.rangefinder import VARIANTS
from tests.synthetic_holes import synthetic_hole


@pytest.fixture
def hole():
    made = synthetic_hole(3)
    return content_hash(made), json.loads(canonical_json(made))


def files(root) -> set[str]:
    return {path.relative_to(root).as_posix() for path in root.rglob("*.png")}


def test_a_hole_is_rendered_at_its_pin_under_its_hash(tmp_path, hole):
    digest, data = hole
    render = HoleRenders(tmp_path).ensure(digest, 2, data)
    assert render.main == f"{VARIANTS}/{digest}/main_pin_2.png"
    assert render.green == f"{VARIANTS}/{digest}/green.png"
    assert render.flag == f"{VARIANTS}/{digest}/green_flag_2.png"
    assert files(tmp_path) == {render.main, render.green, render.flag}
    assert (render.width, render.height) == (176, 240)
    assert Image.open(tmp_path / render.main).size == (176, 240)
    assert Image.open(tmp_path / render.green).size == (192, 192)
    overlay = Image.open(tmp_path / render.flag)
    assert overlay.mode == "RGBA" and overlay.size == (192, 192)


def test_the_main_image_shows_the_pin_it_is_named_for(tmp_path, hole):
    digest, data = hole
    data["flag_positions"][1]["x_offset"] = 160
    renders = HoleRenders(tmp_path)
    first = Image.open(tmp_path / renders.ensure(digest, 0, data).main)
    second = Image.open(tmp_path / renders.ensure(digest, 1, data).main)
    assert first.tobytes() != second.tobytes()


def test_another_pin_adds_only_its_own_images(tmp_path, hole):
    digest, data = hole
    renders = HoleRenders(tmp_path)
    renders.ensure(digest, 0, data)
    renders.ensure(digest, 3, data)
    assert files(tmp_path) == {
        f"{VARIANTS}/{digest}/{name}"
        for name in (
            "main_pin_0.png",
            "main_pin_3.png",
            "green.png",
            "green_flag_0.png",
            "green_flag_3.png",
        )
    }


def test_what_is_there_is_not_rendered_again(tmp_path, hole, monkeypatch):
    digest, data = hole
    first = HoleRenders(tmp_path).ensure(digest, 1, data)

    def refuse(*args, **kwargs):
        raise AssertionError("rendered again")

    monkeypatch.setattr(hole_renders, "HoleRenderer", refuse)
    assert HoleRenders(tmp_path).ensure(digest, 1, data) == first


def test_a_failed_render_leaves_nothing_behind(tmp_path, hole, monkeypatch):
    digest, data = hole

    def fail(self, path, *args, **kwargs):
        path.write(b"half")
        raise OSError("disk full")

    monkeypatch.setattr(Image.Image, "save", fail)
    with pytest.raises(OSError, match="disk full"):
        HoleRenders(tmp_path).ensure(digest, 0, data)
    assert list((tmp_path / VARIANTS / digest).iterdir()) == []


@pytest.mark.parametrize("pin", [-1, 4])
def test_a_pin_is_0_to_3(tmp_path, hole, pin):
    digest, data = hole
    with pytest.raises(ValueError, match="a pin is 0-3"):
        HoleRenders(tmp_path).ensure(digest, pin, data)
