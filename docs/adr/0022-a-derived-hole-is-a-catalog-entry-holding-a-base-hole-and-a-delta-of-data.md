+++
status = "accepted"
date = 2026-10-08
area = "randomizer"
permanent = false
revisit_when = "a variant needs to move a hole's terrain sideways or one part of it against another, which a cell delta can only record by copying the base, or a derived hole needs another derived hole as its base"
drafted_by = "Claude"
supersedes = []
+++

# A derived hole is a catalog entry holding a base hole and a delta of data

## Context

The randomizer wants holes that are vanilla holes changed: a forward tee that turns a
par 5 into a par 3 or a par 4, and variants such as a dogleg at another angle. Across
the 144 vanilla holes the tee sits 38 to 86 pixels above the bottom edge and every par 3
is 30 or 32 rows tall, so a forward tee in that convention is a terrain edit: rows
cropped, a new bottom edge, forest carved out for a tee box, and new par, distance, tee
and scroll limit.

Two constraints shape how such a hole is stored. Vanilla course data is not committed
(`golf-rehydrate` rebuilds it from the ROMs), so the changed hole cannot be checked in
as a hole file. And a catalog id resolves to the same hole data forever
(`docs/catalog.md`), which the content hash enforces on every load.

## Decision

A derived hole is a catalog entry whose source is a base hole and a delta:
`{"base": "nes_us/12", "delta": "derived/community/nes_us_12_forward3.json"}`.

- **The delta is data.** It holds the metadata values that differ and, for each of the
  terrain, attribute and greens grids, the row count it ends with and the cells that
  differ, as runs of `[row, column, values]` (`golf/randomizer/delta.py`). Both holes
  are compared in the canonical form the content hash covers.
- **One move by whole rows is part of the format.** A delta's `row_offset` says how
  many terrain rows the base moved up, so a hole cropped at the top costs an offset
  and no cells, as one cropped at the bottom costs a row count, and rows added at the
  top cost only themselves. A forward tee crops the bottom; a green brought down toward
  the tee crops the top.
- **It holds only cells that differ.** A delta that restates base cells is refused by
  `golf-derive check` and the tests.
- **The base is a hole id**, so it names one version of the base forever, and it is a
  vanilla hole: a derived hole is not the base of another.
- **The hole is built on load.** `HoleStore.load` loads the base, checks it against its
  hash, applies the delta and checks the result against the derived entry's hash.
  Nothing derived is written to the hole store.
- **Deltas are checked in** under `derived/` beside the index and are never edited. A
  changed hole is a new version with a new delta.
- **The lineage is `<owner>/<slug>`**, never a vanilla course's. The owner is
  `community` or one author's name, and the entry's `author` holds the credit. The
  slug names the base, what moved and the par (`nes_us_12_forward3`), so a lineage's
  versions keep its par.
- **`golf-derive` makes the delta** from a hole edited in the editor, and writes the
  entry and its curation record with it. It puts the hole in its base's family.
- **A derived hole comes from its base's ROM** for the pool's `sources`, a seed's
  required ROMs and rehydration's checks.

## Rejected alternatives

- **A delta of operations** (crop to 30 rows, forest-fill, stamp a tee box at x, y).
  The hole would then be whatever those algorithms produce in the release that loads
  it. ADR 0015 accepts that for transforms because a seed's built ROM is stored; a
  catalog entry has no such copy, and its id must resolve the same way forever. A
  forward tee also needs hand work no operation names, such as carving forest.
- **Checking in the whole hole file**, as a community hole is. It would put the vanilla
  hole in the repository.
- **Replacing whole rows** where any cell differs. It is simpler to read, but each row
  carries the vanilla cells beside the changed ones.
- **Writing the derived holes into the hole store during `golf-rehydrate`.** Every
  consumer would read a plain file, but the files could go stale against the catalog,
  and a delta added after rehydrating would need another run. Loading the US 12th's
  forward tee took 1.3 ms against 0.4 ms for the vanilla hole.
- **A lineage under the base's owner** (`nes_us/12_short`). It reads as Nintendo's
  hole, and tools take the `nes_` prefix to mean an NES Open hole.
- **A derived hole as the base of another.** Nothing needs it yet, and it would make
  loading and withdrawal a chain to walk.

## Consequences

- A derived hole costs the repository its changed cells and no vanilla rows.
- Nothing that reads holes through `HoleStore` changes: the build, the yardage book and
  the curation tools load a derived hole as they do any other.
- A derived hole needs its base's ROM, and a base that is withdrawn takes its derived
  holes out of the pool with it.
- A hole must stay in register with its base apart from the one move by whole rows.
  Moving a hole sideways, or one part against another, changes nearly every cell it
  touches, and the delta would be the base displaced; `golf-derive` reports a large
  delta and refuses a very large one.
- The delta format is as permanent as the entries that name it. A change to it is a new
  format number that `apply` reads beside the old one.
- The cells in a delta are whatever the author put there, which can be tiles copied from
  elsewhere in the same hole, such as a bottom edge moved up.
- The rangefinder, which renders the vanilla courses, and the difficulty data do not
  cover derived holes.

## Sources

- `docs/derived_holes.md`, `docs/catalog.md`
- `golf/randomizer/delta.py`, `golf/randomizer/derive.py`, `golf/randomizer/catalog.py`,
  `tools/data/derive.py`
- ADR 0015, ADR 0021, ADR 0023
- Session with jdharms, 2026-10-08 (session 01BoPckb): jdharms's sketch of the entry,
  and their choices of a delta of data ("the correct architecture"), cell-level deltas,
  resolving on load, pinning the base by versioned id, one family for a hole and its
  derived holes, `community` as the owner of the holes they author, the `_forward` and
  `_short` slugs with the par appended, and cropping from the top in format 1.
