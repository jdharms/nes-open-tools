+++
status = "proposed"
date = 2026-10-01
area = "tooling"
permanent = false
revisit_when = "jdharms takes the solver up again, or something the results rest on changes: the physics model or the solver, the randomizer wanting the other pins or wind, or the randomizer depending on exact expected scores rather than rough rankings"
drafted_by = "Claude"
supersedes = []
+++

# Hole difficulty solving is paused, its results kept at skill 3, pin 0, no wind

## Context

`golf-difficulty` solves a hole for its expected strokes from the tee, over the exact
port of the game's ball physics (ADR 0011) and a model of the player's errors
(`docs/hole_difficulty.md`). What the randomizer wanted from it was where the 90 Mario
Open holes sit against par next to the 54 NES Open holes. Every hole is now solved
once, at skill 3, from the first pin, with no wind: two to three nights of a 12-core
machine for all 144.

The model could go a long way further: the other three pins, wind, behind-the-golfer
trees, a calibrated skill, validation against real scores. Each is days of work and
nights of machine time, and player-facing work on the site is a higher priority.

## Decision

Work on the solver stops here. Its results are kept as they stand:

- `data/difficulty/holes.json`: one row per hole (par, expected strokes, strokes over
  par, visits to unvalued spots, rounds, skill, pin).
- `data/difficulty/solves-skill3-pin0.tar.xz`: every hole's solve, slimmed to each
  state's value, visits and chosen intent, with the solve logs. About 1.5 MB, where the
  full solves are 96 MB and about 10 MB compressed.
- `docs/hole_difficulty.md`: what was built, how to pick it up, and the results.

`golf-difficulty-report` rebuilds all three from a solves directory.

## Rejected alternatives

- **Committing the full solves.** They add every intent each state played, with its
  screen rank, which only matters for studying the screen and comes back with a re-run.
  At about 10 MB compressed they would nearly double the repository, and every later
  re-solve would add as much again to its history.
- **Committing only the summary.** The per-state values and visits are what
  strokes-to-hole maps and any re-ranking need, and producing them again costs nights.
- **Git LFS or a release asset.** Both keep the data outside a plain clone, behind
  tooling or a network fetch, for 1.5 MB.
- **Solving the other three pins before stopping.** The randomizer can use rankings at
  one pin now; three more pins are another week of nights.

## Consequences

- The ranking and the expert holes rest on one pin and no wind. Holes near a boundary
  the randomizer draws (half a stroke over par, a stroke over) could cross it at another
  pin.
- A change to `golf/physics/` or `golf/difficulty/` leaves the kept results as they
  were: they are a record of this solver, not a cache of the current one. The doc and
  the archive's logs record the settings they came from.
- Picking the work up starts from the doc's "Picking this up" and "Future work".

## Sources

- `docs/hole_difficulty.md`, **Results** and **Future work**.
- Sessions with jdharms, 2026-09-30 to 2026-10-01: the Mario Open solves, the
  cleanup-round fix in the solver, and the decision to package the results.
