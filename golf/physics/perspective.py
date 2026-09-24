"""
The behind-the-golfer view: where the ball appears in it, and what it hits there.

While `ViewMode` is $80 the game draws the shot from behind the golfer, as a
perspective scene built before the swing (bank 9 $8829). Each frame,
`LD_BB6D` projects the ball into that scene with `LE87C`:

1. **Relative position**: ball minus the shot's origin ($B8-$BC), in 1/256
   pixels. More than 128 pixels away on either axis and the ball is out of view.
2. **Rotation** by the aim the scene was built along (`MaybeFineAimAnchor`,
   $BD) with `LE640`, into sideways (u) and forward (v) components.
3. **Perspective**: depth is forward + 15 pixels (0-255, else out of view);
   screen x is $90 plus 4u divided by depth/52; screen y is $BD minus $58 plus
   (5 x height - $1600) divided by the same.

`$C5` (depth, 0 when out of view) is also what ends this view: the main loop
switches to overhead when it reaches 0.

A tree is hit when the ball's screen pixel lands on a scene tile whose depth is
1-3 past the ball's and whose shape covers that pixel (`LE9C8`). The scene maps
come from the scene builder, which is not ported: see `PerspectiveScene`.
"""

from dataclasses import dataclass

from golf.physics.arith import MASK8, MASK16, MASK24, byte, is_negative
from golf.physics.state import Ball
from golf.physics.tables import PhysicsTables

VIEW_RANGE = 0x80
"""The ball must be within this many pixels of the origin on each axis."""
DEPTH_OFFSET = 0x0F
SCREEN_CENTRE_X = 0x90
DEPTH_DIVISOR = 0x0D


@dataclass(frozen=True)
class Projection:
    depth: int
    """`$C5`: 0 when the ball is out of view."""
    screen_x: int = 0
    """`$C6`."""
    screen_y: int = 0
    """`$C7/$C8`, 16 bits."""


OUT_OF_VIEW = Projection(0)


def rotate(dx: int, dy: int, angle: int, tables: PhysicsTables) -> tuple[int, int]:
    """
    `LE640` in its 16-bit mode: (dx, dy), each 16-bit two's complement, rotated
    by `angle`. Returns (u, v) = (dx cos - dy sin, dx sin + dy cos) as 24-bit
    two's complement, each product scaled by 1/256 like the table.
    """
    sin = tables.sin(angle)
    cos = tables.sin((angle + 0x40) & MASK8)

    def product(component: int, magnitude: int, sign_source: int) -> int:
        negative = is_negative(component, 16) != is_negative(sign_source, 8)
        size = (-component if is_negative(component, 16) else component) & MASK16
        scaled = (size * magnitude >> 8) & MASK16
        return -scaled & MASK24 if negative else scaled

    cos_sign = (angle + 0x40) & MASK8
    u = product(dx, cos, cos_sign) - product(dy, sin, angle)
    v = product(dx, sin, angle) + product(dy, cos, cos_sign)
    return u & MASK24, v & MASK24


def divide(numerator: int, divisor: int) -> int:
    """
    `LE84B`: 16-bit restoring division. The remainder test is a sign test on
    its high byte, so it matches true division only while the divisor is under
    $8000, which it always is here.
    """
    quotient = numerator & MASK16
    remainder = 0
    for _ in range(16):
        remainder = (remainder << 1 | quotient >> 15) & MASK16
        quotient = quotient << 1 & MASK16
        trial = (remainder - divisor) & MASK16
        if not is_negative(trial, 16):
            quotient |= 1
            remainder = trial
    return quotient


def project(
    ball: Ball, origin_x: int, origin_y: int, anchor: int, tables: PhysicsTables
) -> Projection:
    """
    `LE87C`. `origin_x` is $B8/$B9 (16 bits: pixel and fraction), `origin_y`
    $BA-$BC (24 bits), `anchor` is $BD.
    """
    dy = (origin_y - (ball.y >> 8 & MASK24)) & MASK24
    if not _within_view(byte(dy, 1), byte(dy, 2)):
        return OUT_OF_VIEW
    ball_x = ball.x >> 8
    dx = (ball_x - origin_x) & MASK16
    # The sign byte is the subtraction's borrow, not bit 15 of the result.
    if not _within_view(byte(dx, 1), 0xFF if ball_x < origin_x else 0):
        return OUT_OF_VIEW

    u, v = rotate(dx, dy & MASK16, anchor, tables)
    depth = byte(v, 1) + DEPTH_OFFSET
    if (depth >> 8) + byte(v, 2) & MASK8:
        return OUT_OF_VIEW
    depth &= MASK8

    scale = divide(depth << 8 | byte(v, 0), DEPTH_DIVISOR) >> 2

    # From here the sign is the 16-bit one ($74), not the 24-bit one.
    left = is_negative(u, 16)
    across = -u & MASK16 if left else u & MASK16
    # x4 by two shifts, but only the second shift's carry is tested: a set
    # bit 15 wraps silently.
    if across & 0x4000:
        return OUT_OF_VIEW
    across = across << 2 & MASK16
    offset = divide(across, scale)
    if offset > 0x7F:
        return OUT_OF_VIEW
    if left and offset:
        screen_x = SCREEN_CENTRE_X - offset
        if screen_x < 0:
            return OUT_OF_VIEW
    else:
        screen_x = SCREEN_CENTRE_X + offset
        if screen_x > MASK8:
            return OUT_OF_VIEW

    screen_y = _screen_y(ball, scale)
    if screen_y is None:
        return OUT_OF_VIEW
    return Projection(depth, screen_x, screen_y)


def _within_view(pixels: int, sign: int) -> bool:
    """`LDA #$80 / ADC pixels / LDA #0 / ADC sign`: pixels fits in -128..127."""
    return ((pixels + VIEW_RANGE >> 8) + sign) & MASK8 == 0


def _screen_y(ball: Ball, scale: int) -> int | None:
    """$E941-$E9C4: the height, times 5, less $1600, over the scale, from $BD."""
    lo = byte(ball.height, 2)
    hi = byte(ball.height, 3)
    lifted = hi << 9 | lo << 1
    if lifted > MASK16:
        lifted = 0xFF00 | (lo << 1 & MASK8)
    lifted = lifted * 5 & MASK16
    if is_negative(lifted, 16) and lifted >> 8 >= 0x96:
        return None
    lifted = (lifted - 0x1600) & MASK16
    size = -lifted & MASK16 if is_negative(lifted, 16) else lifted
    rise = divide(size, scale)
    if is_negative(lifted, 16):
        rise = -rise & MASK16
    return (0xBD - ((rise + 0x58) & MASK16)) & MASK16


# --- collisions with the scene ------------------------------------------------

SCENE_DEPTH_MAP = 0x7AE6
"""The builder's per-tile depth map: 32 tiles a row, $FF where nothing stands."""
SCENE_TILE_MAP = 0x77E6
"""The scene's tile map, same layout."""
TILE_MAP_ROW_OFFSETS = 0xE789
TREE_COLOUR_MASKS = 0xEAAC
"""2 bits a pixel, for scene tiles $CF and up."""
OBJECT_MASKS = 0xEA7C
"""1 bit a pixel, for scene tiles $C0-$CB."""
FIRST_TREE_TILE = 0xCF
LAST_OBJECT_TILE = 0xCC
WIDE_BALL_Y = 0x70
"""From this screen y down the ball is near enough to test two pixels."""


class PerspectiveScene:
    """
    The behind-the-golfer scene, as the builder left it in WRAM ($6000-$7FFF),
    plus the two PRG banks mapped while `LE9C8` runs (13 and the fixed bank),
    which its quirks end up reading from.

    `TileMapRowOffsetTable` has 24 rows; for a ball drawn on screen row 24 or
    lower (screen y 189 and up, which play does not reach) the offsets are the
    bytes after it and the maps point into the PRG banks or live internal RAM.
    Internal RAM is not captured, so those reads see zeros.
    """

    def __init__(self, wram: bytes, fixed_bank: bytes, physics_bank: bytes = b""):
        self.memory = bytearray(0x10000)
        self.memory[0x6000:0x8000] = wram
        if physics_bank:
            self.memory[0x8000:0xC000] = physics_bank
        self.memory[0xC000:0x10000] = fixed_bank

    def read(self, address: int) -> int:
        return self.memory[address & MASK16]

    def word(self, address: int) -> int:
        return self.read(address) | self.read(address + 1) << 8


def collide(projection: Projection, scene: PerspectiveScene, tree_hit: int) -> int:
    """
    `LE9C8`: the new `$0599` after testing the ball's screen pixel against the
    scene. A tile whose depth is 1-3 past the ball's is a hit if its shape
    covers the pixel; the value is the tile number, which the physics reads
    as how hard the hit is.
    """
    if projection.screen_y >> 8:
        return tree_hit
    probe_y = (projection.screen_y + 3) & MASK8
    row_offset = scene.word(TILE_MAP_ROW_OFFSETS + ((probe_y >> 2) & 0xFE))
    pointers = {
        "depth": (SCENE_DEPTH_MAP + row_offset) & MASK16,
        "tiles": (SCENE_TILE_MAP + row_offset) & MASK16,
    }
    samples = [projection.screen_x]
    if projection.screen_y >= WIDE_BALL_Y:
        samples = [(projection.screen_x - 3) & MASK8, (projection.screen_x + 3) & MASK8]
    for x in samples:
        tree_hit = _sample(x, probe_y & 7, projection.depth, scene, pointers, tree_hit)
    return tree_hit


def _sample(x, row, depth, scene, pointers, tree_hit) -> int:
    """`LEA12` for one screen pixel."""
    column = x >> 3
    tile_depth = scene.read(pointers["depth"] + column)
    if tile_depth == 0xFF:
        return tree_hit
    gap = (tile_depth - depth - 1) & MASK8
    if gap < 3:
        tree_hit = scene.read(pointers["tiles"] + column)
        if not _covers(x & 7, row, column, scene, pointers):
            tree_hit = 0
        return tree_hit
    if tile_depth <= depth:
        # In front of the ball: only decides whether the sprite is hidden.
        _covers(x & 7, row, column, scene, pointers)
    return tree_hit


def _covers(pixel: int, row: int, column: int, scene, pointers) -> bool:
    """
    `$EA47`: whether the scene tile's shape covers the pixel. It repoints the
    depth pointer ($20) at the mask table it uses and never puts it back, so a
    second sample reads its depth from there.
    """
    tile = scene.read(pointers["tiles"] + column)
    if tile >= FIRST_TREE_TILE:
        pointers["depth"] = TREE_COLOUR_MASKS
        base = TREE_COLOUR_MASKS + (((tile - FIRST_TREE_TILE) << 4 | row) & MASK16)
        low = scene.read(base) >> (7 - pixel) & 1
        high = scene.read(base + 8) >> (7 - pixel) & 1
        return (low | high << 1) < 3
    pointers["depth"] = OBJECT_MASKS
    if tile >= LAST_OBJECT_TILE:
        return False
    index = (tile - 0xC0) & MASK8
    if index >= 6:
        index = (index - 6) & MASK8
    mask = scene.read(OBJECT_MASKS + ((index << 3 | row) & 0x7FF))
    return bool(mask >> (7 - pixel) & 1)
