#!/usr/bin/env python3
"""
NES Open Tournament Golf - ROM Peek Tool

Targeted, scriptable reads of ROM bytes for reverse-engineering work, so
disassembly/patch investigations don't require hand-written one-off Python
each time. Wraps RomReader and golf.core.rom_utils address translation.

Address argument grammar (shared by all subcommands):
  - "$XXXX"  CPU address. Uses the fixed bank ($C000-$FFFF) unless --bank
             is given, in which case it's resolved as a switchable-bank
             address ($8000-$BFFF) in that bank.
  - "0xNNNN" or bare hex digits: a raw PRG ROM offset, used as-is. This
             matches the PRG-offset-style labels (e.g. "3E46D") already
             used in disassembly notes for this project.

Examples:
    golf-rom-peek rom.nes read '$E4F9' --length 10
    golf-rom-peek rom.nes read '$AF14' --bank 2 --length 6
    golf-rom-peek rom.nes read 0x3CA40 --length 192 --format python
    golf-rom-peek rom.nes find '20 84 CE' --follow 2
    golf-rom-peek rom.nes find '20 84 CE' --follow 2 --flag-range '$E4F9-$E516'
    golf-rom-peek rom.nes addr '$E4F9' --bank 2
    golf-rom-peek rom.nes disasm '$AD43' --bank 2 --count 15

    # Annotate output with symbol names from a Mesen .mlb label file.
    # --labels must come before the subcommand (a top-level option).
    golf-rom-peek rom.nes --labels notes.mlb disasm '$AD43' --bank 2 --count 15
    golf-rom-peek rom.nes --labels notes.mlb label '$AD5D'
    golf-rom-peek rom.nes --labels notes.mlb label '001A' --type ram
    golf-rom-peek rom.nes --labels notes.mlb find-label ScrollX

    # Text, in every encoding the game stores it in (golf.core.rom_text).
    golf-rom-peek rom.nes --labels notes.mlb strings --bank 12
    golf-rom-peek rom.nes --labels notes.mlb find-text 'select the course'
    golf-rom-peek rom.nes --labels notes.mlb find-text 'DRIVER' --relative

The `disasm` subcommand decodes opcodes with py65, a project dependency - it is
installed by `uv sync` along with everything else, so `disasm` always works.
"""

import argparse
import re
import sys

from golf.core.known_data import known_regions, plan_labels
from golf.core.mlb_labels import TYPE_ALIASES, Label, LabelStore, describe
from golf.core.object_script import trace_everything
from golf.core.rom_analysis import (
    disassemble,
    find_code_references,
    find_data_references,
    find_pointer_references,
    is_data_range,
)
from golf.core.rom_reader import RomReader
from golf.core.rom_text import (
    TextRun,
    encodings,
    find_text,
    nametable_screens,
    relative_search,
    scan,
)
from golf.core.rom_trace import (
    NONE,
    UNCALLED,
    Seed,
    data_readers,
    label_seeds,
    mark_uncalled,
    trace,
    unreached_roots,
    vector_seeds,
)
from golf.core.rom_utils import (
    FIXED_BANK_PRG_START,
    PRG_BANK_SIZE,
    cpu_to_prg_fixed,
    cpu_to_prg_switched,
    prg_to_bank_and_cpu,
)
from golf.core.rom_utils import (
    parse_cpu_or_prg_address as parse_address,
)
from golf.core.text_script import script_listing


def format_bytes(data: bytes, fmt: str) -> str:
    if fmt == "python":
        return "bytes([" + ", ".join(f"0x{b:02X}" for b in data) + "])"
    if fmt == "ascii":
        return "".join(chr(b) if 32 <= b < 127 else "." for b in data)
    return data.hex(" ").upper()


def cmd_read(reader: RomReader, args, labels: LabelStore | None) -> None:
    prg_offset = parse_address(args.address, args.bank)
    data = reader.read_prg(prg_offset, args.length)
    print(format_bytes(data, args.format))
    if labels is not None:
        label = labels.lookup("NesPrgRom", prg_offset)
        if label is not None:
            print(f"label: {describe(label, prg_offset)}")


def cmd_addr(_reader: RomReader, args, labels: LabelStore | None) -> None:
    if args.address.startswith("$"):
        cpu_addr = int(args.address[1:], 16)
        if args.bank is not None:
            prg_offset = cpu_to_prg_switched(cpu_addr, args.bank)
            bank = args.bank
        else:
            prg_offset = cpu_to_prg_fixed(cpu_addr)
            bank = 15
    else:
        prg_offset = int(args.address, 16)
        bank, cpu_addr = prg_to_bank_and_cpu(prg_offset)
    print(f"bank={bank} cpu=${cpu_addr:04X} prg=0x{prg_offset:X}")
    if labels is not None:
        label = labels.lookup("NesPrgRom", prg_offset)
        if label is not None:
            print(f"label: {describe(label, prg_offset)}")


def _bank_region(bank: int) -> tuple[int, int]:
    if bank == 15:
        return FIXED_BANK_PRG_START, FIXED_BANK_PRG_START + PRG_BANK_SIZE
    return bank * PRG_BANK_SIZE, (bank + 1) * PRG_BANK_SIZE


def cmd_find(reader: RomReader, args, labels: LabelStore | None) -> None:
    pattern = bytes.fromhex(args.pattern.replace(" ", ""))

    flag_low = flag_high = None
    if args.flag_range:
        lo_str, hi_str = args.flag_range.split("-")
        flag_low = int(lo_str.strip().lstrip("$"), 16)
        flag_high = int(hi_str.strip().lstrip("$"), 16)

    if args.bank is not None:
        region_start, region_end = _bank_region(args.bank)
    else:
        region_start, region_end = 0, reader.prg_size

    full = reader.read_prg(region_start, region_end - region_start)

    hits = 0
    search_from = 0
    while True:
        idx = full.find(pattern, search_from)
        if idx == -1:
            break
        hits += 1
        prg_offset = region_start + idx
        bank, cpu_addr = prg_to_bank_and_cpu(prg_offset)
        line = f"bank={bank:2} cpu=${cpu_addr:04X} prg=0x{prg_offset:X}"

        if args.follow:
            follow_start = idx + len(pattern)
            follow_bytes = full[follow_start : follow_start + args.follow]
            if args.follow == 2:
                ptr = follow_bytes[0] | (follow_bytes[1] << 8)
                line += f"  follow=${ptr:04X}"
                if (
                    flag_low is not None
                    and flag_high is not None
                    and flag_low <= ptr <= flag_high
                ):
                    line += "  <-- in flagged range"
            else:
                line += f"  follow={follow_bytes.hex(' ').upper()}"

        if labels is not None:
            label = labels.lookup("NesPrgRom", prg_offset)
            if label is not None:
                line += f"  label={describe(label, prg_offset)}"

        print(line)
        search_from = idx + 1

    if hits == 0:
        print("No matches found.")


_OPERAND_RE = re.compile(r"(?<!#)\$([0-9A-Fa-f]{2,4})\b")


def _operand_label(addr: int, bank: int | None, labels: LabelStore) -> Label | None:
    """Best-effort resolution of a disassembly operand address to a label.

    Zero-page/absolute RAM and PPU/APU register addresses map straight to
    CPU space. $8000-$FFFF operands are resolved against the bank the
    instructions were disassembled in (disasm doesn't track bank switches
    mid-listing, so this assumes the whole run stays in one bank).
    """
    if addr < 0x2000:
        return labels.lookup("NesInternalRam", addr & 0x07FF)
    if 0x2000 <= addr < 0x4020:
        mapped = 0x2000 + ((addr - 0x2000) % 8) if addr < 0x4000 else addr
        return labels.lookup("NesMemory", mapped)
    if 0x6000 <= addr < 0x8000:
        return labels.lookup("NesSaveRam", addr - 0x6000)
    if 0x8000 <= addr <= 0xBFFF and bank is not None:
        return labels.lookup("NesPrgRom", cpu_to_prg_switched(addr, bank))
    if 0xC000 <= addr <= 0xFFFF:
        return labels.lookup("NesPrgRom", cpu_to_prg_fixed(addr))
    return None


def _symbolicate(text: str, bank: int | None, labels: LabelStore) -> str:
    def repl(m: re.Match) -> str:
        addr = int(m.group(1), 16)
        label = _operand_label(addr, bank, labels)
        if label is None:
            return m.group(0)
        return f"{label.name}[{m.group(0)}]"

    return _OPERAND_RE.sub(repl, text)


def cmd_disasm(reader: RomReader, args, labels: LabelStore | None) -> None:
    prg_offset = parse_address(args.address, args.bank)
    listing = disassemble(
        reader,
        prg_offset,
        count=None if args.routine else args.count,
        routine=args.routine,
        max_instructions=args.max,
        labels=labels,
        expand_data=not args.no_data_ranges,
        inline_args=not args.no_inline_args,
    )

    for row in listing.rows:
        if row.label:
            label = labels.lookup("NesPrgRom", row.prg) if labels else None
            print(f"{describe(label, row.prg) if label else row.label}:")
        text = row.text
        if row.kind == "code" and labels is not None:
            text = _symbolicate(text, args.bank, labels)
        elif row.kind == "inline" and row.note:
            text = f"{text}".ljust(44) + f"; inline args for {row.note}"
        raw = row.raw.hex(" ").upper()
        if len(raw) > 8:
            raw = raw[:8] + ".."
        print(f"${row.cpu:04X}  {raw:<10}  {text}")

    if args.routine or not listing.complete:
        print()
        marker = "" if listing.complete else "INCOMPLETE - "
        print(f"[{marker}stopped: {listing.stop_reason}]")
        if not listing.complete:
            print(
                "[the routine may continue past this point; re-run with a larger "
                "--max or an explicit --count]"
            )


def _print_refs(refs, indent="  ") -> None:
    for r in refs:
        line = f"{indent}{r.kind:<15} bank {r.bank:2}  ${r.cpu:04X}  prg 0x{r.prg:05X}"
        if r.detail:
            line += f"  {r.detail}"
        if r.in_data_range:
            line += (
                f"   <-- inside data range {r.in_data_range}, probably a coincidence"
            )
        elif r.aligned is False:
            line += "   <-- lands mid-instruction, byte coincidence"
        elif r.aligned is None:
            line += "   [UNVERIFIED: no nearby code label to check alignment against]"
        print(line)


def cmd_find_refs(reader: RomReader, args, labels: LabelStore | None) -> None:
    if args.type != "prg":
        addr = int(args.address.lstrip("$"), 16)
        direct, reaching = find_data_references(reader, addr, labels, args.reach)
        print(f"${addr:04X} ({args.type})")
        if direct:
            print(f"\n  direct references ({len(direct)}):")
            _print_refs(direct, "    ")
        else:
            print("\n  direct references: NONE FOUND")
        if args.reach:
            if reaching:
                print(
                    f"\n  indexed bases within {args.reach} bytes below, which could reach "
                    "this address if the index register ranges far enough:"
                )
                for base in sorted(reaching):
                    print(f"    ${base:04X},X/Y  ({len(reaching[base])} sites)")
                    _print_refs(reaching[base], "      ")
                print(
                    "\n  [how far X/Y actually range is NOT determined here - read each "
                    "site before concluding this address is safe]"
                )
            else:
                print(f"\n  no indexed bases within {args.reach} bytes below")
        if not direct:
            _print_null_warning(reader, addr, labels, args, code=False)
        return

    prg_offset = parse_address(args.address, args.bank)
    bank, cpu_addr = prg_to_bank_and_cpu(prg_offset)
    report = find_code_references(reader, cpu_addr, bank, labels)

    print(f"{report.target_desc}  prg 0x{prg_offset:05X}")
    if labels is not None:
        label = labels.lookup("NesPrgRom", prg_offset)
        if label is not None:
            print(f"  {describe(label, prg_offset)}")

    confirmed = report.confirmed
    suspect = [r for r in report.refs if r.suspect]
    if confirmed:
        unverified = len(report.unverified)
        suffix = f", {unverified} unverified" if unverified else ""
        print(f"\n  references ({len(confirmed)}{suffix}):")
        _print_refs(confirmed)
    else:
        print("\n  references: NONE FOUND")
    if suspect:
        print(
            f"\n  discarded as coincidence ({len(suspect)}) - byte matches inside data ranges:"
        )
        _print_refs(suspect)

    print("\n  searched:")
    for item in report.searched:
        print(f"    - {item}")

    if report.empty:
        _print_null_warning(reader, cpu_addr, labels, args, code=True, report=report)


def _print_null_warning(reader, addr, labels, args, code: bool, report=None) -> None:
    print("\n  NOT COVERED by this search - a null result is NOT evidence that this")
    print("  address is unused:")
    items = (
        report.not_covered
        if report is not None
        else [
            "any access that computes the address at run time",
            "DMA, the decompressor, and anything the PPU reads directly",
        ]
    )
    for item in items:
        print(f"    - {item}")

    hits = find_pointer_references(reader, addr, labels)
    print(
        f"\n  escalating: {len(hits)} raw byte-pair(s) matching ${addr:04X} in the ROM."
    )
    print(
        "  For a pointer search the usual reading is inverted - a hit inside a labeled"
    )
    print("  table is a LIKELY indirect reference, not a coincidence:")
    for hit in hits[:25]:
        where = (
            f"in {hit.in_data_range}  <-- likely a real pointer-table entry"
            if hit.in_data_range
            else "not in any labeled range"
        )
        print(f"    bank {hit.bank:2}  ${hit.cpu:04X}  prg 0x{hit.prg:05X}  {where}")
    if len(hits) > 25:
        print(f"    ... and {len(hits) - 25} more")
    print("\n  [confirm with a Mesen breakpoint before treating this address as dead,")
    print(
        "   then record the result in the .mlb comment or a doc so it isn't re-derived]"
    )


_STUB_RE = re.compile(r"^L[0-9A-F]?_?[0-9A-F]{4}(_|$)")


def _where(labels: LabelStore | None, prg: int) -> str:
    bank, cpu = prg_to_bank_and_cpu(prg)
    text = f"bank {bank:2}  ${cpu:04X}  prg 0x{prg:05X}"
    if labels is not None:
        label = labels.lookup("NesPrgRom", prg)
        if label is not None:
            text += f"  {label.name}" + (
                "" if label.start == prg else f"+{prg - label.start}"
            )
    return text


def _nearest_label_before(labels: LabelStore | None, prg: int) -> str:
    if labels is None:
        return ""
    best = None
    for label, _ in labels.iter_merged():
        if (
            label.type == "NesPrgRom"
            and label.start <= prg
            and prg - label.start < 0x4000
            and (best is None or label.start > best.start)
        ):
            best = label
    return f"after {best.name}" if best is not None else ""


def cmd_trace(reader: RomReader, args, labels: LabelStore | None) -> None:
    if args.start:
        prg = parse_address(args.start, args.bank)
        bank, cpu = prg_to_bank_and_cpu(prg)
        seeds = [Seed(cpu, None if bank == 15 else bank, f"--from {args.start}")]
    else:
        seeds = vector_seeds(reader)
        if args.seed_labels:
            if labels is None:
                print("Error: --seed-labels needs --labels", file=sys.stderr)
                sys.exit(1)
            seeds += label_seeds(labels)
    if args.start:
        result = trace(reader, labels, seeds)
    else:
        result, walk, objects = trace_everything(reader, labels, seeds)
        print(
            f"scene objects: {len(objects.records)} records, "
            f"{sum(len(c) for c in objects.covered.values())} stream bytes, "
            f"{len(objects.frames)} sprites"
        )
        for problem in objects.problems:
            print(
                f"  object problem: {problem.kind} at bank {problem.bank} "
                f"${problem.cpu:04X} {problem.detail}"
            )
        print(
            f"text scripts: {len(walk.entries)} entry points, {len(walk.covered)} "
            f"bytes, {len(walk.native)} native code addresses"
        )
        for problem in walk.problems:
            print(f"  script problem: {problem.kind} at ${problem.cpu:04X}")
    uncalled = None
    if labels is not None and not args.start and not args.seed_labels:
        uncalled = mark_uncalled(reader, labels, result)
    show = None if args.bank is None or args.start else args.bank

    def wanted(prg: int) -> bool:
        return show is None or prg_to_bank_and_cpu(prg)[0] == show

    print(
        f"seeds: {len(seeds)} ({'vectors' if not args.seed_labels else 'vectors + labels'}"
        f"{', one address' if args.start else ''})"
    )
    print("\nbank   code   data   both  uncalled  neither")
    totals = dict.fromkeys(("code", "data", "both", "uncalled", "neither"), 0)
    for b in range(result.banks):
        c = result.coverage(b)
        for k in totals:
            totals[k] += c[k]
        print(
            f"{b:4}  {c['code']:5}  {c['data']:5}  {c['both']:5}  {c['uncalled']:8}  "
            f"{c['neither']:7}"
        )
    print(
        f" all  {totals['code']:5}  {totals['data']:5}  {totals['both']:5}  "
        f"{totals['uncalled']:8}  {totals['neither']:7}"
    )
    print(
        "\n  code = reached as code; data = inside a range label; both = a conflict;"
        "\n  uncalled = code only unreached code labels lead to (dead, or a caller "
        "not yet found)"
    )

    unresolved = [f for f in result.unresolved if wanted(f.prg)]
    print(f"\nunresolved control flow ({len(unresolved)}):")
    for f in unresolved:
        ctx = "" if f.ctx is None else f"  [bank {f.ctx} mapped]"
        print(f"  {f.kind:<38} {_where(labels, f.prg)}  {f.detail}{ctx}")

    conflicts = [f for f in result.conflicts if wanted(f.prg)]
    print(
        f"\nconflicts ({len(conflicts)}) - a mis-trace, a wrong label, or a call that "
        "doesn't return:"
    )
    for f in conflicts:
        print(f"  {f.kind:<38} {_where(labels, f.prg)}  {f.detail}")
        if f.via is not None:
            print(f"  {'':<38}   reached from {_where(labels, f.via)}")
    if uncalled is not None:
        bad = [f for f in uncalled.conflicts if wanted(f.prg)]
        if bad:
            print(f"\nconflicts tracing the unreached code labels ({len(bad)}):")
            for f in bad:
                print(f"  {f.kind:<38} {_where(labels, f.prg)}  {f.detail}")

    gaps = sorted((g for g in result.gaps(show)), key=lambda g: g[1], reverse=True)
    print(
        f"\ngaps: {len(gaps)} runs, {sum(n for _, n in gaps)} bytes "
        f"(largest {min(args.gaps, len(gaps))} shown)"
    )
    for start, n in gaps[: args.gaps]:
        raw = reader.read_prg(start, n)
        fill = f"  all ${raw[0]:02X}" if len(set(raw)) == 1 else ""
        print(
            f"  {n:6} bytes  {_where(labels, start)}{fill}  {_nearest_label_before(labels, start)}"
        )

    entries = sorted(p for p in result.entries if wanted(p))
    exact = (
        {
            label.start: label
            for label, _ in labels.iter_merged()
            if label.type == "NesPrgRom"
        }
        if labels is not None
        else {}
    )
    unnamed = [p for p in entries if p not in exact or _STUB_RE.match(exact[p].name)]
    print(
        f"\nroutine entries reached: {len(entries)} "
        f"({len(unnamed)} without a full name)"
    )
    if args.unnamed:
        for p in unnamed:
            label = exact.get(p)
            have = label.name if label else "no label"
            print(f"  {_where(None, p)}  {have:<28} {result.entries[p]}")

    if labels is not None and not args.seed_labels:
        code_labels = [
            label
            for label in exact.values()
            if not is_data_range(label) and wanted(label.start)
        ]
        missed = sorted(
            (
                label
                for label in code_labels
                if result.marks[label.start] in (NONE, UNCALLED)
            ),
            key=lambda lb: lb.start,
        )
        print(
            f"\nsingle-address labels not reached as code: {len(missed)} of "
            f"{len(code_labels)} (data labeled without a range, or reached only "
            "through unresolved control flow)"
        )
        if args.unreached:
            seeds = [
                s for s in label_seeds(labels) if s.how[6:] in {m.name for m in missed}
            ]
            upstream = unreached_roots(reader, labels, seeds)
            roots = [m for m in missed if not upstream.get(m.start)]
            print(f"  {len(roots)} roots - nothing else unreached leads to them:")
            for label in missed:
                ups = upstream.get(label.start)
                if ups:
                    heads = sorted(exact[u].name for u in ups if not upstream.get(u))
                    under = f"under {', '.join(heads)}" if heads else "in a cycle"
                    print(f"      {_where(None, label.start)}  {label.name}  ({under})")
                else:
                    print(f"  ROOT {_where(None, label.start)}  {label.name}")


def cmd_readers(reader: RomReader, args, labels: LabelStore | None) -> None:
    result, _, _ = trace_everything(reader, labels)
    rom = reader.read_prg(0, reader.prg_size)
    found = data_readers(rom, result)
    if labels is not None:
        found += data_readers(rom, mark_uncalled(reader, labels, result))
    gaps = [(s, n) for s, n in result.gaps(args.bank) if n >= args.min]
    print(
        f"gaps: {len(gaps)} of {args.min}+ bytes; readers: absolute operands in "
        f"the bank mapped when they run, indexed bases up to {args.reach} bytes "
        "before a gap, immediate pairs (candidates)"
    )
    for start, n in gaps:
        end = start + n
        near = sorted(
            (
                r
                for r in found
                if start <= r.target < end
                or (r.indexed and start - args.reach <= r.target < start)
            ),
            key=lambda r: (r.target, r.site),
        )
        print(
            f"\n{n:5} bytes  {_where(labels, start)}  {_nearest_label_before(labels, start)}"
        )
        if not near:
            print("       no direct reader")
        for r in near:
            offset = r.target - start
            at = f"+{offset}" if offset >= 0 else str(offset)
            bank = "" if r.ctx is None else f"  [bank {r.ctx} mapped]"
            rows = disassemble(reader, r.site, count=1, expand_data=False).rows
            line = rows[0].text if rows else ""
            print(f"  {at:>6}  {_where(labels, r.site)}  {line}  ; {r.how}{bank}")


def cmd_known_data(reader: RomReader, args, labels: LabelStore | None) -> None:
    if labels is None:
        print("Error: known-data needs --labels", file=sys.stderr)
        sys.exit(1)
    result, walk, objects = trace_everything(reader, labels)
    regions = known_regions(reader, result, walk, objects)
    plan = plan_labels(regions, labels, result)

    print(f"known data regions: {len(regions)}, {sum(r.length for r in regions)} bytes")
    for kind in sorted({r.kind for r in regions}):
        of_kind = [r for r in regions if r.kind == kind]
        print(f"  {kind:<9} {len(of_kind):4}  {sum(r.length for r in of_kind):7} bytes")
    print(f"\nalready inside range labels: {plan.labeled_bytes} bytes")
    print(f"new range labels: {len(plan.new)}, {sum(r.length for r in plan.new)} bytes")
    print(f"single-address labels to widen into ranges: {len(plan.widen)}")
    for label, region in plan.widen:
        print(f"  {label.name}  -> {region.length} bytes")
    if plan.inside:
        print(f"\nsingle-address labels inside a new range ({len(plan.inside)}):")
        for label, region in plan.inside:
            print(f"  {_where(None, label.start)}  {label.name}  in {region.name}")
    if plan.overlaps:
        print(
            f"\nCONTRADICTIONS - regions that claim the same bytes ({len(plan.overlaps)}):"
        )
        for first, second in plan.overlaps:
            print(f"  {first.name} and {second.name} at {_where(None, second.start)}")
    if plan.code:
        print(
            f"\nCONTRADICTIONS - regions the trace decoded as code ({len(plan.code)}):"
        )
        for region in plan.code:
            print(
                f"  {_where(None, region.start)}  {region.length} bytes  {region.name}"
            )

    if args.list:
        print()
        for region in plan.new:
            print(
                f"  {_where(None, region.start)}  {region.length:5}  "
                f"{region.name}  ; {region.comment}"
            )

    if not args.write:
        print("\n(dry run; --write adds the new labels and widens the others)")
        return
    if plan.code or plan.inside or plan.overlaps:
        print(
            "\nError: resolve the contradictions above before writing", file=sys.stderr
        )
        sys.exit(1)
    for region in plan.new:
        if region.name is None:
            print(f"\nError: no name for {_where(None, region.start)}", file=sys.stderr)
            sys.exit(1)
        labels.base.add(
            Label("NesPrgRom", region.start, region.end, region.name, region.comment)
        )
    for label, region in plan.widen:
        labels.base.add(
            Label(
                "NesPrgRom",
                label.start,
                region.end,
                label.name,
                label.comment or region.comment,
            )
        )
    labels.save("base")
    print(
        f"\nwrote {len(plan.new)} labels and widened {len(plan.widen)} in "
        f"{labels.base_path}"
    )


def cmd_label(_reader: RomReader, args, labels: LabelStore | None) -> None:
    if labels is None:
        print("Error: --labels PATH is required for this command", file=sys.stderr)
        sys.exit(1)
    type_ = TYPE_ALIASES[args.type]
    if type_ == "NesPrgRom":
        addr = parse_address(args.address, args.bank)
    else:
        addr = int(args.address.lstrip("$"), 16)
    label = labels.lookup(type_, addr)
    if label is None:
        print("No label found.")
        return
    print(describe(label, addr))


def cmd_find_label(_reader: RomReader, args, labels: LabelStore | None) -> None:
    if labels is None:
        print("Error: --labels PATH is required for this command", file=sys.stderr)
        sys.exit(1)
    matches = labels.search_name(args.name)
    if not matches:
        print("No matches found.")
        return
    for label in matches:
        print(f"{label.type} {label.address_str}: {describe(label, label.start)}")


def _text_sources(reader: RomReader, args):
    """(PRG banks to read, decoded screens to read) for `strings` and `find-text`."""
    banks = set(args.bank) if args.bank else None
    prg_banks = set() if args.source == "nametables" else banks
    screens = None
    if args.source != "prg":
        screens = [
            s for s in nametable_screens(reader) if banks is None or s.bank in banks
        ]
    return prg_banks, screens


def _chosen_encodings(args):
    known = encodings()
    names = args.encoding or list(known)
    unknown = [n for n in names if n not in known]
    if unknown:
        raise ValueError(
            f"unknown encoding {', '.join(unknown)}; known: {', '.join(known)}"
        )
    return [known[n] for n in names]


def _text_label(run: TextRun, labels: LabelStore | None) -> str:
    if labels is None:
        return ""
    if run.screen is not None:
        s = run.screen
        prg = s.bank * PRG_BANK_SIZE + s.cpu - 0x8000
        label = labels.lookup("NesPrgRom", prg)
        name = describe(label, prg).split("  (")[0] if label else "unlabeled table"
        return f"  [{name}, decoded]"
    assert run.prg is not None
    label = labels.lookup("NesPrgRom", run.prg)
    return f"  [{describe(label, run.prg).split('  (')[0]}]" if label else ""


def _print_runs(runs: list[TextRun], labels: LabelStore | None) -> None:
    def order(run: TextRun):
        if run.screen is not None:
            return (1, run.screen.bank, run.screen.cpu, run.ppu)
        return (0, run.prg, 0, 0)

    for run in sorted(runs, key=order):
        print(
            f"{run.where():<28} {run.encoding:<15} {run.score:4.2f}  "
            f"{run.text!r}{_text_label(run, labels)}"
        )


def cmd_strings(reader: RomReader, args, labels: LabelStore | None) -> None:
    prg_banks, screens = _text_sources(reader, args)
    runs = scan(reader, _chosen_encodings(args), args.min, prg_banks, screens)
    if not args.all:
        runs = [r for r in runs if r.score >= args.min_score]
    _print_runs(runs, labels)
    print(f"\n{len(runs)} strings", end="")
    if not args.all:
        print(f" scoring {args.min_score} or more (--all for every run)", end="")
    print(".")


def cmd_find_text(reader: RomReader, args, labels: LabelStore | None) -> None:
    prg_banks, screens = _text_sources(reader, args)
    if args.relative:
        runs = relative_search(
            reader, args.text, prg_banks, screens, list(encodings().values())
        )
    else:
        runs = find_text(reader, args.text, _chosen_encodings(args), prg_banks, screens)
    if not runs:
        print("No matches found.", end="")
        if not args.relative:
            print(" Try --relative, which finds text in fonts not yet named.", end="")
        print()
        return
    _print_runs(runs, labels)


def cmd_script(reader: RomReader, args, labels: LabelStore | None) -> None:
    entries = [int(a.lstrip("$"), 16) for a in args.address]
    for line in script_listing(reader, entries, labels):
        print(line)


def main():
    parser = argparse.ArgumentParser(
        description="Targeted reads/searches of ROM bytes for RE work"
    )
    parser.add_argument("rom_file", help="ROM file to read")
    parser.add_argument(
        "--labels",
        help="Path to a Mesen .mlb label file to annotate output with symbol names "
        "(must appear before the subcommand)",
    )
    parser.add_argument(
        "--sidecar",
        help="Path to a sidecar .mlb overlay (defaults to '<labels>.sidecar.mlb' next to "
        "--labels, if it exists); entries here shadow --labels at the same address",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    read_parser = subparsers.add_parser("read", help="Read bytes at an address")
    read_parser.add_argument(
        "address", help="'$XXXX' CPU address or raw hex PRG offset"
    )
    read_parser.add_argument("--bank", type=int, help="Switchable bank number (0-14)")
    read_parser.add_argument(
        "--length", type=int, default=1, help="Number of bytes to read"
    )
    read_parser.add_argument(
        "--format",
        choices=["hex", "python", "ascii"],
        default="hex",
        help="Output format (default: hex)",
    )

    find_parser = subparsers.add_parser(
        "find", help="Search for a byte pattern across the ROM"
    )
    find_parser.add_argument("pattern", help="Hex byte pattern, e.g. '20 84 CE'")
    find_parser.add_argument(
        "--bank", type=int, help="Restrict search to one bank (0-14, or 15 for fixed)"
    )
    find_parser.add_argument(
        "--follow",
        type=int,
        help="Also show N bytes following each match (2 decodes as a little-endian pointer)",
    )
    find_parser.add_argument(
        "--flag-range",
        help="Flag matches whose --follow 2 pointer falls in 'LOW-HIGH', e.g. '$E4F9-$E516'",
    )

    addr_parser = subparsers.add_parser(
        "addr", help="Convert between CPU address and PRG offset (no ROM read)"
    )
    addr_parser.add_argument(
        "address", help="'$XXXX' CPU address or raw hex PRG offset"
    )
    addr_parser.add_argument("--bank", type=int, help="Switchable bank number (0-14)")

    disasm_parser = subparsers.add_parser(
        "disasm", help="Disassemble instructions starting at an address"
    )
    disasm_parser.add_argument(
        "address", help="'$XXXX' CPU address or raw hex PRG offset"
    )
    disasm_parser.add_argument("--bank", type=int, help="Switchable bank number (0-14)")
    disasm_parser.add_argument(
        "--count",
        type=int,
        default=10,
        help="Number of instructions to decode (default: 10)",
    )
    disasm_parser.add_argument(
        "--routine",
        action="store_true",
        help="Decode until the routine ends (terminator with no pending forward branch, "
        "or the start of a labeled data range) instead of a fixed --count",
    )
    disasm_parser.add_argument(
        "--max",
        type=int,
        default=200,
        help="Safety cap on rows for --routine (default: 200); output says so if hit",
    )
    disasm_parser.add_argument(
        "--no-inline-args",
        action="store_true",
        help="Decode inline arguments as instructions (the vanilla, desynchronizing behavior)",
    )
    disasm_parser.add_argument(
        "--no-data-ranges",
        action="store_true",
        help="Decode labeled data ranges as instructions instead of .db rows",
    )

    refs_parser = subparsers.add_parser(
        "find-refs",
        help="Find references to an address across every encoding (JSR/JMP/branch/far call/dispatch)",
    )
    refs_parser.add_argument(
        "address", help="'$XXXX' CPU address or raw hex PRG offset"
    )
    refs_parser.add_argument(
        "--bank", type=int, help="Bank the target lives in, for type=prg"
    )
    refs_parser.add_argument(
        "--type",
        choices=list(TYPE_ALIASES),
        default="prg",
        help="What kind of address the target is (default: prg)",
    )
    refs_parser.add_argument(
        "--reach",
        type=int,
        default=0,
        help="For RAM: also list indexed bases up to N bytes below that could reach it",
    )

    trace_parser = subparsers.add_parser(
        "trace",
        help="Follow control flow from the vectors and map code, data and gaps",
    )
    trace_parser.add_argument(
        "--from",
        dest="start",
        help="Trace from this one address instead of the vectors",
    )
    trace_parser.add_argument(
        "--bank",
        type=int,
        help="Bank for --from; without --from, only list findings in this bank",
    )
    trace_parser.add_argument(
        "--seed-labels",
        action="store_true",
        help="Also start from every single-address PRG label (assumes they are code)",
    )
    trace_parser.add_argument(
        "--gaps", type=int, default=20, help="How many of the largest gaps to list"
    )
    trace_parser.add_argument(
        "--unnamed",
        action="store_true",
        help="List routine entries with no label, a stub, or a tier-2 label",
    )
    trace_parser.add_argument(
        "--unreached",
        action="store_true",
        help="List single-address labels the trace never decoded as code",
    )

    readers_parser = subparsers.add_parser(
        "readers",
        help="List each gap with the traced instructions that name it as data",
    )
    readers_parser.add_argument(
        "--bank", type=int, help="Only gaps in this bank (15 for the fixed bank)"
    )
    readers_parser.add_argument(
        "--min", type=int, default=1, help="Only gaps of at least N bytes"
    )
    readers_parser.add_argument(
        "--reach",
        type=int,
        default=0,
        help="Also list indexed bases up to N bytes before a gap that could run into it",
    )

    known_parser = subparsers.add_parser(
        "known-data",
        help="Compare the data regions the repo can locate with the label file",
    )
    known_parser.add_argument(
        "--list", action="store_true", help="List every new label it would add"
    )
    known_parser.add_argument(
        "--write",
        action="store_true",
        help="Add the new range labels and widen single-address ones (base file)",
    )

    label_parser = subparsers.add_parser(
        "label", help="Look up the label at an address (requires --labels)"
    )
    label_parser.add_argument(
        "address", help="'$XXXX' CPU address or raw hex address/offset"
    )
    label_parser.add_argument(
        "--type",
        choices=list(TYPE_ALIASES),
        default="prg",
        help="Label type to search (default: prg)",
    )
    label_parser.add_argument(
        "--bank", type=int, help="Switchable bank number (0-14), used when --type prg"
    )

    find_label_parser = subparsers.add_parser(
        "find-label", help="Search labels by name substring (requires --labels)"
    )
    find_label_parser.add_argument(
        "name", help="Substring to search for (case-insensitive)"
    )

    def add_text_options(sub) -> None:
        sub.add_argument(
            "--bank",
            type=int,
            action="append",
            help="Only this bank (repeatable); 15 is the fixed bank",
        )
        sub.add_argument(
            "--source",
            choices=["both", "prg", "nametables"],
            default="both",
            help="Search the PRG bytes, the nametables the graphics codec "
            "decompresses, or both (default)",
        )

    strings_parser = subparsers.add_parser(
        "strings",
        help="List text in every known encoding, in the PRG and in decoded nametables",
        description="List runs of bytes that decode as text. Encodings: ascii; "
        "clubhouse (A-Z at $00, a-z at $1A, 0-9 at $37); scorecard (0-9 at $00, "
        "A-Z at $0A); digits30 (0-9 at $30, A-Z at $3A); stats (A-Z at $9E). "
        "Each run is scored "
        "0-1 by how English its letter pairs look, and shown when it scores "
        "--min-score or more.",
    )
    add_text_options(strings_parser)
    strings_parser.add_argument(
        "--encoding", action="append", help="Only this encoding (repeatable)"
    )
    strings_parser.add_argument(
        "--min", type=int, default=5, help="Shortest run to list (default 5)"
    )
    strings_parser.add_argument(
        "--min-score", type=float, default=0.65, help="Lowest score to list (0.65)"
    )
    strings_parser.add_argument(
        "--all", action="store_true", help="List every run, whatever its score"
    )

    find_text_parser = subparsers.add_parser(
        "find-text",
        help="Find text in every known encoding, or (--relative) in any font",
        description="Find TEXT encoded in each known encoding, tried as typed, "
        "upper case, lower case and capitalized, in the PRG and in decoded "
        "nametables. Each hit shows the whole string around it. --relative "
        "instead matches the differences between TEXT's letters, finding it in any "
        "font that keeps A-Z in order and reporting where that font puts A.",
    )
    find_text_parser.add_argument("text")
    add_text_options(find_text_parser)
    find_text_parser.add_argument(
        "--encoding", action="append", help="Only this encoding (repeatable)"
    )
    find_text_parser.add_argument(
        "--relative",
        action="store_true",
        help="Match letter differences: finds the text in fonts not yet named",
    )

    script_parser = subparsers.add_parser(
        "script",
        help="List a bank 11 text script and every script it can reach",
        description="List the text scripts reachable from each bank 11 ADDRESS: "
        "text in quotes with [nl], [wait] and [clear] inline, one line per other "
        "opcode. Branches, calls and jumps are followed, and so are natives that "
        "pick the next script from a pointer table. docs/text_scripts.md has the "
        "opcodes.",
    )
    script_parser.add_argument("address", nargs="+", help="'$XXXX' in bank 11")

    args = parser.parse_args()
    reader = RomReader(args.rom_file)
    labels = LabelStore.load(args.labels, args.sidecar) if args.labels else None

    commands = {
        "read": cmd_read,
        "find": cmd_find,
        "addr": cmd_addr,
        "disasm": cmd_disasm,
        "label": cmd_label,
        "find-label": cmd_find_label,
        "find-refs": cmd_find_refs,
        "trace": cmd_trace,
        "known-data": cmd_known_data,
        "readers": cmd_readers,
        "strings": cmd_strings,
        "find-text": cmd_find_text,
        "script": cmd_script,
    }
    try:
        commands[args.command](reader, args, labels)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
