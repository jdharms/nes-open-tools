"""Feature fit: the border tiles that draw a given shape in the vanilla holes' style.

A feature (`golf.algorithms.features`) is drawn with `$27` inside and one of 64 border
tiles round its edge, each a different cut of a tile into color 3 and ground. Given the
shape wanted, as a pixel mask, `FeatureFitter.fit` picks the tile for every cell by
minimizing three costs together:

- how far the tile's shape is from the mask, where a pixel within `slide` of the mask's
  outline costs almost nothing, so the outline may settle where the tiles can draw it;
- how badly neighboring tiles' edges miss each other, in pixels;
- how unusual the result is in the vanilla holes: side-by-side and stacked pairs by how
  rarely they occur, and 2x2 blocks of tiles by whether they occur at all.

The last is a preference, never a filter: a pair or block no vanilla hole has is allowed
when the shape needs it. The statistics are `data/tables/feature_style.json`, written by
`golf-feature-style`.

The out-of-bounds line (`golf.algorithms.boundary`) is fitted the same way, as a third
family whose tiles cut a cell into out-of-bounds ground and rough. See
`docs/feature_brush.md`.
"""

import json
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

import numpy as np

from golf.core.chr_tile import TilesetData
from golf.core.palettes import TERRAIN_WIDTH
from golf.formats import compact_json
from golf.formats.hole_data import HoleData

from .boundary import FOREST_TILES, LINE_TILES, OPEN_GROUND, line_masks
from .features import KIND_OF_PALETTE, TEE_BOX, TERRAIN_TILESET, Kind, find_features

STYLE_TABLE = (
    Path(__file__).resolve().parents[2] / "data" / "tables" / "feature_style.json"
)

#: the tile that is color 3 throughout: the inside of every feature
FULL_TILE = 0x27
BORDER_TILES = range(0x40, 0x80)
#: the tiles that are bare ground, which a feature may be drawn over
GROUND_TILES = (0x25, 0xDF)
#: a tree standing in a feature: `$27` with a tree drawn over it
TREES_IN_FEATURE = range(0xBC, 0xC0)

#: a cell the fit must leave alone, which reads as bare ground
LOCKED = -1
#: a cell the fit must leave alone, which suits any neighbor: to the out-of-bounds line,
#: the edge of a water hazard, which may itself be the boundary
LOCKED_WILD = -2
#: a cell the fit must leave alone, which reads as the inside of the feature: a tree
#: standing in it
LOCKED_FULL = -3

#: weight of the squared pixels of edge mismatch between neighboring tiles
SEAM_WEIGHT = 1.0
#: how many times the vanilla holes must have a pair to halve its mismatch's cost
SEAM_TRUST = 15
#: weight of a pair's rarity in the vanilla holes
PAIR_WEIGHT = 2.0
#: cost of a 2x2 block of tiles that no vanilla hole has
BLOCK_COST = 10.0
#: how far, in pixels, the outline may move from the mask for free
SLIDE = 1
#: cost of a wrong pixel inside the free band, so that ties go to the mask
TIE_BREAK = 0.05
#: distances from the outline are capped here
DEPTH_CAP = 5
#: smoothing of the pair counts
PAIR_SMOOTHING = 0.5
#: what a settled cell's present tile is ahead by, so that it changes only for cause
SETTLED_BONUS = 4.0
SWEEPS = 10


@cache
def tile_pixels(tileset: Path = TERRAIN_TILESET) -> np.ndarray:
    """Every terrain tile's pixels as color indexes, `[tile, y, x]`."""
    data = TilesetData(str(tileset))
    return np.array([data.decode_tile(tile) for tile in range(256)])


class TileFamily:
    """The tiles one kind of feature is drawn with, and how their edges meet.

    Tiles are indexed in the order given, the one that fills the whole cell first; one
    index past the last, `empty`, stands for bare ground. A feature's family draws in
    color 3 and is found by `find_features`; a family with no `kinds` brings its own
    `masks` and is read straight from the tiles, with `full_tiles` counting as its first.
    """

    def __init__(
        self,
        name: str,
        tiles: Iterable[int],
        kinds: Iterable[Kind] = (),
        masks: np.ndarray | None = None,
        full_tiles: Iterable[int] = (),
    ):
        self.name = name
        self.tiles = list(tiles)
        self.kinds = frozenset(kinds)
        #: tiles besides the first that fill the whole cell
        self.full_tiles = frozenset(full_tiles)
        if masks is None:
            if self.tiles[0] != FULL_TILE:
                raise ValueError(f"a feature family's first tile is ${FULL_TILE:02X}")
            masks = np.asarray(tile_pixels()[self.tiles] == 3)
        self.full = 0
        self.empty = len(self.tiles)
        self.size = len(self.tiles) + 1
        self.index = {tile: i for i, tile in enumerate(self.tiles)}
        #: `[index, y, x]`: the pixels each index draws of the shape
        self.masks = np.concatenate([masks, np.zeros((1, 8, 8), bool)])
        #: tiles that are all feature or all ground: a block of only one of them has no
        #: border to speak of
        self.plain = np.zeros(self.size, bool)
        self.plain[[self.full, self.empty]] = True
        m = self.masks
        #: `[a, b]`: pixels that disagree along the seam when b is right of, or below, a
        self.seam_right = (m[:, None, :, 7] != m[None, :, :, 0]).sum(-1).astype(float)
        self.seam_below = (m[:, None, 7, :] != m[None, :, 0, :]).sum(-1).astype(float)

    def render(self, pick: np.ndarray) -> np.ndarray:
        """The shape a grid of indexes draws; locked cells draw none of it, except
        `LOCKED_FULL`, which draws all of it."""
        rows, cols = pick.shape
        index = np.where(pick == LOCKED_FULL, self.full, pick)
        cells = self.masks[np.where(index < 0, self.empty, index)]
        return cells.transpose(0, 2, 1, 3).reshape(rows * 8, cols * 8)

    def text(self, index: int) -> str:
        return "--" if index == self.empty else f"{self.tiles[index]:02X}"


@cache
def families() -> dict[str, TileFamily]:
    """The families: fairways draw with the tiles that have no black outline, and the
    out-of-bounds line with its own, inside which forest counts as bare out-of-bounds
    ground."""
    pixels = tile_pixels()
    soft = [tile for tile in BORDER_TILES if not (pixels[tile] == 0).any()]
    out = np.concatenate([np.ones((1, 8, 8), bool), line_masks(pixels)])
    return {
        "fairway": TileFamily("fairway", [FULL_TILE, *soft], [Kind.FAIRWAY]),
        "hazard": TileFamily(
            "hazard", [FULL_TILE, *BORDER_TILES], [Kind.SAND, Kind.WATER]
        ),
        "boundary": TileFamily(
            "boundary",
            [OPEN_GROUND, *LINE_TILES],
            masks=out,
            full_tiles=FOREST_TILES,
        ),
    }


def tile_grid(family: TileFamily, hole: HoleData) -> np.ndarray:
    """The hole's visible terrain as the indexes of a family with no `kinds`: its tiles,
    `full_tiles` as the first, bare ground as `empty`, a water hazard's tiles
    `LOCKED_WILD`, since the vanilla holes let a water hazard's edge be the boundary, and
    anything else - fairways, bunkers, trees, the tee box - `LOCKED`."""
    height = hole.terrain_height
    tiles = np.array(hole.terrain[:height])
    colored = (tile_pixels() == 3).any((1, 2))
    feature = np.where(tiles < len(colored), colored[tiles % len(colored)], False)
    water = np.array(
        [
            [
                KIND_OF_PALETTE[hole.get_attribute(row, col)] is Kind.WATER
                for col in range(TERRAIN_WIDTH)
            ]
            for row in range(height)
        ]
    )
    wild = feature & water & ~np.isin(tiles, list(TEE_BOX))
    grid = np.where(wild, LOCKED_WILD, LOCKED)
    grid[np.isin(tiles, list(family.full_tiles))] = family.full
    for tile, index in family.index.items():
        grid[tiles == tile] = index
    grid[np.isin(tiles, GROUND_TILES)] = family.empty
    return grid


def style_grid(family: TileFamily, hole: HoleData) -> np.ndarray:
    """The hole's visible terrain as the family's indexes, for counting.

    A cell is a tile's index where one feature of the family's kinds owns the whole tile,
    `empty` where the tile is bare ground, and `LOCKED` anywhere else: beside a tree or
    the forest says nothing about how a border meets the ground. A family with no kinds
    is read from the tiles alone (`tile_grid`).
    """
    height = hole.terrain_height
    if not family.kinds:
        return tile_grid(family, hole)
    pixels = tile_pixels() == 3
    grid = np.full((height, TERRAIN_WIDTH), LOCKED)
    for row in range(height):
        for col in range(TERRAIN_WIDTH):
            if hole.terrain[row][col] in GROUND_TILES:
                grid[row, col] = family.empty
    for feature in find_features(hole):
        if feature.kind not in family.kinds:
            continue
        owned = Counter((y // 8, x // 8) for x, y in feature.pixels)
        for (row, col), count in owned.items():
            tile = hole.terrain[row][col]
            if tile in family.index and count == pixels[tile].sum():
                grid[row, col] = family.index[tile]
    return grid


@dataclass
class StyleCounts:
    """How often tiles sit together in a set of holes."""

    family: TileFamily
    holes: int = 0
    #: `[a, b]`: times b is immediately right of a, and immediately below it
    right: np.ndarray = field(default_factory=lambda: np.zeros((0, 0)))
    below: np.ndarray = field(default_factory=lambda: np.zeros((0, 0)))
    #: 2x2 blocks in reading order, except those all `$27` or all bare ground
    blocks: Counter = field(default_factory=Counter)

    def __post_init__(self):
        if not self.right.size:
            size = self.family.size
            self.right = np.zeros((size, size), int)
            self.below = np.zeros((size, size), int)

    def add(self, grid: np.ndarray) -> None:
        """Count one hole's grid (`style_grid`)."""
        empty = self.family.empty
        self.holes += 1
        for counts, a, b in (
            (self.right, grid[:, :-1], grid[:, 1:]),
            (self.below, grid[:-1], grid[1:]),
        ):
            use = (a >= 0) & (b >= 0) & ~((a == empty) & (b == empty))
            np.add.at(counts, (a[use], b[use]), 1)
        self.blocks.update(grid_blocks(self.family, grid))

    def to_json(self) -> dict:
        text = self.family.text

        def pairs(counts: np.ndarray) -> dict[str, int]:
            return {
                f"{text(a)} {text(b)}": int(counts[a, b])
                for a, b in zip(*np.nonzero(counts), strict=True)
            }

        return {
            "tiles": " ".join(text(i) for i in range(self.family.empty)),
            "holes": self.holes,
            "right": pairs(self.right),
            "below": pairs(self.below),
            "blocks": {
                " ".join(text(i) for i in block): count
                for block, count in sorted(self.blocks.items())
            },
        }

    @classmethod
    def from_json(cls, family: TileFamily, data: dict) -> "StyleCounts":
        if data["tiles"] != " ".join(family.text(i) for i in range(family.empty)):
            raise ValueError(f"style table has other tiles for {family.name}")
        index = {family.text(i): i for i in range(family.size)}
        counts = cls(family, holes=data["holes"])
        for name, table in (("right", counts.right), ("below", counts.below)):
            for key, count in data[name].items():
                a, b = key.split()
                table[index[a], index[b]] = count
        for key, count in data["blocks"].items():
            counts.blocks[tuple(index[part] for part in key.split())] = count
        return counts


def grid_blocks(family: TileFamily, grid: np.ndarray) -> Counter:
    """The 2x2 blocks of a grid that have a border and no locked cell.

    `$27` beside bare ground is a border: the vanilla fairways draw a flat edge with it
    between soft tiles of about the same height, never round a lone `$27`.
    """
    blocks: Counter = Counter()
    rows, cols = grid.shape
    for row in range(rows - 1):
        for col in range(cols - 1):
            block = tuple(int(i) for i in grid[row : row + 2, col : col + 2].flat)
            if min(block) < 0 or (len(set(block)) == 1 and family.plain[block[0]]):
                continue
            blocks[block] += 1
    return blocks


def count_style(family: TileFamily, holes: Iterable[HoleData]) -> StyleCounts:
    counts = StyleCounts(family)
    for hole in holes:
        counts.add(style_grid(family, hole))
    return counts


def _rarity(counts: np.ndarray, empty: int) -> np.ndarray:
    """A cost per pair: nothing for each tile's commonest partner, more the rarer the pair.

    Measured against the commonest partner so that drawing a feature in its usual tiles
    costs about what leaving the ground bare does; otherwise small features are not worth
    drawing at all.
    """
    smoothed = counts + PAIR_SMOOTHING
    forward = smoothed / smoothed.max(1, keepdims=True)
    backward = smoothed / smoothed.max(0, keepdims=True)
    rarity = -0.5 * (np.log(forward) + np.log(backward))
    rarity[empty, empty] = 0
    return rarity


def _pair_cost(seam: np.ndarray, counts: np.ndarray, empty: int) -> np.ndarray:
    """The cost of each pair of neighbors: its rarity, and its edges' mismatch squared.

    The mismatch counts in full for a pair the vanilla holes do not have, and fades as
    they have it more often than `SEAM_TRUST` times. A tile whose whole edge is feature
    stands over bare ground often as the flat underside of a lipped bunker, and fairways
    in 64 of the 144 holes have `$27` meet bare ground in a hard, straight edge; bunkers
    almost never do, and neither should be the answer to a dab of the brush.
    """
    unproven = 1 / (1 + (counts / SEAM_TRUST) ** 2)
    return SEAM_WEIGHT * seam**2 * unproven + PAIR_WEIGHT * _rarity(counts, empty)


def outline_distance(mask: np.ndarray) -> np.ndarray:
    """Each pixel's distance from the mask's outline: 1 beside it, capped at `DEPTH_CAP`."""

    def grow(area: np.ndarray) -> np.ndarray:
        padded = np.pad(area, 1)
        out = area.copy()
        for dy in range(3):
            for dx in range(3):
                out |= padded[dy : dy + area.shape[0], dx : dx + area.shape[1]]
        return out

    distance = np.full(mask.shape, DEPTH_CAP, np.int32)
    inside, outside = mask.copy(), ~mask
    for step in range(1, DEPTH_CAP):
        grown_in, grown_out = grow(inside), grow(outside)
        reached = (grown_in & ~inside) | (grown_out & ~outside)
        distance[reached] = np.minimum(distance[reached], step)
        inside, outside = grown_in, grown_out
    return distance


class FeatureFitter:
    """Fits one family's tiles to shapes, in the style of the counted holes."""

    def __init__(self, counts: StyleCounts):
        self.family = family = counts.family
        #: the index a `LOCKED_WILD` cell holds while fitting, one past the family's own
        self.wild = family.size
        self.right = self._with_wild(
            _pair_cost(family.seam_right, counts.right, family.empty)
        )
        self.below = self._with_wild(
            _pair_cost(family.seam_below, counts.below, family.empty)
        )
        #: `[top left, top right, bottom left, bottom right]`: whether the block occurs
        self.seen = np.zeros((family.size,) * 4, bool)
        for block in counts.blocks:
            self.seen[block] = True

    def _with_wild(self, cost: np.ndarray) -> np.ndarray:
        """A pair cost table with a row and column for `wild`, which cost nothing."""
        out = np.zeros((self.wild + 1, self.wild + 1))
        out[: self.wild, : self.wild] = cost
        return out

    def fit(
        self,
        target: np.ndarray,
        start: np.ndarray | None = None,
        free: np.ndarray | None = None,
        settled: np.ndarray | None = None,
        loose: np.ndarray | None = None,
    ) -> np.ndarray:
        """The grid of tile indexes that draws `target`, a pixel mask 8 times its size.

        With `start`, a grid to begin from, only cells set in `free` may change, and the
        rest - cells below 0 among them, which are never changed and read as bare
        ground (`LOCKED`), suit anything (`LOCKED_WILD`) or read as `$27`
        (`LOCKED_FULL`) - are what the free cells have to agree with. Free cells set in `settled` begin as they are in `start`
        and change only for a gain of more than `SETTLED_BONUS`. Pixels set in `loose`
        cost nothing either way.
        """
        family = self.family
        rows, cols = target.shape[0] // 8, target.shape[1] // 8
        cells = target.reshape(rows, 8, cols, 8).transpose(0, 2, 1, 3)
        weight = np.maximum(outline_distance(target) - SLIDE, 0) + TIE_BREAK
        if loose is not None:
            weight = np.where(loose, 0.0, weight)
        weight = weight.reshape(rows, 8, cols, 8).transpose(0, 2, 1, 3)
        filled = np.asarray(cells.all((2, 3)))
        touched = np.asarray(cells.any((2, 3)))
        by_target = np.where(filled, family.full, family.empty)
        if start is None:
            pick = by_target
            locked = np.zeros((rows, cols), bool)
            free = np.ones((rows, cols), bool)
        else:
            locked = start < 0
            pick = np.where(start == LOCKED_WILD, self.wild, start)
            pick = np.where(start == LOCKED, family.empty, pick)
            pick = np.where(start == LOCKED_FULL, family.full, pick)
            free = np.ones((rows, cols), bool) if free is None else free
            pick = np.where(free & ~locked, by_target, pick)

        # Only cells on or beside the outline are worth choosing between, an outline along
        # the grid included
        on_outline = touched & ~filled
        on_outline[1:] |= filled[1:] != filled[:-1]
        on_outline[:-1] |= filled[1:] != filled[:-1]
        on_outline[:, 1:] |= filled[:, 1:] != filled[:, :-1]
        on_outline[:, :-1] |= filled[:, 1:] != filled[:, :-1]
        padded = np.pad(on_outline, 1)
        near = np.zeros_like(on_outline)
        for dy in range(3):
            for dx in range(3):
                near |= padded[dy : dy + rows, dx : dx + cols]
        active = [
            (int(row), int(col))
            for row, col in zip(*np.nonzero(near & free & ~locked), strict=True)
        ]
        misfit = {
            cell: np.append(
                ((cells[cell][None] != family.masks) * weight[cell][None]).sum((1, 2)),
                np.inf,
            )
            for cell in active
        }
        for cell in active:
            if start is not None and settled is not None and settled[cell]:
                pick[cell] = start[cell]
                misfit[cell][start[cell]] -= SETTLED_BONUS
            else:
                pick[cell] = int(misfit[cell].argmin())

        plain = family.plain

        def inside(cell: tuple[int, int]) -> bool:
            return 0 <= cell[0] < rows and 0 <= cell[1] < cols

        def unseen(corner: tuple[int, int], changing: list[tuple[int, int]]):
            """The cost of the 2x2 block whose top left cell is `corner` being one no
            vanilla hole has, over the indexes of the one or two cells of `changing` it
            holds, in reading order."""
            row, col = corner
            block = [(row, col), (row, col + 1), (row + 1, col), (row + 1, col + 1)]
            if not inside(block[0]) or not inside(block[3]):
                return 0.0
            if any(locked[cell] for cell in block):
                return 0.0
            missing = ~self.seen[
                tuple(slice(None) if c in changing else int(pick[c]) for c in block)
            ]
            # A block all $27 or all bare ground is never counted, so never unseen
            fixed = {int(pick[cell]) for cell in block if cell not in changing}
            if len(fixed) == 1 and plain[same := fixed.pop()]:
                missing = missing.copy()
                missing[(same,) * missing.ndim] = False
            # and a free cell is never wild
            return BLOCK_COST * np.pad(missing, [(0, 1)] * missing.ndim)

        def solve(run: list[tuple[int, int]], horizontal: bool, blocks: bool) -> bool:
            """Give a run of neighboring cells in one row or column its best tiles, with
            every other cell as it is. Returns whether anything changed."""
            along, across = (
                (self.right, self.below) if horizontal else (self.below, self.right)
            )
            step, side = ((0, 1), (1, 0)) if horizontal else ((1, 0), (0, 1))
            first, last = run[0], run[-1]
            before = (first[0] - step[0], first[1] - step[1])
            after = (last[0] + step[0], last[1] + step[1])

            own = []
            for row, col in run:
                total = misfit[row, col].copy()
                near_side = (row - side[0], col - side[1])
                far_side = (row + side[0], col + side[1])
                if inside(near_side):
                    total += across[pick[near_side], :]
                if inside(far_side):
                    total += across[:, pick[far_side]]
                own.append(total)
            if inside(before):
                own[0] += along[pick[before], :]
            if inside(after):
                own[-1] += along[:, pick[after]]
            joint = [along for _ in run[1:]]
            if blocks:
                # Blocks that hold two cells of the run, then those that hold only an end
                for i, (a, b) in enumerate(zip(run, run[1:], strict=False)):
                    for corner in ((a[0] - side[0], a[1] - side[1]), a):
                        joint[i] = joint[i] + unseen(corner, [a, b])
                for end, cell, beyond in ((0, first, before), (-1, last, after)):
                    corner = (min(cell[0], beyond[0]), min(cell[1], beyond[1]))
                    for shift in (side, (0, 0)):
                        own[end] += unseen(
                            (corner[0] - shift[0], corner[1] - shift[1]), [cell]
                        )

            # The cheapest assignment along the run, by dynamic programming
            best = own[0]
            came_from = []
            for pair, total in zip(joint, own[1:], strict=True):
                through = best[:, None] + pair
                came_from.append(through.argmin(0))
                best = through.min(0) + total
            choice = [int(best.argmin())]
            for back in reversed(came_from):
                choice.append(int(back[choice[-1]]))
            choice.reverse()

            now = [int(pick[cell]) for cell in run]
            if choice == now:
                return False
            was = sum(total[i] for total, i in zip(own, now, strict=True)) + sum(
                pair[i, j] for pair, i, j in zip(joint, now, now[1:], strict=False)
            )
            if was <= best.min() + 1e-9:
                return False
            for cell, index in zip(run, choice, strict=True):
                pick[cell] = index
            return True

        def runs(horizontal: bool) -> list[list[tuple[int, int]]]:
            """The active cells as runs of neighbors along rows, or along columns."""
            order = sorted(active, key=lambda cell: cell if horizontal else cell[::-1])
            found: list[list[tuple[int, int]]] = []
            for cell in order:
                last = found[-1][-1] if found else None
                step = (0, 1) if horizontal else (1, 0)
                if last is not None and (last[0] + step[0], last[1] + step[1]) == cell:
                    found[-1].append(cell)
                else:
                    found.append([cell])
            return found

        # First settle seams and pairs, then also steer away from unseen blocks
        row_runs, column_runs = runs(True), runs(False)
        for blocks in (False, True):
            for _ in range(SWEEPS):
                changed = False
                for run in row_runs:
                    changed |= solve(run, True, blocks)
                for run in column_runs:
                    changed |= solve(run, False, blocks)
                if not changed:
                    break
        return np.where(locked, start if start is not None else LOCKED, pick)


def write_style_table(counts: Iterable[StyleCounts], path: Path = STYLE_TABLE) -> None:
    path.write_text(style_table_text(counts))


def style_table_text(counts: Iterable[StyleCounts]) -> str:
    return compact_json.dumps(
        {"families": {style.family.name: style.to_json() for style in counts}}
    )


@cache
def load_fitters(path: Path = STYLE_TABLE) -> dict[str, FeatureFitter]:
    """A fitter per family, from the style table."""
    data = json.loads(Path(path).read_text())["families"]
    return {
        name: FeatureFitter(StyleCounts.from_json(family, data[name]))
        for name, family in families().items()
    }
