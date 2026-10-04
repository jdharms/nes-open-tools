# The Perspective Scene

> **Note**: This document was written by Claude based on investigation requested by jdharms.

Before each shot the game draws the hole as seen from behind the golfer: a scene built in
WRAM as a tile map (`$77E6` onwards) and a depth map (`$7AE6`), from probes of the course
ahead. The code and its tables are in bank 9. This document covers what was read while
labeling that bank; names beginning `Maybe` in the label file mark the parts whose purpose
is a reading of the code rather than something confirmed in the emulator.

## Probing the course - `BuildPerspectiveScene` (`$8829`)

Called from `ShotSetupSequence`. It probes 20 rows of 64 points ahead of the ball along
`Aiming`:

- `PerspectiveProbeOffsetTable` (`$89D0`-`$8ECF`) holds one byte per probe, 20 x 64,
  walked through `$64`. `L9_8991` passes the byte in A to `LE638`, with the row's byte from
  `PerspectiveRowTable` (`$8ED0`-`$8EE3`) in Y; the result is added to the ball's position
  and probed with `LEDD4_ProbeWithClampedX`.
- Each probe's terrain class goes into the tile map; class 6 is rewritten as 2 unless
  `$0727` is set or the row is one of the first four.
- After each row, `L9_896C` takes that row's byte from `MaybePerspectiveRowFadeTable`
  (`$897D`) and hands it to `LD7DB` with `PaletteBuffer` as its inline word - stepping the
  palette as the rows appear - or calls `LCDB3` for a `$80`.

It then runs `L9_9C1C`, `L9_8EE4`, `L9_9CB8` and `L9_A30B`; the last leads to the tile pass
below.

## Fixing tiles from their neighbors - `L9_A348`

Ten rows of 32 cells of the map at `$7AC5`, bottom-right first. For each cell:

1. The cell's tile is looked up in `SceneNeighborKeyTileTable` (`$A56C`, 38 tiles); the
   index of the match, in `$00`, picks one of seven tables:

   | Table | Key index |
   |---|---|
   | `SceneNeighborTileTableKeys0To4` (32 entries) | 0-4 |
   | `SceneNeighborTileTableKeys5To6` | 5-6 |
   | `SceneNeighborTileTableKeys7To8` | 7-8 |
   | `SceneNeighborTileTableKeys9To11` | 9-11 |
   | `SceneNeighborTileTableKeys12To13` | 12-13 |
   | `SceneNeighborTileTableKeys14To15` | 14-15 |
   | `SceneNeighborTileTableKeys16Up` | 16 and up |

2. A neighbor mask is built in `$29`, one bit per test. Each test (`L9_A4AD`, `L9_A4E0`,
   `L9_A50A`, `L9_A534`) searches a neighbor's tile in a list from
   `SceneNeighborTileLists` (`$A592`-`$A63B`): nine lists that overlap, sharing tails, with
   a second list chosen when `$2A` is set.
3. The table entry for the mask (+8 when `$2A` is set, `L9_A4A3`) replaces the tile; 0
   leaves it.
4. `L9_A644` then replaces any of four tiles in `SceneNeighborMaskedKeyTable` when bit 3 of
   the mask is set, and any of the 24 tiles at `$A592` with its entry in
   `SceneNeighborReplaceTileTable`.

## Tile-match routines - `$9E23`

A second pass compares each cell's class (`$EA`) with its four neighbors, sets one bit per
match (`$9E23`-`$9E32`), and jumps through `SceneTileMatchRoutinePtrTable` (`$9E41`, 16
entries) by that mask. Each routine points `$20` at a `SceneTileMatchTable` block and calls
`L9_A294`:

- A block starts with 4 signed tile-map offsets (`$C0` is a row up). `L9_A294` reads the
  map at each (`L9_A2F9`) and counts matches with `$EA` in the first pair and the second
  pair, giving an index 0-8; `L9_A305` adds 9 when `$EA` is 1.
- The 24-byte blocks start with 2 more offsets for `L9_A2D8`, which picks between halves.
- 18 result tiles follow. A result of 0 falls back to `SceneTileByClassTable` (`$A28D`, by
  class); `SceneTileMatchShared9F1E` serves four routines without the +9.

`SceneClassPriorityTable` (`$9E18`) ranks the seven classes where two meet, and
`SceneNeighborOffsetTableA`/`B` (`$9DC8`) are the offsets one more routine checks.

## Drawing the ball into the scene - `L9_91C9`

The ball is composited into the tile map as background tiles, at a size set by its depth:

1. Per screen column, `$9195` finds the ball's depth band (1-16) by scanning
   `SceneBallBandThresholdTable` (`$91B8`) with `BallScreenY`, and stores it in `$7DE6`
   with `BallSceneDepth` in `$7E06`.
2. For each band, `SceneBallStripPtrTable` (`$9499`) points at a run of ball tiles in
   `SceneBallStripTiles`; tiles found in `SceneBallTileTable` (`$9295`, six) are written,
   swapped for their `SceneBallOnTile3ATable` entry over tile `$3A`, and the first three
   are also queued to `PPU_UpdateBuffer` from `SceneBallPpuTileTable`.
3. `SceneBallSizeByBandTable` (`$9488`) turns the band into a size 0-6, which indexes
   `SceneBallColumnPtrTable`, `SceneBallRowPtrTable` and `SceneBallTilePtrTable`: three
   parallel lists of column offsets, rows (ended by a negative byte) and tiles.
4. Where the ball covers scenery, both tiles are classified by `L9_93FE` - a search of
   `SceneTileClassKeyTable` (`$940F`, 28 tiles) returning `SceneTileClassTable` (`$945C`) -
   and `SceneBallOverlapTileTable` (`$9478`) gives the tile for the pair. Class `$0D`
   scenery picks one of four `SceneClass0DTileTable` tiles at random.

The 49 bytes between the two class tables (`$942B`-`$945B`, all 0 or 1) have no reader.

## Probably the flagstick

`L9_99B2` draws a strip of tiles at `$078E`/`$078F` chosen by `$0790`: a count and
(dY, tile) pairs from `MaybeSceneFlagstickLists`, six lists of one to six tiles, offset by
`MaybeSceneFlagstickXOffsetTable`. `MaybeSceneFlagTileTable` (`$9B59`, 3 x 3) adds a tile
by `$0792`, which `$9960`-`$996E` raises as the target gets nearer. Read as the flagstick
growing with distance, but not confirmed.

`GreenCornerXOffsetTable`/`YOffsetTable` (`$99AA`) are the four points around the green
the loop at `$9971` checks.

## Open questions

- What `$942B`-`$945B` is, and what reads it.
- Whether the flagstick reading is right, and what `$0790`-`$0794` are.
- What `LE638` computes from the probe and row bytes.
