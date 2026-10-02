"""
What lies under the ball on a real hole: `ClassifyProbePosition` ($EDEA).

The game decides the lie from two things at the ball's pixel:

1. **The palette** of the 16x16 supertile, from the attribute table. It says
   what the plain pixels of a shaped tile are: fairway, sand or water.
2. **The terrain tile.** Most tiles decide the lie outright: tee box, rough,
   out of bounds. Shaped tiles (a fairway edge, a bunker lip, a shoreline)
   carry a one-bit-per-pixel mask in the fixed bank, and the pixel's bit picks
   between the palette's surface and rough. Tree tiles carry a two-bit mask,
   so a ball at tree height can be told whether it hit trunk or leaves.

The green overrides both inside its 24x24-pixel box, where each pixel is one
tile of the green's own 24x24 grid, and that tile also gives the slope.

Every table is read from the ROM. The hole comes from `HoleData`, in the same
tiles, palettes and green grid the game decompresses into RAM.

Holes over 48 rows need a ROM with the `wram_expansion` patch, which moves
the terrain buffer to make room for 60 rows and grows the tables indexed by
`ScrollLimit` (`docs/wram_expansion.md`). `TerrainTables` finds those tables
and buffers through the operands of the instructions that read them, so it
reads either ROM as it plays.
"""

from dataclasses import dataclass, replace
from typing import Self

from golf.core.rom_reader import RomReader
from golf.formats.hole_data import HoleData
from golf.physics.arith import byte
from golf.physics.state import Ball, Lie, Slope, Terrain

GREEN_SIZE = 24
"""The green's grid is 24x24 tiles, one per course pixel."""

#: Tile ranges `ClassifyProbePosition` tests, in the order it tests them.
LIGHT_ROUGH_TILE = 0x25
PLAIN_SURFACE_TILE = 0x27
TEE_TILES = range(0x35, 0x3D)
LONE_TREE_TILE = 0x3E
SHAPED_SURFACE_TILES = range(0x40, 0x80)
SHAPED_ROUGH_TILES = range(0x80, 0x9C)
TREE_TILES = range(0x9C, 0xC0)
DEEP_ROUGH_TILE = 0xDF

#: Green tiles below this are fringe: the lie comes from the terrain instead.
FIRST_GREEN_TILE = 0x30
#: Green tiles that get the extra roll friction ($CA bit 7).
SLOW_GREEN_TILES = range(0x48, 0x88)
#: Green tiles with a slope, in two sets that scale the slope differently.
DARK_SLOPE_TILES = range(0x30, 0x48)
LIGHT_SLOPE_TILES = range(0x88, 0xA0)

GREEN_FLAG_SLOW = 0x80
GREEN_FLAG_LIGHT_SLOPE = 0x40

TREE_TRUNK_COLOR = 2

TERRAIN_COLUMNS = 22
"""Tiles in a row of the terrain buffer."""
MAX_SCROLL_LIMIT = 16
"""`ScrollLimit` of a 60-row hole, the tallest the `wram_expansion` patch makes room for."""

#: Operands that say where `ClassifyProbePosition` and `LEE9F` find things.
BOTTOM_Y_LO_OPERAND = 0xEE04
"""$EE03: SBC TerrainBottomYLo,Y."""
BOTTOM_Y_HI_OPERAND = 0xEE09
"""$EE08: SBC TerrainBottomYHi,Y (moved to $E4F9 by `wram_expansion`)."""
TERRAIN_BUFFER_OPERANDS = (0xEEC5, 0xEECB)
"""$EEC4/$EECA: ADC #lo, ADC #hi of the terrain buffer's base."""
GREEN_BUFFER_OPERANDS = (0xEE74, 0xEE7A)
"""$EE73/$EE79: ADC #lo, ADC #hi of the green buffer's base."""


@dataclass(frozen=True)
class TerrainTables:
    """The fixed-bank tables `ClassifyProbePosition` reads."""

    surface_masks: bytes
    """$F020: 8 bytes (rows) per tile $40-$7F, one bit per pixel, set = surface."""
    rough_masks: bytes
    """$F220: the same for tiles $80-$9B, set = rough, clear = out of bounds."""
    tree_masks: bytes
    """$F3E2: 16 bytes (two bit planes) per tile $3E, then $9C-$BF."""
    slope_x_codes: bytes
    """$F359: per slope tile, index into the magnitude tables, bit 7 = negative."""
    slope_y_codes: bytes
    """$F389."""
    slope_fractions: bytes
    """$F3B9: the fraction byte ($EA/$ED) for each slope code."""
    slope_magnitudes: bytes
    """$F3C0: the magnitude byte ($EB/$EE) for each slope code."""
    bottom_y: tuple[int, ...]
    """
    `TerrainBottomYLo/Hi`: Y at and past which is out of bounds, by scroll
    limit, for every scroll limit a hole can have. The vanilla tables hold
    10; the entries past them are the bytes the game reads there.
    """
    terrain_rows: int
    """How many rows the terrain buffer holds before it runs into the green's: 48, or 60 expanded."""

    @classmethod
    def from_rom(cls, rom: RomReader) -> Self:
        def operand(address: int) -> int:
            return int.from_bytes(rom.read_fixed(address, 2), "little")

        def immediates(addresses: tuple[int, int]) -> int:
            low, high = (rom.read_fixed(address, 1)[0] for address in addresses)
            return high << 8 | low

        entries = MAX_SCROLL_LIMIT + 1
        lo = rom.read_fixed(operand(BOTTOM_Y_LO_OPERAND), entries)
        hi = rom.read_fixed(operand(BOTTOM_Y_HI_OPERAND), entries)
        terrain_bytes = immediates(GREEN_BUFFER_OPERANDS) - immediates(
            TERRAIN_BUFFER_OPERANDS
        )
        return cls(
            surface_masks=rom.read_fixed(0xF020, 0x40 * 8),
            rough_masks=rom.read_fixed(0xF220, len(SHAPED_ROUGH_TILES) * 8),
            tree_masks=rom.read_fixed(0xF3E2, (1 + len(TREE_TILES)) * 16),
            slope_x_codes=rom.read_fixed(0xF359, 0x30),
            slope_y_codes=rom.read_fixed(0xF389, 0x30),
            slope_fractions=rom.read_fixed(0xF3B9, 7),
            slope_magnitudes=rom.read_fixed(0xF3C0, 7),
            bottom_y=tuple(h << 8 | lo_ for lo_, h in zip(lo, hi, strict=True)),
            terrain_rows=terrain_bytes // TERRAIN_COLUMNS,
        )


class HoleGround:
    """A `Ground` for one hole."""

    def __init__(self, hole: HoleData, tables: TerrainTables):
        if hole.terrain_height > tables.terrain_rows:
            # The game would decompress it over the green's buffer.
            raise ValueError(
                f"a {hole.terrain_height}-row hole does not fit this ROM's "
                f"{tables.terrain_rows}-row terrain buffer; use a ROM with the "
                "wram_expansion patch"
            )
        scroll_limit = hole.metadata["scroll_limit"]
        self.hole = hole
        self.tables = tables
        self.bottom_y = tables.bottom_y[scroll_limit]
        self._classified: dict[int, Terrain] = {}

    def probe(self, ball: Ball) -> Terrain:
        """`ProbeBallPosition` ($EDBC): the terrain under the ball itself."""
        return self.classify(
            ball.pixel_x, byte(ball.x, 1), ball.pixel_y, byte(ball.y, 1)
        )

    def classify(self, x: int, x_fraction: int, y: int, y_fraction: int) -> Terrain:
        """
        `ClassifyProbePosition` for a pixel (x 8 bits, y 16 bits) and its
        fractions. The fractions never change the answer, so each pixel is
        worked out once.
        """
        key = y << 8 | x
        terrain = self._classified.get(key)
        if terrain is None:
            terrain = self._classified[key] = self._classify(x, y)
        return terrain

    def _classify(self, x: int, y: int) -> Terrain:
        if x >= 0xB0 or y >= self.bottom_y:
            return Terrain(Lie.OUT_OF_BOUNDS)

        dx = (x - self.hole.green_x) & 0xFF
        dy = y - self.hole.green_y
        if dx < GREEN_SIZE and 0 <= dy < GREEN_SIZE:
            green_tile = self.hole.greens[dy][dx]
            if green_tile >= FIRST_GREEN_TILE:
                return self._green(green_tile)
            # Fringe: the terrain decides, but $CA has already been cleared.
            return replace(self._terrain(x, y), in_green_box=True)
        return self._terrain(x, y)

    def _green(self, tile: int) -> Terrain:
        flags = GREEN_FLAG_SLOW if tile in SLOW_GREEN_TILES else 0
        slope = Slope()
        if tile in DARK_SLOPE_TILES:
            slope = self._slope(tile - DARK_SLOPE_TILES.start)
        elif tile in LIGHT_SLOPE_TILES:
            flags = GREEN_FLAG_LIGHT_SLOPE
            slope = self._slope(tile - LIGHT_SLOPE_TILES.start + len(DARK_SLOPE_TILES))
        return Terrain(Lie.GREEN, green_flags=flags, slope=slope, in_green_box=True)

    def _slope(self, index: int) -> Slope:
        """`LF300`: each axis's code picks a fraction and magnitude; bit 7 is the sign."""

        def axis(code: int) -> int:
            level = code & 0x7F
            return (
                (code & 0x80) << 16
                | self.tables.slope_magnitudes[level] << 8
                | self.tables.slope_fractions[level]
            )

        return Slope(
            axis(self.tables.slope_x_codes[index]),
            axis(self.tables.slope_y_codes[index]),
        )

    def _terrain(self, x: int, y: int) -> Terrain:
        """`LEED5`: the terrain tile and palette under the pixel."""
        tile = self.hole.terrain[y >> 3][x >> 3]
        row, column = y & 7, x & 7
        palette = self.hole.attributes[y >> 4][x >> 4]

        if tile == LIGHT_ROUGH_TILE:
            return _rough(0)
        if tile == PLAIN_SURFACE_TILE:
            return _surface(palette)
        if tile < TEE_TILES.start:
            return Terrain(Lie.OUT_OF_BOUNDS)
        if tile in TEE_TILES:
            return Terrain(Lie.TEE)
        if tile == LONE_TREE_TILE:
            return _rough(1, *self._tree(0, row, column))
        if tile < SHAPED_SURFACE_TILES.start:
            return Terrain(Lie.OUT_OF_BOUNDS)
        if tile in SHAPED_SURFACE_TILES:
            mask = self.tables.surface_masks[(tile - 0x40) * 8 + row]
            if _pixel(mask, column):
                return _surface(palette)
            # Outside the shape: light rough beside fairway, deep rough otherwise.
            return _rough(0 if palette == 1 else 1)
        if tile in SHAPED_ROUGH_TILES:
            mask = self.tables.rough_masks[(tile - 0x80) * 8 + row]
            return _rough(1) if _pixel(mask, column) else Terrain(Lie.OUT_OF_BOUNDS)
        if tile in TREE_TILES:
            trunk, edge = self._tree(tile - (TREE_TILES.start - 1), row, column)
            if tile < 0xA0:
                return _rough(1, trunk, edge)
            if tile < 0xBC:
                return Terrain(Lie.OUT_OF_BOUNDS, tree_trunk=trunk, tree_edge=edge)
            return _surface(palette, trunk, edge)
        if tile == DEEP_ROUGH_TILE:
            return _rough(1)
        return Terrain(Lie.OUT_OF_BOUNDS)

    def _tree(self, index: int, row: int, column: int) -> tuple[bool, bool]:
        """
        `LEF59`: (trunk, edge) for a tree tile. A clear pixel looks one row
        down (up, on the tile's last row); clear there too still counts as edge.
        """
        color = self._tree_color(index, row, column)
        if color == TREE_TRUNK_COLOR:
            return True, False
        if color:
            return False, False
        neighbor = row - 1 if row >= 7 else row + 1
        if self._tree_color(index, neighbor, column) == TREE_TRUNK_COLOR:
            return True, False
        return False, True

    def _tree_color(self, index: int, row: int, column: int) -> int:
        """`LF632`: the tree tile's 2-bit color at a pixel."""
        base = index * 16 + row
        low = _pixel(self.tables.tree_masks[base], column)
        high = _pixel(self.tables.tree_masks[base + 8], column)
        return low | high << 1


def _pixel(mask: int, column: int) -> int:
    """Bit `column` of a mask row, leftmost pixel in bit 7 (the table at $F018)."""
    return mask >> (7 - column) & 1


def _rough(depth: int, trunk: bool = False, edge: bool = False) -> Terrain:
    return Terrain(Lie.ROUGH, rough_depth=depth, tree_trunk=trunk, tree_edge=edge)


def _surface(palette: int, trunk: bool = False, edge: bool = False) -> Terrain:
    """`LEFA7`: what a palette's surface is: fairway, sand, or water."""
    lie = {1: Lie.FAIRWAY, 2: Lie.BUNKER}.get(palette, Lie.WATER)
    return Terrain(lie, tree_trunk=trunk, tree_edge=edge)
