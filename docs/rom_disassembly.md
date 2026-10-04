# Disassembling the ROM

> **Note**: This document was written by Claude, at jdharms's request.

The label file (`NES Open Tournament Golf (USA).mlb`, a symlink into the private
`jdharms/nes-open-labels` repository; never publish it) accounts for every byte of the
US ROM's 256KB PRG: each is traced code, inside a range label, or uncalled code under a
named label. The one exception is bank 13 `$8F35`, an unread `$FF` between
`ViewOffsetSpriteYHiTable` and `LD_8F36`, which a one-byte range can't label (the Hi
table's comment explains it). What remains is confirming guesses, not finding bytes (see
**Open questions**).

`docs/rom_map.md` says where a topic lives. This document is about keeping the label file
complete and right: the invariants, the method that measured the data, and the traps
already found. The tools themselves are described in the `nes-open-golf-rom-peek` skill,
and naming in `nes-open-golf-label-conventions`.

## Invariants

These hold now; any labeling session must leave them holding. `$M` below is the label
file's path.

| Invariant | Check |
|---|---|
| No unresolved control flow and no conflicts | `golf-rom-peek ... trace` |
| No two PRG range labels overlap, no name repeats | `golf-labels "$M" check` |
| `known-data` is idempotent | `golf-rom-peek ... known-data` reports 0 new |
| One object problem, expected: the bank 10 `$9D65` stream | pinned by `test_object_script_rom.py` |
| Lint and tests pass | `golf-check`, `pytest` |

`trace` reports **uncalled** code separately from gaps: code that only single-address
labels nothing reaches lead to, with no static caller and no pointer found by
`find-refs` or the raw pointer-pair scan. Its entry label's comment starts "maybe dead".

## Measuring a bank

1. **`readers --bank N --reach 8`**, then read the code before each reader for the
   index range: the loop bound, the `ASL` that doubles it, the `CMP #n` that caps it.
   Size each table from that and check it against where the next thing starts. Tables are
   packed with no slack, so a gap's total almost always comes out exact.
2. **Look for a general mechanism first.** Most progress came from `known-data`
   collectors and walker registries, not one-off labels: if a gap is handed to a known
   routine through an inline word, a fixed RAM pointer or a slot array, every other site
   probably has the same shape, and one registry entry labels them all. A gap with no
   reader is often a record or stream: `find 'lo hi'` its raw pointer and read what holds
   it.
3. **A gap that disassembles cleanly and ends in `RTS` is usually an uncalled routine.**
   `find-refs` its entry, scan for the raw pointer and the `RTS`-trick pointer (entry
   - 1), then give it a tier-3 name with a comment starting "maybe dead: no static
   caller".
4. **Label** with `golf-labels "$M" add prg '$START-$END' --bank N Name --comment '...'`
   (no `--bank` for the fixed bank). Names come from what the readers do, prefixed
   `Maybe` when the purpose isn't certain. Overlapping envelopes read at shifted bases
   get one label listing every base and reader (`Pulse2SfxEnvelopeTables`).
5. **Check the invariants** after each batch.

The registries to extend when a new case is confirmed, each entry carrying its
reasoning: `INLINE_ARG_ROUTINES` (`golf/core/rom_analysis.py`), `CODE_POINTER_TABLES`
(`golf/core/rom_trace.py`), `SCRIPT_POINTER_TABLES` (`golf/core/text_script.py`),
`RECORD_POINTER_TABLES` and `RECORD_LISTS` (`golf/core/object_script.py`), and
`GRAPHICS_POINTER_TABLES` and `RENDERERS` (`golf/core/known_data.py`).

## Confirming in Mesen

Static analysis proposes; a breakpoint confirms. Record every result in the label's
comment with the date and what was played, so it is never re-run.

- Use **execute** breakpoints for code. A read breakpoint on a label right after an
  `RTS` fires on every return, because the 6502 reads and discards the byte after a
  one-byte instruction (`$D131`, after the `RTS` at `$D130`).
- Use **read** breakpoints for data nothing statically reads.

## Traps already found

- **`DispatchInlineJumpTable` returns** after its table (shared tail at `$D24F`). It
  was once registered as non-returning, which hid the whole course intro.
- **Four metasprite formats**: chunked (`RenderMetasprite`, `RenderMetaspriteClipped`),
  a count then 3 bytes a sprite (`RenderMetaspriteWithAttr`), a count then 4 bytes a
  sprite (bank 13 `RenderGreenViewMetasprite`), and inline loops with their own formats.
  Measure with the renderer the site actually reaches; `known-data` looks one call deep
  for it.
- **Lo/Hi one byte apart is a word table read with a stride**, not two one-entry
  tables (`ReplaySaveHeaderPtrTable`/`ReplaySaveDataPtrTable` were once mislabeled so).
- **A zero-count object stream step halts the stream**; reading on runs into data.
- **`$FF` runs**: a graphics stream's terminator looks like padding, so padding starts
  only after every measured region. And **padding can be read**: bank 11 `$85BB` points
  a 2-byte attribute descriptor at `$FFEE`, inside `MaybeBank15TailPadding`.
- **Overlapping data is real**: metasprites, tile lists and DPCM samples share tails
  (the `$C000` sample runs 17 bytes into `DmcDrumData`), and envelope tables are read at
  shifted bases. Merge same-kind overlaps into one label; report the rest.
- **Labels can be wrong about what they are**: `ViewOffsetToAttrStart` was a nametable
  descriptor (now `AttributeTransferDescriptor`), and `LD_8F24` was a stub a linear
  disassembly left inside a table. When a new range warns about an overlap, check the
  other label before trusting it.
- **Label extents can be off by one entry.** `NoiseDecayEnvelopeTable` looked indexed
  1-15, but its counter starts at 16 and is decremented before each read (2-16);
  `SignpostBannerDescriptorTable` once stopped 4 bytes short of its fifth descriptor. A
  small gap right after a table is worth checking against that table's reader first.
- **RAM labels lie by context**: `$071D` is `SuppressMenuHistoryPushFlag` in the menu and
  a variant index or animation pointer elsewhere; `SceneTileMap` covers many unrelated
  arrays, the object slot arrays at `$7811`-`$7B01` among them. Read the code, not the
  label.
- **A script or stream can be named only inside other data.** `PrizeAwardTextScript` has
  no code pointer at all; its address sits in an object stream's `$F6` operands
  (`stream_scripts` now finds these).
- **Tests pinned to label state** break when a gap gets labeled. Test tool behavior on
  mock ROMs instead.
- **`golf-labels`**: `edit` can't change a range (remove and re-add; it inserts in
  address order); a one-byte range is read as a code label (`is_data_range`), so lone
  bytes stay gaps; write the base file, not the sidecar.

## Open questions

Each is recorded where it lives, in the label's comment.

- **Uncalled code**: 13 blocks in the fixed bank (839 bytes, the largest
  `DecompressGraphicsStreamToRam` at `$D69E`) and 7 in banks 9, 13 and 14. One Mesen pass
  (2026-10-04, jdharms) put execute breakpoints over every block and hit none through the
  credits combo, every club house screen, a one-hole tournament bet against a CPU
  opponent, practice, two-player stroke play and one-player match play with saves. Not
  covered: a full tournament or the earned ending, a hole-in-one or albatross, rank
  promotion, a new save file. Bank 11 `LB_80C7` and bank 14 `LE_8A44` follow a `JMP` with
  nothing branching to them, so need no breakpoint.
- **`Maybe` data nothing reads**, for read breakpoints: `MaybeUnusedSceneFlagTable`
  (bank 9 `$942B`), `MaybeUnusedData9B38B`, `MaybeUnusedDataC8293`,
  `MaybeUnusedDataAA296`, `MaybeUnusedDataDAC85`, `MaybeUnusedDataDB3A0`, and the table
  tails `MaybeUnusedPutterDistanceSpeed34`, `MaybeUnusedPutterDistAltSpeed34` and
  `MaybeBunkerExitClubThresholdTable` (only entry 1 read).
- **Names**: generated data names (`Metasprites4BF7F`, `ObjectAnimStreamAA278`,
  `TextScriptBA089`, ...) and the routine entries without a tier-3 name
  (`trace --unnamed`).
