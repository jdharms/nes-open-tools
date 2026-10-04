"""
The bank 11 text scripts: a byte-code walker, and where the scripts start.

The dialogue in the course intro and the money cutscenes is a byte-code program
run by `RunTextScript` (bank 11 `$9033`), one token a frame. Bytes `$00-$EF`
print a character; `$F1-$FF` are opcodes (see `docs/text_scripts.md`).
Two of them leave the script for 6502 code - `$F8` calls native code once and
`$F7` installs a per-frame callback - and their operands are the only way that
code is reached, which is why the code trace needs the walker: those calls are
the `JMP ($22)` at `$92A1` and the `JMP ($20)` at `$90AB`.

`walk_scripts` follows every opcode that can change the script counter, the way
`trace` follows branches, and records the bytes it read as script, the native
code addresses it found, and anything it couldn't decode. `trace_with_scripts`
alternates the two until neither finds anything new, since native code reached
from a script can itself point `ScriptPtr` at another script.
"""

from dataclasses import dataclass, field

from golf.core.rom_trace import OPCODE, Seed, TraceResult, trace, vector_seeds
from golf.core.rom_utils import PRG_BANK_SIZE

SCRIPT_BANK = 11
SCRIPT_PTR = 0x06E7  # ScriptPtr, lo; the hi byte follows
WINDOW_GEOMETRY_TABLE = 0x9648  # ScriptWindowGeometryTable: 4 bytes per window

# The indirect jumps the walker answers for the trace.
CALL_NATIVE_SITE = 0x92A1  # $F8's JMP ($22)
RESUME_CALLBACK_SITE = 0x90AB  # RunTextScript's JMP ($20) through ScriptResumePtr

# Opcode -> (length, how it moves the script counter). Each was read from its
# handler in the dispatch table at $906F; `$F0` has no entry there.
NEXT, JUMP, BRANCH, CALL, RETURN, STOP, NATIVE = (
    "next",
    "jump",
    "branch",
    "call",
    "return",
    "stop",
    "native",
)
OPCODES: dict[int, tuple[int, str]] = {
    0xF1: (2, NEXT),  # start portrait animation n
    0xF2: (5, BRANCH),  # if [lo hi] == 0 go to target (bytes 3-4)
    0xF3: (3, NEXT),  # set cursor x, y
    0xF4: (6, BRANCH),  # if v >= [lo hi] go to target (bytes 4-5)
    0xF5: (3, JUMP),  # go to target
    0xF6: (4, NEXT),  # store v to [lo hi]
    0xF7: (3, NATIVE),  # install a per-frame native callback, then continue
    0xF8: (3, NATIVE),  # call native code, then continue
    0xF9: (2, NEXT),  # select window geometry n
    0xFA: (1, NEXT),  # clear the window
    0xFB: (1, NEXT),  # newline
    0xFC: (1, NEXT),  # wait for a button, then continue
    0xFD: (1, STOP),  # stop the script
    0xFE: (3, CALL),  # call a script subroutine
    0xFF: (1, RETURN),  # return from it
}


@dataclass(frozen=True)
class ScriptPointerTable:
    """Words that `ScriptPtr` is loaded from."""

    bank: int
    cpu: int
    count: int
    why: str


# Each count comes from the index its loader uses.
SCRIPT_POINTER_TABLES = (
    ScriptPointerTable(12, 0xA9A5, 6, "by A*2 at $A8DC; its callers pass 0-5"),
    ScriptPointerTable(
        12, 0x940A, 12, "(OpponentGolferIdentity-1)*4 + 0 or 2 at random, $93DF"
    ),
    ScriptPointerTable(12, 0x9422, 12, "the same, the other branch of $93C8"),
    ScriptPointerTable(
        12, 0x92C3, 12, "OpponentIntroScriptPtrTable, the same at $92B2"
    ),
    # Based at $938B and $9396 by result, then 0 or 2 at random from $93F0.
    ScriptPointerTable(12, 0x9402, 2, "random pick at $93F0, based at $938B"),
    ScriptPointerTable(12, 0x9406, 2, "random pick at $93F0, based at $9396"),
    # (A AND 3) could be 3, but a fourth word would be the first two bytes of the
    # script at $A078 ($0FF6), so the index never gets there.
    ScriptPointerTable(11, 0xA072, 3, "by (A AND 3)*2 at $A061, native code"),
    ScriptPointerTable(11, 0x962E, 13, "by TotalMoney bracket 0-12 at $95F9"),
    ScriptPointerTable(11, 0xB812, 3, "course name, by CurrCourse at $B800"),
    ScriptPointerTable(11, 0xB83E, 2, "18 or 36, by (GolfGameMode AND 3)-1 at $B827"),
    ScriptPointerTable(11, 0xB8C1, 4, "ordinal suffix, by 1-4 at $B8A4"),
)


@dataclass
class Problem:
    kind: str
    cpu: int
    detail: str = ""


@dataclass
class ScriptWalk:
    """What walking the scripts found."""

    covered: set[int] = field(default_factory=set)  # bank 11 CPU addresses
    entries: dict[int, str] = field(default_factory=dict)  # script start -> found by
    native: dict[int, str] = field(default_factory=dict)  # code address -> found by
    windows: set[int] = field(default_factory=set)  # $F9 operands
    problems: list[Problem] = field(default_factory=list)


def _prg(cpu: int) -> int:
    return SCRIPT_BANK * PRG_BANK_SIZE + (cpu - 0x8000)


def walk_scripts(
    rom, entries: dict[int, str], redirects: frozenset[int] = frozenset()
) -> ScriptWalk:
    """Follow every path through the scripts that start at `entries`.

    `redirects` are native targets that load `ScriptPtr` themselves, so an
    `$F8` calling one doesn't continue with the bytes after it.
    """
    bank = rom.read_switched(0x8000, SCRIPT_BANK, PRG_BANK_SIZE)
    walk = ScriptWalk(entries=dict(entries))
    work = list(entries)
    seen: set[int] = set()

    def queue(target: int, at: int) -> None:
        if 0x8000 <= target < 0xC000:
            work.append(target)
        elif target >= 0x6000 or target < 0x0800:
            pass  # RAM: `FE FF 06` calls the name fragment built at $06FF
        else:
            walk.problems.append(
                Problem("target outside bank 11", at, f"${target:04X}")
            )

    while work:
        pc = work.pop()
        while pc not in seen:
            if not 0x8000 <= pc < 0xC000:
                walk.problems.append(Problem("ran off the end of bank 11", pc))
                break
            seen.add(pc)
            op = bank[pc - 0x8000]
            if op < 0xF0:
                walk.covered.add(pc)
                pc += 1
                continue
            if op not in OPCODES:
                walk.problems.append(Problem(f"no handler for ${op:02X}", pc))
                break
            length, flow = OPCODES[op]
            args = bank[pc - 0x8000 + 1 : pc - 0x8000 + length]
            walk.covered.update(range(pc, pc + length))
            word = args[0] | (args[1] << 8) if len(args) >= 2 else 0
            if flow == JUMP:
                queue(word, pc)
                break
            if flow == CALL:
                queue(word, pc)
            elif flow == BRANCH:
                queue(args[-2] | (args[-1] << 8), pc)
            elif flow == NATIVE:
                what = "callback" if op == 0xF7 else "native call"
                walk.native.setdefault(word, f"script {what} at ${pc:04X}")
                if op == 0xF8 and word in redirects:
                    break
            elif op == 0xF9:
                walk.windows.add(args[0])
            elif flow in (RETURN, STOP):
                break
            pc += length
    return walk


def script_entries(rom, result: TraceResult) -> dict[int, str]:
    """Script addresses that traced code loads into `ScriptPtr`, and the tables."""
    data = rom.read_prg(0, rom.prg_size)
    lo_sites, hi_sites = [], []
    for prg in range(len(data) - 2):
        if result.marks[prg] != OPCODE or data[prg] != 0x8D or data[prg + 2] != 0x06:
            continue
        if data[prg + 1] == SCRIPT_PTR & 0xFF:
            lo_sites.append(prg)
        elif data[prg + 1] == (SCRIPT_PTR + 1) & 0xFF:
            hi_sites.append(prg)

    def immediate_before(prg: int) -> int | None:
        if result.marks[prg - 2] == OPCODE and data[prg - 2] == 0xA9:
            return data[prg - 1]
        return None

    entries: dict[int, str] = {}
    for lo in lo_sites:
        # LDA #lo / STA ScriptPtr, then LDA #hi / STA ScriptPtr+1 just after.
        hi = next((h for h in hi_sites if 0 < h - lo <= 12), None)
        if hi is None:
            continue
        lo_value, hi_value = immediate_before(lo), immediate_before(hi)
        if lo_value is None or hi_value is None:
            continue
        bank, cpu = lo // PRG_BANK_SIZE, 0x8000 + lo % PRG_BANK_SIZE
        entries.setdefault(lo_value | hi_value << 8, f"set at bank {bank} ${cpu:04X}")

    for table in SCRIPT_POINTER_TABLES:
        for i in range(table.count):
            at = table.bank * PRG_BANK_SIZE + table.cpu - 0x8000 + 2 * i
            entries.setdefault(
                data[at] | data[at + 1] << 8,
                f"entry {i} of bank {table.bank} ${table.cpu:04X} ({table.why})",
            )
    # Scripts are bank 11 addresses; `$06FF` is the name fragment built in RAM.
    return {cpu: how for cpu, how in entries.items() if 0x8000 <= cpu < 0xC000}


NAME_FRAGMENT = 0x06FF  # RAM script that natives build and call, ending in $FF


def writes_script_ptr(rom, labels, cpu: int) -> bool:
    """Does the code at bank 11 `cpu` (and what it calls) pick the next script?

    A store of `#<$06FF` doesn't count: that native saves `ScriptPtr` as the
    return address and calls the fragment it built in RAM (`$B84E`), whose
    `$FF` returns to the bytes after the `$F8`.
    """
    sub = trace(rom, labels, [Seed(cpu, SCRIPT_BANK, "native")], pointer_tables=())
    data = rom.read_prg(0, rom.prg_size)
    return any(
        sub.marks[prg] == OPCODE
        and data[prg] == 0x8D
        and data[prg + 1] == SCRIPT_PTR & 0xFF
        and data[prg + 2] == SCRIPT_PTR >> 8
        and not (data[prg - 2] == 0xA9 and data[prg - 1] == NAME_FRAGMENT & 0xFF)
        for prg in range(2, len(data) - 2)
    )


def trace_with_scripts(
    reader,
    labels=None,
    seeds: list[Seed] | None = None,
    scripts: dict[int, str] | None = None,
) -> tuple[TraceResult, ScriptWalk]:
    """Trace, walk the scripts, trace again from their native code, until stable.

    `scripts` are script entries found some other way than code storing to
    `ScriptPtr` (an object stream's `$F6` stores: `stream_scripts`).
    """
    base = vector_seeds(reader) if seeds is None else seeds
    extra: dict[int, str] = {}
    redirects: set[int] = set()
    while True:
        result = trace(
            reader,
            labels,
            base + [Seed(cpu, SCRIPT_BANK, how) for cpu, how in sorted(extra.items())],
        )
        entries = {**(scripts or {}), **script_entries(reader, result)}
        walk = walk_scripts(reader, entries, frozenset(redirects))
        new = {cpu: how for cpu, how in walk.native.items() if cpu not in extra}
        if not new:
            break
        extra.update(new)
        redirects.update(c for c in new if writes_script_ptr(reader, labels, c))
    # The walker answers these two: their targets are the native addresses above.
    answered = {_prg(CALL_NATIVE_SITE), _prg(RESUME_CALLBACK_SITE)}
    result.unresolved = [f for f in result.unresolved if f.prg not in answered]
    return result, walk
