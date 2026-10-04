"""
Data regions the repository already knows how to find, as PRG byte ranges.

The dumpers, renderers and patches each locate their own data - graphics
tables, course terrain and greens, the decompression tables - but that
knowledge lives in code, not in the label file. This module gathers it into one
list of `KnownRegion`s so it can be compared against the `.mlb` and written
into it as range labels, which is what lets `golf-rom-peek trace` and `disasm`
tell data from code.

Every region is measured from the ROM, not assumed: a graphics table's extent
comes from decoding it, a hole's terrain from its start and end pointers, its
greens from how many bytes the decompressor reads.

Graphics tables are found three ways:

- the inline `(bank, address)` after every `JSR LoadCompressedGraphics` the
  trace reached;
- `GRAPHICS_POINTER_TABLES`, the pointer tables that feed
  `LoadCompressedGraphicsFromPtr` (`$D684`) with a fixed bank;
- the tables `golfer_sprites` and `signpost` name directly.
"""

from dataclasses import dataclass

from golf.core import golfer_sprites, rom_utils, signpost
from golf.core.decompressor import GreensDecompressor, TerrainDecompressor
from golf.core.graphics_codec import load_graphics_table
from golf.core.mlb_labels import Label
from golf.core.object_script import (
    OBJECT_DATA_END,
    RECORD_POINTER_TABLES,
    TABLE_BANK,
    ObjectWalk,
    bank_read,
    bank_word,
    metasprite_length,
)
from golf.core.palettes import ATTR_TOTAL_BYTES
from golf.core.rom_trace import OPCODE, TraceResult
from golf.core.rom_utils import PRG_BANK_SIZE
from golf.core.text_script import (
    SCRIPT_BANK,
    SCRIPT_POINTER_TABLES,
    WINDOW_GEOMETRY_TABLE,
    ScriptWalk,
)

LOAD_COMPRESSED_GRAPHICS = 0xD45F


@dataclass(frozen=True)
class KnownRegion:
    """A run of PRG bytes whose contents the repository can account for."""

    start: int  # PRG offset of the first byte
    end: int  # PRG offset of the last byte (inclusive, as in the .mlb)
    kind: str
    name: str | None  # a proposed label name, when the purpose is known
    comment: str
    bank: int
    cpu: int
    table: int | None = None  # streams of one table: that table's header prg

    @property
    def length(self) -> int:
        return self.end - self.start + 1


def _region(bank, cpu, length, kind, name, comment) -> KnownRegion:
    start = _prg(bank, cpu)
    return KnownRegion(start, start + length - 1, kind, name, comment, bank, cpu)


def _prg(bank: int, cpu: int) -> int:
    if cpu >= 0xC000:
        return rom_utils.cpu_to_prg_fixed(cpu)
    return rom_utils.cpu_to_prg_switched(cpu, bank)


# --- Graphics tables ----------------------------------------------------


@dataclass(frozen=True)
class GraphicsPointerTable:
    """Words naming graphics tables in `target_bank`, read by $D684's callers."""

    bank: int
    cpu: int
    count: int
    target_bank: int
    why: str


# The count of each comes from the indices its loaders use, not from where the
# words stop looking like addresses.
GRAPHICS_POINTER_TABLES = (
    GraphicsPointerTable(12, 0x96A7, 3, 8, "CourseIntroTilePtrTable, by course"),
    GraphicsPointerTable(12, 0x96AD, 3, 8, "CourseIntroNametablePtrTable, by course"),
    GraphicsPointerTable(
        12, 0x96C7, 7, 8, "CourseIntroPortraitGfxPtrTable, by portrait"
    ),
    GraphicsPointerTable(
        9, 0xBE56, 5, 7, "loaded at bank 9 $BC41 with X = 0, 2, 4, 6, 8"
    ),
)


def graphics_table_refs(rom, result: TraceResult) -> dict[tuple[int, int], str]:
    """Every (bank, address) of a graphics table, and where it was found."""
    data = rom.read_prg(0, rom.prg_size)
    refs: dict[tuple[int, int], str] = {}
    lo, hi = LOAD_COMPRESSED_GRAPHICS & 0xFF, LOAD_COMPRESSED_GRAPHICS >> 8
    for prg in range(len(data) - 5):
        if (
            result.marks[prg] == OPCODE
            and data[prg] == 0x20
            and data[prg + 1] == lo
            and data[prg + 2] == hi
        ):
            bank, addr = data[prg + 3], data[prg + 4] | (data[prg + 5] << 8)
            site_bank, site = prg // PRG_BANK_SIZE, _cpu_of(prg)
            refs.setdefault(
                (bank, addr), f"LoadCompressedGraphics at bank {site_bank} ${site:04X}"
            )
    for table in GRAPHICS_POINTER_TABLES:
        base = _prg(table.bank, table.cpu)
        for i in range(table.count):
            addr = data[base + 2 * i] | (data[base + 2 * i + 1] << 8)
            refs.setdefault(
                (table.target_bank, addr),
                f"entry {i} of bank {table.bank} ${table.cpu:04X} ({table.why})",
            )
    for bank, addr in golfer_sprites.GOLFER_CHR_TABLES:
        refs.setdefault((bank, addr), "golfer_sprites.GOLFER_CHR_TABLES")
    for tables in golfer_sprites.CLUB_CHR_TABLES.values():
        for bank, addr in tables:
            refs.setdefault((bank, addr), "golfer_sprites.CLUB_CHR_TABLES")
    for addr in signpost.CHR_TABLES:
        refs.setdefault((signpost.CHR_BANK, addr), "signpost.CHR_TABLES")
    return refs


def _cpu_of(prg: int) -> int:
    if prg >= rom_utils.FIXED_BANK_PRG_START:
        return 0xC000 + (prg - rom_utils.FIXED_BANK_PRG_START)
    return 0x8000 + prg % PRG_BANK_SIZE


def _ppu_kind(dest: int) -> tuple[str, str]:
    """What a table writes, as (prose, label-name word)."""
    if dest < 0x2000:
        return "pattern tiles", "Chr"
    if dest < 0x3F00:
        return "nametable", "Nametable"
    return "palette", "Palette"


def _graphics_name(kind: str, what: str, bank: int, cpu: int) -> str:
    """`ChrGraphicsTable7BAD5`: the bank as one hex digit, as in code stubs."""
    return f"{kind}Graphics{what}{bank:X}{cpu:04X}"


def graphics_regions(rom, result: TraceResult) -> list[KnownRegion]:
    """Graphics bytes as runs: a table's header with its own streams, or shared streams.

    A table's header (destination, count, stream pointers) is usually followed
    by its own streams, but tables also share streams: `$9309` and `$930E` in
    bank 6 both decode the stream at `$9315`. Each byte is tagged with the
    tables that read it, and a run ends wherever that set changes or another
    header begins, so no label holds bytes that belong to a different table.
    """
    readers: list = [None] * rom.prg_size  # prg -> frozenset of table names
    headers: dict[int, tuple[str, str]] = {}  # header prg -> (comment, kind)
    kinds: dict[str, str] = {}  # table name -> kind
    header_of: dict[str, int] = {}  # table name -> header prg
    for (bank, addr), found in sorted(graphics_table_refs(rom, result).items()):
        if not 0x8000 <= addr < 0xC000:
            continue
        table, _ = load_graphics_table(rom, bank, addr)
        tag = f"${addr:04X}"
        header = _prg(bank, addr)
        prose, kind = _ppu_kind(table.dest_ppu_addr)
        kinds[tag] = kind
        header_of[tag] = header
        count = len(table.streams)
        headers[header] = (
            f"graphics table, {count} stream{'s' if count != 1 else ''} of {prose} "
            f"to PPU ${table.dest_ppu_addr:04X}; {found}",
            kind,
        )
        for prg in range(header, header + 3 + 2 * count):
            readers[prg] = frozenset({tag})
        for stream in table.streams:
            first = _prg(bank, stream.cpu_addr)
            for prg in range(first, first + stream.compressed_length):
                readers[prg] = (readers[prg] or frozenset()) | {tag}

    regions = []
    prg = 0
    while prg < len(readers):
        if readers[prg] is None:
            prg += 1
            continue
        start, owners = prg, readers[prg]
        prg += 1
        while (
            prg < len(readers)
            and readers[prg] == owners
            and prg not in headers
            and prg % PRG_BANK_SIZE
        ):
            prg += 1
        bank, cpu = start // PRG_BANK_SIZE, _cpu_of(start)
        table = None
        if start in headers:
            comment, kind = headers[start]
            name = _graphics_name(kind, "Table", bank, cpu)
        else:
            tables = sorted(owners)
            kind = kinds[tables[0]]
            shared = "shared by the tables" if len(tables) > 1 else "of the table"
            comment = f"graphics streams {shared} at {', '.join(tables)}"
            name = _graphics_name(kind, "Streams", bank, cpu)
            if len(tables) == 1:
                table = header_of[tables[0]]
        regions.append(
            KnownRegion(start, prg - 1, "graphics", name, comment, bank, cpu, table)
        )
    return regions


# --- Course data --------------------------------------------------------


def course_regions(rom) -> list[KnownRegion]:
    """Terrain plus attributes per course, the greens block, and their tables."""
    regions = []
    terrain = TerrainDecompressor(rom)
    for course_idx, course in enumerate(rom_utils.COURSES):
        bank = rom.read_fixed_byte(rom_utils.TABLE_COURSE_BANK_TERRAIN + course_idx)
        first = course_idx * rom_utils.HOLES_PER_COURSE
        starts, ends = [], []
        for hole in range(first, first + rom_utils.HOLES_PER_COURSE):
            start = rom.read_fixed_word(rom_utils.TABLE_TERRAIN_START_PTR + 2 * hole)
            end = rom.read_fixed_word(rom_utils.TABLE_TERRAIN_END_PTR + 2 * hole)
            rows = len(terrain.decompress(rom.read_switched(start, bank, end - start)))
            # The game copies a 72-byte attribute window but a hole only reads
            # the rows it has; past a course's last hole the rest is other data.
            attr_rows = (rows + 1) // 2
            starts.append(start)
            ends.append(end + min(ATTR_TOTAL_BYTES, (attr_rows + 1) // 2 * 6))
        lo, hi = min(starts), max(ends)
        regions.append(
            _region(
                bank,
                lo,
                hi - lo,
                "course",
                f"{course['display_name']}CourseTerrainData",
                "18 holes of compressed terrain, each followed by the attribute "
                "bytes its height uses; per-hole starts and ends in the fixed "
                "bank tables at $DBC1 and $DC2D",
            )
        )

    greens = GreensDecompressor(rom, 3)
    starts, ends = [], []
    for hole in range(rom_utils.TOTAL_HOLES):
        ptr = rom.read_fixed_word(rom_utils.TABLE_GREENS_PTR + 2 * hole)
        greens.decompress(rom.read_switched(ptr, 3, 0xC000 - ptr))
        starts.append(ptr)
        ends.append(ptr + greens.consumed)
    regions.append(
        _region(
            3,
            min(starts),
            max(ends) - min(starts),
            "course",
            "GreensCompressedData",
            "54 holes of compressed greens; per-hole starts in "
            "GreenCompressedDataPtrTable",
        )
    )

    tables = (
        (15, rom_utils.TABLE_HORIZ_TRANSITION, 224, "TerrainHorizTransitionTable"),
        (15, rom_utils.TABLE_VERT_CONTINUATION, 224, "TerrainVertContinuationTable"),
        (15, rom_utils.TABLE_DICTIONARY, 64, "TerrainDictionaryTable"),
        (3, 0x8000, 192, "GreensHorizTransitionTable"),
        (3, 0x80C0, 192, "GreensVertContinuationTable"),
        (3, 0x8180, 64, "GreensDictionaryTable"),
    )
    for bank, cpu, length, name in tables:
        regions.append(
            _region(
                bank,
                cpu,
                length,
                "course",
                name,
                "decompression table; see golf/core/compression.md",
            )
        )
    return regions


RESET_STUB = 0xBFF3


def padding_regions(rom) -> list[KnownRegion]:
    """The run of `$FF` that ends each switchable bank, before its reset stub.

    Nothing reads these as far as the trace can tell, but that is not proof,
    and several patches in `golf/core/patches/` already claim parts of them;
    the names say `Maybe` and the comment says to check before reusing one.
    """
    regions = []
    for bank in range(rom_utils.FIXED_BANK_PRG_START // PRG_BANK_SIZE):
        data = rom.read_switched(0x8000, bank, PRG_BANK_SIZE)
        end = RESET_STUB - 0x8000  # exclusive
        start = end
        while start > 0 and data[start - 1] == 0xFF:
            start -= 1
        if start < end:
            regions.append(
                _region(
                    bank,
                    0x8000 + start,
                    end - start,
                    "padding",
                    f"MaybeBank{bank}TailPadding",
                    "$FF fill up to the reset stub; the trace reaches no read of "
                    "it, which is not proof - check golf/core/patches/ before "
                    "reusing any",
                )
            )
    return regions


@dataclass
class LabelPlan:
    """How the known regions compare with a label file."""

    new: list[KnownRegion]  # bytes no range label covers yet
    widen: list[tuple[Label, KnownRegion]]  # a single-address label at the start
    inside: list[tuple[Label, KnownRegion]]  # single-address labels mid-region
    code: list[KnownRegion]  # regions the trace decoded as code: a contradiction
    overlaps: list[tuple[KnownRegion, KnownRegion]]  # two regions claim a byte
    labeled_bytes: int  # known bytes some range label already covers


def _streams_name(table_label: str) -> str | None:
    """`LuigiSpriteChrTable` -> `LuigiSpriteChrStreams`."""
    for suffix in ("Tables", "Table"):
        if table_label.endswith(suffix):
            return table_label[: -len(suffix)] + "Streams"
    return None


def _remainder_name(region: KnownRegion, start: int, result: TraceResult) -> str | None:
    """A name for the part of a region left after an existing label's span.

    The usual case is a graphics table whose header is labeled
    (`LuigiSpriteChrTable`) and whose streams follow: they become
    `LuigiSpriteChrStreams`.
    """
    before = result.data_names[start - 1]
    if region.kind == "graphics":
        if before is not None and _streams_name(before):
            return _streams_name(before)
        word = region.name[: region.name.index("Graphics")] if region.name else "Chr"
        return _graphics_name(word, "Streams", region.bank, _cpu_of(start))
    # A mechanical name ends in its bank and address; re-address it.
    suffix = f"{region.bank:X}{region.cpu:04X}"
    if region.name and region.name.endswith(suffix):
        return f"{region.name[: -len(suffix)]}{region.bank:X}{_cpu_of(start):04X}"
    return None


def plan_labels(regions: list[KnownRegion], labels, result: TraceResult) -> LabelPlan:
    """Subtract what range labels already cover; sort out the rest."""
    from golf.core.rom_analysis import is_data_range

    singles = {}
    for label, _ in labels.iter_merged():
        if label.type == "NesPrgRom" and not is_data_range(label):
            singles[label.start] = label
    plan = LabelPlan([], [], [], [], [], 0)
    ordered = sorted(regions, key=lambda r: r.start)
    plan.overlaps = [
        (a, b) for a, b in zip(ordered, ordered[1:], strict=False) if b.start <= a.end
    ]
    for region in regions:
        if any(result.marks[p] in (1, 2) for p in range(region.start, region.end + 1)):
            plan.code.append(region)
            continue
        # Split the region around bytes a range label already names.
        piece_start = None
        for prg in range(region.start, region.end + 2):
            free = prg <= region.end and result.data_names[prg] is None
            if prg <= region.end and not free:
                plan.labeled_bytes += 1
            if free and piece_start is None:
                piece_start = prg
            elif not free and piece_start is not None:
                name, comment = region.name, region.comment
                owner = result.data_names[region.table] if region.table else None
                if piece_start == region.start and owner is not None:
                    name = _streams_name(owner) or name
                    comment = f"the streams of {owner}"
                elif piece_start != region.start:
                    name = _remainder_name(region, piece_start, result)
                    before = result.data_names[piece_start - 1]
                    if before is not None and comment.startswith("graphics table, "):
                        comment = f"the streams of {before}: " + comment[16:]
                piece = KnownRegion(
                    piece_start,
                    prg - 1,
                    region.kind,
                    name,
                    comment,
                    region.bank,
                    _cpu_of(piece_start),
                )
                head = singles.get(piece_start)
                if head is not None:
                    plan.widen.append((head, piece))
                else:
                    plan.new.append(piece)
                plan.inside.extend(
                    (singles[p], piece)
                    for p in range(piece_start + 1, prg)
                    if p in singles
                )
                piece_start = None
    # Streams named after one label that covers several tables
    # (ClubSpriteChrTables) come out as adjacent pieces with the same name.
    merged: list[KnownRegion] = []
    for piece in plan.new:
        last = merged[-1] if merged else None
        if last and last.name == piece.name and last.end + 1 == piece.start:
            merged[-1] = KnownRegion(
                last.start,
                piece.end,
                last.kind,
                last.name,
                last.comment,
                last.bank,
                last.cpu,
                last.table,
            )
        else:
            merged.append(piece)
    plan.new = merged
    return plan


# --- Text scripts -------------------------------------------------------


def script_regions(walk: ScriptWalk) -> list[KnownRegion]:
    """The bytes the script walker read, cut at each entry point, and their tables."""
    runs: list[list[int]] = []  # [start, end] in CPU addresses
    for cpu in sorted(walk.covered):
        if runs and cpu == runs[-1][1] + 1 and cpu not in walk.entries:
            runs[-1][1] = cpu
        else:
            runs.append([cpu, cpu])
    regions = []
    for start, end in runs:
        comment = "text script for RunTextScript (bank 11 $9033)"
        if start in walk.entries:
            comment += f"; {walk.entries[start]}"
        regions.append(
            _region(
                SCRIPT_BANK,
                start,
                end - start + 1,
                "script",
                f"TextScript{SCRIPT_BANK:X}{start:04X}",
                comment,
            )
        )

    for table in SCRIPT_POINTER_TABLES:
        regions.append(
            _region(
                table.bank,
                table.cpu,
                2 * table.count,
                "script",
                f"TextScriptPtrTable{table.bank:X}{table.cpu:04X}",
                f"{table.count} bank 11 script pointers; {table.why}",
            )
        )
    if walk.windows:
        count = max(walk.windows) + 1
        regions.append(
            _region(
                SCRIPT_BANK,
                WINDOW_GEOMETRY_TABLE,
                4 * count,
                "script",
                "ScriptWindowGeometryTable",
                f"left, top, right, bottom for each of the {count} windows "
                "the scripts select with $F9",
            )
        )
    return regions


# --- Metasprites drawn directly ----------------------------------------

SPRITE_PTR = 0x45  # PointerToSpriteData
LDA_ABS_X, LDA_ABS_Y, LDA_IMM, STA_ZP = 0xBD, 0xB9, 0xA9, 0x85
MAX_SPLIT_TABLE = 64
RENDERER_REACH = 12  # instructions to look ahead from the pointer load

# Renderer -> its metasprite format. RenderMetasprite and RenderMetaspriteClipped
# read chunked metasprites (`metasprite_length`); RenderMetaspriteWithAttr a
# count byte and 3 bytes a sprite, with the attribute from $29.
CHUNKED, TRIPLES_ONLY = "chunked", "count + 3 per sprite"
RENDERERS = {0xFEBD: CHUNKED, 0xFDCE: CHUNKED, 0xFF38: TRIPLES_ONLY}


def _metasprite_size(data: bytes, form: str) -> int | None:
    if form == CHUNKED:
        return metasprite_length(data)
    return 1 + 3 * data[0] if data else None


def _renderer_after(rom_data: bytes, result: TraceResult, prg: int) -> str | None:
    """The format of the first renderer a straight run from `prg` calls."""
    for _ in range(RENDERER_REACH):
        prg = _next_opcode(result, prg)
        if prg >= len(rom_data) - 2:
            return None
        op = rom_data[prg]
        if op in (0x20, 0x4C):  # JSR, JMP
            target = rom_data[prg + 1] | rom_data[prg + 2] << 8
            if target in RENDERERS:
                return RENDERERS[target]
            if op == 0x4C:
                return None
        elif op in (0x60, 0x40):  # RTS, RTI
            return None
    return None


def _next_opcode(result: TraceResult, prg: int) -> int:
    prg += 1
    while prg < len(result.marks) and result.marks[prg] != OPCODE:
        prg += 1
    return prg


def metasprite_regions(rom, result: TraceResult) -> list[KnownRegion]:
    """Metasprites that switchable-bank code hands straight to the renderer.

    Two shapes load `PointerToSpriteData`: `LDA lo,X / STA $45 / LDA hi,X /
    STA $46` from split Lo/Hi tables, and the same with immediates. Split tables
    here are packed with no slack, so the distance from Lo to Hi is the entry
    count. Fixed-bank sites are left out: which bank their tables are in depends
    on the caller.
    """
    data = rom.read_prg(0, rom.prg_size)
    tables, singles = set(), {}  # entries carry the renderer's format
    for prg in range(rom_utils.FIXED_BANK_PRG_START - 12):
        if result.marks[prg] != OPCODE:
            continue
        store_lo = _next_opcode(result, prg)
        load_hi = _next_opcode(result, store_lo)
        store_hi = _next_opcode(result, load_hi)
        if not (
            data[store_lo] == STA_ZP
            and data[store_lo + 1] == SPRITE_PTR
            and data[store_hi] == STA_ZP
            and data[store_hi + 1] == SPRITE_PTR + 1
            and data[load_hi] == data[prg]
        ):
            continue
        bank, site = prg // PRG_BANK_SIZE, _cpu_of(prg)
        form = _renderer_after(data, result, store_hi)
        if form is None:
            continue
        if data[prg] in (LDA_ABS_X, LDA_ABS_Y):
            lo = data[prg + 1] | data[prg + 2] << 8
            hi = data[load_hi + 1] | data[load_hi + 2] << 8
            # One apart is a word table read with a stride, not split Lo/Hi
            # tables, and its length isn't knowable from here.
            if 1 < hi - lo <= MAX_SPLIT_TABLE:
                tables.add((bank, lo, hi - lo, site, form))
        elif data[prg] == LDA_IMM:
            ptr = data[prg + 1] | data[load_hi + 1] << 8
            singles.setdefault((bank, ptr), form)

    pieces: list[tuple[int, int, int, str, str]] = []  # bank, start, end, name, comment
    metas: dict[tuple[int, int], int] = {}  # (bank, start) -> end

    def metasprite(bank, ptr, form):
        if 0x8000 <= ptr < 0xC000:
            size = _metasprite_size(rom.read_switched(ptr, bank, 0x100), form)
            if size:
                metas[(bank, ptr)] = max(metas.get((bank, ptr), 0), ptr + size - 1)

    for bank, lo, count, site, form in sorted(tables):
        for half, base in (("Lo", lo), ("Hi", lo + count)):
            pieces.append(
                (
                    bank,
                    base,
                    base + count - 1,
                    f"MetaspritePtr{half}Table{bank:X}{base:04X}",
                    f"{count} metasprite pointers ({form}); loaded at ${site:04X}",
                )
            )
        for i in range(count):
            ptr = data[_prg(bank, lo + i)] | data[_prg(bank, lo + count + i)] << 8
            metasprite(bank, ptr, form)
    for (bank, ptr), form in singles.items():
        metasprite(bank, ptr, form)

    # One metasprite can start inside another's tail, so merge into runs.
    run = None
    for (bank, start), end in sorted(metas.items()) + [((-1, 0), 0)]:
        if run and bank == run[0] and start <= run[2] + 1:
            run[2] = max(run[2], end)
            continue
        if run:
            pieces.append(
                (
                    run[0],
                    run[1],
                    run[2],
                    f"Metasprites{run[0]:X}{run[1]:04X}",
                    "metasprites drawn directly by a metasprite renderer",
                )
            )
        run = [bank, start, end]
    return [
        _region(bank, start, end - start + 1, "metasprite", name, comment)
        for bank, start, end, name, comment in pieces
    ]


# --- Palettes -----------------------------------------------------------

LOAD_32_BYTES = 0xD80A  # Load32BytesToBuffer: inline word -> PaletteBuffer
PALETTE_SIZE = 32


def palette_regions(rom, result: TraceResult) -> list[KnownRegion]:
    """The 32-byte palettes traced code passes inline to `Load32BytesToBuffer`.

    A switchable-bank site's palette is in its own bank; a fixed-bank site
    naming `$8000-$BFFF` depends on its caller, so it is left out.
    """
    data = rom.read_prg(0, rom.prg_size)
    found: dict[tuple[int, int], int] = {}
    lo, hi = LOAD_32_BYTES & 0xFF, LOAD_32_BYTES >> 8
    for prg in range(len(data) - 4):
        if not (
            result.marks[prg] == OPCODE
            and data[prg] == 0x20
            and data[prg + 1] == lo
            and data[prg + 2] == hi
        ):
            continue
        cpu = data[prg + 3] | data[prg + 4] << 8
        bank = prg // PRG_BANK_SIZE
        if cpu >= 0xC000:
            bank = 15
        elif cpu < 0x8000 or bank == 15:
            continue
        found.setdefault((bank, cpu), prg)
    return [
        _region(
            bank,
            cpu,
            PALETTE_SIZE,
            "palette",
            f"PaletteData{bank:X}{cpu:04X}",
            f"32-byte palette set copied to PaletteBuffer by Load32BytesToBuffer at "
            f"${_cpu_of(site):04X}",
        )
        for (bank, cpu), site in sorted(found.items())
    ]


# --- Nametable descriptors ----------------------------------------------

# Entry -> transfer mode ($29): 0 normal, 1 repeat one byte, 2 no PPU address
# in the descriptor (the caller set $22/$23). See docs/menu_system.md.
DESCRIPTOR_WRITERS = {0xCE84: 0, 0xCE75: 1, 0xCE7E: 2}
DESCRIPTOR_SOURCE_POINTER, DESCRIPTOR_REPEAT = 0x80, 0x40


def descriptor_regions(rom, result: TraceResult) -> list[KnownRegion]:
    """The nametable descriptors traced code passes inline to WriteNametableTiles.

    A descriptor is a PPU address (not in mode 2), a byte of flags and width,
    a height, then either the data inline or, with bit 7, a pointer to it.
    The data is width x height bytes, read row by row whichever way it is
    drawn, or a single byte in repeat mode (mode 1, or bit 6 with inline
    data), since the source pointer then never advances.
    """
    data = rom.read_prg(0, rom.prg_size)
    found: dict[tuple[int, int], tuple[int, int]] = {}  # (bank, cpu) -> (mode, site)
    for prg in range(len(data) - 4):
        if result.marks[prg] != OPCODE or data[prg] != 0x20:
            continue
        mode = DESCRIPTOR_WRITERS.get(data[prg + 1] | data[prg + 2] << 8)
        if mode is None:
            continue
        cpu = data[prg + 3] | data[prg + 4] << 8
        bank = prg // PRG_BANK_SIZE
        if cpu >= 0xC000:
            bank = 15
        elif cpu < 0x8000 or bank == 15:
            continue  # RAM, or a switchable address whose bank is the caller's
        found.setdefault((bank, cpu), (mode, prg))

    regions = []
    sources: dict[tuple[int, int], tuple[int, list[str]]] = {}  # shared by several
    for (bank, cpu), (mode, site) in sorted(found.items()):
        at = _prg(bank, cpu)
        header = 2 if mode == 2 else 4
        flags, height = data[at + header - 2], data[at + header - 1]
        width = flags & 0x3F
        if not width or not height:
            continue
        dest = "" if mode == 2 else f" to PPU ${data[at] | data[at + 1] << 8:04X}"
        where = f"WriteNametableTiles at ${_cpu_of(site):04X}"
        if flags & DESCRIPTOR_SOURCE_POINTER:
            source = data[at + header] | data[at + header + 1] << 8
            regions.append(
                _region(
                    bank,
                    cpu,
                    header + 2,
                    "descriptor",
                    f"NametableDescriptor{bank:X}{cpu:04X}",
                    f"{width}x{height}{dest} from ${source:04X}; {where}",
                )
            )
            size = 1 if mode == 1 else width * height
            src_bank = 15 if source >= 0xC000 else bank
            if source >= 0x8000 and not (src_bank == 15 and source < 0xC000):
                old_size, users = sources.get((src_bank, source), (0, []))
                sources[(src_bank, source)] = (
                    max(old_size, size),
                    users + [f"${cpu:04X}"],
                )
        else:
            repeat = mode == 1 or flags & DESCRIPTOR_REPEAT
            size = 1 if repeat else width * height
            regions.append(
                _region(
                    bank,
                    cpu,
                    header + size,
                    "descriptor",
                    f"NametableDescriptor{bank:X}{cpu:04X}",
                    f"{width}x{height}{dest}{', one tile repeated' if repeat else ''}; "
                    f"{where}",
                )
            )
    for (bank, cpu), (size, users) in sorted(sources.items()):
        regions.append(
            _region(
                bank,
                cpu,
                size,
                "descriptor",
                f"NametableSourceData{bank:X}{cpu:04X}",
                f"tiles for the descriptor(s) at {', '.join(users)}",
            )
        )
    return regions


# --- CPU opponent shots -------------------------------------------------

OPPONENT_SHOT_BANK = 3
OPPONENT_COURSE_LO, OPPONENT_COURSE_HI = 0xA923, 0xA926  # per course, by CurrCourse
OPPONENT_CHOICE_TABLE = 0xA929  # 8 levels x 16: (level << 4 | random) -> choice * 2
OPPONENT_MATCH_LEVEL_TABLE = 0xA9A9  # tournament match: opponent * 4 | $6003
OPPONENT_CHOICES = 4  # shot lists per hole: 18 holes x 4 words per course
OPPONENT_SEED = 2  # each list starts with the RNG state to replay it under
REPLAY_RECORD = 5  # LoadReplayShotRecord's record


def opponent_shot_regions(rom, result: TraceResult) -> list[KnownRegion]:
    """The CPU opponents' prerecorded shots in bank 3, read by `$A869`.

    For the opponent's turn, `$A869` takes the course's table of 18 x 4 list
    pointers, picks one of the hole's four by skill level and a random nibble,
    and replays the list: an RNG seed, then one replay record per stroke. The
    lists are packed back to back, so each ends where the next begins; the last
    ends at the code after it.
    """
    bank = OPPONENT_SHOT_BANK

    def word(cpu):
        lo, hi = rom.read_switched(cpu, bank, 2)
        return lo | hi << 8

    courses = []
    for i, course in enumerate(rom_utils.COURSES):
        lo = rom.read_switched(OPPONENT_COURSE_LO + i, bank, 1)[0]
        hi = rom.read_switched(OPPONENT_COURSE_HI + i, bank, 1)[0]
        table = lo | hi << 8
        count = rom_utils.HOLES_PER_COURSE * OPPONENT_CHOICES
        lists = sorted({word(table + 2 * j) for j in range(count)})
        courses.append((course["display_name"], table, count, lists))

    regions = [
        _region(
            bank,
            OPPONENT_COURSE_LO,
            3,
            "opponent",
            "OpponentShotCourseLoTable",
            "per CurrCourse: the course's shot list pointer table, low byte",
        ),
        _region(
            bank,
            OPPONENT_COURSE_HI,
            3,
            "opponent",
            "OpponentShotCourseHiTable",
            "the same, high byte",
        ),
        _region(
            bank,
            OPPONENT_CHOICE_TABLE,
            128,
            "opponent",
            "OpponentShotChoiceTable",
            "by skill level * 16 + a random nibble at $A8E6; value >> 1 picks one of "
            "the hole's 4 shot lists",
        ),
        _region(
            bank,
            OPPONENT_MATCH_LEVEL_TABLE,
            20,
            "opponent",
            "OpponentMatchLevelTable",
            "tournament match play: the skill level, by opponent * 4 | SRAM $6003",
        ),
    ]
    starts = [table for _, table, _, _ in courses]
    for n, (name, table, count, lists) in enumerate(courses):
        regions.append(
            _region(
                bank,
                table,
                2 * count,
                "opponent",
                f"{name}OpponentShotListPtrTable",
                f"18 holes x {OPPONENT_CHOICES} shot list pointers, by hole * 8 + "
                "choice * 2",
            )
        )
        first = lists[0]
        if n + 1 < len(courses):
            end = starts[n + 1]
        else:
            end = first
            while result.marks[_prg(bank, end)] == 0 and end < 0xC000:
                end += 1
        regions.append(
            _region(
                bank,
                first,
                end - first,
                "opponent",
                f"{name}OpponentShotLists",
                f"{len(lists)} shot lists: a 2-byte RNG seed, then a "
                f"{REPLAY_RECORD}-byte replay record per stroke (LoadReplayShotRecord)",
            )
        )
    return regions


# --- Scene objects ------------------------------------------------------


def object_regions(rom, walk: ObjectWalk) -> list[KnownRegion]:
    """Record lists, and in banks 2 and 10 the sprite tables, metasprites, streams."""
    pieces: dict[tuple[int, int], tuple[int, str, str]] = {}  # (bank, start) -> ...

    def claim(bank, start, end, name, comment):
        key = (bank, start)
        if key not in pieces or pieces[key][0] < end:
            pieces[key] = (end, name, comment)

    for record in walk.records:
        base = record.cpu
        claim(
            record.bank,
            base,
            base + record.length - 1,
            f"ObjectRecords{record.bank:X}{base:04X}",
            f"scene object records; {record.found}",
        )

    for table in RECORD_POINTER_TABLES:
        claim(
            TABLE_BANK,
            table.cpu,
            table.cpu + 2 * len(table.counts) - 1,
            f"ObjectRecordPtrTable{TABLE_BANK:X}{table.cpu:04X}",
            f"{len(table.counts)} record lists for LF7EE; {table.why}",
        )
    for bank in {b for b, _ in walk.frames}:
        end, low, n = OBJECT_DATA_END[bank], OBJECT_DATA_END[bank], 0
        while 0x8000 + 2 * n < low:  # the id table runs up to what it points at
            word = bank_word(rom, bank, 0x8000 + 2 * n)
            if 0x8000 <= word < end:
                low = min(low, word)
            n += 1
        claim(
            bank,
            0x8000,
            0x8000 + 2 * n - 1,
            f"ObjectSpriteTable{bank:X}8000",
            "frame table per sprite id, read by LoadObjectSpriteAttr ($FD54) "
            "with this bank in $3A",
        )
    for (bank, sprite), frames in walk.frames.items():
        table = bank_word(rom, bank, 0x8000 + 2 * sprite)
        claim(
            bank,
            table,
            table + 2 * max(frames) + 1,
            f"ObjectFrameTable{bank:X}{table:04X}",
            f"metasprite per frame of sprite ${sprite:02X}",
        )
        # Every entry up to the highest frame used is a real pointer, used or not.
        for frame in range(max(frames) + 1):
            ptr = bank_word(rom, bank, table + 2 * frame)
            if not 0x8000 <= ptr < OBJECT_DATA_END[bank]:
                continue
            size = metasprite_length(bank_read(rom, bank, ptr, 0x100)) or 1
            claim(
                bank,
                ptr,
                ptr + size - 1,
                f"ObjectMetasprites{bank:X}{ptr:04X}",
                f"metasprite for sprite ${sprite:02X}",
            )
    for bank, covered in walk.covered.items():
        run = None
        for cpu in sorted(covered) + [None]:
            if run and (
                cpu is None or cpu != run[1] + 1 or (bank, cpu) in walk.stream_starts
            ):
                start = run[0]
                how = walk.stream_starts.get((bank, start), "object stream")
                kind = "Motion" if how.startswith("motion") else "Anim"
                if (bank, start) not in walk.stream_starts:
                    kind = ""
                claim(
                    bank, start, run[1], f"Object{kind}Stream{bank:X}{start:04X}", how
                )
                run = None
            if cpu is not None:
                run = [cpu, cpu] if run is None else [run[0], cpu]

    # Adjacent metasprites of one sprite, and adjacent record lists, read as one.
    regions: list[KnownRegion] = []
    for (bank, start), (end, name, comment) in sorted(pieces.items()):
        last = regions[-1] if regions else None
        same_kind = (
            last
            and last.comment == comment
            and (
                name.startswith("ObjectMetasprites") or name.startswith("ObjectRecords")
            )
        )
        # Adjacent, or overlapping: one metasprite can start in another's tail.
        if (
            last
            and last.bank == bank
            and same_kind
            and last.end + 1 >= _prg(bank, start)
        ):
            regions[-1] = KnownRegion(
                last.start,
                max(last.end, _prg(bank, end)),
                "object",
                last.name,
                comment,
                bank,
                last.cpu,
            )
            continue
        regions.append(_region(bank, start, end - start + 1, "object", name, comment))
    return regions


def known_regions(
    rom,
    result: TraceResult,
    walk: ScriptWalk | None = None,
    objects: ObjectWalk | None = None,
) -> list[KnownRegion]:
    """Everything above, sorted by PRG offset."""
    measured = graphics_regions(rom, result) + course_regions(rom)
    if walk is not None:
        measured += script_regions(walk)
    if objects is not None:
        measured += object_regions(rom, objects)
    measured += opponent_shot_regions(rom, result)
    measured += metasprite_regions(rom, result)
    measured += palette_regions(rom, result)
    measured += descriptor_regions(rom, result)
    regions = list(measured)
    for pad in padding_regions(rom):
        # A graphics stream ends in its own $FF terminator, which the scan
        # back from the stub can't tell from padding.
        start = max(
            [pad.start] + [r.end + 1 for r in measured if pad.start <= r.end < pad.end]
        )
        if start <= pad.end:
            regions.append(
                KnownRegion(
                    start,
                    pad.end,
                    pad.kind,
                    pad.name,
                    pad.comment,
                    pad.bank,
                    _cpu_of(start),
                )
            )
    return sorted(regions, key=lambda r: r.start)
