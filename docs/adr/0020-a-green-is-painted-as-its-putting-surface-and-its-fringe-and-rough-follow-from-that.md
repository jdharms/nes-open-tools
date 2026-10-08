+++
status = "accepted"
date = 2026-10-08
area = "tooling"
permanent = false
revisit_when = "greens drawn with the brush need their fringe corrected by hand often enough that tile-by-tile editing is still the main way a green gets made, or a fringe of another width is wanted"
drafted_by = "Claude"
supersedes = []
+++

# A green is painted as its putting surface, and its fringe and rough follow from that

## Context

A green's fringe was drawn with Fringe Gen: click a tile, walk a closed loop one tile at
a time with the arrow keys, and on closing the loop get a random set of fringe tiles in
which every neighboring pair occurs in some vanilla green, from a table of the pairs in
the 54 NES Open greens. Green Fill, an action, then filled the rough outside and flat
putting surface inside. It could only
make a whole loop from scratch, never reshape part of a green; the tiles were chosen by
what may sit side by side, with nothing said about where the edge should run; and a loop
for which no assignment existed failed after it was traced.

The 56 fringe tiles are each a cut of a tile into three zones: rough, fringe and putting
surface. Over the 144 vanilla greens the fringe is a band of near-constant width, with
rough four to six pixels from the nearest putting surface. A straight run of it sits in
one of two places in a cell, and the rest of the tiles are diagonals between those.

The Feature Brush (ADR 0013) and the Out of Bounds Brush (ADR 0014) already fit border
tiles to a shape painted in pixels.

## Decision

The Green Brush (`N`, greens mode) takes the putting surface painted in the green's
pixels. The fringe is whatever lies within 4.5 pixels of it and the rough everything
beyond (`golf/algorithms/green_zones.py`), and the tiles are fitted to those zones by
the Feature Brush's fit with a fourth family, `green`.

The fit takes families that draw in zones, one shape within the next: for `green`, the
putting surface, and the putting surface with its fringe. Each shape is fitted with its
own outline and the costs are summed. A family with one shape, which the three terrain
families are, is fitted exactly as before.

The brush writes all three zones on release: fringe tiles, the flat tile for new putting
surface, and rough in its checkerboard with the strips of fringe that four of the fringe
tiles want beside them. Slopes are left wherever the putting surface was already.
Putting surface is not painted within five pixels of the edge of the green's grid, so
that the fringe closes there.

Fringe Gen, its generator and its table of pairs are removed. Green Fill stays as Green
Fix (`U`), for tidying a green edited some other way: it redoes the rough outside the
fringe and fills placeholder, by the brush's rules for the rough
(`golf/algorithms/green_zones.py`) and checkered the way the green's rough is already.

## Rejected alternatives

- **Keeping Fringe Gen beside the brush.** The brush makes every loop Fringe Gen could
  and reshapes them too; two ways to draw a fringe is one more to keep working.
- **Dropping Green Fix as well, with the brush filling any placeholder it finds.** The
  brush only writes near a stroke, and a fringe tile placed by hand leaves the rough
  beside it wrong; one action that puts the whole green's rough right is worth a
  button.
- **Painting the fringe itself, as a line or a band.** The user would be drawing a ring
  five pixels wide and keeping its width; the putting surface is the shape they mean.
- **Fitting one shape, the putting surface or everything but the rough.** Neither tells
  all the tiles apart: the tiles that are rough and a wedge of fringe hold no putting
  surface, and those that are putting surface and a wedge of fringe hold no rough.
- **A separate fitter for greens.** The trial copy of the fit differed from the
  original only in how a tile's misfit and a seam are counted.
- **Leaving the rough to a second step, as the Out of Bounds Brush leaves forest to
  Forest Fill.** Forest is filled by taste and seeded first; the rough is decided entirely by
  the fringe beside it, so a second step would be busywork.
- **Keeping the hard rule that neighbors must be a pair some vanilla green has.** As
  for features (ADR 0013), the statistics are a cost: 98.6% of the 2x2 blocks in fits
  of vanilla greens moved off the grid occur in vanilla, without forbidding the rest.

## Consequences

- A green is drawn and reshaped with the mouse, in one step, with undo per stroke.
- The fringe is always the vanilla width. Along a straight run the outline lands two
  to three pixels from where it was painted.
- Fits of slanted and tightly curved edges are lumpier than the vanilla greens'.
- Slopes under a moved fringe are lost, and new putting surface is flat.
- `data/tables/feature_style.json` gains the `green` family, counted over the greens
  of both ROMs.
- The rough's rules are in one place, `green_zones.py`, for the brush and Green Fix
  alike. Both keep the way a green's rough is checkered: 139 of the vanilla greens go
  one way and five the other.
- A green cannot be painted out to the edge of its grid.
- Nothing draws a fringe by rule any more: a fringe is painted, or placed tile by tile.

## Sources

- `docs/feature_brush.md`
- `golf/algorithms/green_zones.py`, `golf/algorithms/feature_fit.py`,
  `golf/algorithms/feature_brush.py`, `editor/tools/feature_brush_tool.py`,
  `editor/algorithms/green_fix.py`
- Session with jdharms, 2026-10-07: the survey of the fringe tiles' pixels, the trial
  fit of the vanilla greens from their putting surfaces, jdharms's choice to replace
  Fringe Gen outright, and to keep Green Fill under the name Green Fix.
