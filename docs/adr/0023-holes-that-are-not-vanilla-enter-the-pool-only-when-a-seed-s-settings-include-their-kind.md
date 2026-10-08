+++
status = "accepted"
date = 2026-10-08
area = "randomizer"
permanent = false
revisit_when = "players need to choose among derived or community holes more finely than by kind, such as short holes without other variants"
drafted_by = "Claude"
supersedes = []
+++

# Holes that are not vanilla enter the pool only when a seed's settings include their kind

## Context

A seed's pool was every drawable hole from the settings' `sources`, less the holes with
an excluded tag. Every way to shape it took holes away. Derived holes (ADR 0022) are the
first holes added to the catalog that existing seeds' settings should not start drawing:
they are not ready for the site, and a player who wants the vanilla courses' holes
should keep getting them.

With only `exclude_tags`, keeping a new hole out means tagging it and having every
caller exclude the tag. An uncurated lineage is drawable with no tags, so a derived hole
whose tag was forgotten would be drawn by every seed.

## Decision

`settings.include` names the kinds of hole added to the pool beside the vanilla ones.

- A hole's kind is read from its catalog source: `vanilla` for a ROM location,
  `derived` for a base and a delta, `community` for a hole file.
- Vanilla holes are always in the pool. A derived or community hole is in it only when
  `include` names its kind. `include` is empty by default.
- A hole still needs its ROM among the `sources`: a derived hole's is its base's, and a
  community hole has none and needs none.
- `exclude_tags`, drawability and families apply to an included hole as to any other.
  `golf-derive` tags a derived hole of lower par than its base `short`.
- The manifest schema becomes 4, which adds `include` to `settings`. Schemas 1 to 3
  load with an empty `include` and serialize back without it.
- `golf-randomize generate --include` sets it. The site's form does not offer it.

## Rejected alternatives

- **A tag on every derived hole, excluded by default.** It is the leak described above,
  and it makes each caller responsible for a default.
- **`drawable: false` in curation until release.** It is one switch for every seed, so
  it cannot be a setting a player chooses, and it has the same forgotten-record leak.
- **New values in `sources`**, such as `derived`. A derived hole needs its base's ROM as
  well, so `sources` would mix two questions, and the site reads `sources` as the ROMs a
  player has.
- **Tags that must be included**, a list of opt-in tags beside `exclude_tags`. It needs
  a registry of which tags are opt-in, and still depends on a curation record existing.
- **A `kinds` setting that lists `vanilla` too.** It allows a seed of derived holes
  only, which no pool could fill and nothing has asked for.

## Consequences

- Adding a derived or community hole to the catalog changes the holes in no pool that
  did not ask for its kind.
- Its curation can still move a vanilla draw. `golf-derive` puts a base that has no
  family into a new one, which renames that hole's key in the pool and so reorders the
  seeded draw, as any curation edit may. Which holes can be drawn, and how likely each
  is, do not change.
- The setting is the hook for offering derived holes on the site.
- Community holes gain the way into a pool they lacked, though the catalog has none.
- Choosing among derived holes more finely than by kind is done with tags.
- Stored manifests keep their shape; the loader reads four schemas.

## Sources

- `docs/manifest.md`, `docs/catalog.md`, `docs/derived_holes.md`
- `golf/randomizer/pool.py`, `golf/randomizer/manifest.py`, `golf/randomizer/catalog.py`
- ADR 0016, ADR 0022
- Session with jdharms, 2026-10-08 (session 01BoPckb): "we only have 'opt out'
  mechanisms and don't have a good mechanism for 'adding holes to the pool'", and their
  note that their first plan for the randomizer had operations that add to the pool as
  well as filter it.
