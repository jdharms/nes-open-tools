"""
Scene objects: their records, animation streams and metasprites.

Cutscenes and menus animate sprites with a small object engine in the fixed
bank (`LF8CA`). `AllocateObjectRecords` (`$F7C0`), `LF7F3` and `LF826` copy
9-byte records into object slots (`LFC2B_CopyObjectRecord`):

    0 x  1 y  2 sprite id  3 OAM attribute  4 clip window
    5-6 motion stream      7-8 animation stream

A step with a frame count of 0 halts its stream: the engine only advances a
stream when its countdown reaches 0 from 1, so it never moves again.

Each frame the engine steps both streams. A **motion stream** is 3-byte steps
(frames, x speed, y speed); `$DD` sets a velocity. An **animation stream** is
2-byte steps (frames, metasprite frame); `$EF n` changes the sprite id and
`$ED lo hi` calls native code (`JMP ($0C)` at `$FCF6`). Both share the control
opcodes `$F1-$FF` at `LFB08`: jumps, calls, loops and branches on RAM.

The engine runs with the bank in `$3A` mapped, which is always 2 or 10, so the
streams and the sprite data are in one of those two banks. At `$8000` each
starts with a word per sprite id pointing at a frame table, and each frame
table holds a word per frame pointing at a metasprite (`RenderMetasprite`,
`$FEBD`). Which of the two banks a scene uses is set at run time - the club
house menu maps 10, most of its screens 2 - so `walk_objects` decodes each
record against both and keeps the bank where everything it reads is well
formed, reporting the records where that doesn't single one out.
"""

from dataclasses import dataclass, field

from golf.core.rom_trace import OPCODE, TraceResult
from golf.core.rom_utils import FIXED_BANK_PRG_START, PRG_BANK_SIZE

OBJECT_BANKS = (2, 10)
# Bank 2's object data is the 895 bytes before the UK course terrain at $837F
# (the "pre-terrain tables" of the layout skill); the two banks share the first
# 32 bytes of the sprite table, so most of bank 2's ids point into the terrain.
OBJECT_DATA_END = {2: 0x837F, 10: 0xC000}
RECORD_SIZE = 9

ALLOCATORS = {
    0xF7C0: "AllocateObjectRecords",  # A = count, inline word = 9-byte records
    # One record each, from the inline word, entering the copy at $FC39 past
    # x and y (which come in X and Y): 7 bytes, sprite id first.
    0xF7F3: "LF7F3",
    0xF826: "LF826",
}
# $F856 copies a short record from SramPtr, with x, y and A in registers; its
# records come through RECORD_POINTER_TABLES with size 7.
SHORT_RECORD = RECORD_SIZE - 2


@dataclass(frozen=True)
class RecordPointerTable:
    """Words that `LF7EE` gets its record list from (via `$22/$23`), in bank 12.

    `counts` is how many 9-byte records each entry's list holds (the A its
    loader passes); `site` is the loader's `JSR LF7EE`.
    """

    cpu: int
    counts: tuple[int, ...]
    site: int
    why: str
    size: int = 9  # 7 for the short records $F856 copies, x and y in X and Y


RECORD_POINTER_TABLES = (
    RecordPointerTable(
        0x911B, (1, 2, 2, 2, 2), 0x8FE3, "Prize Money variant; 1 record for 0"
    ),
    RecordPointerTable(0xA9B1, (2,) * 6, 0xA936, "by A*2 at $A8DC, A = 0-5"),
    RecordPointerTable(
        0xB562, (1,) * 10, 0xB38B, "by CourseIntroPhaseStep, +10 for player 2"
    ),
    RecordPointerTable(
        0xB871, (1,) * 4, 0xB86B, "CurrentPlayerIndex*4, +2 for clubs 4 and up"
    ),
    RecordPointerTable(
        0x96D5, (2,) * 7, 0x953A, "CourseIntroPortraitObjPtrTable, by $071D*2"
    ),
    RecordPointerTable(
        0xBAA7,
        (1,) * 3,
        0xBA93,
        "MaybeWagerChoiceRecordPtrTable, by $06BC*2, $06BC = 0-2",
        size=7,
    ),
)
TABLE_BANK = 12


@dataclass(frozen=True)
class RecordList:
    """Records found other than through a traced allocator's arguments.

    `count` 9-byte records from `cpu` in `bank`; `site` is the `JSR LF7EE`
    that reaches them through a RAM pointer, or None when no allocator is known
    (their streams are still decoded, so the bytes they name are accounted for).
    """

    bank: int
    cpu: int
    count: int
    site: int | None
    why: str


RECORD_LISTS = (
    RecordList(
        12,
        0x8F10,
        4,
        0x85A8,
        "MenuSpriteInitData: MenuEntryTablePtr set at $8592, stepped 9 bytes a "
        "record while MenuOptionCount counts 3 down to 0",
    ),
    RecordList(12, 0xB740, 2, None, "no allocator or pointer found"),
    RecordList(12, 0xB77F, 2, None, "no allocator or pointer found"),
    RecordList(12, 0xB7BE, 3, None, "pointed at only by MaybeObjectRecordPairTable"),
)

# Control opcodes both streams share (LFB08): opcode -> (length, flow).
NEXT, JUMP, BRANCH, CALL, RETURN, STOP, NATIVE = (
    "next",
    "jump",
    "branch",
    "call",
    "return",
    "stop",
    "native",
)
CONTROL = {
    0xF1: (3, NEXT),  # decrement [addr]
    0xF2: (3, NEXT),  # set two per-object bytes ($7821/$7851)
    0xF6: (4, NEXT),  # store v to [addr]
    0xF7: (6, BRANCH),  # if [addr] >= v go to target
    0xF8: (5, BRANCH),  # if [addr] != 0 go to target
    0xF9: (5, BRANCH),  # if [addr] == 0 go to target
    0xFA: (1, NEXT),  # loop end
    0xFB: (2, NEXT),  # loop start, n times
    0xFC: (1, RETURN),  # return from a stream subroutine
    0xFD: (3, CALL),  # call a stream subroutine
    0xFE: (3, JUMP),  # go to target
    0xFF: (1, STOP),  # free the object
}
STORE = 0xF6
MOTION_OPS = {0xDD: (3, NEXT)}  # $FCB2: set velocity
ANIM_OPS = {0xEF: (2, NEXT), 0xED: (3, NATIVE)}  # $FCD5: sprite id, native call
MOTION_STEP, ANIM_STEP = 3, 2
MOTION_OPCODE_BASE, ANIM_OPCODE_BASE = 0xD0, 0xE0


@dataclass
class Problem:
    kind: str
    bank: int
    cpu: int
    detail: str = ""


@dataclass
class StreamWalk:
    """One stream decoded in one bank."""

    covered: set[int] = field(default_factory=set)  # CPU addresses
    uses: set[tuple[int, int]] = field(default_factory=set)  # (sprite id, frame)
    native: set[int] = field(default_factory=set)
    stores: dict[int, tuple[int, int]] = field(default_factory=dict)  # $F6 at: (a, v)
    problems: list[str] = field(default_factory=list)


def bank_read(rom, bank: int, cpu: int, length: int) -> bytes:
    """Up to `length` bytes, stopping at the end of the bank."""
    end = 0x10000 if cpu >= 0xC000 else 0xC000
    length = max(0, min(length, end - cpu))
    if cpu >= 0xC000:
        return rom.read_fixed(cpu, length)
    return rom.read_switched(cpu, bank, length)


def walk_stream(rom, bank: int, start: int, anim: bool, sprite: int = 0) -> StreamWalk:
    """Follow one motion or animation stream as the engine would in `bank`.

    `sprite` is the object's sprite id at the start; `$EF` changes it, and each
    animation step is recorded against the id in force on that path.
    """
    walk = StreamWalk()
    work, seen = [(start, sprite)], set()
    step = ANIM_STEP if anim else MOTION_STEP
    base = ANIM_OPCODE_BASE if anim else MOTION_OPCODE_BASE
    own = ANIM_OPS if anim else MOTION_OPS
    while work:
        pc, sprite = work.pop()
        while (pc, sprite) not in seen:
            if not 0x8000 <= pc <= 0xFFFF:
                walk.problems.append(f"stream address ${pc:04X} outside ROM")
                break
            seen.add((pc, sprite))
            op = bank_read(rom, bank, pc, 1)[0]
            if op < base:
                args = bank_read(rom, bank, pc, step)
                if len(args) < step:
                    walk.problems.append(f"step at ${pc:04X} runs off the bank")
                    break
                walk.covered.update(range(pc, pc + step))
                if op == 0:
                    break  # a zero count is never counted down: the stream halts
                if anim:
                    walk.uses.add((sprite, args[1]))
                pc += step
                continue
            length, flow = (own if op < 0xF0 else CONTROL).get(op, (0, ""))
            if not length:
                walk.problems.append(f"no handler for ${op:02X} at ${pc:04X}")
                break
            args = bank_read(rom, bank, pc + 1, length - 1)
            walk.covered.update(range(pc, pc + length))
            if flow in (JUMP, CALL):
                work.append((args[0] | args[1] << 8, sprite))
            elif flow == BRANCH:
                work.append((args[-2] | args[-1] << 8, sprite))
            elif flow == NATIVE:
                walk.native.add(args[0] | args[1] << 8)
            elif op == STORE:
                walk.stores[pc] = (args[0] | args[1] << 8, args[2])
            elif op == 0xEF and anim:
                sprite = args[0]
            if flow in (JUMP, RETURN, STOP):
                break
            pc += length
    return walk


def metasprite_length(data: bytes) -> int | None:
    """Bytes in the metasprite at the start of `data`, or None if malformed.

    A chunk header's low six bits count its sprites; bit 6 says another chunk
    follows. With bit 7 clear each sprite is 4 bytes (dY, tile, attr, dX);
    with it set one attribute byte follows the header and each sprite is 3.
    A header of 0 (ignoring bit 6) is an empty metasprite.
    """
    pos = 0
    while pos < len(data):
        header = data[pos]
        count = header & 0x3F
        if header & 0xBF == 0:
            return pos + 1
        size = 1 + (1 + 3 * count if header & 0x80 else 4 * count)
        pos += size
        if not header & 0x40:
            return pos if pos <= len(data) else None
    return None


@dataclass
class Record:
    """One object record. `raw` always holds the full 9-byte layout; a short
    record (from `LF7F3`/`LF826`, which take x and y in registers) has its
    first two bytes zeroed."""

    bank: int  # where the record table is
    cpu: int
    raw: bytes
    found: str
    site: int  # PRG offset of the allocating JSR
    length: int = RECORD_SIZE

    @property
    def sprite_id(self) -> int:
        return self.raw[2]

    @property
    def motion(self) -> int:
        return self.raw[5] | self.raw[6] << 8

    @property
    def anim(self) -> int:
        return self.raw[7] | self.raw[8] << 8


def object_records(rom, result: TraceResult) -> list[Record]:
    """Every record that traced code passes to an allocator with a known count."""
    data = rom.read_prg(0, rom.prg_size)
    records = []
    for prg in range(len(data) - 5):
        if result.marks[prg] != OPCODE or data[prg] != 0x20:
            continue
        target = data[prg + 1] | data[prg + 2] << 8
        if target not in ALLOCATORS:
            continue
        if target == 0xF7C0:
            if result.marks[prg - 2] != OPCODE or data[prg - 2] != 0xA9:
                continue  # count not an immediate
            count, size = data[prg - 1], RECORD_SIZE
        else:
            count, size = 1, SHORT_RECORD
        table = data[prg + 3] | data[prg + 4] << 8
        bank = prg // PRG_BANK_SIZE
        site = 0x8000 + prg % PRG_BANK_SIZE if prg < FIXED_BANK_PRG_START else 0
        for i in range(count):
            cpu = table + size * i
            raw = bytes(RECORD_SIZE - size) + bank_read(rom, bank, cpu, size)
            found = f"{ALLOCATORS[target]} at bank {bank} ${site:04X}"
            records.append(Record(bank, cpu, raw, found, prg, size))
    for table in RECORD_POINTER_TABLES:
        site = TABLE_BANK * PRG_BANK_SIZE + table.site - 0x8000
        for i, count in enumerate(table.counts):
            first = bank_word(rom, TABLE_BANK, table.cpu + 2 * i)
            for j in range(count):
                cpu = first + table.size * j
                raw = bytes(RECORD_SIZE - table.size) + bank_read(
                    rom, TABLE_BANK, cpu, table.size
                )
                found = f"entry {i} of bank 12 ${table.cpu:04X} ({table.why})"
                records.append(Record(TABLE_BANK, cpu, raw, found, site, table.size))
    for listed in RECORD_LISTS:
        # Without an allocator, the records' own place stands in for the site.
        at = listed.cpu if listed.site is None else listed.site
        site = listed.bank * PRG_BANK_SIZE + at - 0x8000
        for j in range(listed.count):
            cpu = listed.cpu + RECORD_SIZE * j
            raw = bank_read(rom, listed.bank, cpu, RECORD_SIZE)
            records.append(Record(listed.bank, cpu, raw, listed.why, site))
    return records


@dataclass
class BankFit:
    """A record decoded against one candidate object bank."""

    bank: int
    motion: StreamWalk
    anim: StreamWalk
    problems: list[str]


def fit(rom, record: Record, bank: int) -> BankFit:
    motion = walk_stream(rom, bank, record.motion, anim=False)
    anim = walk_stream(rom, bank, record.anim, anim=True, sprite=record.sprite_id)
    problems = motion.problems + anim.problems
    end = OBJECT_DATA_END[bank]
    for cpu in motion.covered | anim.covered:
        if end <= cpu < 0xC000:
            problems.append(f"stream byte ${cpu:04X} is past the object data")
            break
    for sprite, frame in sorted(anim.uses):
        if sprite & 0x80 or frame & 0x80:
            continue  # a free slot, or a hidden frame
        table = bank_word(rom, bank, 0x8000 + 2 * sprite)
        if not 0x8000 <= table < end:
            problems.append(f"sprite ${sprite:02X} has no frame table")
            continue
        ptr = bank_word(rom, bank, table + 2 * frame)
        if not 0x8000 <= ptr < end:
            problems.append(f"sprite ${sprite:02X} frame {frame} points nowhere")
        elif metasprite_length(bank_read(rom, bank, ptr, 0x100)) is None:
            problems.append(f"sprite ${sprite:02X} frame {frame} is malformed")
    return BankFit(bank, motion, anim, problems)


def bank_word(rom, bank: int, cpu: int) -> int:
    lo, hi = bank_read(rom, bank, cpu, 2)
    return lo | hi << 8


# --- The whole walk -----------------------------------------------------

NEIGHBOR_REACH = 0x100  # allocations this close in one bank share a scene
SCENE_CALLBACK_SETTER = 0xF8A2  # LF8A2: inline word -> $7B11
SCENE_CALLBACK_SITE = 0xF950  # JMP ($7B11), run with the object bank mapped
OBJECT_NATIVE_SITE = 0xFCF6  # $ED's JMP ($0C)


@dataclass
class ObjectWalk:
    records: list[Record] = field(default_factory=list)
    banks: dict[int, int] = field(default_factory=dict)  # record index -> bank
    covered: dict[int, set[int]] = field(default_factory=dict)  # bank -> stream CPU
    stream_starts: dict[tuple[int, int], str] = field(default_factory=dict)
    frames: dict[tuple[int, int], set[int]] = field(default_factory=dict)  # (bank, id)
    native: dict[tuple[int, int], str] = field(default_factory=dict)  # (bank, cpu)
    stores: dict[tuple[int, int], tuple[int, int]] = field(default_factory=dict)
    problems: list[Problem] = field(default_factory=list)


UNKNOWN_SPRITE = 0x80  # bit 7: frames recorded against it are skipped
# (lo array, hi array, animation?) - the slot arrays a stream pointer lives in.
STREAM_ARRAYS = ((0x7A41, 0x7A51, False), (0x7A61, 0x7A71, True))
STREAM_STORE_REACH = 4  # instructions from the low store to the high one


def code_streams(rom, result: TraceResult) -> list[tuple[int, int, bool, int]]:
    """(bank, stream, anim?, site) for each stream object-bank code installs.

    Native code in an object bank (a scene callback, an `$ED` call) can point a
    slot at a new stream: `LDA #lo / STA $7A41,X` then `LDA #hi / STA $7A51,X`
    (motion), or `$7A61/$7A71` (animation). The stream is in the code's bank.
    """
    data = rom.read_prg(0, rom.prg_size)
    found = []

    def store(prg):  # (value, array) for LDA #v / STA abs,X|Y, else None
        if data[prg] != 0xA9 or data[prg + 2] not in (0x9D, 0x99):
            return None
        return data[prg + 1], data[prg + 3] | data[prg + 4] << 8

    for bank in OBJECT_BANKS:
        base = bank * PRG_BANK_SIZE
        for prg in range(base, base + PRG_BANK_SIZE - 5):
            if result.marks[prg] != OPCODE or (low := store(prg)) is None:
                continue
            for lo_array, hi_array, anim in STREAM_ARRAYS:
                if low[1] != lo_array:
                    continue
                p = prg
                for _ in range(STREAM_STORE_REACH):
                    p += 1
                    while p < base + PRG_BANK_SIZE - 5 and result.marks[p] != OPCODE:
                        p += 1
                    high = store(p) if result.marks[p] == OPCODE else None
                    if high is not None and high[1] == hi_array:
                        site = 0x8000 + prg % PRG_BANK_SIZE
                        found.append((bank, low[0] | high[0] << 8, anim, site))
                        break
    return found


def walk_objects(rom, result: TraceResult) -> ObjectWalk:
    """Decode every record, settle its bank, and gather what it reads."""
    walk = ObjectWalk(records=object_records(rom, result))
    fits = [{b: fit(rom, rec, b) for b in OBJECT_BANKS} for rec in walk.records]
    for i, options in enumerate(fits):
        clean = [b for b, f in options.items() if not f.problems]
        if len(clean) == 1:
            walk.banks[i] = clean[0]
    for i, options in enumerate(fits):
        if i in walk.banks:
            continue
        clean = {b for b, f in options.items() if not f.problems}
        site = walk.records[i].site
        near = {
            walk.banks[j]
            for j, other in enumerate(walk.records)
            if j in walk.banks
            and other.site // PRG_BANK_SIZE == site // PRG_BANK_SIZE
            and abs(other.site - site) <= NEIGHBOR_REACH
        }
        if len(near & clean) == 1:
            walk.banks[i] = (near & clean).pop()
            continue
        rec = walk.records[i]
        detail = "fits neither bank" if not clean else "fits both banks"
        first = next((f.problems[0] for f in options.values() if f.problems), "")
        walk.problems.append(Problem(detail, rec.bank, rec.cpu, first))

    for bank, start, anim, site in code_streams(rom, result):
        stream = walk_stream(rom, bank, start, anim=anim, sprite=UNKNOWN_SPRITE)
        if stream.problems:
            walk.problems.append(
                Problem("stream set by code", bank, start, stream.problems[0])
            )
            continue
        walk.covered.setdefault(bank, set()).update(stream.covered)
        kind = "animation" if anim else "motion"
        walk.stream_starts.setdefault(
            (bank, start), f"{kind} stream; set by code at bank {bank} ${site:04X}"
        )
        for cpu in stream.native:
            walk.native.setdefault(
                (bank, cpu), f"object $ED call; stream at ${start:04X}"
            )
        walk.stores.update({(bank, pc): st for pc, st in stream.stores.items()})

    for i, bank in walk.banks.items():
        rec, chosen = walk.records[i], fits[i][bank]
        walk.covered.setdefault(bank, set()).update(
            chosen.motion.covered | chosen.anim.covered
        )
        how = f"record at bank {rec.bank} ${rec.cpu:04X}"
        walk.stream_starts.setdefault((bank, rec.motion), f"motion stream; {how}")
        walk.stream_starts.setdefault((bank, rec.anim), f"animation stream; {how}")
        for sprite, frame in chosen.anim.uses:
            if not sprite & 0x80 and not frame & 0x80:
                walk.frames.setdefault((bank, sprite), set()).add(frame)
        for cpu in chosen.anim.native:
            walk.native.setdefault((bank, cpu), f"object $ED call; {how}")
        for stream in (chosen.motion, chosen.anim):
            walk.stores.update({(bank, pc): st for pc, st in stream.stores.items()})
    return walk


def stream_scripts(walk: ObjectWalk) -> dict[int, str]:
    """Text scripts a stream starts by storing their address into `ScriptPtr`.

    The tournament win scene's animation (bank 10 `$BB0A`) ends with `$F6` stores
    of the prize-award script's address into `ScriptPtr` and `ScriptPtr+1`, then
    `ScriptDelayCounter`: the only place that script is named.
    """
    from golf.core.text_script import SCRIPT_PTR

    found = {}
    for (bank, pc), (addr, lo) in sorted(walk.stores.items()):
        high = walk.stores.get((bank, pc + 4))
        if addr == SCRIPT_PTR and high is not None and high[0] == SCRIPT_PTR + 1:
            cpu = lo | high[1] << 8
            if 0x8000 <= cpu < 0xC000:
                found.setdefault(
                    cpu, f"set by an object stream at bank {bank} ${pc:04X}"
                )
    return found


def scene_callbacks(rom, result: TraceResult, walk: ObjectWalk) -> dict:
    """`LF8A2`'s inline callbacks, in the object bank of the scene that sets them."""
    data = rom.read_prg(0, rom.prg_size)
    lo, hi = SCENE_CALLBACK_SETTER & 0xFF, SCENE_CALLBACK_SETTER >> 8
    found = {}
    for prg in range(len(data) - 4):
        if not (
            result.marks[prg] == OPCODE
            and data[prg] == 0x20
            and data[prg + 1] == lo
            and data[prg + 2] == hi
        ):
            continue
        near = {
            walk.banks[i]
            for i, rec in enumerate(walk.records)
            if i in walk.banks
            and rec.site // PRG_BANK_SIZE == prg // PRG_BANK_SIZE
            and abs(rec.site - prg) <= NEIGHBOR_REACH
        }
        if len(near) == 1:
            cpu = data[prg + 3] | data[prg + 4] << 8
            bank = near.pop()
            site = 0x8000 + prg % PRG_BANK_SIZE
            found[(bank, cpu)] = (
                f"scene callback set at bank {prg // PRG_BANK_SIZE} ${site:04X}"
            )
    return found


def trace_everything(reader, labels=None, seeds=None):
    """The code trace with both walkers, repeated until nothing new turns up.

    Returns (result, script walk, object walk).
    """
    from golf.core.rom_trace import Seed, vector_seeds
    from golf.core.text_script import trace_with_scripts

    base = vector_seeds(reader) if seeds is None else list(seeds)
    extra: dict[tuple[int, int], str] = {}
    scripts_from_streams: dict[int, str] = {}
    while True:
        more = [Seed(cpu, bank, how) for (bank, cpu), how in sorted(extra.items())]
        result, scripts = trace_with_scripts(
            reader, labels, base + more, scripts_from_streams
        )
        objects = walk_objects(reader, result)
        found = {**objects.native, **scene_callbacks(reader, result, objects)}
        new = {k: v for k, v in found.items() if k not in extra}
        new_scripts = {
            k: v
            for k, v in stream_scripts(objects).items()
            if k not in scripts_from_streams
        }
        if not new and not new_scripts:
            break
        extra.update(new)
        scripts_from_streams.update(new_scripts)
    answered = {_prg_of(15, OBJECT_NATIVE_SITE)}
    if any("scene callback" in how for how in extra.values()):
        answered.add(_prg_of(15, SCENE_CALLBACK_SITE))
    result.unresolved = [f for f in result.unresolved if f.prg not in answered]
    return result, scripts, objects


def _prg_of(bank: int, cpu: int) -> int:
    if cpu >= 0xC000:
        return FIXED_BANK_PRG_START + cpu - 0xC000
    return bank * PRG_BANK_SIZE + cpu - 0x8000
