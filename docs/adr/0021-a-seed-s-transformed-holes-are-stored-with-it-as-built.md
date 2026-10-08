+++
status = "accepted"
date = 2026-10-08
area = "site"
permanent = false
revisit_when = "the stored holes grow large enough to matter to the database or its replication, or the site starts rebuilding seeds from their manifests, which would give every release each build version's transforms"
drafted_by = "Claude"
supersedes = []
+++

# A seed's transformed holes are stored with it, as built

## Context

A seed's yardage book (`/h/<id>/book`) shows each of its holes as the ROM plays it,
which for a slot with transforms is the transformed hole. Players get the book on the
day generation starts adding transforms, so that a mirrored hole or a bunker turned to
water is something they can look up.

The manifest names a slot's transforms (`mirror@1`, `hazards@1:<seed>`) and does not
hold their result. ADR 0015 lets a transform's output change between build versions
without its name changing, because the site serves each seed's stored unfinished IPS and
never rebuilds one. So a later release cannot work out an older seed's transformed hole
from its manifest, and until now the only record of that hole was inside the IPS. The
manifest's `course` otherwise holds concrete values, and a slot with no transforms still
resolves to its hole in any release, through the frozen catalog and its content hashes.

Measured over every dumped hole after `mirror@1`, alone and with `hazards@1`: a hole's
canonical JSON is 5.1 KB on average and 1.1 KB under zlib, so a seed with all 18 holes
transformed adds about 20 KB to the roughly 21 KB its manifest and IPS already take.

## Decision

The site stores each transformed hole when the seed is created.

- `build_unfinished` returns the 18 holes it built (`UnfinishedBuild.holes`), and
  `insert_seed` stores those whose slot has transforms, in the seed's transaction.
- The table `hole_data` holds a hole as the zlib-compressed canonical JSON its content
  hash is taken over (`canonical_json` in `golf/randomizer/catalog.py`), keyed by that
  hash. A hole two seeds share, such as a mirrored hole with no seeded transform, is
  stored once.
- `seed_holes.data_hash` names the row. It is NULL for a slot with no transforms, whose
  hole is the catalog's, and so for every seed made before this.
- `insert_seed` refuses a manifest with transforms unless it is given the built holes.
- A stored hole is checked against its hash when it is read.
- The manifest is unchanged. It stays a complete recipe within its build version, and
  the stored holes are the site's record of what the recipe made, as the stored IPS is.

This narrows a consequence of ADR 0015: a manifest from an older build version still
cannot be rebuilt into its ROM, but its holes can be read.

The book's images are not stored. They are rendered from the hole the first time a book
asks for them, into `variants/<content hash>/` in the rangefinder directory
(`golf/rendering/hole_renders.py`), and `golf-rehydrate` clears them when it renders
the rangefinder again.

## Rejected alternatives

- **The hash on the manifest slot.** It would describe only a row in the site's
  database. Someone holding the manifest alone cannot use it, since checking it means
  running the transforms under the same build version, which ADR 0015's golden test
  already guards. The slot's id, transforms and `build_version` already determine the
  hole, so the hash would be a second statement of it, and generation would have to
  transform holes to write it.
- **Keeping every build version's transform code**, so any release can transform any
  seed. ADR 0015 turned this down for builds, and the reasons hold here.
- **Reading the holes back out of the stored IPS.** It needs no new storage, but it
  ties the book to a dumper that reads the patched course layout of every build
  version.
- **Rendering the images at seed creation and storing those.** It spends seed
  generation time on books nobody may open, and the images would then be data to back
  up rather than a cache: the hole could not be rendered again after the renderer
  changes.
- **Storing the JSON uncompressed**, to query it. Nearly all of it is tile grids, which
  SQL cannot ask anything useful of, and the fields worth querying are columns
  already.
- **Storing every slot's hole**, transformed or not. A slot with no transforms already
  resolves through the catalog in any release.

## Consequences

- The yardage book of any seed can be made by any later release, and its renders can
  be thrown away and made again.
- A fully transformed seed's row roughly doubles. The blobs are written once, with the
  seed, so Litestream ships them once.
- Anything else that wants a seed's course as hole data, such as rating its difficulty,
  reads it the same way and does not depend on the transform code.
- The stored holes are vanilla-derived data in the database, as the unfinished IPS
  already is.
- A hole from a seeded transform is in effect its seed's alone, so those rows are never
  shared, and nothing removes a row.

## Sources

- `docs/hole_transforms.md`, `docs/manifest.md`, `docs/randomizer_devplan.md`
- `server/seeds.py`, `server/yardage_book.py`, `golf/rendering/hole_renders.py`
- ADR 0015
- Session with jdharms, 2026-10-08 (session 01BoPckb): the yardage book's design, with
  jdharms's choice of the database over the manifest for the hash: "the only thing it
  'describes' is database-internal data."
