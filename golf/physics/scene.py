"""
The behind-the-golfer scene builder: `BuildPerspectiveScene` (bank 9 $8829).

Before a shot the game works out what stands ahead of the golfer and leaves
two maps in WRAM, 32 tiles a row and 24 rows: the tile map ($77E6) it draws and
the depth map ($7AE6) of how far away whatever is drawn there stands. The
flight then collides with them (`golf.physics.perspective.collide`). The
builder's steps, in order:

1. **The flag** (`$98EA`): where the pin and the green's corners fall on screen.
2. **The probe grid** (`$8848`): 20 rows of 64 terrain probes ahead along the
   aim, a lie each, kept where the depth map will go.
3. **The ground** (`$9C1C`, `$8EE4`, `$9CB8`, `$A30B`): the grid thinned to
   three lies per 4x4 block, turned into tiles a 2x2 block at a time by its
   neighbors, then each tile fitted to the tiles around it.
4. **The trees** (`$8FE4`, `$91C9`): every tree tile in the box of course the
   scene covers is projected onto the screen; the nearest in each screen column
   is drawn as a trunk and a canopy, and those cells get its depth. This is the
   only step that writes the depth map, and the only one that draws on the RNG:
   once for each canopy cell drawn over a tile it has no class for.
5. **The sky** (`$9785`, from `$96EC` after the builder returns): six blocks of
   cloud tiles, each only where the tile map is still blank.

What is left out only draws: the palette fade between probe rows, the
flagstick and the other sprites (`$99B2`, `$9A79`), the tile changes queued
for the PPU, and the nametable and attribute uploads.

The port keeps the maps, the palette map ($072D) and the few page-7 registers
at the game's own addresses in one 64K image with bank 9 and the fixed bank
mapped. That is what makes its quirks come out right without special cases:
the ground passes read past the edges of the probe grid, into the tile map
above it (still holding the last scene's bottom rows), the WRAM after it, and
then bank 9 itself. So a scene depends on the WRAM it is built over, and
`build_scene` takes it.

Two more leftovers reach the maps, both from the last projection the game
ran (`stale`): the tree projections never write the fraction bytes of the
point they project, and when the flag is out of view the builder still reads
the screen position the projection did not write.
"""

from dataclasses import dataclass
from typing import Self

from golf.core.rng import lfsr_step
from golf.core.rom_reader import RomReader
from golf.physics.arith import MASK8, MASK16, mul8
from golf.physics.perspective import (
    SCENE_DEPTH_MAP,
    SCENE_TILE_MAP,
    TILE_MAP_ROW_OFFSETS,
    PerspectiveScene,
    Projection,
    project_registers,
)
from golf.physics.shot import Flag
from golf.physics.state import Ball, Lie
from golf.physics.tables import PHYSICS_BANK, PhysicsTables
from golf.physics.terrain import HoleGround

SCENE_BANK = 9
BANK_SIZE = 0x4000
WRAM = 0x6000
WRAM_SIZE = 0x2000

MAP_COLUMNS = 32
MAP_ROWS = 24
GROUND_ROW = 14
"""The first tile map row the ground is drawn on; the rows above start as sky."""
GROUND_TILES = SCENE_TILE_MAP + GROUND_ROW * MAP_COLUMNS  # $79A6
GROUND_DEPTHS = SCENE_DEPTH_MAP + GROUND_ROW * MAP_COLUMNS  # $7CA6

GRID = SCENE_DEPTH_MAP
"""The probe grid shares the depth map's memory until the depth map is cleared."""
GRID_COLUMNS = 64
GRID_ROWS = 20
BALL_CELL = 0x7F88
"""Row 18, column 34 of the grid: the lie the ball is on."""

PALETTE_MAP = 0x072D
"""16 a row: 16 bytes of 3 for the sky, then one per 4x4 block of the grid."""
GROUND_PALETTES = 0x073D
PALETTE_ROW_OFFSETS = 0xE7B9

BALL_LIE_CLASS = 0x0726
FLAG_NEAR = 0x0727
FLAG_SCREEN_X = 0x078E
FLAG_SCREEN_Y = 0x078F
FLAG_SIZE = 0x0790
GREEN_LEFT = 0x0793
GREEN_RIGHT = 0x0794
TREE_BANDS = 0x7DE6
"""Per screen column: the size band (1-15) of the tree drawn there, 0 for none."""
TREE_DEPTHS = 0x7E06
TREE_BOX = 0x7E26
DEPTH_BEFORE = 0x7E2C

SKY_TILE = 0x3A
ROUGH_TILE = 0x38
BLOCKED_TILE = 0x39

# Bank 9 tables, by the address of the instruction that reads them.
PROBE_OFFSETS = 0x89D0
ROW_DISTANCES = 0x8ED0
BLOCK_CELLS = 0x8FD4
TREE_COUNTS = 0x90ED
TREE_SHAPES = 0x9112
TREE_SHAPE_X = 0x9137
TREE_SHAPE_Y = 0x9140
BAND_THRESHOLDS = 0x91B8
TRUNK_TILES = 0x9295
TRUNK_TILES_ON_SKY = 0x929B
CANOPY_KEEPS_DEPTH = 0x935F
"""Indexed by tiles $CC and up, so the table proper starts at $942B."""
RANDOM_CANOPY_TILES = 0x9375
TILE_CLASS_KEYS = 0x940F
TILE_CLASSES = 0x945C
UNCLASSED = 0x0D
OVERLAP_TILES = 0x9478
SIZE_BY_BAND = 0x9488
TRUNK_POINTERS = 0x9499
CANOPY_COLUMN_POINTERS = 0x94CC
CANOPY_ROW_POINTERS = 0x957F
CANOPY_TILE_POINTERS = 0x9639
GREEN_CORNER_X = 0x99AA
GREEN_CORNER_Y = 0x99AE
QUAD_ABOVE = 0x9DC8
QUAD_BESIDE = 0x9DCC
LIE_PRIORITY = 0x9E18
SHARED_MATCHES = 0x9F1E
DIAGONAL_PAIRS = 0x9FF7
FULL_QUAD_PAIRS = 0xA265
FULL_QUAD_TILES = 0xA26D
FULL_QUAD_GREEN_TILES = 0xA27D
TILE_BY_LIE = 0xA28D
NEIGHBOR_KEYS = 0xA56C
NEIGHBOR_KEY_COUNT = 0x26
NEIGHBOR_LISTS = 0xA592
EDGE_KEYS = 0xA68D
EDGE_TILES = 0xA691
REPLACEMENT_TILES = 0xA675

#: The four corners of the box of course the tree scan covers, as (side,
#: ahead) bytes for the rotation: 55 pixels either side, 105 ahead.
TREE_BOX_CORNERS = ((0xC9, 0x69), (0x37, 0x69))

#: `$9E41`'s routines by how the four lies of a 2x2 block match the chosen one.
#: A plain entry is (offsets, tiles, what to do when the tile is 0).
_PLAIN = {
    1: (0x9E81, None),
    2: (0x9EB1, None),
    4: (0x9F44, None),
    8: (0xA051, None),
    7: (0xA01E, (0, 1)),
    11: (0xA125, (1, 2)),
    13: (0xA1B3, (2, 3)),
    14: (0xA1EA, (3, 0)),
}
#: (pair, the corner bit 0 of the shared table repaints, the corner bit 1 does).
_PAIRED = {
    3: (0x9F06, 3, 2),
    5: (0x9F99, 3, 1),
    10: (0xA0EC, 2, 0),
    12: (0xA17A, 1, 0),
}

#: The sky blocks `$9785` stamps: (tiles, width, height, column, row).
SKY_BLOCKS = (
    (0x98A2, 4, 2, 6, 6),
    (0x98B2, 4, 2, 6, 10),
    (0x98AA, 4, 2, 12, 4),
    (0x98BA, 4, 2, 12, 8),
    (0x98C2, 4, 4, 20, 2),
    (0x98D2, 6, 4, 20, 8),
)

NO_PROJECTION = Projection(0)


@dataclass(frozen=True)
class SceneTables:
    """The two PRG banks the builder runs from, and the one the collision reads."""

    scene_bank: bytes
    fixed_bank: bytes
    physics_bank: bytes
    physics: PhysicsTables

    @classmethod
    def from_rom(cls, rom: RomReader) -> Self:
        def bank(number: int) -> bytes:
            return rom.read_prg(number * BANK_SIZE, BANK_SIZE)

        return cls(
            bank(SCENE_BANK),
            rom.read_fixed(0xC000, BANK_SIZE),
            bank(PHYSICS_BANK),
            PhysicsTables.from_rom(rom),
        )


@dataclass(frozen=True)
class BuiltScene:
    scene: PerspectiveScene
    """What a flight collides with: sky blocks included."""
    wram: bytes
    """$6000-$7FFF as `BuildPerspectiveScene` returns, before the sky blocks."""
    rng_state: int
    """`RngState` once the canopies are drawn."""
    stale: Projection
    """$C6-$C8 as the builder's last projection left them."""

    @property
    def shown(self) -> bytes:
        """$6000-$7FFF with the sky blocks in."""
        return bytes(self.scene.memory[WRAM : WRAM + WRAM_SIZE])


def build_scene(
    ground: HoleGround,
    tables: SceneTables,
    x: int,
    y: int,
    aim: int,
    flag: Flag,
    rng_state: int = 0,
    x_fraction: int = 0,
    y_fraction: int = 0,
    wram: bytes | None = None,
    stale: Projection = NO_PROJECTION,
) -> BuiltScene:
    """
    The scene for a shot from pixel (`x`, `y`) along `aim`, with the pin at
    `flag` and `RngState` at `rng_state`.

    `wram` is $6000-$7FFF as the last scene left it (zeros when there was
    none, as after power-on with a blank save), and `stale` the screen
    position ($C6-$C8) the game's last projection left. Both only matter at
    the edges the module docstring describes.
    """
    builder = SceneBuilder(ground, tables, wram, stale)
    builder.run(x, y, x_fraction, y_fraction, aim, flag, rng_state)
    built = bytes(builder.m[WRAM : WRAM + WRAM_SIZE])
    builder.sky()
    scene = PerspectiveScene(
        bytes(builder.m[WRAM : WRAM + WRAM_SIZE]),
        tables.fixed_bank,
        tables.physics_bank,
    )
    return BuiltScene(scene, built, builder.rng_state, builder.registers)


class SceneBuilder:
    """
    The builder's memory and its steps, one method to a routine. `build_scene`
    runs them all; the tests run some alone against the ROM's.
    """

    def __init__(
        self,
        ground: HoleGround,
        tables: SceneTables,
        wram: bytes | None,
        stale: Projection,
    ):
        self.ground = ground
        self.tables = tables
        self.m = m = bytearray(0x10000)
        if wram is not None:
            m[WRAM : WRAM + WRAM_SIZE] = wram
        m[0x8000:0xC000] = tables.scene_bank
        m[0xC000:0x10000] = tables.fixed_bank
        #: $C5-$C8 as the last projection left them.
        self.registers = stale
        self.rng_state = 0
        #: The four lies of the 2x2 block being drawn ($EC-$EF).
        self.quad = [0, 0, 0, 0]

    def word(self, address: int) -> int:
        return self.m[address] | self.m[address + 1] << 8

    def run(
        self,
        x: int,
        y: int,
        x_fraction: int,
        y_fraction: int,
        aim: int,
        flag: Flag,
        rng_state: int,
    ) -> None:
        self.x, self.y, self.aim = x, y, aim
        self.origin_x = x << 8 | x_fraction
        self.origin_y = y << 8 | y_fraction
        self.flag = flag
        self.rng_state = rng_state
        self.find_flag()
        self.probe_grid()
        self.nudge_flag()
        self.thin_blocks()
        self.draw_ground()
        self.fit_neighbors()
        self.finish_horizon()
        self.block_bottom_rows()
        self.clear()
        self.find_trees()
        self.draw_trees()

    # --- projection -------------------------------------------------------

    def project(self, x: int, y: int) -> Projection:
        """
        `LE87C` for a whole pixel. The callers set only the pixel bytes
        ($BF, $C1, $C2), so the fractions are still the flag's from `$98EA`.
        """
        ball = Ball(
            x=x << 16 | (self.flag.x & MASK8) << 8,
            y=y << 16 | (self.flag.y & MASK8) << 8,
        )
        self.registers = project_registers(
            ball,
            self.origin_x,
            self.origin_y,
            self.aim,
            self.tables.physics,
            self.registers,
        )
        return self.registers

    def offset(self, side: int, ahead: int) -> tuple[int, int]:
        """
        `L9_899B`: the point `side` pixels across and `ahead` pixels along the
        aim from the ball (signed bytes), through `LE638`, the rotation's
        8-bit entry. X comes back clamped to $FF (off the left) or $B0 (off
        the right); Y is 16 bits and wraps.
        """
        angle = -self.aim & MASK8
        physics = self.tables.physics
        sin, cos = physics.sin(angle), physics.sin((angle + 0x40) & MASK8)
        cos_sign = (angle + 0x40) & MASK8

        def product(component: int, magnitude: int, sign_source: int) -> int:
            # `LE6AB`: the high byte of |component| x magnitude, signed.
            size = -component & MASK8 if component & 0x80 else component
            high, _ = mul8(size, magnitude)
            return -high & MASK16 if (component ^ sign_source) & 0x80 else high

        across = (product(side, cos, cos_sign) - product(ahead, sin, angle)) & MASK16
        along = (product(side, sin, angle) + product(ahead, cos, cos_sign)) & MASK16
        probe_x = self.x + (across & MASK8)
        high = ((across >> 8) + (probe_x >> 8)) & MASK8
        probe_x &= MASK8
        if high & 0x80:
            probe_x = 0xFF
        elif high or probe_x >= 0xB0:
            probe_x = 0xB0
        return probe_x, (self.y - along) & MASK16

    def probe(self, x: int, y: int) -> tuple[int, int]:
        """`LEDD4`: (lie, terrain tile) at a point, with X pulled onto the course."""
        if x >= 0xB0:
            x = 0 if x >= 0xD8 else 0xAF
        return self.ground.classify(x, 0, y, 0).lie, self.ground.tile(x, y)

    # --- 1. the flag ------------------------------------------------------

    def find_flag(self) -> None:
        """`L9_98EA`: where the pin and the green fall on screen."""
        m = self.m
        flag = self.flag
        self.registers = project_registers(
            Ball(x=flag.x << 8, y=flag.y << 8),
            self.origin_x,
            self.origin_y,
            self.aim,
            self.tables.physics,
            self.registers,
        )
        depth, screen_x, screen_y = (
            self.registers.depth,
            self.registers.screen_x,
            self.registers.screen_y,
        )
        m[FLAG_NEAR] = 0
        size = 0xFF
        if not screen_y >> 8 and screen_y < 0xA5 and depth:
            size = sum(depth < limit for limit in (0x19, 0x23, 0x28, 0x32, 0x4B))
        m[FLAG_SIZE] = size
        m[FLAG_SCREEN_X] = screen_x
        m[GREEN_LEFT] = screen_x & 0xF8
        m[GREEN_RIGHT] = screen_x | 7
        base_y = (screen_y + 3) & MASK8
        m[FLAG_SCREEN_Y] = base_y
        if depth and base_y < 0x84 and not screen_y >> 8:
            m[FLAG_NEAR] = 1

        green_x, green_y = self.ground.hole.green_x, self.ground.hole.green_y
        for corner in range(3, -1, -1):
            # The flag's Y high byte is 0 and stays 0: the green is in the
            # top 256 rows.
            corner_x = (green_x + m[GREEN_CORNER_X + corner]) & MASK8
            corner_y = (green_y + m[GREEN_CORNER_Y + corner]) & MASK8
            found = self.project(corner_x, corner_y)
            if not found.depth or found.screen_y >> 8:
                continue
            column = found.screen_x & 0xF8
            if column >= m[GREEN_RIGHT]:
                m[GREEN_RIGHT] = column
            if column < m[GREEN_LEFT]:
                m[GREEN_LEFT] = column

    # --- 2. the probe grid ------------------------------------------------

    def probe_grid(self) -> None:
        """
        `$8834`-`$888A`. A green probe is kept as green only on rows 4 and up
        of a scene the flag is not in; otherwise it is drawn as rough.
        """
        m = self.m
        cell = GRID
        offsets = PROBE_OFFSETS
        for row in range(GRID_ROWS):
            ahead = m[ROW_DISTANCES + row]
            green_as_rough = m[FLAG_NEAR] or row < 4
            for _ in range(GRID_COLUMNS):
                lie, _tile = self.probe(*self.offset(m[offsets], ahead))
                if lie == Lie.GREEN and green_as_rough:
                    lie = Lie.ROUGH
                m[cell] = lie
                cell += 1
                offsets += 1
        m[BALL_LIE_CLASS] = m[BALL_CELL]

    # --- 3. the ground ----------------------------------------------------

    def nudge_flag(self) -> None:
        """
        `L9_9C1C`: with the flag in view but not near ($0727 clear), move the
        flagstick's foot left, four pixels up to five times, while
        `_flag_off_green` says so.
        """
        m = self.m
        if m[FLAG_NEAR] or m[FLAG_SIZE] & 0x80:
            return
        raised = (m[FLAG_SCREEN_Y] - 2) & MASK8
        for _ in range(5):
            if not self._flag_off_green():
                return
            if m[FLAG_SCREEN_X] < 4:
                return
            m[FLAG_SCREEN_X] -= 4
            m[FLAG_SCREEN_Y] = raised

    def _flag_off_green(self) -> bool:
        """`L9_9C4C`: whether the grid cells around the flag's foot are not all green."""
        m = self.m
        row = ((m[FLAG_SCREEN_Y] - 0x70) & MASK8) >> 2
        cells = (GRID + row * GRID_COLUMNS) & MASK16
        column = m[FLAG_SCREEN_X] >> 2

        def green(address: int) -> bool:
            return m[address & MASK16] == Lie.GREEN

        if not green(cells + column):
            return True
        column += 1
        if column >= GRID_COLUMNS:
            return False
        if not green(cells + column):
            return True
        cells -= GRID_COLUMNS
        above = green(cells + column)
        column -= 1
        if above and green(cells + column):
            return False
        cells += 2 * GRID_COLUMNS
        if not green(cells + column):
            return True
        return not green(cells + column + 1)

    def thin_blocks(self) -> None:
        """
        `L9_8EE4`: each 4x4 block of the grid cut down to at most three lies,
        and its palette chosen. Out of bounds and the tee become rough, and
        green becomes 1. Then sand and water both become rough, unless one of
        them outnumbers both the other and the fairway: that one is kept, the
        fairway becomes rough instead, and the block takes its palette.
        """
        m = self.m
        for index in range(0x10):
            m[PALETTE_MAP + index] = 3
        for index in range(0x10, 0x60):
            m[PALETTE_MAP + index] = 1
        for index in range(0x10, 0x60):
            block = GRID + (index - 0x10 >> 4) * 0x100 + (index & 0x0F) * 4
            cells = [block + m[BLOCK_CELLS + cell] for cell in range(16)]
            counts = [0] * 7
            for cell in cells:
                lie = m[cell]
                if lie in (Lie.OUT_OF_BOUNDS, Lie.TEE):
                    lie = Lie.ROUGH
                elif lie == Lie.GREEN:
                    lie = 1
                m[cell] = lie
                counts[lie] += 1
            fairway, sand, water = counts[0], counts[3], counts[4]
            repaint = (Lie.WATER, Lie.BUNKER)
            if sand < water:
                if fairway < water:
                    repaint = (Lie.FAIRWAY, Lie.BUNKER)
                    m[PALETTE_MAP + index] = 3
            elif fairway < sand:
                repaint = (Lie.WATER, Lie.FAIRWAY)
                m[PALETTE_MAP + index] = 2
            for cell in cells:
                if m[cell] in repaint:
                    m[cell] = Lie.ROUGH

    def neighbor(self, cell: int, offset: int) -> int:
        """
        `L9_A2F9`: the grid cell a signed byte away from `cell`: $C0 is a row
        up, $3F a row down and one left. Nothing keeps it inside the grid.
        """
        if offset & 0x80:
            offset -= 0x100
        return self.m[(cell + offset) & MASK16]

    def draw_ground(self) -> None:
        """`L9_9CB8`: one tile for each 2x2 block of the grid, ten rows of 32."""
        m = self.m
        cell = GRID
        tile = GROUND_TILES
        for _row in range(10):
            for _column in range(MAP_COLUMNS):
                self.quad = [m[cell + offset] for offset in (0, 1, 0x40, 0x41)]
                chosen, other = self._choose_lies(cell)
                m[tile] = self._quad_tile(cell, chosen, other)
                cell += 2
                tile += 1
            cell += GRID_COLUMNS

    def _choose_lies(self, cell: int) -> tuple[int, int]:
        """
        `L9_9D1C`: the lie the block is drawn as ($EA) and the one it is drawn
        against ($EB). A block of three lies first repaints one corner.

        The game also has a path for four different lies (`$9DD0`), which
        runs on into this one's search with counts that hold no 2 and walks
        off into the rest of the zero page. `thin_blocks` leaves a 4x4 block
        at most three lies and these blocks never straddle two, so it cannot
        be reached from a probe grid, and it is not ported.
        """
        m = self.m
        quad = self.quad
        kinds = len(set(quad))
        if kinds == 1:
            return quad[0], 5
        if kinds > 3:
            raise NotImplementedError("a 2x2 block of four lies ($9DD0)")
        if kinds == 3:
            counts = [quad.count(lie) for lie in range(max(quad) + 1)]
            chosen = counts.index(2)
            single = counts.index(1)
            corner = quad.index(single)
            if (
                self.neighbor(cell, m[QUAD_ABOVE + corner]) == single
                and self.neighbor(cell, m[QUAD_BESIDE + corner]) == single
            ):
                # That single has its own lie around it: repaint the other one.
                corner = quad.index(counts.index(1, single + 1))
            quad[corner] = chosen
        chosen = quad[0]
        other = next(lie for lie in quad[1:] if lie != chosen)
        if m[LIE_PRIORITY + other] < m[LIE_PRIORITY + chosen]:
            chosen, other = other, chosen
        return chosen, other

    def _pair(self, cell: int, pair: int, lie: int) -> int:
        """`L9_A2D8`: 2 if the first of a pair of neighbors is `lie`, plus 1 for the second."""
        m = self.m
        return 2 * (self.neighbor(cell, m[pair]) == lie) + (
            self.neighbor(cell, m[pair + 1]) == lie
        )

    def _matches(self, cell: int, block: int, lie: int) -> int:
        """
        `L9_A294`: 0-8 from two pairs of neighbors. In each pair the first
        being `lie` counts 2 and, failing that, the second counts 1; the first
        pair counts three times over.
        """
        m = self.m

        def score(pair: int) -> int:
            if self.neighbor(cell, m[pair]) == lie:
                return 2
            return int(self.neighbor(cell, m[pair + 1]) == lie)

        return 3 * score(block) + score(block + 2)

    def _quad_tile(self, cell: int, chosen: int, other: int) -> int:
        """
        `L9_9E1F` and the sixteen routines of `$9E41`: the tile for a block
        whose corners match `chosen` in the pattern `mask`. Several repaint a
        corner and start again.
        """
        m = self.m
        quad = self.quad
        for _ in range(64):
            mask = 0
            for lie in quad:
                mask = mask << 1 | (lie == chosen)
            green = 9 if chosen == 1 else 0
            if mask == 0:
                return m[TILE_BY_LIE + other]
            if mask in _PLAIN:
                block, repaint = _PLAIN[mask]
                tile = m[block + 4 + self._matches(cell, block, chosen) + green]
                if tile:
                    return tile
                if repaint is None:
                    return m[TILE_BY_LIE + other]
                quad[repaint[0]] = quad[repaint[1]]
            elif mask in _PAIRED:
                block, first, second = _PAIRED[mask]
                pair = self._pair(cell, block, chosen)
                matches = self._matches(cell, block + 2, chosen)
                shared = m[SHARED_MATCHES + matches]
                if shared and not pair:
                    if shared & 1:
                        quad[first] = other
                    if shared & 2:
                        quad[second] = other
                        continue
                return m[block + 6 + matches + green]
            elif mask == 6:
                if self._pair(cell, DIAGONAL_PAIRS, chosen):
                    quad[3] = chosen
                elif self._pair(cell, DIAGONAL_PAIRS + 2, chosen) != 3:
                    quad[2] = other
                elif self._pair(cell, DIAGONAL_PAIRS + 4, chosen) != 3:
                    quad[1] = other
                else:
                    quad[0] = chosen
            elif mask == 9:
                if self._pair(cell, DIAGONAL_PAIRS, chosen) != 3:
                    quad[3] = other
                elif self._pair(cell, DIAGONAL_PAIRS + 2, chosen):
                    quad[2] = chosen
                elif self._pair(cell, DIAGONAL_PAIRS + 4, chosen):
                    quad[1] = chosen
                else:
                    quad[0] = other
            else:
                return self._full_quad_tile(cell, chosen)
        raise RuntimeError("the 2x2 block never settled on a tile")

    def _full_quad_tile(self, cell: int, chosen: int) -> int:
        """`$A200`: all four corners alike; the neighbors on each side pick an edge."""
        m = self.m
        if chosen == Lie.ROUGH:
            return m[TILE_BY_LIE + chosen]
        index = 0
        for side in range(4):
            pair = self._pair(cell, FULL_QUAD_PAIRS + 2 * side, chosen)
            index = index << 1 | (pair != 0)
        table = FULL_QUAD_GREEN_TILES if chosen == 1 else FULL_QUAD_TILES
        return m[table + index] or m[TILE_BY_LIE + chosen]

    def palette(self, column: int, row: int) -> int:
        """
        `L9_A695`: the palette of the block under tile (`column`, `row`) of
        the ground. A column of -1 or 32, or row 10, reads a neighboring entry.
        """
        m = self.m
        index = (
            m[PALETTE_ROW_OFFSETS + ((row & MASK8) >> 1)] + ((column & MASK8) >> 1)
        ) & MASK8
        return m[GROUND_PALETTES + index]

    def fit_neighbors(self) -> None:
        """
        `L9_A348`: every ground tile, from the bottom right, refitted to the
        tiles above, left, below and right of it. A neighbor counts as open
        (a set bit) when its tile is not one that joins on that side, or when
        its block has a different palette.
        """
        cell = SCENE_TILE_MAP + MAP_ROWS * MAP_COLUMNS - 1  # $7AC5 + $20
        for row in range(9, -1, -1):
            for column in range(MAP_COLUMNS - 1, -1, -1):
                own_palette = self.palette(column, row)
                mask = self._refit(cell, column, row, own_palette)
                self._replace(cell, mask, own_palette)
                cell -= 1

    def _refit(self, cell: int, column: int, row: int, own_palette: int) -> int:
        m = self.m
        tile = m[cell]
        key = -1
        for index in range(NEIGHBOR_KEY_COUNT - 1, -1, -1):
            if m[NEIGHBOR_KEYS + index] == tile:
                key = index
                break
        if key < 0:
            return 0
        green = key >= 0x13
        if green:
            key -= 0x13

        def open_side(address, lists, lengths, column, row) -> int:
            there = m[address]
            start, length = lists[green], lengths[green]
            if there not in m[start : start + length]:
                return 1
            if row < 0 or green:
                return 0
            return int(self.palette(column, row) != own_palette)

        above = open_side(cell - 0x20, (0xA59A, 0xA5FC), (0x16, 0x15), column, row - 1)
        left = open_side(cell - 1, (0xA5B0, 0xA603), (0x1A, 0x19), column - 1, row)
        below = open_side(cell + 0x20, (0xA5E7, 0xA627), (0x15, 0x15), column, row + 1)
        right = open_side(cell + 1, (0xA5CA, 0xA61C), (0x2B, 0x19), column + 1, row)
        mask = above << 3 | left << 2 | below << 1 | right

        shift = 8 if green else 0
        if mask == 0x0F:
            new = ROUGH_TILE
        elif key < 5:
            new = m[0xA3D2 + mask + 2 * shift]
        else:
            folded = (mask >> 3) * 4 + (mask >> 2 & 1) * 2 + (mask & 1) + shift
            if key < 7:
                new = m[0xA408 + folded]
            elif key < 9:
                new = m[0xA423 + folded]
            elif key < 0x0C:
                new = m[0xA440 + folded]
            elif key < 0x0E:
                new = m[0xA463 + (mask & 7) + shift]
            elif key < 0x10:
                new = m[0xA47E + (mask & 7) + shift]
            else:
                new = m[0xA493 + (mask & 7) + shift]
        if new:
            m[cell] = new
        return mask

    def _replace(self, cell: int, mask: int, own_palette: int) -> None:
        """`L9_A644`: tiles that become another once fitted, off the fairway palette."""
        m = self.m
        if own_palette == 1:
            return
        tile = m[cell]
        for index in range(3, -1, -1):
            if m[EDGE_KEYS + index] == tile:
                if mask & 8:
                    m[cell] = m[EDGE_TILES + index]
                return
        for index in range(0x17, -1, -1):
            if m[NEIGHBOR_LISTS + index] == tile:
                m[cell] = m[REPLACEMENT_TILES + index]
                return

    def finish_horizon(self) -> None:
        """`L9_A315`: the top ground row's sky and water edges, where the palette is 0 or 3."""
        m = self.m
        for column in range(MAP_COLUMNS - 1, -1, -1):
            block = GROUND_PALETTES + (column >> 1)
            if m[block] not in (0, 3):
                continue
            tile = m[GROUND_TILES + column]
            if tile == SKY_TILE:
                new = 0x3C
            elif tile in (0x5A, 0x71, 0x72):
                new = 0x3D
            else:
                continue
            m[GROUND_TILES + column] = new
            m[block] = 0

    def block_bottom_rows(self) -> None:
        """`L9_A6A7`: from the green, the two bottom rows are one flat tile."""
        m = self.m
        if m[BALL_LIE_CLASS] == 1:
            start = SCENE_TILE_MAP + 22 * MAP_COLUMNS
            m[start : start + 2 * MAP_COLUMNS] = bytes([BLOCKED_TILE]) * 0x40

    def clear(self) -> None:
        """`$88A1`-`$88F3`: sky over the top rows, no trees, nothing standing anywhere."""
        m = self.m
        m[SCENE_TILE_MAP:GROUND_TILES] = bytes([SKY_TILE]) * (GROUND_ROW * MAP_COLUMNS)
        m[TREE_BANDS : TREE_BANDS + MAP_COLUMNS] = bytes(MAP_COLUMNS)
        depths = MAP_ROWS * MAP_COLUMNS
        m[SCENE_DEPTH_MAP : SCENE_DEPTH_MAP + depths] = b"\xff" * depths

    # --- 4. the trees -----------------------------------------------------

    def find_trees(self) -> None:
        """
        `L9_8FE4`: every 8 pixels of the box around the ball and the two far
        corners of the view, each tree tile is projected, at one or two points
        of the tile, and each screen column keeps the nearest.
        """
        m = self.m
        left = right = self.x
        top = bottom = self.y
        for side, ahead in TREE_BOX_CORNERS:
            corner_x, corner_y = self.offset(side, ahead)
            if corner_y & 0x8000:
                corner_y = 0
            if corner_x == 0xFF:
                corner_x = 0
            left, right = min(left, corner_x), max(right, corner_x)
            top, bottom = min(top, corner_y), max(bottom, corner_y)
        # The game keeps the box in WRAM, over what is left of the probe grid.
        m[TREE_BOX : TREE_BOX + 6] = bytes(
            [left, top & MASK8, top >> 8, right, bottom & MASK8, bottom >> 8]
        )

        y = top
        while True:
            x = left
            while True:
                self.tree_at(x, y)
                x += 8
                if x > MASK8 or x >= right:
                    break
            y = (y + 8) & MASK16
            if y >= bottom:
                break

    def tree_at(self, x: int, y: int) -> None:
        m = self.m
        _lie, tile = self.probe(x, y)
        if tile == 0x3E:
            tile = 0xC0
        elif not 0x9C <= tile < 0xC0:
            return
        index = tile - 0x9C
        shape = m[TREE_SHAPES + index]
        for point in range(m[TREE_COUNTS + index]):
            point_x = ((x & 0xF8) + m[TREE_SHAPE_X + shape + point]) & MASK8
            point_y = (
                y & 0xFF00 | ((y & 0xF8) + m[TREE_SHAPE_Y + shape + point]) & MASK8
            )
            self.note_tree(point_x, point_y)

    def note_tree(self, x: int, y: int) -> None:
        """`L9_9149`: the screen column and size band of one tree."""
        m = self.m
        found = self.project(x, y)
        if found.depth < 0x0E:
            return
        screen_y = found.screen_y & MASK8
        base = (screen_y + 3) & MASK8
        if (
            m[FLAG_SCREEN_Y] < 0xA0
            and m[GREEN_LEFT] <= found.screen_x < m[GREEN_RIGHT]
            and base >= m[FLAG_SCREEN_Y]
            and base - m[FLAG_SCREEN_Y] < 8
        ):
            # A tree standing on the green's row is drawn a little nearer.
            screen_y = (screen_y + 4) & MASK8
            self.registers = Projection(
                found.depth, found.screen_x, found.screen_y & 0xFF00 | screen_y
            )
        band = 0
        while screen_y >= m[BAND_THRESHOLDS + band]:
            band += 1
        band += 1
        if band >= 0x10:
            return
        column = found.screen_x >> 3
        if band < m[TREE_BANDS + column]:
            return
        m[TREE_BANDS + column] = band
        m[TREE_DEPTHS + column] = found.depth

    def draw_trees(self) -> None:
        """`L9_91C9`: the trees, smallest band first, right to left."""
        m = self.m
        for band in range(1, 0x10):
            for column in range(MAP_COLUMNS - 1, -1, -1):
                if m[TREE_BANDS + column] == band:
                    self._draw_trunk(band, column)
                    self._draw_canopy(band, column)

    def _draw_trunk(self, band: int, column: int) -> None:
        """
        `$91DD`-`$924E`: the trunk, down from the horizon row. Its tiles go
        only over rough or sky and only where the palette is not 0, but its
        depth goes in every cell of the strip.
        """
        m = self.m
        strip = self.word(TRUNK_POINTERS + 2 * (band - 1))
        cell = column
        row = 0
        while m[strip]:
            kind = bytes(m[TRUNK_TILES : TRUNK_TILES + 6]).rindex(m[strip])
            if self.palette(column, row):
                under = m[GROUND_TILES + cell]
                if under == SKY_TILE:
                    m[GROUND_TILES + cell] = m[TRUNK_TILES_ON_SKY + kind]
                elif under == ROUGH_TILE:
                    m[GROUND_TILES + cell] = m[TRUNK_TILES + kind]
            m[GROUND_DEPTHS + cell] = m[TREE_DEPTHS + column]
            strip += 1
            cell += MAP_COLUMNS
            row += 1

    def _draw_canopy(self, band: int, column: int) -> None:
        """
        `$92A7`-`$93E9`: the canopy, a list of (column, row, tile) for the
        tree's size. A cell over plain ground takes the tile. Over another
        tree's tiles the two are classed and the pair decides: keep, replace,
        or a blend. Over a tree tile with no class, one of four leaf tiles
        is drawn at random. Each cell takes the tree's depth, except that a
        canopy edge tile ($CC and up, flagged 0 at `$942B`) over tree tiles
        leaves the depth as it was.
        """
        m = self.m
        size = m[SIZE_BY_BAND + band - 1]
        columns = self.word(CANOPY_COLUMN_POINTERS + 2 * size)
        rows = self.word(CANOPY_ROW_POINTERS + 2 * size)
        tiles = self.word(CANOPY_TILE_POINTERS + 2 * size)
        index = -1
        while True:
            index += 1
            row = m[rows + index]
            if row & 0x80:
                return
            across = (m[columns + index] + column) & MASK8
            if across >= MAP_COLUMNS:
                continue
            place = across + self.word(TILE_MAP_ROW_OFFSETS + 2 * row)
            tile_cell = (SCENE_TILE_MAP + place) & MASK16
            depth_cell = (SCENE_DEPTH_MAP + place) & MASK16
            depth_before = m[DEPTH_BEFORE] = m[depth_cell]
            m[depth_cell] = m[TREE_DEPTHS + column]
            new = m[tiles + index]
            under = m[tile_cell]
            if under < 0xC0:
                m[tile_cell] = new
                continue
            if new >= 0xCC and not m[CANOPY_KEEPS_DEPTH + new]:
                m[depth_cell] = depth_before
            new_class = self._tile_class(new)
            under_class = self._tile_class(under)
            if new_class == 8 or under_class == 0x0C:
                continue
            if under_class == UNCLASSED:
                self.rng_state, drawn = lfsr_step(self.rng_state)
                m[tile_cell] = m[RANDOM_CANOPY_TILES + (drawn & 3)]
            elif new_class == UNCLASSED:
                m[tile_cell] = new
            elif under_class == 0x0B:
                if new_class < 4:
                    m[tile_cell] = 0xFA
                elif new_class < 8:
                    m[tile_cell] = 0xFB
            elif under_class == 0x0A:
                m[tile_cell] = 0xFD
            elif under_class == 9:
                m[tile_cell] = 0xE5 if new_class < 4 else 0xDB
            elif (new_class < 4) == (under_class < 4):
                if new_class not in (1, 5):
                    m[tile_cell] = new
            else:
                blend = m[OVERLAP_TILES + (new_class & 3) * 4 + (under_class & 3)]
                if not blend:
                    # `BNE` falls through to the next column: the canopy stops.
                    return
                m[tile_cell] = blend

    def _tile_class(self, tile: int) -> int:
        """`L9_93FE`."""
        m = self.m
        for index in range(0x1B, -1, -1):
            if m[TILE_CLASS_KEYS + index] == tile:
                return m[TILE_CLASSES + index]
        return UNCLASSED

    # --- 5. the sky -------------------------------------------------------

    def sky(self) -> None:
        """`L9_9785`: each block of cloud tiles, where all of its cells are still sky."""
        m = self.m
        for tiles, width, height, column, row in SKY_BLOCKS:
            start = SCENE_TILE_MAP + row * MAP_COLUMNS + column
            rows = [start + line * MAP_COLUMNS for line in range(height)]
            if any(
                tile != SKY_TILE for line in rows for tile in m[line : line + width]
            ):
                continue
            for line in rows:
                m[line : line + width] = m[tiles : tiles + width]
                tiles += width
