+++
status = "accepted"
date = 2026-11-07
area = "randomizer"
permanent = false
revisit_when = "the catalog grows past a few thousand holes, so the in-memory cache or its startup fill stops being cheap, or a transform's seedless work moves somewhere a hole's key does not reach"
drafted_by = "Claude"
supersedes = []
+++

# What a hole transform computes from the hole alone is cached in memory, keyed by the whole hole

## Context

Seed generation was the site's slowest request: a median of 1.3 s and up to 4.8 s in the
production timings from 2026-10-09 to 2026-11-08, nearly all of it the `build` phase.
Since generator version 4 most seeds have 10 to 18 transformed holes, and build time
followed them: about 160 ms for a seed with none, 2.1 to 4.6 s for one with every hole
mirrored. Profiling a production seed with every hole mirrored found about 75% of the
build refilling its forests (`ForestFiller.fill_all` from `mirror_hole`), and in a seed
with hazard redraws only, about 80% finding features (`feature_groups`).

Neither depends on a seed: `mirror@1` takes none, and a hazard seed only picks among
the groups found. The catalog holds 144 holes, and in production 70% of mirrored draws
and 80% of hazard draws were of a hole an earlier seed had drawn the same way. A
transform's output is pinned by golden digests (ADR 0015, superseded by ADR 0024), so a
change in what it computes is noticed.

## Decision

- `golf/randomizer/transform_cache.py` keeps, for the life of the process, each hole's
  mirror and its `hazard_groups`: its feature groups cut to the kinds, pixel count and
  supertiles `redraw_hazards` reads. The registry in `golf/randomizer/transforms.py`
  reads through it, so every build, CLI and the site use it.
- The key is SHA-256 over every field of the hole but the editor's `filepath` and
  `modified`, not its `content_hash`.
- A mirrored hole is deep-copied out of the cache; hazard groups are immutable and
  shared.
- Entries are never evicted.
- `Config.prewarm_transforms` (`GOLF_PREWARM_TRANSFORMS`, off by default) has the site
  fill the cache for every live catalog hole in a thread at startup
  (`SeedBuilder.prewarm`). It takes the build semaphore for one hole at a time, waits
  while a build is queued for it, and pauses after each hole, since the semaphore is
  not fair.
- `tests/conftest.py` empties the cache before and after every test.

## Rejected alternatives

- **Keying by `content_hash`.** It covers only what reaches the ROM. Forest fill sees
  terrain rows past `terrain_height`, and the mirror copies all of the metadata, so two
  holes with one content hash could mirror differently. No catalog hole has such rows
  today, but nothing would keep it so.
- **Caching `feature_groups` whole.** Each feature keeps every pixel it covers: 372 MB for
  the catalog and its mirrors, against about 2.3 MB cut to what a redraw reads.
- **A cache on disk**, built once like the rangefinder renders. It would survive
  restarts, but it needs a version key of its own and a step in `golf-rehydrate`, to save
  about a minute of filling after each deploy.
- **Prewarming always.** Every `golf-site` start and every `--reload` restart would spend
  about 20 s of a core on it, and tests whose app builds a real builder would too.
- **Prewarming without the semaphore.** Python threads share the interpreter lock, so a
  build beside the fill would take up to about twice as long.
- **Throttling the fill to a fixed duty cycle**, such as a hole every 5 s. A build never
  runs beside the fill either way; the throttle only stretches the fill to about 12
  minutes.

## Consequences

- On the development machine, an all-mirrored seed builds in 65 ms from a full cache
  against 960 ms before, and the 51 production seeds of this build version in 3.1 s
  against 24.6 s. A seed with no transforms is unchanged. On a miss a build costs about
  what it did before (880 ms for an all-mirrored seed, the forest fill no longer running
  its winning orientation twice).
- The cache holds about 42 KB a hole, 6.1 MB for the catalog, and grows only with it. A
  full prewarm takes about 20 s on the development machine.
- A running process keeps what it computed until it restarts: a change to forest fill,
  feature detection or the mirror table reaches a running site only on restart, which a
  deploy always is.
- A transform that computes something seedless from the hole adds it to the cache rather
  than recomputing it per build.
- A build that arrives during the fill waits for at most the hole in progress, a few
  hundred milliseconds on the production server.

## Sources

- `docs/hole_transforms.md` (**Caching**), `golf/randomizer/transform_cache.py`,
  `server/builder.py`, `server/app.py`
- `tests/unit/test_transform_cache.py`, `tests/unit/test_server_builder.py`
- ADR 0015, ADR 0021, ADR 0024
- Claude Code session 2026-11-07 `01Rn2bVx`: the timings in the production database,
  profiling `build_unfinished`, the cache's memory and what the existing tests did not
  cover; jdharms asked that the fill not let "the worst-case time to blow up", and for
  the caches with the tests they needed and a measurement of the gains.
