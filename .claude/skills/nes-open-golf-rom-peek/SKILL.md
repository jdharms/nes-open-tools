---
name: nes-open-golf-rom-peek
description: >
  How to inspect and reverse-engineer a NES Open Tournament Golf ROM with
  golf-rom-peek (tools/research/rom_peek.py, logic in golf/core/rom_analysis.py). Use
  whenever reading ROM bytes, disassembling 6502 code, tracing what calls a
  routine, checking whether an address or region is referenced, or looking for
  reclaimable space in this project. Covers the subcommands, the four ways a
  naive byte search or linear disassembly silently lies about this ROM, and the
  confidence discipline for null results - a "no references found" is never
  proof an address is dead.
---

# Inspecting the ROM with golf-rom-peek

`golf-rom-peek` is the project's tool for targeted ROM reads, searches and
disassembly. **Use it instead of writing one-off Python.** Analysis logic lives
in `golf/core/rom_analysis.py` and is unit-tested, so extend it there rather
than reimplementing a scan in a scratch script.

```bash
uv run golf-rom-peek <rom.nes> [--labels <file.mlb>] <subcommand> ...
```

Always pass `--labels "NES Open Tournament Golf (USA).mlb"`, so output is
annotated with everything the project has named so far. `--labels` is a
top-level option and must come **before** the subcommand.

**Start from `docs/rom_map.md`**, which maps a topic to the bank, address and
label to read from. If you had to search to find where something lives, add a
row there before you finish. Before labeling, read `docs/rom_disassembly.md`:
the label file's invariants (check them with `golf-labels <label file> check` and
`known-data`), the method for measuring a table, and the traps already found.

## Address grammar

Shared by every subcommand:

- `$XXXX` — a CPU address. Resolved in the fixed bank (`$C000-$FFFF`) unless
  `--bank N` is given, in which case it's a switchable-bank address
  (`$8000-$BFFF`) in bank N.
- `0xNNNN` or bare hex — a raw PRG ROM offset, used as-is.

Bank 15 is the fixed bank. `addr` converts between the two forms without
reading anything.

## Subcommands

| Command | Purpose |
|---|---|
| `read <addr> [--bank N] [--length N] [--format hex\|python\|ascii]` | Raw bytes. `--format python` emits a `bytes([...])` literal ready to paste into a `BytePatch`. |
| `find <hex pattern> [--bank N] [--follow N] [--flag-range LO-HI]` | Byte-pattern search. `--follow 2` decodes the trailing bytes as a little-endian pointer. |
| `addr <addr> [--bank N]` | CPU address ↔ PRG offset, no ROM read. |
| `disasm <addr> [--bank N] [--count N \| --routine] [--max N]` | Disassemble. See below. |
| `find-refs <addr> [--bank N] [--type prg\|ram] [--reach N]` | Find references across every encoding. See below. |
| `trace [--from <addr> --bank N] [--bank N] [--gaps N] [--unnamed] [--unreached]` | Follow control flow from the vectors and map code, data and gaps. See below. |
| `readers [--bank N] [--min N] [--reach N]` | Each gap the trace leaves, with the traced instructions that name it. See below. |
| `known-data [--list] [--write]` | Compare the data regions the repo can locate with the label file; `--write` adds them as range labels. See below. |
| `strings [--bank N] [--encoding E] [--source prg\|nametables\|both] [--min N] [--min-score F] [--all]` | Text in every known encoding, in the PRG and in decoded nametables. See below. |
| `find-text <text> [--bank N] [--encoding E] [--source ...] [--relative]` | Where a piece of on-screen text is stored. See below. |
| `script <addr>...` | A bank 11 dialogue script and every script it reaches, readable. See below. |
| `label <addr> [--type ...] [--bank N]` | Look up the label at an address. |
| `find-label <substring>` | Search labels by name. |

Use `golf-labels` (separate tool) to *add* labels; it writes to the label file. See the `nes-open-golf-label-conventions` skill for naming.

## Four ways this ROM lies to a naive reading

These are the reason the tool exists. Each has burned a previous session.

### 1. Inline arguments desynchronize a linear disassembly

Several routines read bytes that follow their own `JSR` and then skip past
them. A disassembler that doesn't know this decodes the arguments as opcodes
and produces plausible-looking garbage for the next ten to twenty
instructions.

`disasm` handles all of these automatically, rendering the arguments as
`.db`/`.dw` and resuming on the correct boundary:

| Routine | Bank | Inline |
|---|---|---|
| `ExecuteFarCall` `$D372` | fixed | 3 bytes: bank, lo, hi |
| `LoadCompressedGraphics` `$D45F` | fixed | 3 bytes: bank, lo, hi |
| `WriteNametableTiles` `$CE84` | fixed | 2 bytes: descriptor pointer |
| `WriteNametableTilesMode2` `$CE7E` | fixed | 2 bytes: descriptor pointer (no PPU address in the descriptor) |
| `Load32BytesToBuffer` `$D80A` | fixed | 2 bytes: source pointer |
| `CopyInlineMemoryBlock` `$D41A` | fixed | 6 bytes: src, dst, length |
| `DispatchInlineJumpTable` `$D227` | fixed | `(key, lo, hi)` triples, `$00`-terminated; it JMPs to the handler with the post-table address stacked, so a handler's `RTS` (or no match) continues after the table |
| `DispatchInlineJumpTableFF` `$D267` | fixed | the same, but `$FF`-terminated, so `$00` is a usable key |
| `LookupInlineByteTable` `$8A14` | 12 | `(key, value)` pairs, `$00`-terminated |
| `LookupInlineRangeTable` `$8A56` | 12 | `(lo, hi, value)` triples, `$00`-terminated |
| `LookupInlineRangeTableBank11` `$9490` | 11 | the same, a byte-for-byte copy |
| `$D7DB`, `$F7F3`, `$F826`, `$F881`, `$F8A2` | fixed | 2 bytes: word (they reach `JSR $D8A2` before pushing anything) |
| `$B4C6`, `$B4CF`, `$B4E3`, `$B4F7` | 9 | 2 bytes: word, the same way |
| `$A5C9` | 13 | 2 bytes: word, the same way |

**`$D8A2 ReadInlineWordParameter` and `$D436` are not on this list, and must not be
added to it.** Both do `TSX` then read `$0103,X`, skipping their own return address — so
the inline word belongs to whoever called *their* caller. A `JSR $D8A2` consumes nothing
itself; it is the enclosing routine (`$D80A`, `$D41A`, and a dozen others) that carries
the inline bytes. Listing `$D8A2` here desynchronizes every direct call site by two
bytes. Check for this `$0103,X` pattern before adding any new entry. Conversely, any
routine that reaches `JSR $D8A2` before pushing anything takes a word, and belongs on
the list.

```
$8F85  20 5F D4    JSR LoadCompressedGraphics[$D45F]
$8F88  06 00 80    .db $06, $00, $80   ; -> bank $06 $8000
```

If you find another such routine, add it to `INLINE_ARG_ROUTINES` in
`golf/core/rom_analysis.py` — confirm first by disassembling it and checking
that it advances its own return address past the arguments.

`--no-inline-args` restores the raw behavior if you need to see the bytes as
the CPU would misread them.

### 2. Data decodes as convincing code

Range labels in the `.mlb` (`GolferScreenXTable:$80FA-$8109`) mark tables;
single-address labels mark code. `disasm` renders labeled ranges as `.db`
rows instead of decoding them. `--no-data-ranges` opts out.

This only works for ranges someone has already labeled. Unlabeled tables
still decode as nonsense — if a listing suddenly fills with `BRK`, `???`, and
implausible branches, suspect data and go check the bytes with `read`. When
you confirm a table, label it as a range so the next agent doesn't re-derive
it.

### 3. References the obvious search cannot find

A relative branch stores a *displacement*, not an address, so **no byte
pattern will ever find it**. Far calls bury the target in inline arguments.
Dispatch tables store it as inline data.

A previous session ran `find '20 C0 D1'` looking for callers of `$D1C0`, got
"No matches found", concluded it was unreachable, and moved on. Its only
reference is `$D1BC BEQ $D1C0`.

Use `find-refs`, which covers `JSR` / `JMP` / `JMP (ind)`, relative branches,
`ExecuteFarCall` inline targets, and every entry in the inline tables of all
`DispatchInlineJumpTable` and `DispatchInlineJumpTableFF` call sites, in one
command.

### 4. A table is shorter than it looks, and over-running it usually looks fine

Lookup tables here are packed in parallel `Lo`/`Hi` pairs with **zero slack**:
`Hi` starts at the byte after `Lo`'s last entry, and real code usually starts
at the byte after `Hi`'s. So an index past the end of `Lo` silently reads
`Hi`, and an index past the end of `Hi` reads opcodes.

This bites because several tables are indexed by a per-hole value that the
vanilla courses never drive to the end of their own data. `ScrollLimit` tops
out at 8 across the three shipped courses, so nobody noticed its tables hold
10 entries — but a patched-in 60-row hole drives it to 16. Five separate
table pairs have had to be expanded for exactly this reason; see
`docs/wram_expansion.md` and `golf/core/patches/wram_expansion/`.

**The over-run is almost always invisible.** The bytes just past a table are
its sibling table or code, and those usually form a value that happens to
behave — a threshold too large to ever fire, an offset merely wrong rather
than catastrophic. Of the seven out-of-range `ScrollLimit` values the
terrain-bottom tables could see, exactly one produced a visible bug; the
other six played normally. "I tested the tallest hole and it worked" is not
evidence a table is long enough, and neither is a clean playthrough.

So when you find a table:

- Get its length from where the **next** thing starts — the next label, the
  next table's first entry, or the first byte of real code — not from how
  many entries the game appears to use. `read` past the end and find where
  the pattern breaks.
- Work out the full range of its index, including values only reachable on
  patched data, and compare that against the length you just measured.
- Label it as a range (`golf-labels add prg 'START-END' Name`) so `disasm`
  stops decoding it as code and the next agent can see the boundary without
  re-deriving it.

## `disasm --routine`

Decodes until the routine plausibly ends rather than a guessed instruction
count — you usually know an address, and bytes-to-instructions isn't
computable without decoding.

Stops at: a terminator (`RTS`/`RTI`/`JMP`) once no forward branch is still
pending; a call registered as non-returning (none are, today); or the start of
a labeled data range. Always prints why it stopped.

`--max N` (default 200) caps the output so a wrong guess about where code
lives can't dump a whole bank. **If the cap is hit the output says
`INCOMPLETE` — the routine continues past what you were shown.** Don't reason
about a routine's ending from a truncated listing.

```bash
uv run golf-rom-peek rom.nes --labels notes.mlb disasm '$AB16' --bank 13 --routine
```

## `find-refs` and the confidence discipline

Every hit is checked two ways and reported in one of three states:

- **confirmed** — starts on a real instruction boundary (verified by decoding
  forward from the nearest code label) and isn't inside a labeled data range.
- **UNVERIFIED** — no code label within 192 bytes to anchor an alignment check
  from. Reported, but you must read it yourself.
- **discarded** — lands mid-instruction, or sits inside a labeled data range.
  Byte coincidences, listed separately so you can see what was thrown away.

The mid-instruction case is common and convincing: `$88B3` looks exactly like
`JSR $91AD`, but those bytes straddle the operand of `STA $20` and the next
opcode.

### A null result is not proof

**`find-refs` finding nothing does not mean an address is unused.** It cannot
see:

- indirect jumps through a runtime pointer — every menu choice handler is
  reached by `JMP ($22)` and has zero static references;
- addresses computed at run time;
- DMA, the decompressor, and anything the PPU reads directly.

On an empty result the tool says all of this and escalates to a raw
pointer-pair scan. **For pointers the usual reading inverts**: a byte pair
inside a labeled table is a *likely* real indirect reference, not a
coincidence.

So: **static analysis proposes, the emulator disposes.** For anything
expensive to get wrong — reclaiming space, taking over a splice site,
declaring a feature dead — confirm with a Mesen breakpoint, then record the
result in the `.mlb` comment or a doc so it is never re-derived. `docs/
wram_expansion.md` is the model: *"Confirmed via debugger sweep that CPU
`$8F81` and `$8F86` are the only two readers."* That, not a byte search, is
what justified reclaiming `$E4F9`.

### RAM addresses

`--type ram --reach N` also lists indexed bases up to N bytes below the
target, because `LDA $059C,X` can touch `$05BB` if X ranges far enough. **How
far X or Y actually ranges is not determined** — those are candidates to go
read, not findings.

```bash
uv run golf-rom-peek rom.nes --labels notes.mlb find-refs '05BB' --type ram --reach 48
```

## `trace`

Recursive descent from the reset, NMI and IRQ vectors (logic in
`golf/core/rom_trace.py`). It follows branches, `JSR`/`JMP`, far calls, the inline
dispatch tables and the confirmed jump tables in `CODE_POINTER_TABLES`, skipping
inline arguments, and carries which bank is mapped at `$8000`: `LDA #n` /
`JSR BankSwitchRoutine` sets it, a switch from anything but an immediate makes it
unknown. Recognizes the unconditional branch idioms (`BEQ`/`BNE` pairs, `CLC`/`BCC`,
`LDA #nonzero`/`BNE`). It prints:

- **coverage** per bank: bytes reached as code, inside range labels, both
  (a conflict), **uncalled**, and neither. Uncalled is code that only the
  single-address labels nothing reaches lead to: after the main trace,
  `mark_uncalled` traces from those labels and gives what only they reach its own
  column, out of the gaps. It is dead code or code behind a pointer nobody has found;
  name such a routine with a comment starting "maybe dead". Conflicts from that
  sub-trace are printed in their own list. A single-address label inside a range label
  marks a place in that data (a string in a list) and isn't traced.
- **unresolved control flow**: every `JMP (ind)` it couldn't follow. If you
  work one out, add the table to `CODE_POINTER_TABLES` (with the reasoning) rather
  than labeling around it.
- **conflicts**: decodes into undocumented opcodes or `BRK` (the IRQ handler is a
  bare `RTI`, so `BRK` is never real), mid-instruction entries, code running into a
  range label. Each names the transfer that started the straight run and the last
  `JSR` in it, which is usually the culprit: a routine with inline arguments nobody
  has registered, or a call that doesn't return.
- **gaps**, largest first, and with `--unnamed` the routine entries (`JSR`, far
  call, dispatch targets) that still have no tier-3 name.
- with `--unreached`, every single-address label the trace never decoded, marked
  `ROOT` when no other unreached label leads to it. The roots are the to-do list:
  data labeled without a range, dead code, or code behind unresolved control flow.

Unless given `--from`, it also walks the bank 11 dialogue scripts
(`golf/core/text_script.py`): it finds the script addresses traced code loads into
`ScriptPtr` (immediates, plus the tables in `SCRIPT_POINTER_TABLES`), follows every
script opcode that moves the script counter, and traces the native code the `$F8` and
`$F7` opcodes name - which is the only way that code is reached - repeating until
nothing new turns up. An object stream can start a script too, with `$F6` stores into
`ScriptPtr` (`stream_scripts`; the prize-award script is reached only that way). A script that the walker can't decode is printed as a script
problem. When you find another table that feeds `ScriptPtr`, add it to
`SCRIPT_POINTER_TABLES` with the index range its loader uses.

It also walks the scene objects (`golf/core/object_script.py`,
`docs/scene_objects.md`): the records traced code allocates, their motion and animation
streams, and the sprite data in bank 2 or 10, settling each record's bank by which one
decodes cleanly. `$ED` calls and the `$F950` scene callback feed more code to the trace.
Record lists reached through a table go in `RECORD_POINTER_TABLES` (with a record
`size`, 7 for the short records `$F856` copies), and lists reached through a RAM pointer
or with no allocator found in `RECORD_LISTS`. `code_streams` follows streams that
object-bank code points a slot at (`LDA #lo / STA $7A41,X` ... `$7A51,X`, or
`$7A61/$7A71` for animation).

A conditional branch that falls straight into a range label is read as always
taken (`LDA table,X / BNE` over the table), so labeling the table is how you
resolve that kind of conflict. As with `find-refs`, a byte the trace didn't reach
is a question, not dead code.

## `readers`

For each gap the trace leaves (largest first, filtered by `--bank` and `--min`), the
traced instructions that name it (`data_readers` in `golf/core/rom_trace.py`):

- absolute and indexed operands, resolved in every bank the instruction ran with mapped,
  so a fixed-bank reader is listed once per bank it can see (and not at all when that
  bank is unknown); stores to `$8000+` are mapper writes and left out;
- with `--reach N`, indexed bases up to N bytes before the gap, which might run into it;
- immediate pairs - `LDx #lo / STx a` and `LDx #hi / STx a+-1` within six instructions -
  as candidate pointers.

Readers inside uncalled code count. Read the code before each reader for the index range
(loop bound, the `ASL` that doubles it, a `CMP #n` cap) and size the table from that,
checking it against where the next thing starts. "No direct reader" is a prompt to
search the raw pointer (`find 'lo hi'`) - streams and scripts are often named only
inside other data - and, failing that, to record the search in the label's comment.

## `known-data`

Gathers the data the repository already knows how to find (logic in
`golf/core/known_data.py`), each measured from the ROM:

- **graphics tables**, from the inline arguments of every `LoadCompressedGraphics`
  call the trace reaches, the pointer tables in `GRAPHICS_POINTER_TABLES`, and the
  tables `golfer_sprites` and `signpost` name. Each is decoded, so a table's extent
  is exact. A run holds one table's header and its own streams; streams two tables
  share get their own `...Streams` run.
- **course data**: each course's terrain and the attribute bytes its holes use, the
  greens (measured by how far the decompressor reads), and both sets of
  decompression tables.
- **text scripts**: what the script walker read, cut at each entry point
  (`TextScriptB9658`), the script pointer tables, and `ScriptWindowGeometryTable`
  sized by the highest window a script selects.
- **scene objects**: record lists, each object bank's sprite and frame tables,
  metasprites (grouped by sprite) and the motion and animation streams.
- **metasprites drawn directly**: split Lo/Hi pointer tables or immediates loaded into
  `PointerToSpriteData` (`$45/$46`) ahead of a renderer call, measured in that
  renderer's format - chunked for `RenderMetasprite`/`RenderMetaspriteClipped`, a count
  and 3 bytes a sprite for `RenderMetaspriteWithAttr`, a count and 4 bytes a sprite for
  bank 13's `RenderGreenViewMetasprite`. Renderers are registered in `RENDERERS` by
  (bank, address), and a site that reaches one through a single further call is
  followed. A Lo/Hi pair's entry count is the distance between them.
- **palettes**: the inline word of every `Load32BytesToBuffer` call, 32 bytes each.
- **copied blocks**: the inline source of every `CopyInlineMemoryBlock`, named by
  destination (`NametableDescriptorTemplate...` for `$0410`-`$041F`,
  `AttributeTableData...` for 64 bytes to `$0497`).
- **clip windows**: the 5-byte record named by `SetObjectClipWindow`'s inline word.
- **vectors**: every bank's last 6 bytes.
- **nametable descriptors**: the inline word of every `WriteNametableTiles` (and Mode1 /
  Mode2) call, measured from its header - width x height tiles inline, one in repeat
  mode, or a pointer to source data labeled separately (`docs/menu_system.md`).
- **CPU opponent shots** in bank 3 (`docs/opponent_shots.md`).
- **jump tables**: the entries in `CODE_POINTER_TABLES`, under each entry's `name`.
- **padding**: the `$FF` run before each bank's reset stub, named `Maybe...`
  because nothing proves it unread.

It subtracts whatever range labels already cover, widens a single-address label
that sits at a region's start, and refuses to write if a region overlaps traced
code, holds another single-address label, or overlaps another region. Names it can't take from an existing
label follow `ChrGraphicsTable0B2E2` / `NametableGraphicsStreams6B47E` (PPU kind,
bank as one hex digit, address); rename one when you learn its purpose. A rerun
after `--write` should find nothing new.

## `strings` and `find-text`

Text is stored several ways (logic in `golf/core/rom_text.py`), and a plain ASCII
search finds only some of it:

| Encoding | Bytes | Where |
|---|---|---|
| `ascii` | ASCII | dialogue scripts (bank 11), menu strings (bank 12), roster names (bank 9) |
| `clubhouse` | A-Z `$00`, a-z `$1A`, `,` `$34`, `.` `$35`, `-` `$36`, 0-9 `$37`, `?` `$42`, space `$FF` | club house screens (bank 7 nametables), bank 14 messages |
| `scorecard` | 0-9 `$00`, A-Z `$0A`, space `$24` | the scorecard (bank 2), the in-game menu (bank 4) |
| `digits30` | 0-9 `$30`, A-Z `$3A`, space `$03` | tournament screens (banks 1, 2, 6) |
| `stats` | A-Z `$9E`, 1-9 `$B8`, space `$45` | player stats and options screens (banks 7, 9) |

Each tile font was read from the screen's glyphs, not guessed. The club house font
is **not** the dialogue printer's range table (`$90B1`): from `-` onward that table
is one tile off.

Both commands also search every nametable the graphics codec decompresses
(`--source`): text inside a compressed nametable is split up by codec opcodes and
can't be found in the raw bytes. A decoded hit reads `bank 7 $AEB2 PPU $20CB`, the
graphics table and where on screen the text lands.

- **`find-text "<text>"`** is the usual entry point: it tries the text as typed,
  upper case, lower case and capitalized in each encoding, and prints the whole
  string around each hit. For a font no one has named, **`--relative`** matches the
  differences between the letters and reports where that font puts A (`A=$80`).
  If one turns up, add it to `encodings()` with where it was seen.
- **`strings`** lists runs of text, scored 0-1 by how English (or romanized
  Japanese) their letter pairs look. Expect some noise from pattern data at the
  default `--min-score 0.65`, and use `--all` to drop the filter. Banks 11 and
  12 are almost all real text; anywhere else, check the label before trusting a
  hit.
- **`script '$A0EE'`** lists dialogue in full once `find-text` has found one line of
  it. A script's text is split by opcodes (a line break is `$FB`), so `find-text`
  only matches within a line. The listing shows text in quotes with `[nl]`,
  `[wait]` and `[clear]` inline, and one line for each branch, call and native. It
  follows every path, including natives that pick the next script from a
  `SCRIPT_POINTER_TABLES` table. Pass several addresses to list a scene's scripts
  together.

## Recipes

**Understand a routine**
```bash
disasm '$AA09' --bank 13 --routine        # the whole thing, with inline args resolved
find-refs '$AA09' --bank 13               # who reaches it
```

**Trace a far call.** `disasm` shows `.db $0B, $33, $90 ; -> bank $0B $9033`;
follow it with `disasm '$9033' --bank 11 --routine`. Remember the target's
addresses are in *that* bank, so data pointers it sets up (e.g. a script
pointer) resolve against the switched-in bank, not the caller's.

**Find every consumer of a table.** `find '20 5F D4'` for a specific inline
routine, or `find-refs` on the table's address.

**Assess free space.** Never conclude a run of `$FF`/`$00` is free from a scan
alone. `$FF` is a meaningful value inside tile strings and music data, and
several regions that look like padding are already claimed by patches in
`golf/core/patches/`. Check the patch modules' hardcoded offsets, check for
range labels, and confirm with a breakpoint before writing anything there.

## Limits worth stating out loud

- `disasm` does not track bank switches mid-listing; operand labels resolve
  against the single `--bank` you passed.
- `--routine`'s terminator heuristic is wrong for jump tables, deliberate
  fall-through into an adjacent routine, and data interleaved mid-routine.
  `--count` and plain `read` remain the escape hatches.
- The alignment check needs a nearby code label. In unlabeled regions it
  returns "unknown", which is why labeling as you go makes the tool better
  for everyone after you.
