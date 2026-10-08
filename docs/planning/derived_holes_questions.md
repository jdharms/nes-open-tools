# Derived Holes: Open Questions

> **Note**: This document was written by Claude. It lists what the derived holes work
> (`docs/derived_holes.md`, ADR 0022, ADR 0023) left for jdharms to decide or check.
> Nothing here blocks publishing a derived hole with `golf-derive`.

## Decisions taken without asking

Each of these can be changed before a derived hole is committed to the index. After
that, a lineage or a delta path is permanent.

1. **Lineages.** Settled with jdharms: `community/<slug>` for the holes jdharms
   authors, with the slug the base's lineage, what moved and the par
   (`community/nes_us_12_forward3`; `_forward` for a tee moved up, `_short` for a green
   moved down or both). `golf-derive` enforces that the owner is not a vanilla course's
   and that a lineage's versions keep its par; the slug convention is not checked.
2. **Opting in.** A seed draws derived holes only when its settings have
   `include: ["derived"]`, a new settings field that took the manifest to schema 4
   (ADR 0023). The kind comes from the catalog source, so there is no `derived` tag.
   `include` also takes `community`, which lets a community hole into a pool for the
   first time; the catalog has none.
3. **The `short` tag.** `golf-derive` tags a first version `short` when its par is lower
   than its base's, and nothing else. A variant of the same par gets no tag. That
   predates the `_forward` and `_short` slugs: a `_forward3` hole is tagged `short`, and
   a drivable `_forward4` made from a par 4 gets no tag.
4. **Hidden attribute rows are dropped.** The editor's row removal keeps attribute rows
   below the visible height, and `CoursePatch` writes every attribute row a hole has.
   `golf-derive` cuts them, so the published hole's hash differs from the edited file's
   when the file has hidden rows. `golf-derive export` gives the hole as published.
5. **Delta size limits.** A delta that rewrites more than 35% of the terrain the two
   holes share is reported, and over 60% is refused without `--allow-large`. Both numbers
   are guesses: the one forward tee tried, a crude crop of the US 12th, rewrote 6%.

6. **A base's first family reorders vanilla draws.** Publishing a hole whose base has
   no family puts the base in a new one, which changes the base's key in the pool. The
   same holes stay in the pool, equally likely, but a PRNG seed with unchanged settings
   draws a different course afterwards, as after any curation edit. Keying the pool so
   that a family of one drawable member sorts as its hole would avoid it, and would
   itself change what existing PRNG seeds draw, once.

## Questions

1. **The seed page's source column.** A derived hole shows there as a community hole
   does: the `seed.holes.source_community` string with its author
   (`server/templates/seed.html`). Saying which vanilla hole it came from needs a new
   string, which is yours to write. `HoleView` would need the base's ROM, course and
   hole number to fill it.
2. **Does a tee in mid-hole work without cropping?** Every vanilla tee is 38 to 86
   pixels above the bottom edge. Whether the opening camera and the scroll limits cope
   with a tee further up a hole that keeps its full height was not checked in the ROM. A
   forward tee made by cropping the rows below it stays within what vanilla holes do.
3. **Exposure.** A family with a par 5 and its par 3 can fill either kind of slot, so
   each short hole raises how often its design is drawn and takes par 3 slots from the
   vanilla par 3s. `--exclude-tags short` is the only lever today. This is the open
   question in `docs/thoughts_on_par_6.md`.
4. **Handicap.** A derived hole keeps its base's handicap unless the edited file changes
   it. The scorecard shows it.
5. **What the site offers.** `Settings.include` is the hook. Offering it needs a form
   control and its strings, and a decision on whether derived holes are on by default.
6. **A base that gets a new version.** A hole derived from `nes_us/12` stays on version
   1 when `nes_us/12@2` is published. Nothing reports that the derived hole is now built
   on a superseded base.

## Not done

- **The rangefinder** has no page for a derived hole.
- **Difficulty** has no row for one (`data/difficulty/holes.json`).
- **No derived hole is in the catalog.** The index and curation file are unchanged; the
  holes are yours to draw.
