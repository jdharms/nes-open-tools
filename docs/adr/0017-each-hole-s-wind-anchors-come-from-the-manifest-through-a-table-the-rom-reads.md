+++
status = "proposed"
date = 2026-10-06
area = "randomizer"
permanent = true
revisit_when = "a wind speed above the vanilla anchors is wanted, the pin should be chosen per hole as the anchors are, or a patch needs the course-3 flag block the table sits in"
drafted_by = "Claude"
supersedes = []
+++

# Each hole's wind anchors come from the manifest, through a table the ROM reads

## Context

A hole's wind is two anchors `InitHole` draws once: a direction and a speed, which each
swing then jitters (`docs/wind.md`). Under `seeded_wind` both come from the hole's
16-bit wind seed, as the pin and the jitter do.

The wind update gives a seed wind profiles: a strong day, a storm that builds, a
headwind out and a tailwind home. A profile has to decide each hole's anchors. The
game's own draw cannot give it that freedom. The two anchors are neighboring outputs of
a weakly mixing shift register, so only 64 of the 176 (direction, speed) pairs ever
come up, and each direction allows four speeds. A straight headwind can only have
speed anchor 2, 4, 7 or 9, and the four diagonals `$60 $70 $E0 $F0` never go above 6.

`docs/seeded_wind.md` had two ways to give a profile its anchors. Option A needed no
ROM or manifest change: the generator picks, for each hole, a wind seed that deals the
anchors it wants. Option B replaced the draw with a table.

## Decision

A manifest slot carries the hole's `wind_direction` and `wind_speed`, and the
`wind_anchors` patch (`golf/core/patches/wind_anchors.py`) writes them into a table
`InitHole` reads in place of its two anchor draws.

- The 22 bytes at `$DBA0`-`$DBB5` become two `JSR LSFR_RNG_ALGO` whose results are
  unused, then a load of each anchor from the table by the doubled hole index
  (`TempX`). Keeping the draws leaves `RngState` after `InitHole` as it was, so a
  hole's pin and every swing's jitter are still what its `wind_seed` gives.
- The table is two bytes a hole, direction then speed, at `$E00B`-`$E02E`: the second
  half of the course-3 block of `GreenFlagXTable`, whose first half holds
  `seeded_wind`'s seeds. The patch requires `course_mirrors`, which makes that block
  dead.
- The patch and the model accept the vanilla range only: a direction that is a
  multiple of `$10`, a speed anchor from 0 to 10.
- Every seed from unfinished build version 6 has the patch, whatever its profiles. A
  seed with vanilla profiles has the anchors its wind seeds would have dealt written
  into the table.
- Manifest schema 3 adds the two slot fields. A schema 1 or 2 manifest has neither, and
  its holes load with the anchors their seeds deal.

## Rejected alternatives

- **Option A, choosing a wind seed that deals the wanted anchors.** It needs no ROM
  code, and covers speed bands on most directions. It cannot give a straight headwind
  at speed 8, a strong wind on four of the diagonals, or the same speed on every hole
  whatever its direction, and every profile would have to be designed around which 64
  pairs exist. jdharms chose the table outright.
- **One packed byte a hole**, direction in the high nibble and speed in the low, as
  `docs/seeded_wind.md` first sketched. It halves the table but needs masking code, and
  caps the speed at 15. Two bytes a hole index straight off the doubled hole index the
  routine already has, in fewer bytes of code.
- **Dropping the two RNG draws.** The read fits either way. Without the draws the
  jitter sequence of every hole would shift by two steps, so a wind seed would mean
  something different with the patch than without it, and `predict_hole` would need
  two models.
- **Anchors derived at build time from the profile, and not stored in the manifest.**
  The manifest's `course` is what a build reads with nothing left to interpret, and
  `seed_holes` and the stats group by a hole's actual wind.

## Consequences

- Any of the 176 anchor pairs can be dealt to any hole, and a profile is free of the
  RNG's coupling.
- A seed's ROM carries 36 more bytes in the fixed bank's dead flag block, which is now
  full: seeds at `$DFE7`, anchors at `$E00B`, `GreenFlagYTable` at `$E02F`.
- A full byte holds each anchor, so a speed above the vanilla range needs no new table
  format, only a decision about what `WindAdjustmentRoutine`'s wrap at 10 should do
  with it.
- The pin still comes from the wind seed. Choosing it per hole is the same kind of
  change (`docs/seeded_wind.md`, **Pin from the manifest**) and is not made here.
- The patch has been run under emulation (`tests/integration/test_wind_anchors_rom.py`)
  and not yet in an emulator by a person.

## Sources

- `docs/wind.md`, `docs/seeded_wind.md`, `docs/wind_profiles.md`, `docs/manifest.md`
- `golf/core/patches/wind_anchors.py`, `golf/core/rng.py`, `golf/randomizer/manifest.py`
- Session with jdharms, 2026-10-06 (session bb6fe993): Option A and Option B compared
  against the profiles in ADR 0016, and jdharms's choice of Option B.
