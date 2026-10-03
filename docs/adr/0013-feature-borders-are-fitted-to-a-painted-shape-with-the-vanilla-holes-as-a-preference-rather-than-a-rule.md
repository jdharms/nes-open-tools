+++
status = "accepted"
date = 2026-10-03
area = "tooling"
permanent = false
revisit_when = "the brush's fits need hand correction often enough that the cycle tool is still the main way borders get made, or holes drawn in a deliberately different style are wanted"
drafted_by = "Claude"
supersedes = []
+++

# Feature borders are fitted to a painted shape, with the vanilla holes as a preference rather than a rule

## Context

Drawing a fairway, bunker or water hazard in the editor meant placing border tiles one
at a time and cycling each until the edges lined up. A feature is `$27` inside and one
of 64 border tiles round its edge, and each border tile is a different cut of the tile
into feature and ground, so choosing a tile is choosing where the edge crosses the cell.

Two earlier ideas for automating it had problems:

- Picking tiles from the cells an edge passes through gives too little to go on: five
  different tiles draw a left edge through the same cell, from nearly empty to nearly
  full.
- `data/tables/terrain_neighbors.json` lists the tile pairs seen in the vanilla holes,
  and was used to flag any pair it lacks. Many plausible pairs never occur in a vanilla
  hole, so it flags good work. It also only covers the 54 NES Open holes.

Measured over all 144 vanilla holes: 97.6% of the 2x2 blocks of tiles along fairway
borders also occur in another hole, and 93.8% along hazard borders. The vanilla holes
are drawn from a small, repeated vocabulary. About a quarter of neighboring tiles'
edges miss each other by a pixel and about 3% by three or more, so edges lining up
exactly is not the rule either.

## Decision

The editor's Feature Brush takes a shape painted in course pixels and chooses the tiles
(`golf/algorithms/feature_fit.py`) by minimizing three costs together:

- distance from the painted shape, with the outline free to move one pixel;
- pixels by which neighboring tiles' edges miss each other, squared, and discounted
  for pairs the vanilla holes have plenty of;
- rarity in the vanilla holes: of each side-by-side and stacked pair, against each
  tile's commonest partner, and a fixed cost for a 2x2 block that no vanilla hole has.

The vanilla statistics are costs, never a filter: a pair or block that never occurs is
used when the shape needs it. They are counted from all 144 holes into
`data/tables/feature_style.json` by `golf-feature-style`, separately for fairways (the
43 border tiles with no black outline) and for bunkers and water together (all 64).

A stroke refits only the part of the shape it touched, to one tile beyond the change,
and writes only bare ground and the feature's own tiles.

## Rejected alternatives

- **A vanilla-pairs rule, as a lint or as the only tiles a tool may place.** In fits
  that looked right, about 5% of adjacent pairs never occur in a vanilla hole.
- **Matching edges only.** Fits made from seam mismatch alone had clean seams and 45% of
  their 2x2 blocks in the vanilla holes; they read as wrong at a glance. For hazards the
  same fits used outlined tiles for 19% of the border where the vanilla holes use 59%,
  because an outlined tile and its plain twin draw nearly the same shape.
- **Exact fidelity to the painted outline.** A straight vertical edge can only sit one
  to five pixels into a cell, so an outline held exactly hops between positions. Letting
  it move a pixel removed that.
- **Choosing the edge crossing by hand, per tile side.** It is the cycle tool with a
  different handle; kept in mind as a touch-up tool, not the way to draw.
- **A direction-change penalty along the edge.** The pair statistics already prefer the
  runs the vanilla holes use; it was not built.

## Consequences

- A painted shape comes out about a pixel from where it was drawn, in exchange for
  borders in the vanilla style: with the statistics of the other 143 holes, fits of
  vanilla shapes moved off the grid had 92% of their fairway blocks and 96% of their
  hazard blocks in the vanilla holes.
- The brush cannot draw a style the vanilla holes do not have. Shapes thinner than three
  pixels are dropped.
- `data/tables/feature_style.json` is derived from both ROMs' holes and is checked in;
  a test fails when it no longer matches them.
- `terrain_neighbors.json` and the invalid-tile highlight are unchanged, and still have
  the problems above.

## Sources

- `docs/feature_brush.md`
- `golf/algorithms/feature_fit.py`, `golf/algorithms/feature_brush.py`,
  `editor/tools/feature_brush_tool.py`
- Session with jdharms, 2026-10-02: the fit experiments against the vanilla holes, and
  jdharms's account of the vanilla-pairs lint.
