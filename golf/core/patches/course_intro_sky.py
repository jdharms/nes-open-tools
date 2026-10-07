"""
Course intro sky: replace the course name on the intro scene with Mario Open's clouds.

Mario Open Golf shows the same landscape with no course name, its sky filled with
cloud instead (docs/course_intro_scene.md). This patch takes the top eight tile rows of
that sky and draws them where the US scene draws `JAPAN COURSE`, on every course.

The raster split stays at tile row 8, so nothing about the scene's code, its sprite 0
or its timing changes. Rows 8-29 are the US nametable's own: rows 8, 9 and 11 are
pixel for pixel what Mario Open shows there, and row 10 differs by 33 pixels of cloud.

What gets rewritten, all data:

  letters stream    bank 8  $9F0D-$A451   the Japan-only stream of the table at $9BDB,
                                          now the sky tiles the shared stream lacks
  nametable         bank 8  $B728-$B91A   the Japan nametable's stream, rows 0-7 new
  tile pointers     bank 12 $96A9-$96AC   US and UK -> $9BDB
  nametable ptrs    bank 12 $96AF-$96B2   US and UK -> $B723

The table at `$9BDB` loads two streams to PPU `$0000`. The first, shared with the US
and UK table, holds the small mode-text font and 30 cloud tiles (tiles `$00`-`$4A`) and
is left alone: sprite 0 is one pixel of its tile `$1B`. The second held the letters,
from tile `$4B`. Mario Open's eight rows use 98 distinct tiles, 27 of which the shared
stream already has, so the second stream becomes the other 71 and the rows are
renumbered to match. The US and UK tables and nametables are left in place with nothing
pointing at them.

The mode-text row (`18HOLE TOURNAMENT` and the like, PPU `$20E0`) still draws in its
modes, but its 32 tiles include the US scene's row 7 clouds, which do not line up with
the new row 6. `menu_trim` leaves only stroke play, which never writes that row.

The patch draws whatever `Sky` it is given: any eight opaque tile rows work the same
way. `read_sky_image` takes one from an image, and `MARIO_OPEN_SKY_IMAGE` is Mario
Open's, checked in so that a build needs no second ROM. `golf-intro-sky` writes that
image from the Mario Open ROM (`read_mario_open_sky`, `write_sky_image`).
"""

from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from golf.core import rom_utils
from golf.core.graphics_codec import VideoMemory, compress_stream, load_graphics_table
from golf.core.palettes import NES_SYSTEM_PALETTE
from golf.core.rom_writer import RomWriter

from .base import PatchError, ROMPatch

GRAPHICS_BANK = 8
LETTERS_TABLE_ADDR = 0x9BDB  # CourseIntroJapanLettersChrTable
LETTERS_STREAM_ADDR = 0x9F0D  # CourseIntroJapanLettersChrStreams
LETTERS_STREAM_END = 0xA452  # the US and UK table
NAMETABLE_TABLE_ADDR = 0xB723  # CourseIntroJapanNametableTable
NAMETABLE_STREAM_ADDR = 0xB728
NAMETABLE_STREAM_END = 0xB91B  # the US nametable table

SCENE_BANK = 12
TILE_PTR_TABLE_ADDR = 0x96A7  # CourseIntroTilePtrTable, by course
NAMETABLE_PTR_TABLE_ADDR = 0x96AD  # CourseIntroNametablePtrTable, by course
VANILLA_TILE_PTRS = bytes.fromhex("DB9B 52A4 52A4")
VANILLA_NAMETABLE_PTRS = bytes.fromhex("23B7 1BB9 04BB")

#: the first tile the letters stream writes; the shared stream ends just below it
FIRST_FREE_TILE = 0x4B
#: the portrait tiles load at PPU $0C00
TILE_LIMIT = 0xC0
SKY_ROWS = 8  # the raster split: rows 0-7 draw from pattern table $0000
ROW_WIDTH = 32
NAMETABLE_SIZE = 0x400
#: colors 1-3 of background palette 0 (bank 12 `$9778`), which every sky cell uses:
#: cloud shade, cloud white, sky
SKY_COLORS = (0x3C, 0x30, 0x21)

# Mario Open (mario_open_jp.nes), bank 8: sky tiles to PPU $0000, and the nametable
JP_SKY_CHR_TABLE = (8, 0x9D1A)
JP_NAMETABLE_TABLE = (8, 0xB13B)

#: Mario Open's sky as `write_sky_image` draws it, 256x64
MARIO_OPEN_SKY_IMAGE = Path(__file__).parent / "data" / "course_intro_sky.png"


@dataclass(frozen=True)
class Sky:
    """The top `SKY_ROWS` tile rows of a scene, as tile patterns."""

    #: 16-byte patterns, one per nametable cell, row by row
    cells: tuple[bytes, ...]

    def __post_init__(self) -> None:
        if len(self.cells) != SKY_ROWS * ROW_WIDTH:
            raise ValueError(
                f"a sky is {SKY_ROWS * ROW_WIDTH} cells, not {len(self.cells)}"
            )
        for pattern in self.cells:
            if len(pattern) != 16:
                raise ValueError("a tile pattern is 16 bytes")
            # Sprite 0 only registers a hit over an opaque background pixel, and the
            # scene waits for that hit every frame.
            if any((pattern[y] | pattern[y + 8]) != 0xFF for y in range(8)):
                raise ValueError("a sky tile has a transparent pixel")


def read_mario_open_sky(jp_rom) -> Sky:
    """The sky of Mario Open's course intro scene, from a reader on that ROM."""
    vram = VideoMemory()
    load_graphics_table(jp_rom, *JP_SKY_CHR_TABLE, vram)
    load_graphics_table(jp_rom, *JP_NAMETABLE_TABLE, vram)
    return Sky(
        tuple(
            bytes(vram.data[tile * 16 : tile * 16 + 16])
            for tile in vram.data[0x2000 : 0x2000 + SKY_ROWS * ROW_WIDTH]
        )
    )


def read_sky_image(path: Path | str) -> Sky:
    """The sky drawn in the top eight tile rows of a 256-pixel-wide image of the scene.

    Every pixel there has to be one of `SKY_COLORS` as `NES_SYSTEM_PALETTE` shows it.
    The rest of the image, if it is a whole screen, is not read.
    """
    with Image.open(path) as image:
        rgb = image.convert("RGB")
    if rgb.width != ROW_WIDTH * 8 or rgb.height < SKY_ROWS * 8:
        raise ValueError(
            f"{path}: a sky image is {ROW_WIDTH * 8} pixels wide and at least "
            f"{SKY_ROWS * 8} tall, not {rgb.width}x{rgb.height}"
        )
    # keyed by whatever getpixel returns, which for an RGB image is a 3-tuple
    values: dict[object, int] = {
        NES_SYSTEM_PALETTE[color]: value for value, color in enumerate(SKY_COLORS, 1)
    }
    cells = []
    for row in range(SKY_ROWS):
        for col in range(ROW_WIDTH):
            pattern = bytearray(16)
            for y in range(8):
                for x in range(8):
                    at = (col * 8 + x, row * 8 + y)
                    pixel = rgb.getpixel(at)
                    if pixel not in values:
                        raise ValueError(
                            f"{path}: the pixel at {at} is {pixel}, not one of the "
                            "sky palette's three colors"
                        )
                    pattern[y] |= (values[pixel] & 1) << (7 - x)
                    pattern[y + 8] |= (values[pixel] >> 1) << (7 - x)
            cells.append(bytes(pattern))
    return Sky(tuple(cells))


def write_sky_image(sky: Sky, path: Path | str) -> None:
    """Draw `sky` as a 256x64 image that `read_sky_image` reads back."""
    image = Image.new("RGB", (ROW_WIDTH * 8, SKY_ROWS * 8))
    for cell, pattern in enumerate(sky.cells):
        row, col = divmod(cell, ROW_WIDTH)
        for y in range(8):
            for x in range(8):
                low = pattern[y] >> (7 - x) & 1
                high = pattern[y + 8] >> (7 - x) & 1
                color = NES_SYSTEM_PALETTE[SKY_COLORS[(high << 1 | low) - 1]]
                image.putpixel((col * 8 + x, row * 8 + y), color)
    image.save(path)


class _Reader:
    """`read_switched` over a RomWriter, which is what `load_graphics_table` reads."""

    def __init__(self, rom_writer: RomWriter) -> None:
        self.rom_writer = rom_writer

    def read_switched(self, cpu_addr: int, bank: int, length: int = 1) -> bytes:
        return self.rom_writer.read_prg(
            rom_utils.cpu_to_prg_switched(cpu_addr, bank), length
        )


class CourseIntroSkyPatch(ROMPatch):
    """Draw `sky` over the course name on the course intro scene."""

    name = "course_intro_sky"
    description = "Replace the course name on the course intro scene with open sky"

    def __init__(self, sky: Sky) -> None:
        self.sky = sky

    def _writes(self, rom_writer: RomWriter) -> list[tuple[int, int, bytes]]:
        """(bank, CPU address, bytes) for each write, from the ROM as it stands.

        Everything read here is something the patch leaves as it found it - the
        shared stream's tiles and nametable rows 8-29 - so the answer is the same
        before and after applying.
        """
        rom = _Reader(rom_writer)
        _, vram = load_graphics_table(rom, GRAPHICS_BANK, LETTERS_TABLE_ADDR)
        tiles = {
            bytes(vram.data[tile * 16 : tile * 16 + 16]): tile
            for tile in reversed(range(FIRST_FREE_TILE))
        }
        added = []
        for pattern in self.sky.cells:
            if pattern not in tiles:
                tiles[pattern] = FIRST_FREE_TILE + len(added)
                added.append(pattern)
        if FIRST_FREE_TILE + len(added) > TILE_LIMIT:
            raise PatchError(
                f"{self.name}: the sky needs {len(added)} new tiles, and only "
                f"{TILE_LIMIT - FIRST_FREE_TILE} fit below the portrait"
            )
        letters = compress_stream(b"".join(added))

        _, vram = load_graphics_table(rom, GRAPHICS_BANK, NAMETABLE_TABLE_ADDR)
        nametable = bytearray(vram.data[0x2000 : 0x2000 + NAMETABLE_SIZE])
        nametable[: SKY_ROWS * ROW_WIDTH] = bytes(
            tiles[pattern] for pattern in self.sky.cells
        )
        nametable_stream = compress_stream(bytes(nametable))

        for what, stream, start, end in (
            ("tile", letters, LETTERS_STREAM_ADDR, LETTERS_STREAM_END),
            (
                "nametable",
                nametable_stream,
                NAMETABLE_STREAM_ADDR,
                NAMETABLE_STREAM_END,
            ),
        ):
            if len(stream) > end - start:
                raise PatchError(
                    f"{self.name}: the {what} stream is {len(stream)} bytes, and "
                    f"${start:04X}-${end - 1:04X} holds {end - start}"
                )
        tile_ptr = LETTERS_TABLE_ADDR.to_bytes(2, "little")
        nametable_ptr = NAMETABLE_TABLE_ADDR.to_bytes(2, "little")
        return [
            (GRAPHICS_BANK, LETTERS_STREAM_ADDR, letters),
            (GRAPHICS_BANK, NAMETABLE_STREAM_ADDR, nametable_stream),
            (SCENE_BANK, TILE_PTR_TABLE_ADDR + 2, tile_ptr * 2),
            (SCENE_BANK, NAMETABLE_PTR_TABLE_ADDR + 2, nametable_ptr * 2),
        ]

    @staticmethod
    def _read(rom_writer: RomWriter, bank: int, cpu_addr: int, length: int) -> bytes:
        return rom_writer.read_prg(
            rom_utils.cpu_to_prg_switched(cpu_addr, bank), length
        )

    def can_apply(self, rom_writer: RomWriter) -> bool:
        return (
            self._read(rom_writer, SCENE_BANK, TILE_PTR_TABLE_ADDR, 6)
            == VANILLA_TILE_PTRS
            and self._read(rom_writer, SCENE_BANK, NAMETABLE_PTR_TABLE_ADDR, 6)
            == VANILLA_NAMETABLE_PTRS
        )

    def is_applied(self, rom_writer: RomWriter) -> bool:
        if self._read(rom_writer, SCENE_BANK, TILE_PTR_TABLE_ADDR, 6) != (
            VANILLA_TILE_PTRS[:2] * 3
        ):
            return False
        return all(
            self._read(rom_writer, bank, cpu_addr, len(data)) == data
            for bank, cpu_addr, data in self._writes(rom_writer)
        )

    def apply(self, rom_writer: RomWriter) -> None:
        if self.is_applied(rom_writer):
            return
        if not self.can_apply(rom_writer):
            raise PatchError(
                f"Cannot apply patch '{self.name}': the course intro pointer tables "
                "are not the vanilla ones"
            )
        for bank, cpu_addr, data in self._writes(rom_writer):
            rom_writer.write_switched(cpu_addr, bank, data)


def course_intro_sky_patch(sky: Sky) -> CourseIntroSkyPatch:
    """Draw `sky` (`read_mario_open_sky`, `read_sky_image`) over the intro's course name."""
    return CourseIntroSkyPatch(sky)
