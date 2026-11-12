"""Spike: which contiguous parts of a switchable bank could move to another bank.

Runs the code trace, lists every reference that starts or ends in the bank, and scores
each contiguous region by the references that cross its boundary: calls in and out
(each distinct target needs a far-call stub), data read across the boundary, and
branches or fall-through across it (which rule a region out). `docs/bank13_relocation.md`
is the report this was written for.

    uv run python -m tools.spikes.bank_split nes_open_us.nes --labels <file.mlb>
    uv run python -m tools.spikes.bank_split nes_open_us.nes --labels <file.mlb> \
        --region AD0A-B9A7

Without `--region` it prints the cheapest regions in each size band; with it, every
crossing reference of the regions named. A reference the trace cannot see (a pointer
held in a data table, an address computed at run time) is not counted, and an
"immediate pair" is only a candidate pointer: read the code before trusting either
way. Experimental and unmaintained; see tools/spikes/README.md.
"""

import argparse
from dataclasses import dataclass

import numpy as np

from golf.core import rom_trace
from golf.core.mlb_labels import LabelStore
from golf.core.object_script import trace_everything
from golf.core.rom_analysis import INLINE_ARG_ROUTINES, TRIPLES
from golf.core.rom_reader import RomReader

BANK_SIZE = 0x4000
FIXED_BANK = 15
JSR, JMP, JMP_IND, RTS, RTI = 0x20, 0x4C, 0x6C, 0x60, 0x40
SIZE_BANDS = ((800, 1500), (1500, 2500), (2500, 4000), (4000, 6000), (6000, 12000))

#: kinds of reference. FLOW cannot cross a boundary; CALL needs a stub; DATA must move
#: with its reader or be duplicated.
FLOW, CALL, DATA = 0, 1, 2


@dataclass(frozen=True)
class Edge:
    source: int | None  # CPU address in the bank, or None: the fixed or another bank
    target: int  # CPU address in the bank
    kind: int
    how: str


@dataclass(frozen=True)
class Survey:
    edges: list[Edge]
    far_calls_out: list[tuple[int, int, int]]  # (site, bank, target)
    bounds: list[int]  # addresses a region may start or end at
    code_bytes: list[bool]  # per byte of the bank


def _in_bank(cpu: int) -> bool:
    return 0x8000 <= cpu < 0xC000


def survey(reader: RomReader, labels: LabelStore, bank: int) -> Survey:
    result, _, _ = trace_everything(reader, labels)
    rom = reader.read_prg(0, reader.prg_size)
    lengths = rom_trace._opcode_lengths()
    edges: list[Edge] = []
    far_calls_out = []
    falls_into = set()

    for prg, contexts in sorted(result.contexts.items()):
        own = prg // BANK_SIZE
        cpu = prg % BANK_SIZE + (0xC000 if own == FIXED_BANK else 0x8000)
        opcode, length = rom[prg], lengths[rom[prg]]
        sees_bank = own == bank or (own == FIXED_BANK and bank in contexts)
        source = cpu if own == bank else None
        operand = rom[prg + 1] | rom[prg + 2] << 8 if length == 3 else None
        following = prg + length

        if opcode == JSR and operand is not None:
            key = (None if operand >= 0xC000 else own, operand)
            spec = INLINE_ARG_ROUTINES.get(key)
            if spec is not None:
                size = spec.measure(rom[following : following + 256])
                args = rom[following : following + size]
                following += size
                if spec.style == "bank_addr":
                    to_bank, target = args[0], args[1] | args[2] << 8
                    if spec.name != "ExecuteFarCall":
                        if to_bank == bank:
                            edges.append(Edge(source, target, DATA, spec.name))
                    elif to_bank == bank and _in_bank(target):
                        edges.append(Edge(source, target, CALL, "far call"))
                    elif own == bank and to_bank != bank:
                        far_calls_out.append((cpu, to_bank, target))
                elif spec.style in ("word", "copy_block") and sees_bank:
                    target = args[0] | args[1] << 8
                    if _in_bank(target):
                        edges.append(Edge(source, target, DATA, spec.name))
                elif spec.kind == TRIPLES and sees_bank:
                    for i in range(0, size - 1, 3):
                        target = args[i + 1] | args[i + 2] << 8
                        if _in_bank(target):
                            edges.append(Edge(source, target, CALL, "dispatch table"))

        if own == bank:
            if opcode in rom_trace.BRANCH_OPCODES:
                offset = rom[prg + 1]
                target = cpu + 2 + (offset - 256 if offset > 127 else offset)
                edges.append(Edge(cpu, target, FLOW, "branch"))
            if opcode not in (RTS, RTI, JMP, JMP_IND) and following // BANK_SIZE == own:
                target = following % BANK_SIZE + 0x8000
                edges.append(Edge(cpu, target, FLOW, "falls through"))
                falls_into.add(target)

        if sees_bank and operand is not None and _in_bank(operand):
            if opcode in (JSR, JMP):
                edges.append(Edge(source, operand, CALL, "JSR/JMP"))
            elif opcode != JMP_IND and opcode not in rom_trace._MAPPER_WRITES:
                edges.append(Edge(source, operand, DATA, "absolute operand"))

    for reader_ in rom_trace.data_readers(rom, result):
        if reader_.how == "immediate pair" and reader_.target // BANK_SIZE == bank:
            site_bank = reader_.site // BANK_SIZE
            source = reader_.site % BANK_SIZE + 0x8000 if site_bank == bank else None
            target = reader_.target % BANK_SIZE + 0x8000
            edges.append(Edge(source, target, DATA, "immediate pair (candidate)"))
    for table in rom_trace.CODE_POINTER_TABLES:
        if table.bank == bank:
            for target in table.targets(rom):
                edges.append(Edge(None, target, CALL, f"entry in {table.name}"))

    base = bank * BANK_SIZE
    names = [
        result.data_names[base + i] or ("code" if result.marks[base + i] else "none")
        for i in range(BANK_SIZE)
    ]
    bounds = {0x8000, 0xC000}
    for i in range(1, BANK_SIZE):
        starts_run = (
            names[i] == "code"
            and result.marks[base + i] == rom_trace.OPCODE
            and 0x8000 + i not in falls_into
        )
        if names[i] != names[i - 1] or starts_run:
            bounds.add(0x8000 + i)
    return Survey(edges, far_calls_out, sorted(bounds), [n == "code" for n in names])


def _name(labels: LabelStore, bank: int, cpu: int | None) -> str:
    if cpu is None:
        return "(the fixed or another bank)"
    label = labels.lookup("NesPrgRom", bank * BANK_SIZE + cpu - 0x8000)
    return f"${cpu:04X}" + (f" {label.name}" if label else "")


def print_region(found: Survey, labels: LabelStore, bank: int, start: int, end: int):
    print(f"=== ${start:04X}-${end:04X}, {end - start} bytes")
    seen = set()
    for edge in sorted(found.edges, key=lambda e: (e.kind, e.target, e.source or 0)):
        inside_source = edge.source is not None and start <= edge.source < end
        inside_target = start <= edge.target < end
        if inside_source == inside_target or edge in seen:
            continue
        seen.add(edge)
        direction = "in " if inside_target else "out"
        kind = ("FLOW", "call", "data")[edge.kind]
        print(
            f"  {direction} {kind}  {_name(labels, bank, edge.source)} -> "
            f"{_name(labels, bank, edge.target)}  ({edge.how})"
        )
    for site, to_bank, target in found.far_calls_out:
        if start <= site < end:
            print(f"  far call at ${site:04X} -> bank {to_bank} ${target:04X}")


def print_candidates(found: Survey) -> None:
    edges = found.edges
    source = np.array([e.source or 0 for e in edges])
    target = np.array([e.target for e in edges])
    kind = np.array([e.kind for e in edges])
    rows = []
    for i, start in enumerate(found.bounds):
        for end in found.bounds[i + 1 :]:
            if not SIZE_BANDS[0][0] <= end - start < SIZE_BANDS[-1][1]:
                continue
            source_in = (source >= start) & (source < end)
            target_in = (target >= start) & (target < end)
            entering, leaving = ~source_in & target_in, source_in & ~target_in
            if ((entering | leaving) & (kind == FLOW)).any():
                continue
            calls_in = len(set(target[entering & (kind == CALL)]))
            calls_out = len(set(target[leaving & (kind == CALL)]))
            data_in = len(set(target[entering & (kind == DATA)]))
            data_out = len(set(target[leaving & (kind == DATA)]))
            cost = calls_in + calls_out + 3 * (data_in + data_out)
            rows.append((cost, start, end, calls_in, calls_out, data_in, data_out))
    for low, high in SIZE_BANDS:
        print(f"--- {low} to {high} bytes")
        shown: list[tuple[int, int]] = []
        band = [row for row in rows if low <= row[2] - row[1] < high]
        for row in sorted(band, key=lambda row: row[0] / (row[2] - row[1])):
            cost, start, end, calls_in, calls_out, data_in, data_out = row
            if any(abs(start - a) < 300 and abs(end - b) < 300 for a, b in shown):
                continue
            shown.append((start, end))
            code = sum(found.code_bytes[start - 0x8000 : end - 0x8000])
            print(
                f"${start:04X}-${end:04X}  {end - start:5} bytes ({code} code)  "
                f"call targets in {calls_in}, out {calls_out}; "
                f"data in {data_in}, out {data_out}"
            )
            if len(shown) == 6:
                break


def main() -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("rom")
    parser.add_argument("--labels", required=True)
    parser.add_argument("--bank", type=int, default=13)
    parser.add_argument(
        "--region",
        action="append",
        default=[],
        help="START-END in hex CPU addresses, END exclusive; repeatable",
    )
    args = parser.parse_args()
    labels = LabelStore.load(args.labels)
    found = survey(RomReader(args.rom), labels, args.bank)
    if not args.region:
        print_candidates(found)
    for region in args.region:
        start, end = (int(part, 16) for part in region.split("-"))
        print_region(found, labels, args.bank, start, end)


if __name__ == "__main__":
    main()
