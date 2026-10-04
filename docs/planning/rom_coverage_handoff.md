# Hand-off: Explaining the ROM Bytes

> **Note**: This document was written by Claude for the next agent picking up this work,
> at jdharms's request.

The goal is a full disassembly of the US ROM. Every byte of the 256KB PRG is now traced
code, covered by a range label, or uncalled code under a named label, except **one byte**:
bank 13 `$8F35`, an unread `$FF` between `ViewOffsetSpriteYHiTable` and `LD_8F36`, which
can't be labeled because a one-byte range is a code label in this file (the Hi table's
comment explains it). What is left is confirming the guesses, not finding bytes. This
document says where things stand, the tools, the method that worked, and the traps
already found.

## Where things stand

`golf-rom-peek nes_open_us.nes --labels "NES Open Tournament Golf (USA).mlb" trace`:

| Bank | Code | Labeled data | Uncalled | Unexplained |
|---|---|---|---|---|
| 0, 1, 6, 7 | stubs | everything | 0 | 0 |
| 2 | 2,433 | 13,951 | 0 | 0 |
| 3 | 403 | 15,981 | 0 | 0 |
| 4 | 109 | 16,275 | 0 | 0 |
| 5 | 373 | 16,011 | 0 | 0 |
| 8 | 478 | 15,906 | 0 | 0 |
| 9 | 10,466 | 5,880 | 38 | 0 |
| 10 | 183 | 16,201 | 0 | 0 |
| 11 | 5,445 | 10,936 | 3 | 0 |
| 12 | 9,791 | 6,593 | 0 | 0 |
| 13 | 12,410 | 3,771 | 202 | 1 |
| 14 | 6,109 | 10,224 | 51 | 0 |
| 15 (fixed) | 7,526 | 8,019 | 839 | 0 |

**Uncalled** is code that only single-address labels nothing reaches lead to: routines
with no static caller and no pointer found (`find-refs` plus the raw pointer-pair scan).
They are dead, or reached through a pointer nobody has found; none is confirmed in Mesen.
In the fixed bank they are 13 blocks, 839 bytes, the largest
`DecompressGraphicsStreamToRam` (`$D69E`, 317 bytes); every one's label comment starts
"maybe dead".

Invariants that hold now and should keep holding:

- **No unresolved control flow and no conflicts** in the trace.
- **No two range labels overlap**, and no label name repeats (check below).
- **`known-data` is idempotent**: a dry run reports 0 new labels.
- One object problem is reported and expected: the bank 10 `$9D65` stream (see its label);
  `test_object_script_rom.py` pins it.
- `golf-check` and the full `pytest` pass.

## The tools

All in `golf-rom-peek` (see the `nes-open-golf-rom-peek` skill):

- **`trace`** - recursive descent from the vectors (`golf/core/rom_trace.py`), plus the
  text-script walker and the scene-object walker, repeated until neither finds new code.
  `mark_uncalled` then traces from the unreached single-address labels and marks what only
  they reach `UNCALLED`: its own coverage column, left out of the gaps. Conflicts from that
  sub-trace are printed separately (there are none today). A single-address label inside
  a range label marks a place in that data (`CourseOneMenuStr`, a string in
  `MenuTextListData`) and isn't traced. `--unreached` lists labels never decoded, marking
  roots.
- **`readers [--bank N] [--min N] [--reach N]`** - each gap with the traced instructions
  that name it (`data_readers` in `rom_trace.py`): absolute and indexed operands resolved in
  every bank the instruction ran with mapped (`TraceResult.contexts`), indexed bases up to
  `--reach` bytes before the gap, and immediate pairs (`LDx #lo / STx a` and
  `LDx #hi / STx a±1` within 6 instructions) as candidates. Mapper writes (stores to
  `$8000+`) are excluded. Uncalled code's readers are included.
- **`known-data [--list] [--write]`** - collectors that measure data from the ROM
  (`golf/core/known_data.py`). Added this session:
  - `copied_block_regions`: the inline source of every `CopyInlineMemoryBlock`, named by
    destination (`NametableDescriptorTemplate...` for `$0410`-`$041F`,
    `AttributeTableData...` for 64 bytes to `$0497`).
  - `clip_window_regions`: the 5-byte record named by `SetObjectClipWindow`'s inline word
    (`$F881`, formerly `LF881`).
  - `vector_regions`: every bank's last 6 bytes.
  - `code_pointer_table_regions`: the tables in `CODE_POINTER_TABLES`, labeled with each
    entry's `name` (`<name>Lo`/`<name>Hi` for split tables).
  - Palettes, copies and clip windows share `_inline_word_targets`, which resolves a
    fixed-bank site's switchable address through the banks the trace saw mapped.
  - Metasprite renderers are keyed by (bank, address); bank 13's
    `RenderGreenViewMetasprite` (`$9492`, count + 4 bytes a sprite) is registered, and
    `_renderer_after` looks one call deep (`RENDERER_REACH` 24: bank 4's `$BF02` and
    `$BF4F` reach `RenderMetasprite` 21 instructions on).
  - Object frame tables are sized by `_frame_count`: on up to the lowest metasprite they
    point at, not just the highest frame a record uses.
- **Scripts started by object streams**: `stream_scripts` (`object_script.py`) pairs a
  stream's `$F6` stores into `ScriptPtr`/`ScriptPtr+1`, and `trace_everything` hands the
  addresses to `trace_with_scripts` as extra script entries. That is how
  `PrizeAwardTextScript` (bank 11 `$B997`) and its natives `$9504` and `$B8D5` are reached.
- **Object walker registries** (`golf/core/object_script.py`): `RECORD_POINTER_TABLES`
  entries now carry a record `size` (7 for the short records `$F856` copies);
  `RECORD_LISTS` holds records reached through a RAM pointer (`MenuSpriteInitData`) or with
  no allocator found (`site=None`); `code_streams` follows stream pointers that object-bank
  code stores into `$7A41/$7A51` and `$7A61/$7A71` from immediates.
- Registries to extend when a new case is confirmed: `INLINE_ARG_ROUTINES`
  (`rom_analysis.py`), `CODE_POINTER_TABLES` (`rom_trace.py`), `SCRIPT_POINTER_TABLES`,
  `RECORD_POINTER_TABLES`, `RECORD_LISTS`, `GRAPHICS_POINTER_TABLES`, `RENDERERS`. Each
  entry carries the reasoning.

## The method that worked for a bank

1. **`readers --bank N --reach 8`**, and read the code before each reader to work out the
   index range: the loop bound, the `ASL` that doubles it, the `CMP #n` that caps it. Size
   each table from that, then check it against where the next thing starts. Tables here
   are packed with no slack, and a gap's total almost always comes out exact.
2. **Look for a general mechanism first.** Most of the progress came from collectors and
   walker registries rather than one-off labels: if a gap's data is handed to a known
   routine through an inline word, a fixed RAM pointer or a slot array, every other site
   probably has the same shape. A gap with no reader is often a record or stream: search
   the raw pointer (`find 'lo hi'`) and look at what holds it.
3. **Gaps that disassemble cleanly and end in `RTS` are usually uncalled routines.**
   `find-refs` the entry, scan for the raw pointer and the `RTS`-trick pointer (entry - 1),
   then name it (tier 3) with a comment starting "maybe dead: no static caller".
4. **Label** with `golf-labels "$M" add prg '$START-$END' --bank N Name --comment '...'`
   (no `--bank` for the fixed bank). Names come from what the readers do; prefix `Maybe`
   when the purpose isn't certain. Overlapping envelopes read at shifted bases get one label
   listing every base and reader (`Pulse2SfxEnvelopeTables`). A one-byte range can't be a
   range label (`is_data_range`), so lone bytes stay gaps.
5. **Check** after each batch: the overlap check below, `known-data` (0 new), `trace`
   (0 conflicts), the tests.

```bash
uv run python -c "
from golf.core.mlb_labels import LabelStore
from collections import Counter
L=LabelStore.load('NES Open Tournament Golf (USA).mlb')
rs=sorted((l.start,l.end,l.name) for l,_ in L.iter_merged()
          if l.type=='NesPrgRom' and l.end is not None and l.end!=l.start)
c=Counter(l.name for l,_ in L.iter_merged() if l.name)
print('overlaps',[(a[2],b[2]) for a,b in zip(rs,rs[1:]) if b[0]<=a[1]],
      'dupes',[n for n,k in c.items() if k>1])"
```

## What is left

No bytes to find; three kinds of follow-up:

1. **The uncalled code has had one Mesen pass** (2026-10-04, jdharms): execute
   breakpoints over every uncalled block's whole range - all 13 in the fixed bank and
   the 7 in banks 9, 13 and 14 - and none hit through the credits combo, every club house
   screen (options saved, money deposited with DK, replays, stats), a one-hole tournament
   bet against a CPU opponent, practice, two-player stroke play and one-player match play
   with saves. Each block's entry label records this. Not covered: a full tournament or
   the earned ending, a hole-in-one or albatross, rank promotion, a new save file. The
   blocks stay "maybe dead" until something covers those, but nothing ordinary reaches
   them. Two uncalled fragments weren't covered and need no breakpoint: bank 11 `LB_80C7`
   and bank 14 `LE_8A44` each follow a `JMP` with nothing branching to them. Use
   **execute-only** breakpoints: a read breakpoint on a label right after an
   `RTS` fires on every return, because the 6502 reads and discards the byte after a
   one-byte instruction (`$D131` after the `RTS` at `$D130`).
2. **Confirm the `Maybe` data that nothing reads**, the same way with read breakpoints:
   `MaybeUnusedSceneFlagTable` (bank 9 `$942B`), `MaybeUnusedData9B38B`,
   `MaybeUnusedDataC8293`, `MaybeUnusedDataAA296`, `MaybeUnusedDataDAC85`,
   `MaybeUnusedDataDB3A0`, and the unreachable table tails `MaybeUnusedPutterDistanceSpeed34`,
   `MaybeUnusedPutterDistAltSpeed34` and `MaybeBunkerExitClubThresholdTable` (only entry 1
   read). Each comment records the static search that came up empty.
3. **Name what is only measured**: generated names (`Metasprites4BF7F`,
   `ObjectAnimStreamAA278`, `TextScriptBA089`, ...) and the 725 routine entries without a
   tier-3 name (`trace --unnamed`). Bank 9's 32-bit math works on three registers, high
   byte first: MathA `$62`, MathB `$66`, MathC `$6A` (see `ClearMathA`'s comment).

## Traps already found

- **`DispatchInlineJumpTable` returns** after its table (shared tail at `$D24F`); it was
  once registered as non-returning, which hid the whole course intro.
- **Four metasprite formats**: chunked (`RenderMetasprite`, `RenderMetaspriteClipped`),
  count plus 3 bytes a sprite (`RenderMetaspriteWithAttr`), count plus 4 bytes a sprite
  (bank 13 `RenderGreenViewMetasprite`), and inline loops with their own formats. Measure
  with the renderer the site actually reaches.
- **Lo/Hi one byte apart is a word table read with a stride**, not two one-entry tables.
- **A zero-count object stream step halts the stream**; reading on runs into data.
- **`$FF` runs**: a graphics stream's terminator looks like padding; padding must start
  after any measured region.
- **Overlapping data is real**: metasprites, tile lists and DPCM samples share tails
  (the `$C000` sample runs 17 bytes into `DmcDrumData`), and envelope tables are read at
  shifted bases. Merge same-kind overlaps; report the rest.
- **Labels can be wrong about what they are**: `ViewOffsetToAttrStart` was a nametable
  descriptor (now `AttributeTransferDescriptor`), and `LD_8F24` was a stub left inside a
  table by a linear disassembly. When a new range warns about an overlap, check the other
  label before trusting it.
- **Tests pinned to label state** break when a gap gets labeled. Prefer unit tests on mock
  ROMs for tool behavior.
- **RAM labels lie by context**: `$071D` is `SuppressMenuHistoryPushFlag` in the menu and
  a variant index or animation pointer elsewhere; `SceneTileMap` covers many unrelated
  arrays (the object slot arrays at `$7811`-`$7B01` among them). Read the code, not the
  label.
- **A script or stream can be named only inside other data.** `PrizeAwardTextScript` has
  no code pointer at all; its address sits in an object stream's `$F6` operands. When a gap
  has no reader, `find` its raw pointer and read what holds it.
- **Padding can be read.** Bank 11 `$85BB` points a 2-byte attribute descriptor at `$FFEE`,
  inside `MaybeBank15TailPadding`.
- **Label extents can be off by one entry.** `NoiseDecayEnvelopeTable` was read as
  indexed 1-15, but its counter is set to 16 and decremented before each read (2-16);
  `SignpostBannerDescriptorTable` stopped 4 bytes short of its fifth descriptor; and
  `ReplayDestPtrLoTable`/`HiTable` were two word tables read with a stride (now
  `ReplaySaveHeaderPtrTable`/`ReplaySaveDataPtrTable`). A small gap right after a table
  is worth checking against the table's own reader first.
- **`golf-labels edit` can't change a range**; remove and re-add (it inserts in address
  order).

## Housekeeping

- The label file is a symlink into the private `jdharms/nes-open-labels` repository. Never
  publish it. `golf-labels` edits in place without re-sorting, so diffs stay readable.
- `golf-labels` writes the base file; don't use the sidecar.
- Commit messages are jdharms's to write.
