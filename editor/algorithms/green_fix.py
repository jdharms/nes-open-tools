"""
NES Open Tournament Golf - Green Fix Algorithm

Fills the placeholder tiles outside a green's fringe with the rough, and the
placeholders inside it with flat putting surface. The rough's rules are the Green
Brush's (`golf.algorithms.green_zones`).
"""

from collections import deque

from golf.algorithms.green_zones import (
    FLAT_TILE,
    PLACEHOLDER,
    ROUGH_TILES,
    rough_tile,
)


class GreenFix:
    """
    Fills rough and putting surface tiles in a 24x24 greens grid.

    Algorithm:
        1. Find the placeholder tiles connected to the grid's edge: the exterior
        2. Give each its rough tile: its place in the checkerboard, with a strip of
           fringe beside the fringe tiles that want one
        3. Fill the remaining placeholders with flat putting surface
    """

    # Placeholder value for tiles to be filled
    PLACEHOLDER = PLACEHOLDER

    # Flat putting surface tile
    FLAT_TILE = FLAT_TILE

    # All rough tiles (for detection/replacement)
    ROUGH_TILES = ROUGH_TILES

    def fill(self, greens: list[list[int]], phase: int = 0) -> list[list[int]]:
        """
        Fill rough and putting surface tiles in a 24x24 greens grid.

        Args:
            greens: 24x24 grid of tile values. Tiles with value PLACEHOLDER
                    (0x100) will be filled with appropriate rough tiles
                    (exterior) or flat putting surface tiles (interior).
            phase: Which way the rough is checkered (`rough_phase`): 0 puts
                   `$29` where row plus column is even, 1 where it is odd.

        Returns:
            Modified copy of greens with placeholders replaced.
        """
        # Make a deep copy to avoid modifying the input
        result = [row[:] for row in greens]
        height = len(result)
        width = len(result[0]) if height > 0 else 0

        for row, col in self._find_active_set(result, width, height):
            result[row][col] = rough_tile(result, row, col, phase)

        for row in range(height):
            for col in range(width):
                if result[row][col] == self.PLACEHOLDER:
                    result[row][col] = self.FLAT_TILE

        return result

    def _find_active_set(
        self, greens: list[list[int]], width: int, height: int
    ) -> set[tuple[int, int]]:
        """
        Find all placeholder tiles connected to the grid's edge via BFS.

        This identifies the "exterior" placeholder tiles that should be
        filled with rough. Interior placeholders (inside the fringe) are
        not included.

        Args:
            greens: The greens grid
            width: Grid width
            height: Grid height

        Returns:
            Set of (row, col) positions that are placeholders connected
            to the exterior.
        """
        if width == 0 or height == 0:
            return set()

        active = {
            (row, col)
            for row in range(height)
            for col in range(width)
            if (row in (0, height - 1) or col in (0, width - 1))
            and greens[row][col] == self.PLACEHOLDER
        }
        queue = deque(active)
        while queue:
            row, col = queue.popleft()
            for dr, dc in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                near = (row + dr, col + dc)
                if (
                    0 <= near[0] < height
                    and 0 <= near[1] < width
                    and near not in active
                    and greens[near[0]][near[1]] == self.PLACEHOLDER
                ):
                    active.add(near)
                    queue.append(near)

        return active
