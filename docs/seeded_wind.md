# Seeded Wind Patch

> **Note**: This document was written by Claude based on reverse-engineering requested by jdharms. Debugger values quoted below were captured by jdharms in Mesen on the vanilla US ROM.

Makes every hole's pin position and wind sequence a pure function of a build-time seed, so all players of a given ROM face the same conditions on the same swing of the same hole. Implemented in `golf/core/patches/seeded_wind.py`; applied as the `seeded_wind` step of `golf-patch`.

## Vanilla RNG

`LSFR_RNG_ALGO` (fixed bank `$D29C`, PRG `0x3D29C`) is a 16-bit shift-register generator on `RngState` (`$42` low, `$43` high). Each call runs 11 shift steps and returns the new `$42` in A. X is preserved. Nothing in the NMI handler advances it; it only moves when game logic calls it. All 16 call sites:

| Site | Purpose |
|---|---|
| fixed `$DB15` | Pin position: result AND 3 selects one of the hole's 4 flag offsets (`InitHole`) |
| fixed `$DBA0` | Wind direction anchor: result AND $F0 (`InitHole`) |
| fixed `$DBA8` | Wind speed anchor: result AND $0F, values 11-15 become 3-7 (`InitHole`) |
| fixed `$DA2F` | Per-swing speed jitter (`WindAdjustmentRoutine`) |
| fixed `$DA76` | Tournament long-drive / nearest-pin hole picker (game start) |
| bank 13 `$ADDD` | Putt aim noise (putter selected, BallLie != 6) |
| bank 13 `$AE55` | Rough / bunker power variance |
| bank 13 `$B357` | Water skip check |
| bank 12 `$8089`, `$93F0`, `$B8C8` | Title screen loop, menus |
| bank 9 `$936A` | Replay / animation |
| bank 3 `$A8AA` | Demo (restores its own state from `$067D`) |
| bank 2 `$BBE0`, `$BBEC`, `$BCCE` | Scorecard / tournament setup |

## Wind computation

`WindAdjustmentRoutine` (`$DA25`) returns immediately when bit 7 of `$04F6` is set. That is the practice-mode "set your own wind" flag; bank 13 `$89C2` / `$89CF` implement the manual adjustment under it. Bit 7 of `$04F7` is the replay-playback flag, set by `InitializeHoleReplay`.

Otherwise: `WindDirection` = `WindDirectionAnchor`; one RNG draw; low 3 bits map to a jitter:

| rng & 7 | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 |
|---|---|---|---|---|---|---|---|---|
| jitter | 0 | 0 | -1 | 0 | 0 | +1 | +1 | +2 |

Speed = anchor + jitter. If negative, direction is flipped (EOR $80) and speed becomes 1. While speed >= 10, subtract 5. Direction never jitters.

The routine is called from bank 13 `$824F` (normal shot setup) and `$8D28` (a save/restore routine at `$8CBE` that re-derives a player's wind from a stored RNG snapshot after restoring it into `RngState`).

### The vanilla wind as probabilities

`golf/physics/wind.py` enumerates every RNG state on the LFSR's cycle to give the wind
the vanilla game deals, taking the state at hole start as equally likely to be any of
them. The cycle is 65,534 states long. `$5555` and `$AAAA` form a second cycle of their
own, which play never enters.

- **Only 64 of the 176 anchor pairs occur**, each with probability 1/64. The direction
  and speed anchors come from neighboring draws, which share 5 of their bits, so each
  direction comes with four speed anchors. Directions pair up (`$00`/`$10`, `$20`/`$30`,
  and so on), and each opposite direction has the same speeds:

  | Directions | Speed anchors |
  |---|---|
  | `$00 $10 $80 $90` | 2, 4, 7, 9 |
  | `$20 $30 $A0 $B0` | 3, 5, 6, 8 |
  | `$40 $50 $C0 $D0` | 1, 4, 7, 10 |
  | `$60 $70 $E0 $F0` | 0, 3, 5, 6 |

- **The pin is independent of the anchors**, uniform over the hole's four.
- **Each shot's jitter** is −1, 0, +1 or +2 with probability 1/8, 1/2, 1/4, 1/8. It is
  independent of the anchors, of the swing number and of the other shots' jitters, to
  within 0.001.

`tests/physics/test_wind_rom.py` checks `InitHole` and `WindAdjustmentRoutine` against
the Python model under py65.

## Per-player wind slots

Bank 13 already isolates each player's wind stream from the other player's turn:

1. **Hole start** (`$8157` loop): after `InitHole`, `RngState` is copied into `$0525,X` / `$0527,X` for X = 1 and 0. No draw happens inside the loop, so both slots start identical.
2. **Shot setup** (`$823A`): the current player's slot is loaded into `RngState` and snapshotted to `$04FB/$04FC`; `LDA17` (replay recording far call) runs; `WindAdjustmentRoutine` draws once.
3. **Shot end** (`$82BE`): `RngState` is written back into the slot.

The unfairness is the in-shot draws (putt noise, rough/bunker variance, water skip) advancing `RngState` between steps 2 and 3, so the next jitter depends on what the previous shot hit. The hole anchor is the other leak: `InitHole` derives it from whatever the global RNG state is at hole start.

Confirmed in Mesen (2-player stroke play, vanilla ROM):

| Break | `$42 $43` | Notes |
|---|---|---|
| `0x34192` hole start | slots `$0525..$0528` = `88 88 15 15` | both players seeded identically |
| `0x34252` P0 swing 1 | `74 44` | wind speed 8 |
| `0x342BE` P0 shot end | `74 44` | clean fairway shot, no in-shot draw |
| `0x34252` P1 swing 1 | `74 44` | same wind as P0 |
| `0x34252` P1 swing 2 | `CB A7` | one step from `7444` |
| `0x342BE` P1 shot end | `B7 58` | in-shot draw happened; stream polluted |
| `0x34252` P1 swing 3 | `23 BC` | derived from the polluted state |
| `0x34252` P0 swing 2 | `CB A7` | same as P1 swing 2, because P0's swing 1 was clean |

## The patch

### 1. `InitHole` seeding (fixed bank, byte-neutral)

The 10 bytes at `$DB0B` (PRG `0x3DB0B`) save `RngState` to `$04F9/$04FA`. Every consumer of that snapshot (`$8132`, `$8D09`, `$8D5C`, bank 9 replay playback) copies it back into `RngState` immediately before calling `InitHole`, and `InitHole` now overwrites `RngState` from the seed table, so the save is dead. It becomes:

```
LDA $DFE7,X   ; X = doubled global hole index, set at $DAEE
STA $42
LDA $DFE8,X
STA $43
```

Pin position, both anchors and both player slots then derive from the seed, with vanilla distributions intact. The bank 3 replay header at `$A784` still copies the stale `$04F9/$04FA`; playback re-runs `InitHole`, which ignores it.

### 2. Slot write-back moved (bank 13)

- `$82C0` (PRG `0x342C0`): the 10 bytes after `LDX CurrentPlayerIndex` become NOPs. `LDX` stays because `$82D1` uses X.
- `$BFAF` (PRG `0x37FAF`): 16-byte trampoline in bank 13 tail padding, directly after the mercy tap-in routines (`$BF83-$BFAE`) and clear of the MMC1 reset stub at `$BFF3`:

```
LDX CurrentPlayerIndex
JSR WindAdjustmentRoutine
LDA $42 ; STA $0525,X
LDA $43 ; STA $0527,X
RTS
```

- `$824F` (PRG `0x3424F`): `JSR WindAdjustmentRoutine` becomes `JSR $BFAF`.

The slot now advances exactly one LFSR step per swing. In-shot draws still use the live RNG, which is discarded and reloaded from the slot at the next shot setup. The `$8D28` resume path restores the shot-start snapshot and re-derives the same wind; it never touches the slots. The trampoline reloads X itself rather than trusting the replay-recording far call at `$824C` to preserve it. Under practice mode the wind routine returns without drawing and the trampoline writes the unchanged state back, a no-op.

### 3. Seed table

Two bytes per hole (`$42` then `$43`) for the course's 18 holes at `$DFE7` (PRG `0x3DFE7`), the start of the course-3 block of `GreenFlagXTable`. Under `COURSE_MIRRORS_PATCH` every course slot plays holes 0-17, so the course-3 block is never read; the patch declares `COURSE_MIRRORS_PATCH` as a requirement and refuses to apply without it. `CoursePatch` only writes metadata for holes 0-17, so the seed table survives `golf-write` in either order.

Seeds come from `derive_hole_seeds(meta_seed)`: SHA-256 of a fixed prefix, the meta-seed string and the hole index, first two bytes little-endian. The same string always rebuilds the same ROM. The seed string itself is not yet recorded in the ROM.

## Usage

```bash
# ROM produced by golf-write (course_mirrors already applied)
golf-patch modified.nes --any-base -p "seeded_wind:seed=my seed" -o seeded.nes

# print the expected pin index, anchors and first 6 winds per hole
golf-patch modified.nes --any-base -p "seeded_wind:seed=my seed" --validate-only -v
```

Forecast columns: `pin` is the 0-based flag index; `dir` is `WindDirectionAnchor` (`$012F`, bit 7 = reversed); `spd` is `WindSpeedAnchor` (`$0130`); each `dir/spd` pair is (`$96`, `$97`) for that swing.

## Verifying in Mesen

1. Break at PRG `0x34192` at hole start. `$0525/$0527` should equal the forecast's `slot_state` (low byte in `$0525`), `$012F/$0130` the anchors, and the chosen flag the forecast's pin index.
2. Break at PRG `0x37FBE` (the trampoline's `RTS`) each swing. `$96/$97` should match the forecast's wind for that swing number, for either player, regardless of what the previous shot hit.
3. Break at PRG `0x342BE` after a rough or bunker shot. `$42/$43` will differ from the swing-setup value, but the player's slot must still hold the swing-setup value.

## Constraints

- Requires `COURSE_MIRRORS_PATCH`. Without it the UK flag X offsets are live and would get clobbered, so the patch refuses to apply.
- Fixed bank: net zero bytes. Bank 13: 16 bytes at `$BFAF-$BFBE` plus 10 NOPs at `$82C0`. The 52 bytes of bank 13 padding after it, `$BFBF-$BFF2`, are where `practice_swing` puts its 48 bytes (`docs/practice_swing.md`).
- Practice mode manual wind and replay playback are untouched. The hole-in-one auto replay should still reproduce, since playback restores the slots and re-runs `InitHole`, but this has not been exercised.
- `derive_hole_seeds` can return `$5555` or `$AAAA`, the two states off the LFSR's main cycle (`docs/wind.md`). They are valid seeds, but such a hole's wind alternates between two speeds forever.

## Ideas: wind profiles and manifest-specified anchors

Nothing in this section is implemented. The wind behavior it builds on is in `docs/wind.md`.

### Profiles

A seed could shape its wind instead of taking the vanilla distribution:

- **Out and in**: the front nine's anchors mostly headwinds and the back nine's mostly tailwinds, or the reverse, chosen per seed. Every vanilla hole plays up the screen, so headwinds center on `$80` and tailwinds on `$00` regardless of the hole.
- **Gentle, moderate, windy days**: anchors drawn from a band. Bands should target the speeds players see, not anchor values: anchors 7-8 are the windiest steady winds, while 9 and 10 play as gusty moderate winds.
- **Gustiness**: anchor 10 (moderate with gusts), 8 (strong with lulls) and 9 (unsettled) are vanilla's own variable winds. The seed also fixes the jitter sequence, so seeds can be picked for steady or jumpy early swings.
- **Par-aware**: tailwinds on par 5s to make them reachable, or headwinds for a harder round.
- **Changing weather**: speed rising over the round, or direction turning a step every hole or two.
- **Crosswind day**: needs `wind_fix`, since `$40` and `$C0` are among the directions the crosswind bug distorts.

Randomizer seeds carry `wind_fix` (`docs/wind.md`, **The fix**), so a profile there can use all 16 directions. On a ROM without it, a profile that avoids the crosswind bug restricts anchors to `$00`-`$30` and `$80`-`$B0`, which loses winds toward the upper left and lower right.

### Option A: choose seeds

The manifest already carries a 16-bit `wind_seed` per hole, and every hole-start outcome is a pure function of it. The generator could compute `predict_hole` for all 65,536 seeds once, then for each hole pick a target (pin, direction, speed) and any seed that produces it. This needs no ROM or manifest change.

The limit is the coupling in `docs/wind.md`: only 64 (direction, speed) pairs are reachable. A straight headwind or tailwind can only have speed anchor 2, 4, 7 or 9, and anchor 10 exists only on broken crosswind directions. Each (pin, direction, speed) combination has 256 seeds to choose among for the jitter sequence. The generator should skip `$5555` and `$AAAA`.

### Option B: anchors from the manifest

Replace the two anchor draws at `$DBA0`-`$DBB5` (22 bytes) with a read from an 18-byte per-hole table. One byte per hole fits both anchors, direction in the high nibble and speed in the low nibble, the format they already use. The read and the two masked stores take about 18 bytes. `$E00B`-`$E02E`, the part of the course-3 `GreenFlagXTable` block after the seed table, is dead under `COURSE_MIRRORS_PATCH` and has room for it.

The manifest would gain a direction and speed per hole (a schema change with `build_version` and `generator_version` bumps), and the seed would only drive the pin and the jitter. Any of the 176 pairs becomes reachable. `predict_hole` would take the anchors as inputs, and `seed_holes` would store them from the manifest.

### Pin from the manifest

The pin could leave the seed the same way. The only confirmed reader of the flag offset tables is `InitHole`, at `$DB21` and `$DB40` (other `find-refs` hits are in data and unconfirmed). The manifest would gain a pin per hole, `CoursePatch` would write that pin's offsets into slot 0 of the hole's four, and `AND #$03` at `$DB18` would become `AND #$00` (one byte, PRG `0x3DB19`).

Keeping the `JSR LSFR_RNG_ALGO` at `$DB15` leaves the RNG stream unchanged, so a seed gives the same wind with or without the change. The byte belongs with `CoursePatch` or a patch of its own, not with this one. Under Option A it frees seed choice from the pin, giving 1,024 seeds per (direction, speed) pair; under Option B the seed is left driving only the jitter.

Pins could then be chosen on purpose, for easy or hard pin days or to balance against hole difficulty. Seeds already stored on the site are unaffected: it serves their original manifest and unfinished IPS and never rebuilds them.

### Showing wind on the seed page

The site does not display wind yet. A display rule for each hole's wind:

- **Speed**: the anchor's most common speed, which is the anchor for 0-9 and 5 for anchor 10. For every anchor exactly half the hole's swings play at that speed.
- **Variability**: a marker (a class or data attribute) on anchors 8, 9 and 10, the rows the wrap spreads out. Every other anchor stays within -1 to +2 of the speed shown.
- **Direction**: the direction the game displays, not the corrected physical one, so the page agrees with the in-game arrow. With `wind_fix` the two are the same. A seed built without it (unfinished build version 5 or earlier) has the crosswind bug, and its broken directions are the place for a marker, not a corrected arrow.
- **Anchor 0**: shown as calm with no arrow, since half its swings are calm and one in eight blows the other way.
- **Storage**: `seed_holes` keeps the raw anchors, and the display values are derived at render time, so stats queries see the real values and the rule can change without a migration.

Every player's first swing on a hole gets the same wind, so the page could instead show the exact tee-shot wind. That describes one swing rather than the hole, and is a possible addition rather than a replacement.
