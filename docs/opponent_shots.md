# CPU Opponent Shots

> **Note**: This document was written by Claude based on investigation requested by jdharms.

The CPU opponents in match play don't compute their shots. Each one replays a recorded list
of shot inputs, in the same record format the game uses for its highlight replays
(`docs/topspin.md`), so their shots go through the real physics. All of it is in bank 3,
`$A923`-`$BEE7`, between the replay code and the routine at `$BEE8`;
`golf-rom-peek known-data` labels it (`opponent_shot_regions` in
`golf/core/known_data.py`).

## Choosing a list

Bank 13 `$8142` far-calls bank 3 `$A869` for the opponent's turn:

1. `$A923`/`$A926` (by `CurrCourse`) give the course's pointer table: 18 holes x 4 words,
   indexed `HoleNumber * 8 + choice * 2`.
2. If `$052F` is 0, the choice comes from `OpponentShotChoiceTable` (`$A929`, 8 rows of 16):
   the row is a level, the column a random nibble from the RNG seeded by `$067D/$067E`, and
   the entry shifted right once is the choice, 0-3. The level is the opponent number
   (`OpponentGolferIdentity - 1`, capped at 4), except in tournament match play
   (`GolfGameMode` 5 and 6), where `OpponentMatchLevelTable` (`$A9A9`) maps
   `opponent * 4 | SRAM $6003` to a level 0-7.
3. Otherwise the choice is `(OpponentGolferIdentity - 1) AND 3`.

## A shot list

A list is a 2-byte RNG state, loaded into `RngState` before the first stroke, then one
5-byte replay record per stroke for `LoadReplayShotRecord` (`$A796`). Lists have no length
or terminator: they are packed back to back and playback stops at `ReplayMaxStrokes`
(set to 8 at `$A879`) or when the hole is over. Every list from the three pointer tables
is a seed plus a whole number of records, and the last one ends at `$BEE7`.

| Record byte | Unpacked to |
|---|---|
| 0 | `PlayerSavedAiming` (`$0513`) and `Aiming` |
| 1 | `$0515` |
| 2 | low nibble: club (`$0519`); high nibble: swing speed and spin through `ReplayShotSwingSpeedTable` / `ReplayShotSpinTable` |
| 3 | low 6 bits: `$051D`; top 2 bits: 0 clears `$0523`, 1 sets it to `$A859[club]`, 2 to its negative |
| 4 | low 7 bits: `$0521`; bit 7 sets `$051F` |

## Tables

| Bank 3 | Label | Size |
|---|---|---|
| `$A923`-`$A928` | `OpponentShotCourseLoTable`, `OpponentShotCourseHiTable` | 3 + 3 |
| `$A929`-`$A9A8` | `OpponentShotChoiceTable` | 128 |
| `$A9A9`-`$A9BC` | `OpponentMatchLevelTable` | 20 |
| `$A9BD`, `$B0D7`, `$B7D8` | `{Japan,US,UK}OpponentShotListPtrTable` | 144 each |
| `$AA4D`, `$B167`, `$B868` | `{Japan,US,UK}OpponentShotLists` | 72 lists each |

## Open questions

- What record bytes 1, 3 and 4 are (`$0515`, `$051D`, `$0521`, `$051F`); the topspin
  notes name the inputs a replay saves - aiming, club, swing speed, spin, hi/lo and wind -
  but not which byte holds which.
- What `$052F` and SRAM `$6003` are.
- The 16-byte table at `$A859` the hi/lo adjustment reads, indexed by club.
