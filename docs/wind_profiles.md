# Wind Profiles

> **Note**: This document was written by Claude from decisions made with jdharms. The
> profiles are judged from the anchor tables in `docs/wind.md`, not from play.

How a randomizer seed chooses each hole's wind. A hole's wind is two anchors
(`docs/wind.md`): a direction, and a speed that each swing jitters. A seed has two
profiles, `wind_speed_profile` and `wind_direction_profile`, chosen independently, and
the anchors they produce are stored on each manifest slot (`docs/manifest.md`) and
written into the ROM by the `wind_anchors` patch (`docs/seeded_wind.md`).

Code: `golf/randomizer/wind.py` (the profiles), `golf/randomizer/generate.py` (where they
are drawn), `golf/core/patches/wind_anchors.py` (the ROM table). Decisions: ADR 0017 (the
table) and ADR 0018 (the profiles).

## Vanilla

The default for both. A hole keeps the anchor its own `wind_seed` deals, so a seed with
both profiles `vanilla` plays as the game deals wind, with the coupling of direction and
speed that comes with it (`docs/wind.md`, **Direction and speed are coupled**). One
vanilla profile beside a chosen one keeps the seed's own value for its part.

## Speed

### Bands

| Band | Speed anchors | What it plays like |
|---|---|---|
| Gentle | 0, 1, 2, 3 | Each mostly at its own number, within -1 to +2 |
| Moderate | 4, 5, 6, 10 | 4-6 the same way; 10 at 5 on half its swings, up to 9, never 10 |
| Strong | 7, 8, 9 | 7 and 8 the steadiest strong winds; 9 at 8-9 on five swings in eight, 5-6 on the rest |

10 is moderate and 9 strong because of what the game does with a jittered speed of 10 or
more: it takes 5 off (`docs/wind.md`, **Speed by anchor**). An anchor is drawn uniformly
within its band.

### Intensity

Every speed profile but `vanilla` and `moderate` is an intensity for each hole, a number
*t* from 0 to 1. The hole draws its band with these odds, then an anchor within it:

| Band | Odds | At 0 | At 1/4 | At 1/2 | At 3/4 | At 1 |
|---|---|---|---|---|---|---|
| Gentle | (1-t)² | 100% | 56% | 25% | 6% | 0% |
| Moderate | 2t(1-t) | 0% | 38% | 50% | 38% | 0% |
| Strong | t² | 0% | 6% | 25% | 56% | 100% |

Because the bands mix between the ends, a ramp is noisy: a moderate hole can come before
the last gentle one, and a strong hole can be followed by a moderate one.

### Profiles

| `wind_speed_profile` | Each hole's intensity |
|---|---|
| `vanilla` | None: the anchor the hole's seed deals |
| `gentle` | 0 |
| `moderate` | None: the moderate band on every hole |
| `strong` | 1 |
| `storm_rolling_in` | 0 until the storm arrives, 1/5, 2/5, 3/5 and 4/5 over the four holes it takes, then 1 |
| `dying_wind` | `storm_rolling_in` reversed: 1 until the wind starts to drop, four holes falling, then 0 |
| `storm_passing` | A storm that arrives over four holes, holds at 1 for three, and clears over four; 0 elsewhere |
| `back_nine_pressure` | 0 on holes 1-9, 1 on holes 10-18 |

A storm arrives, or clears, over four holes, and where in the round is drawn per seed:

- **`storm_rolling_in`** starts arriving on a hole drawn uniformly from 6 to 10. Holes 1-5
  are always gentle and holes 14-18 always strong.
- **`dying_wind`** starts to drop on a hole drawn from 6 to 10. Holes 1-5 are always
  strong and holes 14-18 always gentle.
- **`storm_passing`** is centered on a hole drawn uniformly from 7 to 12: full strength
  on that hole and the one either side, four holes arriving before them and four
  clearing after. Those are the centers that keep all eleven holes of the storm inside
  the round, so the 1st and the 18th are always gentle, and seven holes are calm.

On a four-hole ramp the first hole is gentle 64% of the time and the last strong 64%,
so the turn is quick but not clean, and the moderate band takes about one and a half
of a storm's holes. A rolling-in round is otherwise about half gentle and half strong.

## Direction

A direction is one of 16 steps of `$10` clockwise from `$00`, the way the wind blows.
Every hole in both ROMs plays up the screen, so `$00` is a tailwind and `$80` a headwind
on all of them, and `$40` and `$C0` blow straight across.

A **cone** is five neighboring directions around a center, drawn with weights 1, 2, 2,
2, 1: the center and its two neighbors a quarter of the time each, and each end an
eighth.

| `wind_direction_profile` | Center of the front nine's cone | Back nine |
|---|---|---|
| `vanilla` | No cone: the direction the hole's seed deals | The same |
| `prevailing` | Drawn uniformly from all 16 | The same center |
| `out_and_back` | Drawn uniformly from all 16 | The opposite center |
| `headwind_out` | `$80`, a headwind | `$00`, a tailwind |
| `tailwind_out` | `$00`, a tailwind | `$80`, a headwind |

## How a seed draws them

`generate` draws the directions from `stream(prng_seed, "wind_direction")` and the speeds
from `stream(prng_seed, "wind_speed")`, so changing one profile leaves the other's
anchors, the holes and everything else as they were. Every roll uses whole-number
weights. The profiles change only the anchors: a hole's pin and each swing's jitter
still come from its `wind_seed`.

The seed page names both profiles in its details. It shows no hole's wind;
`golf-randomize show` prints each hole's speed anchor and the compass point its wind
blows toward, with the top of the screen as north.

## Tests

- `tests/unit/test_wind_profiles.py`: the bands, the intensity curves, the cones and
  their weights.
- `tests/unit/test_wind_anchors.py` and `tests/integration/test_wind_anchors_rom.py`: the
  patch, and `InitHole` and `WindAdjustmentRoutine` run from the patched ROM under
  emulation for all 18 holes.
- Played once: on 2026-10-06 jdharms played the first three holes of a build 6 seed
  rolled on a development site with `moderate` speed and `headwind_out` direction, and
  the wind on them matched what `predict_hole` gives for the seed's manifest.
