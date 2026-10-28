+++
status = "proposed"
date = 2026-10-28
area = "randomizer"
permanent = false
revisit_when = "community holes arrive some way other than a committed hole file, such as an upload through the site, or a community course's holes need more than one owner"
drafted_by = "Claude"
supersedes = []
+++

# A community hole is published as a frozen copy beside the catalog index, under its course or its author

## Context

Community members will send holes: now and then a whole course, as Georgia Pines came,
but more often one hole or a few at a time, for the randomizer's catalog. The catalog
already has a `community` kind, whose source is `{"file": "<path>"}` relative to the hole
store root (`FileSource`, `HoleStore.path_for`), but no entry uses it yet.

Three things make that source unsafe as it stands. The hole store root is
`GOLF_HOLES_DIR`, which is `courses/` in a checkout and `/var/lib/golf-site/courses` on
the server, where `golf-rehydrate` writes only the vanilla dumps and `docs/deployment.md`
re-dumps by deleting the directory, so a community hole would never reach the site and
would not survive a re-dump. A committed entry's source can never change (guarantee 2 of
`docs/catalog.md`), so the first community entry fixes its path forever. And the file a
contributor edits is the file the entry would name, so an edit made in the editor would
fail the entry's content hash on the next load instead of becoming a new version.

Ids are `<owner>/<slug>`, where the owner is `community` or one author's name and the
vanilla owners are reserved (`golf/randomizer/derive.py`). A whole course's holes have
no natural id under that rule other than `<author>/<course>_NN`. Credit lives only in the
catalog entry's `author`; a hole file has nowhere to keep it, and `HoleData.from_dict`
drops keys it does not know, so one added by hand is lost when the editor saves.

## Decision

Committing a hole and publishing it to the randomizer are separate steps, with separate
copies.

- **Working copies live in `courses/community/`, committed.** A course is a folder
  `courses/community/<course>/` of `hole_01.json`-`hole_18.json` with its build recipe;
  loose holes go in `courses/community/<author>/`. They are edited freely. Nothing in the
  randomizer reads them.
- **A published hole is a frozen copy beside the index**, at
  `data/catalog/community/<owner>/<slug>.json`, or `<slug>@<version>.json` for a later
  version, as a derived hole's delta is. A `FileSource` path is relative to the
  directory the index is in, as a `DerivedSource` delta is, not to the hole store. The
  copy is never edited; publishing a changed working copy makes the lineage's next
  version.
- **The owner is a community course or an author.** A course's holes are
  `<course>/01`-`<course>/18`, reading as a vanilla course's do (`georgia_pines/07`
  beside `nes_us/07`). A loose hole is `<author>/<slug>`. `community` stays an owner, as
  derived holes already use it.
- **The index lists community courses.** A `courses` section maps a course's slug to its
  display name and author. An owner listed there is a course; any other is an author.
  Publishing refuses a hole under an author owner that is a listed course, a course
  slug that is already an author owner, and any vanilla owner.
- **A hole file may name its `author`.** `HoleData` reads and writes an optional
  `author` string. It is not in `ROM_BOUND_KEYS`, so it changes no content hash. A
  course's holes take the course's author unless they name their own.
- **Publishing requires an author** and copies it into the catalog entry. The entry's
  `author` stays what seeds copy and the site shows, and may be corrected in place as
  now.
- **A command publishes**, as `golf-derive` publishes a derived hole: it copies the
  working hole (or a whole course folder) into the catalog, writes the entries and
  bumps the index version. Curation is left to `golf-curate`.

Derived holes are unchanged.

## Rejected alternatives

- **The catalog naming the working copy.** An edit would break the entry's hash, or, if
  the hash were updated to match, change a published hole in place, which `docs/catalog.md`
  forbids for anything that matters to play.
- **`FileSource` relative to the hole store**, as it is now. The server's store holds
  only the vanilla dumps and is deleted to re-dump.
- **The author as the only owner**, so a course's holes are `<author>/georgia_pines_07`.
  One rule for owners, but a whole course would not read like a vanilla one, and
  grouping its holes would fall to curation alone.
- **Course and author owners told apart by nothing but convention.** Both are the first
  segment of an id, so without the index's `courses` listing a course slug and an
  author handle could collide unnoticed, and no tool could tell which an owner is.
- **Credit only in the catalog entry.** The file a contributor sends and edits would not
  say who made it, and the editor could not show it.

## Consequences

- A published hole is committed twice, as its working copy and its frozen copy, about
  7 KB a hole.
- Community holes need no ROM and no hole store: `HoleStore.has` is true for them on any
  checkout, and the site needs nothing deployed for them beyond the repository.
- The index loader accepts a `courses` section beside `version` and `holes`, and the
  index version increases when a course is added.
- `HoleData` round-trips `author`; files without one load as before.
- The tests that keep every committed id's source the same apply from the first
  community entry, so this layout cannot change once one is committed.
- A course's lineages are numbered by hole, so a course can hold at most its 18 holes
  under its own owner; a variant of one is another version of that hole or a loose hole
  under its author.

## Sources

- `docs/catalog.md`, `docs/derived_holes.md`, `docs/deployment.md`
- `golf/randomizer/catalog.py`, `golf/randomizer/derive.py`, `golf/formats/hole_data.py`
- ADR 0022, ADR 0023, ADR 0024
- Session with jdharms, 2026-10-28: committing `courses/community/`, renaming the
  Georgia Pines folder, and their choices of separate working and published copies, a
  complete course reading like a vanilla one, and an `author` field in the hole JSON.
