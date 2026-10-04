"""
Recursive-descent code tracing: what is reachable as code from known entry points.

`disassemble` (in `rom_analysis`) decodes forward from one address. This module
follows control flow outward from the reset, NMI and IRQ vectors - branches,
`JSR`/`JMP`, far calls, inline dispatch tables and confirmed pointer tables -
and marks every byte it decodes. What it produces is a map: which bytes are
code, which are labeled data, and which are neither, plus the places where it
had to stop without knowing where control goes next.

**Bank context.** An address in `$8000-$BFFF` means nothing without knowing
which bank is mapped there. Code in a switchable bank runs with its own bank
mapped. Fixed-bank code inherits whatever its caller had mapped, so each work
item carries that bank (`ctx`, or None when unknown) and fixed-bank code is
traced once per context it is reached in. The game switches banks with
`LDA #n` / `JSR BankSwitchRoutine` (or `SetPrgBank`), and through the bank
byte of `ExecuteFarCall`; a switch whose bank isn't an immediate leaves the
context unknown, and a call into `$8000-$BFFF` from there is reported rather
than guessed. A `JSR` is assumed to return with the caller's bank mapped.

**What a trace cannot tell you.** A byte the trace didn't reach is not dead:
it may be reached through a pointer the trace couldn't follow, and every such
pointer it met is listed in `unresolved`. Treat the gaps as questions.
"""

from dataclasses import dataclass, field
from functools import lru_cache

from golf.core.rom_analysis import (
    BRANCH_OPCODES,
    FIXED_BANK,
    JMP_ABS,
    JMP_IND,
    JSR,
    RTI,
    RTS,
    inline_spec_for,
    is_data_range,
)
from golf.core.rom_utils import FIXED_BANK_PRG_START, PRG_BANK_SIZE

BRK = 0x00
LDA_IMM = 0xA9
PHA = 0x48

# Branch opcode -> its complement. `BEQ x / BNE y` together always branch.
_COMPLEMENT = {
    0x10: 0x30,
    0x30: 0x10,
    0x50: 0x70,
    0x70: 0x50,
    0x90: 0xB0,
    0xB0: 0x90,
    0xD0: 0xF0,
    0xF0: 0xD0,
}
_LOAD_IMMEDIATE = (0xA9, 0xA2, 0xA0)  # LDA/LDX/LDY #imm set N and Z
_SETS_CARRY = {0x18: 0x90, 0x38: 0xB0, 0xB8: 0x50}  # CLC->BCC, SEC->BCS, CLV->BVC


def _always_taken(opcode: int, prev: int | None, prev_imm: int | None) -> bool:
    """Is this branch unconditional, given the instruction before it?"""
    if prev is None:
        return False
    if _COMPLEMENT.get(prev) == opcode or _SETS_CARRY.get(prev) == opcode:
        return True
    if prev in _LOAD_IMMEDIATE and prev_imm is not None:
        return {
            0xD0: prev_imm != 0,  # BNE
            0xF0: prev_imm == 0,  # BEQ
            0x10: prev_imm < 0x80,  # BPL
            0x30: prev_imm >= 0x80,  # BMI
        }.get(opcode, False)
    return False


BANK_SWITCH_ROUTINES = (0xD352, 0xD35A)  # BankSwitchRoutine, SetPrgBank
EXECUTE_FAR_CALL = 0xD372

# Indirect jumps whose targets the trace already follows from the call sites:
# ExecuteFarCall's trampoline (the inline bank+address) and the tail both inline
# dispatchers share (the inline key/address tables).
HANDLED_INDIRECT_JUMPS = (0xD3BE, 0xD264)

_MODE_LENGTHS = {
    "imp": 1,
    "acc": 1,
    "imm": 2,
    "zpg": 2,
    "zpx": 2,
    "zpy": 2,
    "inx": 2,
    "iny": 2,
    "rel": 2,
    "abs": 3,
    "abx": 3,
    "aby": 3,
    "ind": 3,
}


@lru_cache(maxsize=1)
def _opcode_lengths() -> tuple[int, ...]:
    """Instruction length per opcode; 0 for the undocumented ones."""
    from py65.devices.mpu6502 import MPU

    return tuple(
        0 if mnemonic == "???" else _MODE_LENGTHS[mode]
        for mnemonic, mode in MPU().disassemble
    )


# --- Code pointer tables ------------------------------------------------


@dataclass(frozen=True)
class CodePointerTable:
    """A table of code addresses that a `JMP (ind)` dispatches through.

    `bank` holds both the table and its targets. `hi_offset` is None for
    interleaved little-endian words, or the distance from the low-byte table to
    the high-byte table for split Lo/Hi pairs. A `$0000` entry means "no
    handler" and is skipped.
    """

    name: str
    bank: int
    start: int  # CPU address of the first (low) byte
    count: int
    dispatch_sites: tuple[int, ...] = ()  # CPU addresses of the JMP (ind) it feeds
    hi_offset: int | None = None

    def targets(self, rom: bytes) -> list[int]:
        base = _to_prg(self.start, self.bank)
        assert base is not None
        out = []
        for i in range(self.count):
            if self.hi_offset is None:
                lo, hi = rom[base + 2 * i], rom[base + 2 * i + 1]
            else:
                lo, hi = rom[base + i], rom[base + self.hi_offset + i]
            if lo | hi:
                out.append(lo | (hi << 8))
        return out


# Every entry was confirmed by reading the dispatch site: it loads the entry
# into a pointer and jumps through it unmodified (no RTS +1 trick).
CODE_POINTER_TABLES: tuple[CodePointerTable, ...] = (
    CodePointerTable(
        "MenuChoiceHandlerPtrTable", 12, 0x8B09, 22, dispatch_sites=(0x899F,)
    ),
    # Indexed by a 4-bit match mask shifted left once ($9E23-$9E32), so X is
    # even and 0-30: 16 words, and the first points at the byte after the table.
    CodePointerTable("bank 9 $9E41", 9, 0x9E41, 16, dispatch_sites=(0x9E3E,)),
    # The scene callback at bank 10 $9B57 indexes $9BA2 by the object's $7AC1,
    # which is never 0 there (BEQ at $9B73); entry 0 is the JMP's own operand,
    # and the code after entry 3 starts at the first target, $9BAA.
    CodePointerTable("bank 10 $9BA4", 10, 0x9BA4, 3, dispatch_sites=(0x9BA1,)),
)


# --- Results ------------------------------------------------------------

NONE, OPCODE, OPERAND, INLINE = 0, 1, 2, 3


@dataclass
class Finding:
    """Somewhere the trace stopped without knowing, or doubting, what comes next."""

    kind: str
    prg: int
    detail: str = ""
    ctx: int | None = None
    via: int | None = None  # prg of the transfer that started this straight run

    @property
    def bank(self) -> int:
        return _bank_of(self.prg)

    @property
    def cpu(self) -> int:
        return _cpu_of(self.prg)


@dataclass
class TraceResult:
    marks: bytearray  # NONE / OPCODE / OPERAND / INLINE per PRG byte
    data_names: list  # per PRG byte: the covering range label's name, or None
    entries: dict[int, str] = field(default_factory=dict)  # prg -> how it's entered
    unresolved: list[Finding] = field(default_factory=list)
    conflicts: list[Finding] = field(default_factory=list)

    @property
    def banks(self) -> int:
        return len(self.marks) // PRG_BANK_SIZE

    def coverage(self, bank: int) -> dict[str, int]:
        """Byte counts for one bank: code, data, both, neither."""
        counts = {"code": 0, "data": 0, "both": 0, "neither": 0}
        start = bank * PRG_BANK_SIZE
        for prg in range(start, start + PRG_BANK_SIZE):
            data = self.data_names[prg] is not None
            # Inline arguments inside a range label are data both ways round.
            code = self.marks[prg] in (OPCODE, OPERAND) or (
                self.marks[prg] == INLINE and not data
            )
            key = (
                ("both" if data else "code")
                if code
                else ("data" if data else "neither")
            )
            counts[key] += 1
        return counts

    def gaps(self, bank: int | None = None) -> list[tuple[int, int]]:
        """(start_prg, length) runs that are neither code nor labeled data."""
        banks = range(self.banks) if bank is None else [bank]
        out = []
        for b in banks:
            start = b * PRG_BANK_SIZE
            run = None
            for prg in range(start, start + PRG_BANK_SIZE):
                free = self.marks[prg] == NONE and self.data_names[prg] is None
                if free and run is None:
                    run = prg
                elif not free and run is not None:
                    out.append((run, prg - run))
                    run = None
            if run is not None:
                out.append((run, start + PRG_BANK_SIZE - run))
        return out


def data_names_from(labels, prg_size: int) -> list:
    """Per PRG byte, the name of the range label covering it (innermost wins)."""
    names: list = [None] * prg_size
    if labels is None:
        return names
    ranges = [
        label
        for label, _ in labels.iter_merged()
        if label.type == "NesPrgRom" and is_data_range(label)
    ]
    # Widest first, so a nested range overwrites the one it sits inside.
    for label in sorted(ranges, key=lambda r: r.start - r.end):
        for prg in range(label.start, min(label.end, prg_size - 1) + 1):
            names[prg] = label.name
    return names


# --- Address helpers ----------------------------------------------------


def _to_prg(cpu: int, bank: int | None) -> int | None:
    """PRG offset of a ROM address, or None when the bank isn't known."""
    if cpu >= 0xC000:
        return FIXED_BANK_PRG_START + (cpu - 0xC000)
    if 0x8000 <= cpu < 0xC000 and bank is not None:
        return bank * PRG_BANK_SIZE + (cpu - 0x8000)
    return None


def _bank_of(prg: int) -> int:
    return prg // PRG_BANK_SIZE


def _cpu_of(prg: int) -> int:
    if prg >= FIXED_BANK_PRG_START:
        return 0xC000 + (prg - FIXED_BANK_PRG_START)
    return 0x8000 + (prg % PRG_BANK_SIZE)


# --- Seeds --------------------------------------------------------------


@dataclass(frozen=True)
class Seed:
    cpu: int
    ctx: int | None  # the bank mapped at $8000; the code's own bank if switchable
    how: str


def vector_seeds(reader) -> list[Seed]:
    """NMI/RESET/IRQ of the fixed bank, plus each switchable bank's own vectors.

    MMC1 can power up with any bank at `$C000`, so every bank ends in a copy of
    the reset stub with vectors pointing at it as `$FFF3`. Those are seeded as
    the same offset in their own bank.
    """
    seeds = []
    for bank in range(reader.prg_size // PRG_BANK_SIZE):
        raw = reader.read_prg((bank + 1) * PRG_BANK_SIZE - 6, 6)
        for i, name in enumerate(("NMI", "RESET", "IRQ")):
            addr = raw[2 * i] | (raw[2 * i + 1] << 8)
            if bank == FIXED_BANK:
                seeds.append(Seed(addr, None, f"{name} vector"))
            elif addr >= 0x8000:
                cpu = addr - 0x4000 if addr >= 0xC000 else addr
                seeds.append(Seed(cpu, bank, f"bank {bank} {name} vector"))
    return seeds


def label_seeds(labels) -> list[Seed]:
    """Every single-address PRG label, taken as code. Data labeled this way misdecodes."""
    seeds = []
    for label, _ in labels.iter_merged():
        if label.type != "NesPrgRom" or is_data_range(label):
            continue
        bank = _bank_of(label.start)
        seeds.append(
            Seed(
                _cpu_of(label.start),
                None if bank == FIXED_BANK else bank,
                f"label {label.name}",
            )
        )
    return seeds


# --- The trace ----------------------------------------------------------


def trace(reader, labels=None, seeds=None, pointer_tables=CODE_POINTER_TABLES):
    """Follow control flow from `seeds` (default: the vectors) and map the result."""
    rom = reader.read_prg(0, reader.prg_size)
    lengths = _opcode_lengths()
    result = TraceResult(
        bytearray(reader.prg_size), data_names_from(labels, reader.prg_size)
    )
    owner: dict[int, int] = {}  # operand/inline byte -> its instruction's prg
    decoded: set[tuple[int, int | None]] = set()  # (prg, ctx) already walked
    work: list[tuple[int, int | None, int | None]] = []  # (cpu, ctx, from prg)
    via = None

    def note(bucket, kind, prg, detail="", ctx=None):
        bucket.append(Finding(kind, prg, detail, ctx, via))

    def push(cpu, ctx, code_bank, site, how=None):
        """Queue a transfer to cpu from code in code_bank, with ctx mapped at $8000."""
        if cpu < 0x8000:
            note(result.unresolved, "target outside ROM", site, f"${cpu:04X}", ctx)
            return
        if cpu < 0xC000:
            ctx = code_bank if code_bank != FIXED_BANK else ctx
            if ctx is None:
                note(
                    result.unresolved,
                    "switchable-bank target, bank unknown",
                    site,
                    f"${cpu:04X}",
                )
                return
        target = _to_prg(cpu, ctx)
        if how and target is not None:
            result.entries.setdefault(target, how)
        work.append((cpu, ctx, site))

    for seed in vector_seeds(reader) if seeds is None else seeds:
        push(seed.cpu, seed.ctx, FIXED_BANK, None, seed.how)

    resolved_sites = {_to_prg(cpu, None) for cpu in HANDLED_INDIRECT_JUMPS}
    for table in pointer_tables:
        resolved_sites.update(
            _to_prg(site, table.bank) for site in table.dispatch_sites
        )
        for target in table.targets(rom):
            push(target, table.bank, table.bank, None, f"entry in {table.name}")

    while work:
        cpu, ctx, via = work.pop()
        code_bank = FIXED_BANK if cpu >= 0xC000 else ctx
        prev = prev_imm = None  # the previous opcode, and its immediate operand
        last_call = None  # the most recent JSR in this run, the usual culprit
        recent: list[int] = []  # the last few opcodes
        last = -1  # prg of the previous instruction

        while True:
            prg = _to_prg(cpu, ctx if cpu < 0xC000 else None)
            if cpu > 0xFFFF or prg is None:
                note(result.conflicts, "runs off the end of the fixed bank", last)
                break
            if code_bank != FIXED_BANK and cpu >= 0xC000:
                note(result.conflicts, "falls through into the fixed bank", last)
                break
            if (prg, ctx) in decoded:
                break
            decoded.add((prg, ctx))

            if result.data_names[prg] is not None:
                # Straight after a conditional branch, a labeled table is the
                # label saying the branch always goes (`LDA table,X / BNE`).
                if prev not in BRANCH_OPCODES:
                    name = result.data_names[prg]
                    note(result.conflicts, "runs into data range", prg, name)
                break
            mark = result.marks[prg]
            if mark in (OPERAND, INLINE):
                what = "inline arguments" if mark == INLINE else "an instruction"
                note(
                    result.conflicts,
                    f"enters the middle of {what}",
                    prg,
                    f"starting at ${_cpu_of(owner[prg]):04X}",
                )
                break

            opcode = rom[prg]
            length = lengths[opcode]
            if length == 0 or opcode == BRK:
                what = "BRK" if opcode == BRK else f"undocumented opcode ${opcode:02X}"
                after = (
                    ""
                    if last_call is None
                    else f"after JSR at ${_cpu_of(last_call):04X}"
                )
                note(result.conflicts, f"decodes {what}", prg, after)
                break
            clash = next(
                (p for p in range(prg + 1, prg + length) if result.marks[p] == OPCODE),
                None,
            )
            overlap = next(
                (
                    p
                    for p in range(prg + 1, prg + length)
                    if result.data_names[p] is not None
                ),
                None,
            )
            if overlap is not None:
                name = result.data_names[overlap]
                note(result.conflicts, "operand overlaps data range", prg, name)
                break
            if clash is not None:
                note(
                    result.conflicts,
                    "overlaps another instruction",
                    prg,
                    f"starting at ${_cpu_of(clash):04X}",
                )
                break
            if mark == NONE:
                result.marks[prg] = OPCODE
                for p in range(prg + 1, prg + length):
                    result.marks[p] = OPERAND
                    owner[p] = prg

            operand = rom[prg + 1 : prg + length]
            next_cpu = cpu + length
            recent = (recent + [opcode])[-3:]
            last = prg

            if opcode in BRANCH_OPCODES:
                push(next_cpu + ((operand[0] ^ 0x80) - 0x80), ctx, code_bank, prg)
                if _always_taken(opcode, prev, prev_imm):
                    break
            elif opcode == JMP_ABS:
                push(operand[0] | (operand[1] << 8), ctx, code_bank, prg)
                break
            elif opcode == JMP_IND:
                if prg not in resolved_sites:
                    ptr = operand[0] | (operand[1] << 8)
                    note(result.unresolved, "JMP (indirect)", prg, f"(${ptr:04X})", ctx)
                break
            elif opcode in (RTS, RTI):
                if opcode == RTS and recent[:2] == [PHA, PHA]:
                    note(result.unresolved, "pushed-address RTS dispatch", prg, "", ctx)
                break
            elif opcode == JSR:
                last_call = prg
                target = operand[0] | (operand[1] << 8)
                if target in BANK_SWITCH_ROUTINES:
                    if code_bank != FIXED_BANK:
                        note(
                            result.unresolved,
                            "bank switch from switchable-bank code",
                            prg,
                            "",
                            ctx,
                        )
                    push(target, ctx, code_bank, prg, f"JSR from ${cpu:04X}")
                    ctx = prev_imm if prev == LDA_IMM else None
                else:
                    if target == EXECUTE_FAR_CALL:
                        bank, lo, hi = rom[prg + 3], rom[prg + 4], rom[prg + 5]
                        far = lo | (hi << 8)
                        push(far, bank, bank, prg, f"far call from ${cpu:04X}")
                    push(target, ctx, code_bank, prg, f"JSR from ${cpu:04X}")

                spec = inline_spec_for(
                    target, code_bank if code_bank != FIXED_BANK else ctx
                )
                if spec is not None:
                    arg = prg + length
                    n = spec.measure(rom[arg : arg + 64])
                    for p in range(arg, arg + n):
                        if result.marks[p] == NONE:
                            result.marks[p] = INLINE
                            owner[p] = prg
                    if spec.style == "key_addr":
                        for p in range(arg, arg + n - 1, 3):
                            push(
                                rom[p + 1] | (rom[p + 2] << 8),
                                ctx,
                                code_bank,
                                p,
                                f"dispatch table after ${cpu:04X}",
                            )
                    next_cpu += n
                    if not spec.returns:
                        break

            prev = opcode
            prev_imm = operand[0] if length == 2 else None
            cpu = next_cpu

    result.unresolved = _dedupe(result.unresolved)
    result.conflicts = _dedupe(result.conflicts)
    return result


def unreached_roots(reader, labels, seeds: list[Seed]) -> dict[int, set[int]]:
    """Which of `seeds` (labels a trace missed) head their own unreached chain.

    Traces from each seed alone and records which other seeds that reaches.
    Returns, per seed's PRG offset, the seeds upstream of it; an empty set
    marks a root - code nothing else in the list explains, so whatever reaches
    it is control flow the trace couldn't follow (or it is data, or dead).
    """
    starts = {}
    for seed in seeds:
        prg = _to_prg(seed.cpu, seed.ctx)
        if prg is not None:
            starts[prg] = seed
    reaches = {}
    for prg, seed in starts.items():
        sub = trace(reader, labels, [seed], pointer_tables=())
        reaches[prg] = {
            other for other in starts if other != prg and sub.marks[other] == OPCODE
        }
    # x is under y when y reaches x and x doesn't reach back (no cycle).
    return {
        prg: {y for y in starts if prg in reaches[y] and y not in reaches[prg]}
        for prg in starts
    }


def _dedupe(findings: list[Finding]) -> list[Finding]:
    unique: dict = {}
    for f in findings:
        unique.setdefault((f.kind, f.prg, f.detail), f)
    return sorted(unique.values(), key=lambda f: (f.prg, f.kind))
