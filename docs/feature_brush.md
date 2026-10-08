# Feature Brush

The editor tool that paints fairways, bunkers and water as shapes, and the fit behind it
that chooses their border tiles. The decision and what was turned down are in ADR 0013.
The Out of Bounds Brush paints out-of-bounds ground the same way and draws its line
([below](#out-of-bounds-brush), ADR 0014). The Green Brush paints a green's putting
surface and draws the fringe round it ([below](#green-brush), ADR 0020).

## Using it

| Input | Does |
|-------|------|
| `B` | Select the Feature Brush |
| Left-drag | Paint |
| Right-drag | Erase |
| Palette buttons | What is painted: 1 fairway, 2 bunker, 3 water; palette 0, which only the eyedropper selects, is water too |
| `,` / `.` | Brush radius, 2 to 16 course pixels, 6 to begin with |
| `Esc` | Cancel the stroke in progress |

The stroke shows as an overlay while the button is held. On release the tiles round it
are chosen and written, as one undo step. Terrain mode only.

The brush edits what is already there: painting onto an existing fairway widens it, and
erasing cuts into it. It works on every feature of the selected kind that the stroke
touches.

## What it writes

Only bare ground (`$25`, `$DF`), the editor's placeholder (`0x100`, left by cutting a
selection) and the tiles of the kind being painted are changed.
Left alone:

- trees, forest, the out-of-bounds border and the tee box (a tree in a feature counts
  as fixed feature, below);
- features of another kind, and features of the same tiles under another kind's palette;
- bare ground in a supertile that holds any tile drawing in color 3 under another
  kind's palette - a feature, a tree standing in one, or the tee box - since the palette
  under a new tile has to become the brush's, and would recolor them.

Where a painted stroke runs over any of these, the pixels within three of their cells are
left to the fit to draw or not, so the border closes in front of them the way the tiles
allow. A stroke that stays off them is drawn as painted, right up to their cells.

A stroke extends the shape it reaches and stops at what it may not write: any part of
it cut off from that shape, by trees say, is dropped, where cells that touch only at a
corner count as cut off. A stroke that reaches no shape of its kind starts a new one.

A tree standing in a feature of the kind being painted (`$BC`-`$BF`, the tree drawn over
`$27`) is part of the feature, but fixed: the brush never writes it, and the tiles round
it meet it as they would meet `$27`. Painting over it finds the feature already there.

Under each tile it places, the supertile's palette becomes the selected one unless it
already draws that kind (palette 0 stays 0 under water). New water is always drawn with
palette 3, even with palette 0 selected, since palette 0 is the HUD's and would draw any
forest or out-of-bounds line in the supertile white. Erased tiles become whichever
ground tile is commonest nearby, and their palette is left as it is.

Only the part of the shape the stroke touched is fitted again: the cells whose shape
changed, and the cells next to those unless they hold some other feature, or another arm
of the same one. Those neighbors keep their tiles unless the change beside them calls for
another (`SETTLED_BONUS`). Nothing further away changes.

## The fit

`golf/algorithms/feature_fit.py`. A feature is `$27` inside and border tiles round its
edge; every tile draws a different shape in color 3, so the tile for a cell follows from
where the outline crosses it. A family is the set of tiles one kind of border is drawn
with; features use two (the out-of-bounds line is a third, [below](#the-line), and a
green's fringe a fourth, [below](#the-zones)):

| Family | Tiles | Draws |
|--------|-------|-------|
| `fairway` | `$27` and the 43 border tiles with no black outline | fairways |
| `hazard` | `$27` and all 64 border tiles, `$40`-`$7F` | bunkers and water |

`FeatureFitter.fit` takes the wanted shape as a pixel mask and picks a tile, or bare
ground, for each cell on or beside the outline (an outline along the grid included, on
both sides of it), minimizing the sum of:

| Cost | Constant |
|------|----------|
| Pixels where the tile differs from the mask, weighted by distance from the mask's outline beyond `SLIDE`; inside that band a pixel costs `TIE_BREAK` | `SLIDE = 1`, `TIE_BREAK = 0.05` |
| The square of the pixels by which two neighboring tiles' facing edges disagree, less the more of that pair the vanilla holes have | `SEAM_WEIGHT = 1`, `SEAM_TRUST = 15` |
| How rare each side-by-side and stacked pair is in the vanilla holes, against each tile's commonest partner | `PAIR_WEIGHT = 2` |
| Each 2x2 block of tiles that no vanilla hole has | `BLOCK_COST = 10` |

It starts from the best tile per cell, then repeatedly gives each run of neighboring
cells in a row, and then in a column, its cheapest tiles with every other cell held
(exact for the run, by dynamic programming) until nothing improves: first on the first
three costs, then with the fourth. The result is a local optimum.

A pair's rarity is the mean of -log of its count over the count of the left tile's
commonest partner, and over the right tile's, from counts smoothed by `PAIR_SMOOTHING`.
A feature in its usual tiles then costs about what bare ground does, which is what lets
small features be drawn at all. Unseen pairs and blocks cost more; none is forbidden.

The seam cost is squared so that a tile's whole edge standing against bare ground, which
costs 64, is drawn only when nothing else fits: a lone `$27` is not the answer to a dab
of the brush. It fades once the vanilla holes have the pair more than `SEAM_TRUST`
times, because some such pairs are how they draw. `$4A`, the flat-bottomed middle of a
one-row bunker, stands over bare ground 61 times. Fairways in 64 of the 144 holes have a
hard edge, `$27` against bare ground, 118 cells in all: a flat-topped tile between soft
tiles of about the same height (`61 27 62`), with ground on one side only in all but
one. Bunkers have 4 and water 34, so for hazards the pair pays nearly the whole cost.

A 2x2 block of `$27` and bare ground together counts as a border block like any other,
so the block cost keeps a hard edge to the shapes vanilla draws it in; only blocks all
`$27` or all bare ground are left out.

`golf/algorithms/feature_brush.py` applies a stroke to a hole: it reads the shape the
hole's tiles of that kind draw, adds or removes the stroke, drops anything thinner than
three pixels near the stroke, and refits the cells described above against two more
cells of context.

## The style table

`data/tables/feature_style.json` holds, per family, how often each pair of tiles sits
side by side (`right`) and stacked (`below`), and how often each 2x2 block occurs
(`blocks`, in reading order), over the vanilla holes of both ROMs. `--` is bare ground
(`$25`, `$DF`). A cell counts where it is bare ground or one feature of the family's
kinds owns the whole tile; pairs and blocks that take in anything else, a tree say, are
left out, and so are blocks all `$27` or all bare ground. For `boundary`, `$3F` stands
for any out-of-bounds cell, forest included, and cells are read from the tiles alone.
For `green`, counted over the greens, `B0` stands for the flat tile and every slope, and
`--` for the rough.

```bash
uv run golf-feature-style           # rewrite the table from courses/
uv run golf-feature-style --check   # exit 1 if it would change
```

`tests/integration/test_feature_style_vanilla.py` fails when the table no longer matches
the holes.

## Measurements

From the experiments the design came out of, 2026-10-02, made with a seam cost linear in
the mismatch, a pair's rarity taken as its plain share, trees counted as bare ground in
the statistics, and single cells and pairs re-chosen in place of whole runs; all changed
afterwards, as above. Each fit used the statistics of the other 143 holes. "Blocks in vanilla" is the share of a fit's 2x2 border blocks that
occur in some other vanilla hole.

Vanilla holes themselves: 97.6% of fairway blocks and 93.8% of hazard blocks occur in
another hole; 3.1% of fairway seams are off by three pixels or more.

Fairways that own all their tiles, moved 3 pixels right and 5 down:

| Fit | Blocks in vanilla | Seams off by 3+ px | Pixels off per border tile |
|-----|-------------------|--------------------|----------------------------|
| Seams only | 45% | 5.3% | 6.2 |
| Seams, pairs, `SLIDE = 2` | 90% | 1.3% | 10.1 |
| All four costs, `SLIDE = 1` (as built) | 92% | 3.6% | 7.6 |

214 enclosed hazards of 150 pixels or more, same move, as built: 95.6% of blocks in
vanilla, 1.2% of seams off by three or more, 10.6 pixels off per border tile, and 57%
of border tiles outlined against 59% in the vanilla holes. With seams only: 54% and 19%.

A stroke's refit took a median of 20 ms and at most 43 ms over 72 simulated strokes.

With the costs as built and the statistics of all 144 holes, over every twelfth hole:

| | Fairways | Hazards |
|---|----------|---------|
| A vanilla shape fitted as it is: tiles reproduced | 96.4% | 88.7% |
| Moved 3 right and 5 down: blocks in vanilla | 99.4% | 94.5% |
| Moved: pixels off per border tile | 7.9 | 11.0 |

Of the 78 hard-edged `$27` cells in fairways that own all their tiles, a fit of the
shape as it is gives 16 back, and draws hard edges in 18 cells where vanilla has soft
tiles; the shape alone seldom says which. Moved, 2.3% of a fitted fairway's cells are
hard-edged, against 1.0% in vanilla.

Mario Open's Australia 17 has a three-tile fairway (`56 5F` over `55`) in a pocket
between trees and forest; erased and painted back with a stroke that spills over the
trees, it comes back as the same three tiles. The same hole's one-row bunker
(`52 4A 4A 51`, row 7) painted along with a radius of 3 grows by a `4A` for each tile
of stroke.

## Limits

- The outline lands about a pixel from where it was painted.
- A shape thinner than three pixels is dropped, so erasing most of a feature can remove
  the strip that was left.
- A brush taller than a one-row feature grows it into the next row: extending
  `52 4A 4A 51` along its row takes a radius of 3 or less.
- A stroke too small for any tiles to draw changes nothing: a single click of a radius
  under 5 or so.
- Bunkers and water share one family and one set of statistics, so a bunker may take
  the hard lower edge (`$27` over bare ground) that only water draws.
- A single click of a radius of 6 or 7 can come out as a `$27` with bare ground on
  two sides or more, which vanilla draws once: 12 of 192 clicks at every offset within
  a tile.
- Edges of features cut off by the terrain's edge are fitted as if bare ground lay
  beyond it.
- Erasing the cells right beside a tree in a fairway leaves the tree's `$27` meeting
  bare ground in a hard edge: the tree stays, and its cell is all feature.

## Out of Bounds Brush

| Input | Does |
|-------|------|
| `O` | Select the Out of Bounds Brush |
| Left-drag | Paint out-of-bounds ground |
| Right-drag | Erase it back to rough: the commonest nearby, or deep rough (`$DF`) if there is none |
| `,` / `.`, `Esc` | As for the Feature Brush; the palette makes no difference |

On release the line is fitted round the new edge and the cells inside it become the
placeholder (`0x100`, the gray check). Nothing is filled: seed the region with `$3F` or a
forest edge tile to taste (`docs/forest_notes.md`) and run Forest Fill (`F`). Forest
beside any cell the stroke changed becomes placeholder too, since its trees may have run
into that cell, so reshaping a filled forest leaves a strip to fill again. `golf-write`
refuses a hole with placeholder left in it.

It writes over bare ground, the line, forest, `$3F` and the placeholder, and leaves
features, trees and the tee box alone. The line stops where it meets water: in 27
vanilla holes forest stands straight against a water hazard, whose black lip is then
the boundary. Fairways, bunkers, trees and the tee box are in bounds, so the line closes
in front of them, and a push into them stops there, as for the Feature Brush: no vanilla
hole puts forest against a fairway, and only two tile sides put it against a bunker. The
placeholder is out of bounds to this brush, and bare ground to the Feature Brush.

### The line

Out of bounds is speckled ground, edged with a solid black line drawn by `$80`-`$9B`
(`golf/algorithms/boundary.py`). Each tile holds one piece of the line, between two
points on its edge, a corner or the middle of a side, with the out-of-bounds side one
way or the other:

| Tiles | The line runs |
|-------|---------------|
| `$80`-`$83` | corner to opposite corner |
| `$84`-`$93` | from the middle of a side to one of the far corners |
| `$98`-`$9B` | straight across, middle to middle |
| `$94`-`$97` | along one side, corner to corner, the tile otherwise out of bounds |

A side is crossed by the line in its middle (at pixel 3 or 4, by which side is out of
bounds), or is in or out of bounds all along; neighbors continue the line when their
shared side agrees. `OUT_SIDES` records which sides are out of bounds, from where the
vanilla holes put forest. Over all 144 holes the line breaks at 35 places in 15 holes
(`line_breaks`), eight of them the tree `$3E` standing against forest.

The fit is the one above, with a third family, `boundary`: `$3F` filling the cell, the
28 line tiles cut into out-of-bounds pixels (the line included) and the rest, and rough
as `empty`. To it, a water hazard's tiles suit any neighbor (`LOCKED_WILD`); anything
else it may not write is bare ground (`LOCKED`), as every cell a feature may not write
is to a feature's family. The palettes the line uses agree in colors 0-2 except the HUD
palette (0), which draws color 2 white: ground in a supertile with palette 0
that a feature needs is left alone, and other supertiles with palette 0 the brush writes
into get palette 1.

### Measurements

Over the vanilla holes, with the statistics of all 144:

- A vanilla out-of-bounds shape fitted as it is: 97.9% of the 11,008 line tiles
  reproduced, and one break in the line.
- Cleared to rough and painted back as one stroke 3 right and 5 down, features and
  trees held in place, every fourth hole: 1 break in 36 holes, and 95.9% of 2x2 blocks
  in vanilla.
- Forest Fill, unseeded, after a fit: 2% of the cells just inside the line are bare
  `$3F`, against 13% in the vanilla holes; the seeding is for that.

A stroke takes about 40 ms.

### Limits

- The interior has to be filled; a hole with placeholder in it cannot be written.
- A fairway brushed over an unfilled region paints over its placeholder.
- The line is not drawn in a supertile with palette 0 that a feature needs.

## Green Brush

Greens mode only.

| Input | Does |
|-------|------|
| `N` | Select the Green Brush |
| Left-drag | Paint putting surface |
| Right-drag | Erase it back to rough |
| `,` / `.`, `Esc` | As for the Feature Brush; the palette makes no difference |

The stroke is in the green's own pixels, 192 by 192. On release the fringe is fitted
round the putting surface as far as the stroke moved it, as one undo step. Nothing else
has to be run: the rough beyond the fringe is written too. Green Fix (`U`) is for
tidying a green edited some other way: it redoes all the rough outside the fringe,
checkered the way it is already, and fills any placeholder, rough outside the fringe
and flat putting surface inside (`editor/algorithms/green_fix.py`).

- Cells that become putting surface are the flat tile (`$B0`). Slopes are kept wherever
  the putting surface was already, and lost where the fringe moves onto them; paint
  slopes afterwards (Carpet, `C`).
- Cells that become rough take their place in the rough's checkerboard, whichever way
  the green's rough is checkered already.
- Rough beside a changed cell gains or loses its strip of fringe (below).
- Nothing on a green is left alone, and a stroke need not touch the green that is
  there: one on open rough starts a second putting surface, and erasing inside one
  leaves rough ringed by fringe.
- The editor's placeholder (`0x100`) reads as rough, and stays where nothing changes.

### The zones

A green is drawn in three colors: 1 is the putting surface, 3 the rough, and the fringe
is a checkerboard of 1 and 2. `golf/algorithms/green_zones.py` reads every pixel of a
tile as one of three zones, rough, fringe or putting surface:

| Tiles | Are |
|-------|-----|
| `$48`-`$6F`, `$74`-`$83` | the 56 fringe tiles, each a different cut of the cell into the zones |
| `$B0`, `$30`-`$47`, `$88`-`$A7` | flat and sloped putting surface |
| `$29`, `$2C` | rough, checkered |
| `$70`-`$73`, `$84`-`$87` | `$29` and `$2C` with a one-pixel strip of fringe along the right, bottom, top and left side |

No vanilla green holds any other tile, and every fringe tile is used, the rarest
(`$7A`) five times.

The fringe is a band of constant width: rough beside it is four to six pixels from the
nearest putting surface, five most often. So the zones of a green follow from its
putting surface alone (`fringe_zones`: fringe within `FRINGE_WIDTH`, 4.5 pixels, and
rough beyond), and the brush only has to be told where the putting surface is.

A straight run of the band sits in one of two places in a cell, two to three pixels
apart: `$64` has fringe from the cell's top edge and putting surface from its fifth row,
`$62` two rows of rough and then fringe to the bottom, and `$49` and `$4A` step from one
to the other. The tiles the tile picker files as corners are diagonals: mostly
rough with a wedge of fringe, or mostly putting surface with one.

A strip tile goes beside the four tiles whose band begins at the cell's edge: left of
`$66`, above `$64`, right of `$67` and below `$65` (`rough_tile`). 99.9% of the vanilla
greens' rough tiles follow that rule. 139 of the 144 greens have `$29` where row plus
column is even and five the other way round (`rough_phase`); 1.3% of rough tiles are
off their own green's checkerboard.

### The fit

The fit is the one above with a fourth family, `green`: the flat tile filling the cell,
the 56 fringe tiles as their zones, and rough as `empty`. A family in zones draws one
shape within the next, here the putting surface and the putting surface with its
fringe, and each is fitted with its own outline: a tile's misfit is the sum over both,
and a seam counts a pixel once for each shape the two tiles disagree about. Slopes
count as the flat tile, in the fit and in the statistics.

A stroke adds to or cuts from the putting surface the tiles draw, drops anything
thinner than three pixels near the stroke, and makes the zones again within six pixels
of where the putting surface changed. The cells whose zones changed and the cells next
to them are fitted, the latter keeping their tiles unless the change calls for another
(`SETTLED_BONUS`), against two more cells of context.

### Measurements

Over the 144 vanilla greens, with the statistics of all of them:

- The zones made from a vanilla green's putting surface alone, fitted: 98.3% of
  fringe cells reproduced, 83 greens exactly, and 99.9% of 2x2 blocks in vanilla.
- The putting surface moved 3 right and 5 down: 98.6% of blocks in vanilla, and the
  fitted putting surface off by 2.8% of its pixels.
- 2.5% of vanilla fringe cells have other than two fringe cells beside them, mostly
  three, at tight inward corners; 4.1% of a moved green's.

A stroke takes a median of 11 ms and at most 49 ms, over 432 random strokes.

### Limits

- The outline lands two to three pixels from where it was painted along a straight
  run, since the band has two places in a cell.
- A slanted or tightly curved edge is lumpier than the vanilla greens' edges: the
  shape decides the tiles, not an eye for where a step looks best.
- A single click of a radius of 6 or under on an edge may change nothing.
- A shape thinner than three pixels is dropped; a putting surface too small for any
  tiles to draw changes nothing.
- Putting surface is not painted within five pixels of the edge of the 24x24 grid
  (`GREEN_MARGIN`), so that the fringe closes there; putting surface already at the
  edge is left as it is.
- Slopes under a moved fringe are lost, and new putting surface is always flat.
