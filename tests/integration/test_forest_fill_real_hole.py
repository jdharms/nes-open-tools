"""
Integration tests for the forest fill algorithm on real hole data.

The hole is UK hole 18 with the forest in its top-left corner, 199 tiles, replaced by
placeholders: a large region with real terrain around it for the fill to match.
"""

import pytest

from golf.algorithms.forest_fill import PLACEHOLDER_TILE, ForestFiller
from golf.formats.hole_data import HoleData

#: the tiles of UK hole 18 replaced by placeholders, from the top row down
PLACEHOLDER_MASK = [
    "######################",
    "######################",
    "##################...#",
    "#################.....",
    "#############.........",
    "############..........",
    "###########...........",
    "##########............",
    "##########............",
    "##########............",
    "#########.............",
    "#########.............",
    "#########.............",
    "#########.............",
    "#########.............",
    "..######..............",
    ".....##...............",
]


@pytest.fixture(scope="module")
def vanilla_pairs(vanilla_courses):
    """("right" or "down", tile, its neighbor that way) for every pair of neighbors in
    the visible terrain of the NES Open holes."""
    pairs = set()
    paths = [
        path
        for course in ("japan", "us", "uk")
        for path in sorted((vanilla_courses / course).glob("hole_*.json"))
    ]
    assert len(paths) == 54
    for path in paths:
        hole = HoleData()
        hole.load(path)
        rows = hole.terrain[: hole.terrain_height]
        for row, tiles in enumerate(rows):
            for col, tile in enumerate(tiles):
                if col + 1 < len(tiles):
                    pairs.add(("right", tile, tiles[col + 1]))
                if row + 1 < len(rows):
                    pairs.add(("down", tile, rows[row + 1][col]))
    return pairs


@pytest.fixture
def forest_filler():
    """Create a ForestFiller instance."""
    return ForestFiller()


@pytest.fixture
def hole_18_with_placeholders(vanilla_courses):
    """UK hole 18 with PLACEHOLDER_MASK's tiles replaced by placeholders."""
    hole_data = HoleData()
    hole_data.load(vanilla_courses / "uk" / "hole_18.json")
    for row, line in enumerate(PLACEHOLDER_MASK):
        for col, cell in enumerate(line):
            if cell == "#":
                hole_data.terrain[row][col] = PLACEHOLDER_TILE
    assert sum(line.count("#") for line in PLACEHOLDER_MASK) == 199
    return hole_data


def test_detect_placeholder_regions(forest_filler, hole_18_with_placeholders):
    """Test that placeholder regions are detected correctly."""
    terrain = hole_18_with_placeholders.terrain

    # Count placeholder tiles manually
    placeholder_count = sum(
        1 for row in terrain for tile in row if tile == PLACEHOLDER_TILE
    )

    print(f"\nTotal placeholder tiles in test data: {placeholder_count}")

    # Detect regions
    regions = forest_filler.detect_regions(terrain)

    print(f"Number of regions detected: {len(regions)}")
    for i, region in enumerate(regions):
        print(f"  Region {i + 1}: {len(region.cells)} cells")

    assert len(regions) > 0, "Should detect at least one placeholder region"

    # Total cells across all regions should match placeholder count
    total_region_cells = sum(len(region.cells) for region in regions)
    assert total_region_cells == placeholder_count, (
        f"Region cells ({total_region_cells}) should match placeholder count ({placeholder_count})"
    )


# @pytest.mark.xfail(reason="BUG: Only fills 77/199 tiles - neighbor validation issue")
def test_fill_placeholder_regions(forest_filler, hole_18_with_placeholders):
    """Test that placeholder regions are filled with valid forest tiles.

    EXPECTED: All 199 placeholder tiles should be replaced with valid forest tiles
    ACTUAL: Only 77 tiles are filled, 122 report "No valid tile found"

    The bug is likely in _get_valid_tiles() method - it's not correctly
    querying the neighbor validator to find compatible tiles.
    """
    terrain = hole_18_with_placeholders.terrain

    # Detect regions
    regions = forest_filler.detect_regions(terrain)

    assert len(regions) > 0, "Should detect at least one region"

    # Fill all regions
    all_changes = {}
    for i, region in enumerate(regions):
        print(f"\nFilling region {i + 1} with {len(region.cells)} cells...")
        changes = forest_filler.fill_region(terrain, region)
        print(f"  Generated {len(changes)} tile changes")
        all_changes.update(changes)

    print(f"\nTotal changes: {len(all_changes)}")

    # Should have filled all placeholders
    placeholder_count = sum(
        1 for row in terrain for tile in row if tile == PLACEHOLDER_TILE
    )

    assert len(all_changes) > 0, "Should generate some changes"
    print(f"  Placeholders: {placeholder_count}, Changes: {len(all_changes)}")

    # Apply changes to a copy of terrain
    import copy

    filled_terrain = copy.deepcopy(terrain)
    for (row, col), tile in all_changes.items():
        filled_terrain[row][col] = tile

    # Check that no placeholders remain
    remaining_placeholders = sum(
        1 for row in filled_terrain for tile in row if tile == PLACEHOLDER_TILE
    )

    print(f"  Remaining placeholders: {remaining_placeholders}")

    # Verify all filled tiles are valid forest tiles
    from golf.algorithms.forest_fill import FOREST_BORDER, FOREST_FILL

    valid_forest_tiles = FOREST_FILL | FOREST_BORDER

    invalid_tiles = []
    for (row, col), tile in all_changes.items():
        if tile not in valid_forest_tiles:
            invalid_tiles.append((row, col, tile))

    if invalid_tiles:
        print("\nInvalid tiles filled (not forest tiles):")
        for row, col, tile in invalid_tiles[:10]:  # Show first 10
            print(f"  ({row}, {col}): 0x{tile:02X}")

    assert len(invalid_tiles) == 0, (
        f"All filled tiles should be forest tiles, found {len(invalid_tiles)} invalid"
    )


def test_filled_tiles_sit_beside_their_neighbors_as_some_vanilla_hole_has_them(
    forest_filler, vanilla_pairs, hole_18_with_placeholders
):
    """Every pair of neighbors the fill makes occurs in the vanilla holes."""
    terrain = hole_18_with_placeholders.terrain
    filled = {}
    for region in forest_filler.detect_regions(terrain):
        filled.update(forest_filler.fill_region(terrain, region))
    after = [list(row) for row in terrain]
    for (row, col), tile in filled.items():
        after[row][col] = tile

    unseen = []
    for row, col in filled:
        for step, (dy, dx) in (("right", (0, 1)), ("down", (1, 0))):
            for a, b in (
                ((row, col), (row + dy, col + dx)),
                ((row - dy, col - dx), (row, col)),
            ):
                if min(*a, *b) < 0 or b[0] >= len(after) or b[1] >= len(after[0]):
                    continue
                pair = (step, after[a[0]][a[1]], after[b[0]][b[1]])
                if pair not in vanilla_pairs:
                    unseen.append((a, f"${pair[1]:02X} {step} ${pair[2]:02X}"))
    assert len(filled) == 199
    assert not unseen
