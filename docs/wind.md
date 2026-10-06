# Wind

> **Note**: This document was written by Claude based on reverse-engineering requested by jdharms. Distributions were computed with the Python model in `golf/core/patches/seeded_wind.py`, not measured in play.

How the vanilla game picks, varies and applies wind. The RNG itself, its call sites and the per-player wind slots are in `docs/seeded_wind.md`. How a randomizer seed chooses each hole's anchors is in `docs/wind_profiles.md`.

## Variables

| Address | Name | Meaning |
|---|---|---|
| `$012F` | `WindDirectionAnchor` | The hole's direction, drawn once by `InitHole` |
| `$0130` | `WindSpeedAnchor` | The hole's speed, 0-10, drawn once by `InitHole` |
| `$96` | `WindDirection` | This swing's direction |
| `$97` | `WindSpeed` | This swing's speed, 0-9, as displayed |

Direction is an angle byte in steps of `$10` (22.5 degrees), clockwise from `$00`. `$00` pushes the ball toward the top of the screen, `$40` right, `$80` down, `$C0` left.

Every hole in all three vanilla courses has its tee at the bottom of the map and its green at the top, with the tee-to-green line at most about 35 degrees off vertical. So `$00` is a tailwind and `$80` a headwind on every vanilla hole.

## Hole anchors

`InitHole` (fixed bank `$DBA0`-`$DBB5`) makes two RNG draws after the pin draw:

```
$DBA0  JSR LSFR_RNG_ALGO
$DBA3  AND #$F0
$DBA5  STA WindDirectionAnchor
$DBA8  JSR LSFR_RNG_ALGO
$DBAB  AND #$0F
$DBAD  CMP #$0B
$DBAF  BCC StoreWindSpeed
$DBB1  SBC #$08               ; 11-15 become 3-7
StoreWindSpeed:
$DBB3  STA WindSpeedAnchor
```

All 16 directions are equally likely. Speed anchors 3-7 come up twice as often as 0-2 and 8-10:

| Speed anchor | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Odds (/16) | 1 | 1 | 1 | 2 | 2 | 2 | 2 | 2 | 1 | 1 | 1 |

### Direction and speed are coupled

The two draws are consecutive outputs of a weakly mixing LFSR, so they are not independent. Only 64 of the 176 (direction, speed) pairs can occur. Each direction allows exactly four speeds, decided by bits 5 and 6 of the direction:

| Direction anchor | Raw speed nibble | Speed anchor |
|---|---|---|
| `$00 $10 $80 $90` | 2, 4, 9, 15 | 2, 4, 7, 9 |
| `$20 $30 $A0 $B0` | 3, 5, 8, 14 | 3, 5, 6, 8 |
| `$40 $50 $C0 $D0` | 1, 7, 10, 12 | 1, 4, 7, 10 |
| `$60 $70 $E0 $F0` | 0, 6, 11, 13 | 0, 3, 5, 6 |

The pin draw is independent of both: every reachable (direction, speed) pair occurs with all four pins, from 256 hole-start states each. This is a property of the RNG, not of any patch, so it holds for vanilla and seeded ROMs alike.

### RNG cycle

The LFSR's main cycle holds 65,534 of the 65,536 states. `$5555` and `$AAAA` step to each other and form a 2-cycle off it. Vanilla never reaches them. A hole started from one plays anchor `$50`/10 with swings alternating 6 and 9 (`$5555`), or anchor `$A0`/5 with swings alternating 4 and 6 (`$AAAA`).

## Per-swing wind

`WindAdjustmentRoutine` (`$DA25`) runs at every shot setup, the tee shot included:

```
$DA25  BIT ManualWindModeFlag
$DA28  BMI $DA54               ; practice mode: player-set wind, no draw
$DA2A  LDA WindDirectionAnchor
$DA2D  STA WindDirection
$DA2F  JSR LSFR_RNG_ALGO
$DA32  AND #$07
$DA34  LSR A
$DA35  BEQ $DA39
$DA37  SBC #$01                ; jitter: 0,0,-1,0,0,+1,+1,+2 for rng&7 = 0..7
$DA39  CLC
$DA3A  ADC WindSpeedAnchor
$DA3D  BPL $DA47
$DA3F  LDA WindDirection       ; negative: reverse the direction, speed 1
$DA41  EOR #$80
$DA43  STA WindDirection
$DA45  LDA #$01
$DA47  STA WindSpeed
$DA49  CMP #$0A                ; while speed >= 10, subtract 5
$DA4B  BCC $DA52
$DA4D  SBC #$05
$DA4F  JMP $DA49
$DA52  STA WindSpeed
$DA54  RTS
```

The jitter is 0 on 50% of swings, +1 on 25%, -1 on 12.5% and +2 on 12.5%. Over the whole cycle the jitter is independent of the anchors, so the per-anchor table below is exact in the long run. A single hole plays only a few swings from one state and can land well away from it.

### Speed by anchor

Percent of swings at each displayed speed. ↺ is speed 1 in the reversed direction. Bold cells come from the wrap at 10.

| Anchor | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | Mean | Std dev |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 0 | 50 | 25 + 12.5 ↺ | 12.5 | | | | | | | | 0.63 | |
| 1 | 12.5 | 50 | 25 | 12.5 | | | | | | | 1.38 | 0.86 |
| 2 | | 12.5 | 50 | 25 | 12.5 | | | | | | 2.38 | 0.86 |
| 3 | | | 12.5 | 50 | 25 | 12.5 | | | | | 3.38 | 0.86 |
| 4 | | | | 12.5 | 50 | 25 | 12.5 | | | | 4.38 | 0.86 |
| 5 | | | | | 12.5 | 50 | 25 | 12.5 | | | 5.38 | 0.86 |
| 6 | | | | | | 12.5 | 50 | 25 | 12.5 | | 6.38 | 0.86 |
| 7 | | | | | | | 12.5 | 50 | 25 | 12.5 | 7.38 | 0.86 |
| 8 | | | | | | **12.5** | | 12.5 | 50 | 25 | 7.75 | 1.20 |
| 9 | | | | | | **25** | **12.5** | | 12.5 | 50 | 7.50 | 1.73 |
| 10 | | | | | | **50** | **25** | **12.5** | | 12.5 | 6.00 | 1.32 |

For every anchor the most common speed occurs on exactly 50% of swings. It equals the anchor for 0-9 and is 5 for anchor 10.

Each wrapped row mixes two ordinary rows five apart: jitter outcomes below 10 come from the anchor's own row, the rest from anchor - 5.

- **Anchor 8** is anchor 8 with its +2 gust to 10 replaced by a lull to 5.
- **Anchor 10** is anchor 5 with its -1 lull to 4 replaced by a gust to 9. It never plays at 10.
- **Anchor 9** is a true hybrid: 62.5% at 8-9, 37.5% at 5-6. It is the most variable row.

The strongest steady wind the game delivers is anchors 7-8. Anchors 9 and 10 read as stronger but play as gustier.

### Speed over all swings

Weighting the table by the anchor odds, exact over every state on the RNG cycle and the same for every swing number:

| Speed | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 |
|---|---|---|---|---|---|---|---|---|---|---|
| Percent | 3.91 | 6.25 | 7.03 | 10.16 | 11.72 | 17.97 | 14.84 | 12.50 | 8.59 | 7.03 |
| Without the wrap | 3.91 | 6.25 | 7.03 | 10.16 | 11.72 | 12.50 | 12.50 | 11.72 | 8.59 | 7.03 |

Mean speed is 4.96. The wrap takes 8.59% of all swings (11 in 128) and moves them to 5, 6 and 7; without it, speeds 10-12 would carry that share and the distribution would be flat-topped across 5 and 6. Reversed wind occurs on 0.78% of swings (1 in 128).

### Where the wrap came from

The loop is deliberate code rather than a stray overflow. A cap at 9 would have been one `LDA #$09`. Subtracting 5 sends overflow to the middle of the range, the same choice the anchor fold makes with `SBC #$08`. The consequence for anchor 10 looks unconsidered: the fold's `CMP #$0B` admits anchor 10 on purpose, yet speed 10 can never be shown. The first `STA WindSpeed` at `$DA47`, followed by the loop and a second store, is the shape of a range reduction added to a routine that once ended at the first store. That reading is circumstantial.

## Wind in flight

`ApplyWindEffect` (bank 13 `$B4FF`) runs on every flight frame that is not a ground-contact frame (`GroundContactFlag`, `$05B2`). Wind does not act on putts.

Strength is `WindSpeed * min(BallHeight / 2 + 2, 7)`, so wind grows with the ball's height up to a cap. The code at `$B504`-`$B510` computes a factor of 1 or 2 from `BounceState`, `BallHeight` and whether the club is 0-2, but `$B511` overwrites it before use.

The strength is resolved into components, each `trig * strength / 8`, into `$EA`-`$EC` (X) and `$ED`-`$EF` (Y) as 24-bit signed values:

- X magnitude is `TrigLookupTable[d & $7F]`, negated when `d >= $80`.
- Y magnitude is `TrigLookupTable[(d & $7F) + $40]` via `LE7C3`, negated unless `d + $40` has bit 7 set.

`WindDelayCounter` (`$05B5`) is set to 10 at shot start (`$AD40`). Once it reaches 0, the X and Y components are added to `BallX` and `BallY` twice per frame (`$B59A`-`$B5C9`). Positive Y moves the ball down the screen, toward the tee. `$B5CB` onward also subtracts the components from `VelocityDeltaX`/`VelocityDeltaY` on every call; that path has not been traced.

### The crosswind bug

`TrigLookupTable` (`$E7CB`) holds 128 bytes of `|sin|` over a half turn. The Y lookup adds `$40` without masking, so for `d & $7F` of `$40`-`$70` it reads 0-48 bytes past the table, into code. Directions `$00`-`$30` and `$80`-`$B0` are correct. The other eight are not:

| Direction | Displayed bearing | Actual bearing | Strength |
|---|---|---|---|
| `$40` | 90 | 122 | 1.18 |
| `$50` | 112.5 | 125 | 1.13 |
| `$60` | 135 | 90 | 0.71 |
| `$70` | 157.5 | 134 | 0.54 |
| `$C0` | 270 | 302 | 1.18 |
| `$D0` | 292.5 | 305 | 1.13 |
| `$E0` | 315 | 270 | 0.71 |
| `$F0` | 337.5 | 314 | 0.54 |

Bearings are clockwise from the top of the screen; strength is relative to a correct direction at the same speed.

The error is lopsided. `$40` and `$50` gain a large push toward the tee, costing distance; `$C0` and `$D0` gain the same push toward the green. The two pure diagonals `$60`/`$E0` become pure crosswinds at 71%, and `$70`/`$F0` lose half their strength.

The correct set is closed under the reversal at `$DA3F` (`EOR #$80`), so a hole whose anchor is correct stays correct on every swing.

### The fix

The `wind_fix` patch (`golf/core/patches/wind_fix.py`) wraps the lookup inside the table. For an index of `$00`-`$7F`, `(a + $40) mod $80` is `a EOR $40`, which is a byte shorter than the add:

```
$E7C3  18 69 40   CLC / ADC #$40    ->    49 40 EA   EOR #$40 / NOP
```

`LE7C6`, the `TAX / LDA TrigLookupTable,X / RTS` that follows, stays at `$E7C6`; `RotateVector16` calls it at `$E64B` and `$E659` with indexes it has already masked. With the patch every direction's actual bearing is its displayed bearing, at full strength.

`LE7C3` has one other caller, `CalcLaunchVector` at bank 13 `$AEA2`, which passes the launch angle: `ClubLoftIndexTable[club]` plus or minus `ClubHiLoStepTable[club]`, `$00`-`$27` over the 16 clubs. Below `$40` the two forms read the same entry, so launches are unchanged.

Every randomizer seed from unfinished build version 6 has the patch (`docs/manifest.md`, **Schema history**). `tests/integration/test_wind_fix_rom.py` runs `LE7C3` and `ApplyWindEffect` from the patched ROM under py65. The Python physics model ports the vanilla lookup and does not describe a patched ROM (`docs/shot_physics.md`).

## Not verified

- The fix has been played once: on 2026-10-06 jdharms rolled a build 6 seed on a development site, and in training mode with the wind set to 9 left and 9 right (`$C0` and `$40`) the ball's drift looked correct. The other directions, and the vanilla behavior described above, have not been checked in an emulator. The vector table and the direction of push follow from the code and the course data; one Mesen breakpoint on `$B59C` with a `$40` wind would confirm them.
- That the in-game wind arrow shows the nominal direction. The display code has not been read.
