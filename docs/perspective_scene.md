# The Perspective Scene

> **Note**: This document was written by Claude based on investigation requested by jdharms.

Before each shot the game draws the hole as seen from behind the golfer: a scene built in
WRAM as a tile map (`$77E6` onwards) and a depth map (`$7AE6`), from probes of the course
ahead. The code and its tables are in bank 9. `golf/physics/scene.py` ports every step
that writes either map and is checked against the ROM (`docs/shot_physics.md`, **The
scene builder**), so what this document says about those steps is confirmed. Names
beginning `Maybe` in the label file mark the parts whose purpose is still a reading of the
code: the flagstick and the other sprites, which the port leaves out.

## The steps - `BuildPerspectiveScene` (`$8829`)

Far-called from `ShotSetupSequence` (bank 13 `$8829`), with `$BD` set to `Aiming`:

| Step | Routine | Writes |
|---|---|---|
| Where the flag and green fall on screen | `ProjectFlagIntoScene` (`$98EA`) | `$0727`, `$078E`-`$0794` |
| The probe grid | `$8834`-`$888A` | 20 x 64 lies at `$7AE6`; `$0726` |
| Flagstick nudged off a green too small to draw | `NudgeSceneFlagstick` (`$9C1C`) | `$078E`, `$078F` |
| Each 4x4 block cut to three lies | `ThinSceneLieBlocks` (`$8EE4`) | the grid; `ScenePaletteMap` (`$072D`) |
| A tile per 2x2 block | `DrawSceneGroundTiles` (`$9CB8`) | tile map rows 14-23 |
| Tiles fitted to their neighbors | `FitSceneGroundTiles` (`$A30B`) | tile map rows 14-23; `$073D` |
| Sky, and nothing standing | `$88A1`-`$88F3` | tile map rows 0-13 to `$3A`; depth map to `$FF`; `$7DE6` |
| Trees found | `FindSceneTrees` (`$8FE4`) | `SceneTreeBandTable` (`$7DE6`), `SceneTreeDepthTable` (`$7E06`) |
| Flagstick sprites | `$99B2` | OAM, `$078E` |
| Trees drawn | `DrawSceneTrees` (`$91C9`) | both maps; the RNG |
| Other sprites | `$9A79` | OAM |

After it returns, `ShotSetupSequence` far-calls `ShowPerspectiveScene` (`$96EC`), which
turns the palette map into attribute bytes, stamps the sky blocks and sends the tile map
to the nametable. So the sky blocks are in the tile map during the flight but not when
the builder returns.

The probe grid lives where the depth map will be: the depth map is only cleared and
written once the ground is drawn.

## Probing the course

The loop probes 20 rows of 64 points ahead of the ball along `Aiming`:

- `PerspectiveProbeOffsetTable` (`$89D0`-`$8ECF`) holds one signed byte per probe, the
  distance to the side, 20 x 64, walked through `$64`. `PerspectiveRowTable`
  (`$8ED0`-`$8EE3`) holds each row's distance ahead: 99, 67, 49, ... 1, 0, -1.
- `OffsetProbeFromBall` (`$899B`) turns the pair by `Aiming` with `LE638`, the 8-bit
  entry of `RotateVector16`: each product keeps only the high byte of |component| x
  |sin| or |cos|. The result is added to the ball's pixel; X is clamped to the course
  (`LEDD4_ProbeWithClampedX`) and Y wraps at 16 bits, so a probe above the top of the
  hole is out of bounds.
- Each probe's lie (`ClassifyProbePosition`'s 0-6) goes into the grid. Green (6) is
  rewritten as rough (2) on the four farthest rows, and everywhere when `$0727` is set.
- After each row, `L9_896C` takes that row's byte from `MaybePerspectiveRowFadeTable`
  (`$897D`) and hands it to `LD7DB` with `PaletteBuffer` as its inline word - stepping the
  palette as the rows appear - or calls `LCDB3` for a `$80`.

`$0726` keeps the lie at row 18, column 34 (`$7F88`), which is the ball's own.

## Thinning the grid - `ThinSceneLieBlocks` (`$8EE4`)

Each 4x4 block of the grid: out of bounds and the tee become rough, and green becomes 1.
Sand and water then both become rough, unless one of them outnumbers both the other and
the fairway; that one is kept, the fairway becomes rough instead, and the block's entry
in `ScenePaletteMap` becomes 2 (sand) or 3 (water) in place of 1. A block is left with
at most three lies, which the next step depends on.

## A tile for each 2x2 block - `DrawSceneGroundTiles` (`$9CB8`)

Ten rows of 32 tiles, top left first, each from a 2x2 block of the grid (`$EC`-`$EF`).
`L9_9D1C` picks the lie the block is drawn as (`$EA`) and the one it is drawn against
(`$EB`), by `SceneClassPriorityTable` (`$9E18`); a block of three lies first repaints the
corner that stands alone, unless that corner's lie carries on into the cells above and
beside it (`SceneNeighborOffsetTableA`/`B`, `$9DC8`), in which case the other single
corner is repainted. Its path for four different lies (`$9DD0`) runs on into a search
that assumes three and walks off into the zero page; `ThinSceneLieBlocks` makes it
unreachable.

`L9_9E1F` then sets one bit per corner that matches `$EA` and jumps through
`SceneTileMatchRoutinePtrTable` (`$9E41`, 16 entries) by that mask. Each routine points
`$20` at a `SceneTileMatchTable` block and calls `L9_A294`:

- A block starts with 4 signed grid offsets (`$C0` is a row up). `L9_A294` reads the
  grid at each (`L9_A2F9`) and scores two pairs: in each, the first matching `$EA`
  counts 2 and, failing that, the second counts 1; the first pair counts three times
  over, giving an index 0-8. `L9_A305` adds 9 when `$EA` is 1 (green).
- The 24-byte blocks start with 2 more offsets for `L9_A2D8`. When that pair matches
  neither and `SceneTileMatchShared9F1E` has an entry for the index, its bits repaint one
  or two corners with `$EB`, and bit 1 starts the block again at `L9_9E1F`.
- 18 result tiles follow. A result of 0 falls back to `SceneTileByClassTable` (`$A28D`,
  by lie) or, for the three-corner masks, repaints a corner and starts again.

`SceneNeighborOffsetPairs` (`$9FF7`) holds three more offset pairs for `L9_A2D8`, which
the diagonal masks (`$9FB1` and `$A067`) try in turn, repainting a corner each time.

Nothing keeps the offsets inside the grid. The row above it is the bottom of the tile
map, which at that point still holds the last scene's tiles, and the rows after it are
the end of WRAM and then bank 9 itself.

## Fixing tiles from their neighbors - `FitSceneGroundTiles` (`$A30B`)

`L9_A348` goes over the ten ground rows of the tile map, bottom-right first (`$62` starts
at `$7AC5`, a row before the last cell). For each cell:

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
   a second list chosen when `$2A` is set (the cell is a green tile, key 19 and up). A
   neighbor not in its list sets the bit. So does one that is, when its block's entry in
   `ScenePaletteMap` (`ReadScenePaletteMap`, `$A695`) differs from the cell's, unless
   `$2A` is set or the neighbor is above the top row.
3. The table entry for the mask (+8 when `$2A` is set, `L9_A4A3`) replaces the tile; 0
   leaves it.
4. `L9_A644` then replaces any of four tiles in `SceneNeighborMaskedKeyTable` when bit 3 of
   the mask is set, and any of the 24 tiles at `$A592` with its entry in
   `SceneNeighborReplaceTileTable`, except in blocks whose palette is 1.

`L9_A315` then finishes the top ground row where the palette is 0 or 3: sky `$3A` becomes
`$3C` and `$5A`, `$71` and `$72` become `$3D`, and the block's palette becomes 0.
`L9_A6A7` fills the two bottom rows with `$39` when the ball's own lie (`$0726`) is 1,
the green.

## Drawing the trees - `FindSceneTrees` (`$8FE4`) and `DrawSceneTrees` (`$91C9`)

`FindSceneTrees` takes the box around the ball and two points 105 pixels ahead and 55 to
either side (`OffsetProbeFromBall`), and probes it every 8 pixels. A tree tile
(`$9C`-`$BF`, or `$3E`) has one or two points (`SceneTreePointCountTable`, `$90ED`;
offsets from the tile's corner in `SceneTreePointXOffsetTable`/`YOffsetTable`), and
`L9_9149` projects each with `ProjectBallIntoScene`:

1. A point nearer than depth 14 is dropped. One on the green's screen row and between
   its columns (`$078F`, `$0793`, `$0794`) is moved 4 pixels down the screen.
2. `SceneTreeBandThresholdTable` (`$91B8`) turns its screen y into a size band 1-15.
3. Its screen column keeps the band and depth (`SceneTreeBandTable` `$7DE6`,
   `SceneTreeDepthTable` `$7E06`) unless a larger band is already there.

The projection is called with only the pixel bytes of the point set, so its fraction
bytes are the flag's, left from `ProjectFlagIntoScene`.

`DrawSceneTrees` then draws one tree per column, smallest band first, right to left:

1. **The trunk.** `SceneTreeTrunkPtrTable` (`$9499`) points at a run of trunk tiles in
   `SceneTreeTrunkTiles`, drawn down from row 14. A tile is written only over rough
   (`$38`) or sky (`$3A`, as its `SceneTreeTrunkOnSkyTileTable` entry) and only where the
   palette map is not 0, but every cell of the run gets the tree's depth. The first
   three are also queued to `PPU_UpdateBuffer` from `SceneTreeTrunkPpuTileTable`.
2. **The canopy.** `SceneTreeSizeByBandTable` (`$9488`) turns the band into a size 0-6,
   which indexes `SceneTreeCanopyColumnPtrTable`, `SceneTreeCanopyRowPtrTable` and
   `SceneTreeCanopyTilePtrTable`: three parallel lists of column offsets, rows (ended by
   a negative byte) and tiles. Each cell gets the tree's depth and, over anything below
   `$C0`, the tile.
3. **Over another tree**, both tiles are classed by `ClassifySceneTreeTile` (`$93FE`) - a
   search of `SceneTileClassKeyTable` (`$940F`, 28 tiles) returning `SceneTileClassTable`
   (`$945C`), or `$0D` - and the pair decides: keep, replace, a fixed tile, or
   `SceneTreeOverlapTileTable` (`$9478`). An old tile of class `$0D` is replaced by one of
   four `SceneClass0DTileTable` tiles picked with the RNG, the build's only draw. A
   new tile of `$CC` or more with a 0 in `SceneTreeCanopyDepthFlagTable` (read as
   `$935F,X`, so the table starts at `$942B`) puts the cell's depth back as it was.

## Blocks in the sky - `StampSceneSkyBlocks` (`$9785`)

Before the scene goes to the nametable (`$9707`, in `ShowPerspectiveScene`),
`StampSceneSkyBlocks` stamps six fixed tile blocks
from `MaybeSceneSkyBlockTiles` (`$98A2`) into the tile map through `L9_97F8`, at fixed
columns and rows near the top. A block is written only when every tile under it is still the
blank `$3A` (`$9831`), so scenery that reaches that high hides it. Read as clouds, but not
confirmed.

## Probably the flagstick

`L9_99B2` draws a strip of tiles at `$078E`/`$078F` chosen by `$0790`: a count and
(dY, tile) pairs from `MaybeSceneFlagstickLists`, six lists of one to six tiles, offset by
`MaybeSceneFlagstickXOffsetTable`. `MaybeSceneFlagTileTable` (`$9B59`, 3 x 3) adds a tile
by `$0792`, which `$9960`-`$996E` raises as the target gets nearer, on the row
`MaybeSceneFlagYBaseTable` (`$9BCE`) places by the same index. Read as the flagstick
growing with distance, but not confirmed.

`GreenCornerXOffsetTable`/`YOffsetTable` (`$99AA`) are the four points around the green
the loop at `$9971` checks.

## Open questions

- Whether the flagstick reading is right, and what `$0790`-`$0794` are.
- What `$9A79` draws.
