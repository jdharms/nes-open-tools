"""Standalone Practice Greens build; deliberately incompatible with randomizer stacks."""

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

from golf.core.asm6502 import assemble
from golf.core.compressor import GreensCompressor, TerrainCompressor
from golf.core.packing import pack_attributes
from golf.core.rom_utils import US_ROM_SHA1
from golf.core.rom_writer import RomWriter
from golf.formats.hole_data import HoleData
from golf.formats.putting_surface import PUTTING_SURFACE_TILES

from ..mercy_tap_in import mercy_tap_in_patches
from ..signpost_banner import remove_course_banner_patches
from ..skip_hole_celebrations import skip_hole_celebrations_patch
from ..skip_hole_signpost import skip_hole_signpost_patch

CODE_BANK = 2
CODE_START = 0x8400
CATALOG_START = 0x9000
# Only verified course data regions are reclaimed; graphics/code/tails survive.
GREEN_REGIONS = ((0, 0x81C0, 0xA000), (1, 0x81C0, 0xA1E6), (3, 0x81C0, 0xA774))
TERRAIN_START = 0xA000
ROUND_IDS = 0x7100


@dataclass
class Green:
    tiles: bytes
    pins: list[tuple[int, int]] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    compressed: bytes = b""
    bank: int = 0
    address: int = 0


def load_greens(root: Path) -> list[Green]:
    """Read precisely the eight vanilla courses, deduplicating exact tile grids."""
    paths = [root / name for name in ("japan", "us", "uk")]
    paths += [
        root / "jp" / name
        for name in ("jp_australia", "jp_france", "jp_hawaii", "jp_japan", "jp_uk")
    ]
    unique: dict[bytes, Green] = {}
    compressor = GreensCompressor()
    for directory in paths:
        for number in range(1, 19):
            path = directory / f"hole_{number:02d}.json"
            hole = HoleData()
            hole.load(path)
            tiles = bytes(tile for row in hole.greens for tile in row)
            if len(tiles) != 576:
                raise ValueError(f"{path}: expected a 24 by 24 green")
            green = unique.setdefault(tiles, Green(tiles))
            green.sources.append(str(path.relative_to(root)))
            for pin in hole.metadata["flag_positions"]:
                point = (pin["x_offset"], pin["y_offset"])
                if not all(0 <= value < 192 for value in point):
                    raise ValueError(f"Invalid vanilla pin: {path}: {point}")
                if point not in green.pins:
                    green.pins.append(point)
            if not green.compressed:
                green.compressed = compressor.compress(hole.greens)
    greens = list(unique.values())
    if not 18 <= len(greens) <= 128:
        raise ValueError("Runtime supports 18 to 128 unique greens")
    for green in greens:
        if not 1 <= len(green.pins) <= 32:
            raise ValueError("Runtime supports 1 to 32 vanilla pins per green")
        # The deterministic spawn scan must terminate for every possible pin.
        for px, py in green.pins:
            if not any(
                tile in PUTTING_SURFACE_TILES
                and (i % 24, i // 24) != (px // 8, py // 8)
                for i, tile in enumerate(green.tiles)
            ):
                raise ValueError("Green has no valid spawn outside the cup tile")
    return greens


@dataclass
class PracticeBuild:
    rom: bytes
    manifest: dict


def build_practice_greens(
    base: bytes, courses_root: Path, *, skip_signposts: bool = True
) -> PracticeBuild:
    """Build on a verified vanilla USA ROM, rejecting every overlapping write."""
    if hashlib.sha1(base).hexdigest() != US_ROM_SHA1:
        raise ValueError("Practice Greens requires the unmodified NES Open USA ROM")
    writer = RomWriter.from_bytes(base)
    claimed: set[int] = set()
    writes: list[dict] = []

    def put(bank: int, address: int, data: bytes, name: str) -> None:
        offset = bank * 0x4000 + address - (0xC000 if bank == 15 else 0x8000)
        span = set(range(offset, offset + len(data)))
        if claimed & span:
            raise ValueError(f"Overlapping practice writes: {name}")
        claimed.update(span)
        writer.write_prg(offset, data)
        writes.append(
            {"name": name, "bank": bank, "address": address, "size": len(data)}
        )

    def asm(bank: int, address: int, source: str, name: str) -> None:
        put(bank, address, assemble(source, origin=address).code, name)

    def far(symbol: str, size: int) -> bytes:
        target = program.symbol(symbol)
        return bytes((0x20, 0x72, 0xD3, CODE_BANK, target & 255, target >> 8)) + bytes(
            [0xEA]
        ) * (size - 6)

    def existing(patch) -> None:
        parts = getattr(patch, "patches", [patch])
        for part in parts:
            if not part.can_apply(writer):
                raise ValueError(f"Unexpected base bytes: {part.name}")
            bank, offset = divmod(part.prg_offset, 0x4000)
            put(
                bank,
                (0xC000 if bank == 15 else 0x8000) + offset,
                part.patched,
                part.name,
            )

    greens = load_greens(courses_root)
    region_index = 0
    next_address = GREEN_REGIONS[0][1]
    for green in greens:
        while next_address + len(green.compressed) > GREEN_REGIONS[region_index][2]:
            region_index += 1
            if region_index == len(GREEN_REGIONS):
                raise ValueError("All vanilla greens do not fit")
            next_address = GREEN_REGIONS[region_index][1]
        green.bank = GREEN_REGIONS[region_index][0]
        green.address = next_address
        put(green.bank, green.address, green.compressed, f"green_{len(writes)}")
        next_address += len(green.compressed)
    tables = base[16 + 3 * 0x4000 : 16 + 3 * 0x4000 + 448]
    for bank in (0, 1):
        put(bank, 0x8000, tables, "green_decompression_tables")

    count = len(greens)
    symbols = {"GREEN_COUNT": count}
    for i, name in enumerate(
        (
            "BANK_TABLE",
            "LO_TABLE",
            "HI_TABLE",
            "PIN_LO_TABLE",
            "PIN_HI_TABLE",
            "PIN_COUNT_TABLE",
        )
    ):
        symbols[name] = CATALOG_START + i * count
    pin_start = CATALOG_START + count * 6
    pins = bytearray()
    pin_addresses = []
    for green in greens:
        pin_addresses.append(pin_start + len(pins))
        pins.extend(value for point in green.pins for value in point)
    catalog = bytes(g.bank for g in greens)
    catalog += bytes(g.address & 255 for g in greens)
    catalog += bytes(g.address >> 8 for g in greens)
    catalog += bytes(p & 255 for p in pin_addresses)
    catalog += bytes(p >> 8 for p in pin_addresses)
    catalog += bytes(len(g.pins) for g in greens) + pins
    if CATALOG_START + len(catalog) > 0xA554:
        raise ValueError("Catalog exceeds reclaimed UK terrain")
    put(2, CATALOG_START, catalog, "green_catalog_and_vanilla_pins")
    source = Path(__file__).with_name("runtime.asm").read_text()
    program = assemble(source, origin=CODE_START, symbols=symbols)
    if program.end > CATALOG_START:
        raise ValueError("Runtime overlaps catalog")
    put(CODE_BANK, CODE_START, program.code, "practice_runtime")

    # Short synthetic hole: 30 rows of light rough, green well inside the field.
    terrain = TerrainCompressor().compress([[0x25] * 22 for _ in range(30)])
    attrs = pack_attributes([[0] * 11 for _ in range(15)])
    attrs = attrs.ljust(72, b"\x00")
    if TERRAIN_START + len(terrain) + len(attrs) > 0xA23E:
        raise ValueError("Synthetic terrain exceeds old Japan terrain region")
    put(0, TERRAIN_START, terrain + attrs, "shared_shallow_rough_terrain")
    for address, value in (
        (0xDD05, 2),
        (0xDD3B, 0),
        (0xDD71, 2),
        (0xDDA7, 0),
        (0xDE13, 1),
        (0xDE49, 72),
        (0xDE7F, 56),
        (0xDEB5, 84),
    ):
        put(15, address, bytes([value]) * 18, "course_metadata")
    put(15, 0xDEEB, bytes((160, 0)) * 18, "shared_tee_y")
    put(15, 0xDBC1, TERRAIN_START.to_bytes(2, "little") * 18, "shared_terrain_pointers")
    put(
        15,
        0xDC2D,
        (TERRAIN_START + len(terrain)).to_bytes(2, "little") * 18,
        "shared_attribute_pointers",
    )

    put(13, 0x80CE, far("RoundInit", 6), "select_18_greens_at_round_start")
    put(15, 0xDAF1, far("SetupGreen", 10), "load_round_pointer_and_pin")
    asm(15, 0xCA40, "lda $714A\njsr $D352\njsr $E3AC\nrts", "multi_bank_green_loader")
    asm(15, 0xDB60, "jsr $CA40\nnop\nnop\nnop\nnop\nnop", "green_loader_hook")
    asm(15, 0xDB21, "lda $7149", "selected_pin_y")
    asm(15, 0xDB3F, "lda $7148", "selected_pin_x")
    put(13, 0x8173, far("PlaceBall", 18), "random_pixel_spawn")
    put(13, 0xB3DC, far("StopBall", 7), "off_green_scores_five")
    for patch in mercy_tap_in_patches(255, 255)[2:]:
        existing(patch)
    existing(skip_hole_celebrations_patch())
    if skip_signposts:
        existing(skip_hole_signpost_patch())
    existing(remove_course_banner_patches())

    # Two menus only: start Practice Greens, then choose putting speed.
    put(12, 0x8BA0, bytes.fromhex("01 6C 8C"), "one_main_option")
    put(12, 0x8C6C, bytes((8, 14)) + b"PRACTICE GREENS\xff", "practice_course_name")
    put(12, 0x8ACE, bytes((1,)), "main_to_speed_menu")
    put(12, 0x8AD2, bytes((255, 255, 255)), "speed_menu_to_game")
    put(12, 0x8B0B, bytes.fromhex("C6 89"), "speed_choice_handler_pointer")
    asm(
        12,
        0x89C6,
        "lda $068D\nsta $6F9A\nlda #0\nsta $0102\nsta $04D7\nrts",
        "speed_choice_handler",
    )
    # Reuse unreachable MATCH/TOURNAMENT/CLUB HOUSE text for three speed choices.
    put(12, 0x8BDE, bytes.fromhex("03 B7 8B C4 8B D1 8B"), "speed_option_list")
    for address, row, label in (
        (0x8BB7, 14, b"SLOW"),
        (0x8BC4, 16, b"MEDIUM"),
        (0x8BD1, 18, b"FAST"),
    ):
        put(12, address, bytes((12, row)) + label + b"\xff", "speed_option_text")
    # Menus still share PLEASE SELECT; the second adds a specific speed header.
    put(12, 0x8B39, bytes.fromhex("57 8C"), "speed_header_pointer")
    put(12, 0x8C5C, bytes((4, 12)) + b"PUTT SPEED\xff", "speed_header_text")
    asm(13, 0x804F, "lda #0\nsta $068F\nnop", "skip_intro_and_clear_cancel_state")
    put(13, 0x8535, bytes([0xEA]) * 6, "skip_round_end_dialogue")

    # Course 0 scorecard: exact name and totals, without an automatic COURSE suffix.
    from ..scorecard_course_name import title_font_tiles

    text = "PRACTICE GREENS"
    descriptor = bytes((0x69, 0x20, len(text), 1)) + title_font_tiles(text)
    put(2, 0xAFC8, descriptor, "scorecard_practice_name")
    put(2, 0xB9F0, bytes([0xFF]) * 8, "scorecard_name_palette")
    put(2, 0xAF33, bytes((0x40,)), "scorecard_yards_thousands")
    for address, value in ((0xAF71, 3), (0xAF74, 6), (0xAF77, 0)):
        put(2, address, bytes([value]) * 3, "scorecard_360_yards")
    put(2, 0xB9BF, bytes.fromhex("43 46"), "scorecard_total_par_36")

    return PracticeBuild(
        bytes(writer.rom_data),
        {
            "version": 1,
            "skip_signposts": skip_signposts,
            "vanilla_holes": sum(len(g.sources) for g in greens),
            "unique_greens": count,
            "compressed_green_bytes": sum(len(g.compressed) for g in greens),
            "runtime_symbols": program.symbols,
            "writes": writes,
            "greens": [
                {
                    "id": i,
                    "sources": g.sources,
                    "bank": g.bank,
                    "address": g.address,
                    "compressed_bytes": len(g.compressed),
                    "pins": g.pins,
                }
                for i, g in enumerate(greens)
            ],
        },
    )
