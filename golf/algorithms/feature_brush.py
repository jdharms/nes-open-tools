"""Feature brush: paint or erase part of a fairway, bunker or water hazard in a hole, or
of its out-of-bounds ground.

A stroke is a pixel mask. It is added to, or cut from, the shape the hole's tiles of that
kind already draw, and the cells round the stroke are fitted again (`feature_fit`), with
everything further away held as it is. Only bare ground and the feature's own tiles are
ever written, with the editor's placeholder taken as bare ground: trees, forest, the tee
box and features of another kind are left alone, and so is bare ground in a supertile
whose palette another feature needs. A tree standing in a feature of the kind (`$BC`-
`$BF`) is left alone too, but is part of the feature: its neighbors meet it as `$27`. Where a painted stroke runs into them, its last few
pixels are the fit's to draw or not, so that the border closes as the tiles allow.

Out of bounds (`boundary_change`) is the same with the out-of-bounds line
(`golf.algorithms.boundary`) as the border. It writes over bare ground, the line, forest
and bare out-of-bounds ground, and leaves the cells inside the line as the placeholder,
for the forest fill.
"""

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass

import numpy as np

from golf.core.palettes import TERRAIN_WIDTH
from golf.formats.hole_data import HoleData

from .boundary import FOREST_TILES, PLACEHOLDER, cell_palettes
from .feature_fit import (
    GROUND_TILES,
    LOCKED,
    LOCKED_FULL,
    TREES_IN_FEATURE,
    FeatureFitter,
    load_fitters,
    tile_grid,
    tile_pixels,
)
from .features import KIND_OF_PALETTE, Kind

#: the family that draws each kind
FAMILY_OF_KIND = {Kind.FAIRWAY: "fairway", Kind.SAND: "hazard", Kind.WATER: "hazard"}
#: cells beyond the stroke that are fitted again with it
REACH = 1
#: cells beyond those that the fit reads but does not change
CONTEXT = 2
SHALLOW_ROUGH, DEEP_ROUGH = GROUND_TILES
#: the HUD's palette, which draws color 2 white: no out-of-bounds tile can use it
HUD_PALETTE = 0
#: the palette given a HUD-palette supertile the out-of-bounds brush writes into
OUT_OF_BOUNDS_PALETTE = 1
#: the palette given a supertile that new water is drawn into, whichever water palette
#: is selected: the HUD palette would draw any forest or out-of-bounds line there white
WATER_PALETTE = 3
#: how near, in pixels, to cells it ran into but may not write a painted stroke is left
#: to the fit
LOCKED_MARGIN = 3


def fitter_for(palette: int) -> FeatureFitter:
    """The fitter for the kind of feature a palette draws."""
    return load_fitters()[FAMILY_OF_KIND[KIND_OF_PALETTE[palette]]]


def stroke_mask(
    points: Iterable[tuple[int, int]], radius: float, hole: HoleData
) -> np.ndarray:
    """The pixels within `radius` of any point, (x, y) in course pixels, in the hole."""
    height, width = hole.terrain_height * 8, TERRAIN_WIDTH * 8
    mask = np.zeros((height, width), bool)
    reach = int(radius) + 1
    for x, y in set(points):
        top, bottom = max(0, y - reach), min(height, y + reach + 1)
        left, right = max(0, x - reach), min(width, x + reach + 1)
        if top >= bottom or left >= right:
            continue
        ys, xs = np.mgrid[top:bottom, left:right]
        mask[top:bottom, left:right] |= (xs - x) ** 2 + (ys - y) ** 2 <= radius * radius
    return mask


def brush_grid(hole: HoleData, fitter: FeatureFitter, palette: int) -> np.ndarray:
    """The hole's visible terrain as the fitter's indexes, for a brush of `palette`.

    The feature's own tiles are their indexes and ground it may be drawn over is `empty`;
    a tree standing in a feature of the kind is `LOCKED_FULL`, `$27` the brush may not
    write; everything else is `LOCKED`.
    """
    family = fitter.family
    kind = KIND_OF_PALETTE[palette]
    colored = (tile_pixels() == 3).any((1, 2))
    height = hole.terrain_height
    tiles = np.array(hole.terrain[:height])
    kinds_match = np.array(
        [
            [
                KIND_OF_PALETTE[hole.get_attribute(row, col)] is kind
                for col in range(TERRAIN_WIDTH)
            ]
            for row in range(height)
        ]
    )
    grid = np.full(tiles.shape, LOCKED)
    for tile, index in family.index.items():
        grid[(tiles == tile) & kinds_match] = index
    grid[np.isin(tiles, TREES_IN_FEATURE) & kinds_match] = LOCKED_FULL
    # Ground is free unless its supertile's palette belongs to a feature of another kind
    foreign = np.where(tiles == PLACEHOLDER, False, colored[tiles % PLACEHOLDER])
    taken = _per_supertile(foreign & ~kinds_match)
    grid[np.isin(tiles, (*GROUND_TILES, PLACEHOLDER)) & ~taken] = family.empty
    return grid


def _spread(area: np.ndarray, fill: bool) -> np.ndarray:
    """Grow the area by a pixel all round (`fill` False), or shrink it by one (True)."""
    padded = np.pad(area, 1, constant_values=fill)
    out = area.copy()
    for dy in range(3):
        for dx in range(3):
            window = padded[dy : dy + area.shape[0], dx : dx + area.shape[1]]
            out = out & window if fill else out | window
    return out


def _reach(seed: np.ndarray, within: np.ndarray) -> np.ndarray:
    """The pixels of `within` joined to `seed` side by side, not just corner to corner."""
    reached = seed & within
    while True:
        grown = reached.copy()
        grown[1:] |= reached[:-1]
        grown[:-1] |= reached[1:]
        grown[:, 1:] |= reached[:, :-1]
        grown[:, :-1] |= reached[:, 1:]
        grown &= within
        if (grown == reached).all():
            return reached
        reached = grown


def _pixels(cells: np.ndarray) -> np.ndarray:
    """A mask of cells as a mask of their pixels."""
    return np.repeat(np.repeat(cells, 8, 0), 8, 1)


def _cells(pixels: np.ndarray) -> np.ndarray:
    """The cells that hold any of a mask of pixels."""
    rows, cols = pixels.shape[0] // 8, pixels.shape[1] // 8
    return np.asarray(pixels.reshape(rows, 8, cols, 8).any((1, 3)))


def _per_supertile(cells: np.ndarray) -> np.ndarray:
    """Every cell of a supertile set where any cell of it is."""
    out = np.zeros_like(cells)
    for row in range(0, cells.shape[0], 2):
        for col in range(0, cells.shape[1], 2):
            out[row : row + 2, col : col + 2] = cells[
                row : row + 2, col : col + 2
            ].any()
    return out


def _opened(mask: np.ndarray) -> np.ndarray:
    """The mask without anything too thin to hold a 3x3 square: slivers no tile draws."""
    return _spread(_spread(mask, True), False)


@dataclass(frozen=True)
class FeatureChange:
    """What a stroke does to a hole."""

    #: (row, column, tile) for every terrain tile that changes
    tiles: tuple[tuple[int, int, int], ...] = ()
    #: (supertile row, supertile column, palette) for every attribute that changes
    attributes: tuple[tuple[int, int, int], ...] = ()

    def __bool__(self) -> bool:
        return bool(self.tiles)

    def apply(self, hole: HoleData) -> None:
        for row, col, tile in self.tiles:
            hole.set_terrain_tile(row, col, tile)
        for row, col, palette in self.attributes:
            hole.set_attribute(row, col, palette)


def _refit(
    hole: HoleData,
    fitter: FeatureFitter,
    grid: np.ndarray,
    stroke: np.ndarray,
    erase: bool,
    ground: int = SHALLOW_ROUGH,
) -> tuple[list[tuple[int, int, int]], int]:
    """The cells a stroke changes, as (row, column, the fitter's index), and the bare
    ground tile to write where a cell becomes `empty`: the commonest nearby, or `ground`
    if there is none.

    `grid` is the hole as the fitter's indexes, below 0 where the brush may not write.
    """
    family = fitter.family
    rows, cols = grid.shape
    paintable = _pixels(grid >= 0)
    # Where a painted stroke ran into cells it may not write, the pixels just short of
    # them are left to the fit, so that it can close the border there as the tiles like
    loose = np.zeros_like(stroke)
    if not erase:
        loose = _pixels(_cells(stroke & ~paintable))
        for _ in range(LOCKED_MARGIN):
            loose = _spread(loose, False)
        loose &= stroke & paintable
    stroke = stroke & paintable

    drawn = family.render(grid)
    # A painted stroke extends the shape it reaches, and stops at what it may not write:
    # the parts of it cut off from that shape are dropped. One that reaches no shape
    # starts a new one
    if not erase:
        joined = stroke & _spread(drawn, False)
        if joined.any():
            stroke = _reach(joined, stroke)
    target = drawn & ~stroke if erase else drawn | stroke
    if (target == drawn).all():
        return [], ground

    # The cells that may change, and the window of them and their context the fit sees
    ys, xs = np.nonzero(target != drawn)
    top = max(0, int(ys.min()) // 8 - REACH)
    bottom = min(rows, int(ys.max()) // 8 + REACH + 1)
    left = max(0, int(xs.min()) // 8 - REACH)
    right = min(cols, int(xs.max()) // 8 + REACH + 1)
    w_top, w_bottom = max(0, top - CONTEXT), min(rows, bottom + CONTEXT)
    w_left, w_right = max(0, left - CONTEXT), min(cols, right + CONTEXT)
    window = grid[w_top:w_bottom, w_left:w_right]
    pixels = np.s_[w_top * 8 : w_bottom * 8, w_left * 8 : w_right * 8]
    drawn, target, loose = drawn[pixels], target[pixels], loose[pixels]
    reach = np.zeros(window.shape, bool)
    reach[top - w_top : bottom - w_top, left - w_left : right - w_left] = True

    # The part of the shape the stroke touched: what it added and whatever that joins, or
    # what is left beside a cut
    touched = _spread(target != drawn, False) & target
    while True:
        grown = _spread(touched, False) & target
        if (grown == touched).all():
            break
        touched = grown
    slivers = touched & ~_opened(touched) & _pixels(reach)
    target = target & ~slivers
    touched = touched & target

    # Only the cells whose shape changed and their neighbors are fitted again, and of the
    # neighbors only those that hold nothing but the touched part: another feature close
    # by, or another arm of this one, stays as it is
    changed = _cells(target != drawn)
    beside = np.zeros_like(changed)
    padded = np.pad(changed, 1)
    for dy in range(3):
        for dx in range(3):
            beside |= padded[dy : dy + changed.shape[0], dx : dx + changed.shape[1]]
    free = changed | (beside & reach & ~_cells(target & ~touched))
    fitted = fitter.fit(
        target, start=window, free=free, settled=free & ~changed, loose=loose
    )

    plain = Counter(
        hole.terrain[row][col]
        for row in range(w_top, w_bottom)
        for col in range(w_left, w_right)
        if hole.terrain[row][col] in GROUND_TILES
    )
    if plain:
        ground = plain.most_common(1)[0][0]
    cells = [
        (int(row) + w_top, int(col) + w_left, int(fitted[row, col]))
        for row, col in zip(*np.nonzero(fitted != window), strict=True)
    ]
    return cells, ground


def feature_change(
    hole: HoleData, palette: int, stroke: np.ndarray, erase: bool = False
) -> FeatureChange:
    """What adding `stroke` to the hole's features of `palette`'s kind, or cutting it out, changes.

    `stroke` is a pixel mask of the visible terrain (`stroke_mask`).
    """
    fitter = fitter_for(palette)
    family = fitter.family
    cells, ground = _refit(
        hole, fitter, brush_grid(hole, fitter, palette), stroke, erase
    )
    kind = KIND_OF_PALETTE[palette]
    new_palette = WATER_PALETTE if kind is Kind.WATER else palette
    tiles = []
    attributes = set()
    for row, col, index in cells:
        if index == family.empty:
            tiles.append((row, col, ground))
            continue
        tiles.append((row, col, family.tiles[index]))
        if KIND_OF_PALETTE[hole.get_attribute(row, col)] is not kind:
            attributes.add((row // 2, col // 2, new_palette))
    return FeatureChange(tuple(tiles), tuple(sorted(attributes)))


def boundary_grid(hole: HoleData, fitter: FeatureFitter) -> np.ndarray:
    """The hole's visible terrain as the out-of-bounds line's indexes.

    Line tiles are their indexes; forest, bare out-of-bounds ground and the placeholder
    the forest fill fills are out of bounds; bare ground is `empty`. Water hazards are
    `LOCKED_WILD`, free to be the boundary themselves; fairways, bunkers, trees, the tee
    box and anything else are `LOCKED` and in bounds, so the line closes in front of
    them.
    So is ground in a supertile of the HUD palette (0) that a feature needs, since the
    line's speckle would be white there.
    """
    height = hole.terrain_height
    tiles = np.array(hole.terrain[:height])
    grid = tile_grid(fitter.family, hole)
    grid[tiles == PLACEHOLDER] = fitter.family.full
    colored = (tile_pixels() == 3).any((1, 2))
    feature = np.where(tiles == PLACEHOLDER, False, colored[tiles % PLACEHOLDER])
    hud = cell_palettes(hole) == HUD_PALETTE
    grid[hud & _per_supertile(feature) & (grid >= 0)] = LOCKED
    return grid


def boundary_change(
    hole: HoleData, stroke: np.ndarray, erase: bool = False
) -> FeatureChange:
    """What adding `stroke` to the hole's out-of-bounds ground, or cutting it out, changes.

    The line is fitted round the new edge. Cells that become out of bounds are left as
    the placeholder, for the forest fill to fill as the user likes; so is any forest
    beside a changed cell, whose trees may have run into it.
    """
    fitter = load_fitters()["boundary"]
    family = fitter.family
    grid = boundary_grid(hole, fitter)
    cells, ground = _refit(hole, fitter, grid, stroke, erase, DEEP_ROUGH)
    tiles = {}
    for row, col, index in cells:
        if index == family.empty:
            tiles[row, col] = ground
        elif index == family.full:
            tiles[row, col] = PLACEHOLDER
        else:
            tiles[row, col] = family.tiles[index]
    rows, cols = grid.shape
    for row, col in list(tiles):
        for near in ((row - 1, col), (row + 1, col), (row, col - 1), (row, col + 1)):
            inside = 0 <= near[0] < rows and 0 <= near[1] < cols
            forest = inside and hole.terrain[near[0]][near[1]] in FOREST_TILES
            if forest and near not in tiles:
                tiles[near] = PLACEHOLDER
    attributes = {
        (row // 2, col // 2, OUT_OF_BOUNDS_PALETTE)
        for (row, col), tile in tiles.items()
        if tile not in GROUND_TILES and hole.get_attribute(row, col) == HUD_PALETTE
    }
    return FeatureChange(
        tuple((row, col, tile) for (row, col), tile in sorted(tiles.items())),
        tuple(sorted(attributes)),
    )


def paint_feature(
    hole: HoleData, palette: int, stroke: np.ndarray, erase: bool = False
) -> int:
    """Apply `feature_change` to the hole; returns how many tiles changed."""
    change = feature_change(hole, palette, stroke, erase)
    change.apply(hole)
    return len(change.tiles)


def paint_boundary(hole: HoleData, stroke: np.ndarray, erase: bool = False) -> int:
    """Apply `boundary_change` to the hole; returns how many tiles changed."""
    change = boundary_change(hole, stroke, erase)
    change.apply(hole)
    return len(change.tiles)
