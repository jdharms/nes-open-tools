"""Unit tests for the course intro sky patch's inputs."""

import pytest
from PIL import Image

from golf.core.palettes import NES_SYSTEM_PALETTE
from golf.core.patches.course_intro_sky import (
    MARIO_OPEN_SKY_IMAGE,
    ROW_WIDTH,
    SKY_COLORS,
    SKY_ROWS,
    Sky,
    read_sky_image,
    write_sky_image,
)

SOLID = b"\xff" * 16
CELLS = SKY_ROWS * ROW_WIDTH


class TestSky:
    def test_accepts_opaque_tiles(self):
        assert len(Sky((SOLID,) * CELLS).cells) == CELLS

    def test_rejects_the_wrong_number_of_cells(self):
        with pytest.raises(ValueError, match="256 cells"):
            Sky((SOLID,) * (CELLS - 1))

    def test_rejects_a_short_pattern(self):
        with pytest.raises(ValueError, match="16 bytes"):
            Sky((SOLID,) * (CELLS - 1) + (b"\xff" * 15,))

    def test_rejects_a_transparent_pixel(self):
        # One pixel clear in both planes: sprite 0 could miss its hit over it.
        holed = b"\xff" * 3 + b"\xfe" + b"\xff" * 7 + b"\xfe" + b"\xff" * 4
        with pytest.raises(ValueError, match="transparent"):
            Sky((SOLID,) * (CELLS - 1) + (holed,))


def sky_image(tmp_path, size=(256, 240), spot=None):
    """A screen of sky color with a white cell at (1, 0), and `spot` at pixel (0, 0)."""
    shade, white, blue = (NES_SYSTEM_PALETTE[color] for color in SKY_COLORS)
    image = Image.new("RGB", size, blue)
    image.paste(white, (8, 0, 16, 8))
    image.putpixel((15, 7), shade)
    if spot is not None:
        image.putpixel((0, 0), spot)
    path = tmp_path / "sky.png"
    image.save(path)
    return path


class TestReadSkyImage:
    def test_reads_the_top_rows_as_patterns(self, tmp_path):
        sky = read_sky_image(sky_image(tmp_path))
        assert sky.cells[0] == b"\xff" * 16  # sky is color 3: both planes
        # white is color 2, the high plane; the last pixel is shade, color 1
        assert sky.cells[1] == b"\x00" * 7 + b"\x01" + b"\xff" * 7 + b"\xfe"
        assert set(sky.cells[2:]) == {b"\xff" * 16}

    def test_ignores_everything_below_the_sky(self, tmp_path):
        path = sky_image(tmp_path)
        with Image.open(path) as image:
            image.putpixel((0, SKY_ROWS * 8), (1, 2, 3))
            image.save(path)
        assert len(read_sky_image(path).cells) == CELLS

    def test_rejects_a_color_outside_the_palette(self, tmp_path):
        with pytest.raises(ValueError, match=r"pixel at \(0, 0\)"):
            read_sky_image(sky_image(tmp_path, spot=(1, 2, 3)))

    def test_rejects_the_wrong_size(self, tmp_path):
        with pytest.raises(ValueError, match="256 pixels wide"):
            read_sky_image(sky_image(tmp_path, size=(512, 480)))


class TestWriteSkyImage:
    def test_writes_what_read_sky_image_reads(self, tmp_path):
        sky = read_sky_image(sky_image(tmp_path))
        write_sky_image(sky, tmp_path / "out.png")
        with Image.open(tmp_path / "out.png") as image:
            assert image.size == (256, 64)
        assert read_sky_image(tmp_path / "out.png") == sky


def test_the_checked_in_sky_is_a_sky_the_patch_takes():
    sky = read_sky_image(MARIO_OPEN_SKY_IMAGE)
    assert len(set(sky.cells)) == 98
