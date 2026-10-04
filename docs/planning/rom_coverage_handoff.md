# Hand-off: Explaining the Remaining ROM Bytes

> **Note**: This document was written by Claude for the next agent picking up this work,
> at jdharms's request.

The goal is a full disassembly of the US ROM. The work so far has made every byte of the
256KB PRG either traced code or covered by a range label, except for **7,767 bytes in 138
runs**. This document says where things stand, how the remaining bytes were left, the
method that worked, and the traps already found.

## Where things stand

`golf-rom-peek nes_open_us.nes --labels "NES Open Tournament Golf (USA).mlb" trace`:

| Bank | Code | Labeled data | Unexplained |
|---|---|---|---|
| 0, 1, 5, 6, 7, 8 | stubs | everything | 6-10 each (vectors) |
| 2 | 2,433 | 13,840 | 111 |
| 3 | 403 | 15,959 | 22 |
| 4 | 109 | 16,205 | 70 |
| 9 | 10,466 | 5,735 | 183 |
| 10 | 183 | 15,448 | 753 |
| 11 | 5,424 | 10,188 | 772 |
| 12 | 9,791 | 6,519 | 74 |
| 13 | 12,410 | 2,064 | **1,910** |
| 14 | 6,109 | 8,716 | **1,559** |
| 15 (fixed) | 7,526 | 6,585 | **2,273** |

Invariants that hold now and should keep holding:

- **No unresolved control flow and no conflicts** in the trace.
- **No two range labels overlap**, and no label name repeats (check below).
- **`known-data` is idempotent**: a dry run reports 0 new labels.
- `uv run pytest` and `uv run golf-check` pass.

## The tools

All in `golf-rom-peek` (see the `nes-open-golf-rom-peek` skill):

- **`trace`** - recursive descent from the vectors (`golf/core/rom_trace.py`), plus the
  text-script walker (`golf/core/text_script.py`, `docs/text_scripts.md`) and the
  scene-object walker (`golf/core/object_script.py`, `docs/scene_objects.md`), repeated
  until neither finds new code. `--unreached` lists labels never decoded, marking roots.
- **`known-data [--list] [--write]`** - collectors that measure data from the ROM
  (`golf/core/known_data.py`): graphics tables, course data, padding, text scripts, scene
  objects, CPU opponent shots (`docs/opponent_shots.md`), metasprites drawn directly,
  palettes, nametable descriptors. It refuses to write if regions overlap traced code,
  each other, or a single-address label.
- Registries to extend when a new case is confirmed: `INLINE_ARG_ROUTINES`
  (`rom_analysis.py`), `CODE_POINTER_TABLES` (`rom_trace.py`), `SCRIPT_POINTER_TABLES`,
  `RECORD_POINTER_TABLES`, `GRAPHICS_POINTER_TABLES`. Each entry carries the reasoning.

## The method that worked for a bank

1. **List the gaps with their readers.** For each gap, every traced `abs`, `abs,X` or
   `abs,Y` operand pointing into it. This was a scratch script, not a tool - adding it as a
   `golf-rom-peek` subcommand (`readers <bank>`) would be the first useful step. Restrict
   fixed-bank readers to the bank they actually have mapped; the scratch version didn't,
   and sent one investigation after a bank 13 call.
2. **Read the code before each reader** and work out the index range: the loop bound, the
   `ASL` that doubles it, the `CMP #n` that caps it. Size each table from that, then check
   it against where the next thing starts. Tables here are packed with no slack.
3. **Look for a general mechanism first.** Most of the progress came from collectors
   (graphics, descriptors, palettes, metasprites) rather than one-off labels: if a gap's
   data is handed to a known routine through an inline word or a fixed RAM pointer, every
   other call site probably has the same shape.
4. **Search for pointers built from immediates** (`LDA #lo ... LDA #hi`, often into `$20`,
   `$22`, `$0414`, `$0685`, `$071D`) for gaps with no direct reader.
5. **Label** with `golf-labels add prg '$START-$END' --bank N Name --comment '...'`.
   Names come from what the readers do. When a reader shows what a table does but not what
   it is for, prefix `Maybe` and put the exact indexing and reader address in the comment.
   Mechanical names follow `<Kind><What><bank hex digit><addr>` (`ChrGraphicsTable7BAD5`),
   chosen by jdharms.
6. **Check** after each batch: the overlap check below, `known-data` (0 new), `trace`
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

## Leads on what is left

Largest first. Most need the reader method above; a few have a head start.

- **Fixed bank `$EA7C` (832).** `TestSceneTileCoversPixel`'s comment already describes it:
  1bpp masks for tiles `$C0`-`$CB` at `$EA7C`, 2bpp from `$EAAC` for tiles `$CF` up. Size
  from the tile ranges and label.
- **Bank 13 `$9275` (536).** A metasprite set the metasprite collector skips: the renderer
  call is more than 12 instructions after the pointer load (`RENDERER_REACH`). Read the
  site, then raise the reach or handle it by hand.
- **Fixed bank `$C1E3` (349), right after `DmcDrum2Data`.** Probably audio; check
  `golf/core/audio.py` (`DMC_*` tables) and `docs/music_format.md`.
- **Fixed bank `$D69E` (317), after `LD693`** (the graphics decompression path), and
  `$F359` (110).
- **Bank 10 `$9C48` (264), `$9D65` (103) and the rest (753).** Scene-object data: sprite
  `$00`'s frame table and metasprites, used by no record the walker finds. The club house
  menu allocates objects from `MenuEntryTablePtr` (bank 12 `$85A8`), runtime data the
  object walker doesn't follow - following `docs/menu_system.md`'s tables would likely
  account for it.
- **Bank 14 (1,559)** - menu screens: gaps after palettes (`$B31B`, `$BEFE`, `$B818`),
  after object records (`$BC2C`), and in code areas (`$8681`, `$843E`).
- **Bank 13 (1,910)** - course view and physics-adjacent: `$A77A`, `$9EC4`, `$BAD2` and
  smaller. `golf/physics/tables.py` already names many tables in this bank.
- **Bank 11 (772)** - `$8887` (219; a table of `$60xx` SRAM addresses), `$8982`, `$8F51`,
  and `$B997` (126): the prize-award script ("We hereby award you..."), which nothing
  found loads; a Mesen breakpoint on a `ScriptPtr` write during a tournament win would find
  its setter.
- **Every bank's vectors at `$BFFA`** (6 bytes each, ~90 in all): a small collector would
  label them in one step.
- **Leftovers with no reader** in banks 9 and 12 (listed in `docs/perspective_scene.md`'s
  open questions and the bank 12 notes in the label comments): candidates for dead data.
- **Unreached code**: bank 9 `$B4E3`, `$BF76`, `$A63C`; fixed `$D3C1` (a far nametable
  write with no callers); possibly dead, confirm in Mesen before calling it so.

## Traps already found

- **`DispatchInlineJumpTable` returns** after its table (shared tail at `$D24F`); it was
  once registered as non-returning, which hid the whole course intro.
- **Three metasprite formats**: chunked (`RenderMetasprite`, `RenderMetaspriteClipped`),
  count plus 3 bytes a sprite (`RenderMetaspriteWithAttr`), and inline loops with their
  own formats. Measure with the renderer the site actually reaches.
- **Lo/Hi one byte apart is a word table read with a stride**, not two one-entry tables.
- **A zero-count object stream step halts the stream**; reading on runs into data.
- **`$FF` runs**: a graphics stream's terminator looks like padding; padding must start
  after any measured region.
- **Overlapping data is real**: metasprites share tails, tile lists share tails, tables
  overlap by design (`$9478` style). Merge same-kind overlaps; report the rest.
- **Tests pinned to label state** break when a gap gets labeled (`test_rom_analysis_rom`
  had one). Prefer unit tests on mock ROMs for tool behavior.
- **RAM labels lie by context**: `$071D` is `SuppressMenuHistoryPushFlag` in the menu and
  a variant index or animation pointer elsewhere; `SceneTileMap` covers many unrelated
  arrays. Read the code, not the label.

## Housekeeping

- The label file is a symlink into the private `jdharms/nes-open-labels` repository. Never
  publish it. jdharms has uncommitted work there; `golf-labels` edits in place without
  re-sorting, so diffs stay readable.
- `golf-labels` writes the base file; don't use the sidecar.
- Commit messages are jdharms's to write.
