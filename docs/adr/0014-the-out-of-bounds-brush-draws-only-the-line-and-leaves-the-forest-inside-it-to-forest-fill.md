+++
status = "accepted"
date = 2026-10-03
area = "tooling"
permanent = false
revisit_when = "filling the out-of-bounds interior by hand after every stroke proves to be busywork, with the seeding rarely used"
drafted_by = "Claude"
supersedes = []
+++

# The out-of-bounds brush draws only the line, and leaves the forest inside it to Forest Fill

## Context

With fairways, bunkers and water drawn by the Feature Brush (ADR 0013), the edge of the
out-of-bounds ground was the last border drawn tile by tile. That edge is a solid black
line drawn by `$80`-`$9B`. Each tile holds one piece of it, running between corners and
the middles of sides, with the out-of-bounds side on one side or the other. Over all
144 vanilla holes the line breaks at only 35 places, so the tiles that may sit side by
side are close to a hard rule.

Inside the line is forest, or bare out-of-bounds ground (`$3F`). Forest Fill
(`golf/algorithms/forest_fill.py`) already fills a region of the editor's
placeholder with forest, its edge tiles and `$3F` where it has to. User seeds a
region with a forest edge tile or `$3F` before filling, to pin the tiling and open
clearings (`docs/forest_notes.md`). In the vanilla holes 13% of the cells just inside
the line are bare `$3F`; an unseeded fill leaves 2%.

## Decision

The Out of Bounds Brush (`O`) fits the line with the Feature Brush's fit, as a third
family of tiles, `boundary`, with `$3F` as the inside and forest counted as inside too.
It writes the line, makes the cells inside it the placeholder (`0x100`), and fills
nothing. Forest beside any cell it changes also becomes the placeholder, since its trees
may have run into that cell. The user seeds the region to taste and runs Forest Fill.

To the line, the edge of a water hazard suits any neighbor, since 27 vanilla holes let
a water hazard's lip be the boundary; fairways, bunkers, trees and the tee box are in
bounds, so the line closes in front of them. No vanilla hole puts forest against a
fairway, and only two tile sides put it against a bunker. A stroke that pushes into them stops
there: the parts of a stroke cut off from the shape it extends are dropped. The
placeholder counts as out of bounds to this brush and as bare ground to the Feature
Brush.

## Rejected alternatives

- **Running Forest Fill on release.** It gives a finished forest in one step, but a
  dense one, and the clearing and tiling choices made by seeding are taste a stroke
  cannot express.
- **A pen that draws the line itself.** The user would have to keep track of which
  side is out of bounds; painting the area settles that.
- **A separate solver for the line.** The fit already handles it: fitted back, the
  vanilla shapes keep 93% of their line tiles with no break.

## Consequences

- Drawing a forest takes two steps, and a hole can be left with unfilled placeholder;
  `golf-write` already refuses to write one (`golf/core/course_validation.py`).
- Reshaping a filled forest leaves a strip of placeholder along the change, to fill
  again.
- A fairway brushed into an unfilled region paints over the placeholder.
- The line cannot be drawn in a supertile with the HUD palette (0) that a feature
  needs; elsewhere such a supertile gets palette 1.

## Sources

- `docs/feature_brush.md`, `docs/forest_notes.md`
- `golf/algorithms/boundary.py`, `golf/algorithms/feature_brush.py`,
  `editor/tools/feature_brush_tool.py`
- Session with jdharms, 2026-10-02: the survey of the line tiles in the vanilla holes,
  and jdharms's choice to leave the interior to Forest Fill.
