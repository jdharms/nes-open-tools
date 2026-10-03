"""Filling every placeholder at once (`ForestFiller.fill_all`)."""

import pytest

from golf.algorithms.forest_fill import (
    ALL_FOREST_TILES,
    INNER_BORDER,
    PLACEHOLDER_TILE,
    ForestFiller,
    ForestFillError,
)


def terrain_with_two_forests() -> list[list[int]]:
    terrain = [[0xDF] * 22 for _ in range(12)]
    for row, col in ((1, 1), (7, 14)):
        for dy in range(3):
            for dx in range(4):
                terrain[row + dy][col + dx] = PLACEHOLDER_TILE
    return terrain


def test_fills_every_region():
    terrain = terrain_with_two_forests()
    ForestFiller().fill_all(terrain)
    assert terrain[1][1] in ALL_FOREST_TILES | {INNER_BORDER}
    assert terrain[9][17] in ALL_FOREST_TILES | {INNER_BORDER}
    assert all(PLACEHOLDER_TILE not in row for row in terrain)


def test_a_placeholder_left_behind_is_an_error(monkeypatch):
    monkeypatch.setattr(ForestFiller, "fill_region", lambda self, terrain, region: {})
    with pytest.raises(ForestFillError, match="row 1, column 1"):
        ForestFiller().fill_all(terrain_with_two_forests())
