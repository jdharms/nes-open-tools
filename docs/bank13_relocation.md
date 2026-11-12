# Moving the ball physics out of bank 13 (proposal)

A proposal, not a plan: nothing here is built, tested or committed to. It records the
research behind one way to make room in bank 13, the implementation guidance that
research supports, and what is still unknown. Everything below is static analysis of the
vanilla US ROM unless it says otherwise.

## Why

Bank 13 holds the round: hole flow, shot setup, the swing, ball physics, the course and
green views, the in-game menu and the HUD. It is full: 12,410 bytes of traced code,
3,771 bytes of labeled data, 202 bytes of uncalled code and 1 unlabeled byte
(`golf-rom-peek trace --bank 13`). The 112 bytes before the reset stub
(`$BF83`-`$BFF2`) are already taken by `mercy_tap_in`, `seeded_wind` and
`green_shortcut` (and `practice_swing` claims `$BFBF` on, the same bytes as
`green_shortcut`). Any new gameplay patch has to find its room in another bank and
far-call to it.

Moving a large self-contained block to another bank frees its bytes in bank 13 for
patching what stays, and puts the moved code somewhere with room to grow.

## The candidate: `$AD0A`-`$B9A6`

3,229 contiguous bytes, about 20% of the bank: 3,047 of code and 182 of tables. It runs
from `CalcLaunchVector` to the byte before `CalcAimTowardFlag` (`$B9A7`) and holds the
launch, `ProcessLanding`, roll, friction, spin, `ApplyWindEffect`, air drag, the
velocity helpers and the club, lie and timing tables (`docs/shot_physics.md`).

Every reference the trace finds across its boundary:

| Direction | Target | Sites |
|---|---|---|
| In | `CalcLaunchVector` `$AD0A` | `$AA2D`, once a frame while a shot is in progress |
| In | `$B114` (copies `WaterDropPositionData` back to the ball) | `$8636` |
| In | `ClearBallHeight` `$B75C` | `$866C`, `$A9FF` |
| Out | `DrawCourseGameplayView` `$8DA6` | `$B324` (bunker splash) |
| Out | `UpdateShotDistanceReadout` `$A246` | `$AF8D`, `$B0C2` |
| Out | `$A5B1` (a `WriteNametableTiles` call, descriptor `$A5BB`) | `$AD5A` |
| Out | `SavePlayerState` `$BD89` | `$AD1F` |

What makes it movable:

- **No data crosses.** Nothing outside reads the block's tables, and the block reads no
  bank 13 data outside itself. The trace reports one "immediate pair" into it
  (`$9FB0` to `$B634`); it is a false positive, `LDX #$34` / `LDY #$B6` being sprite
  coordinates.
- **No pointer tables inside.** Its data ranges are all value tables, so relocating to a
  different address only means rebasing absolute operands in its code that point inside
  it.
- **No stack tricks.** Its only stack use is seven balanced `PHA`/`PLA` pairs.
- **It does not use `$30`-`$32`**, which `ExecuteFarCall` clobbers.
- **Its one far call** (`$B31B` to bank 9 `$A6BA`) works from any bank.
- **The fixed-bank routines it calls** are `ProbeBallPosition` `$EDBC`, `$EDD4`,
  `LSFR_RNG_ALGO`, `Mult8x8to16`, `$E7C3` and `$D823`. None names a `$8000`-`$BFFF`
  address directly. `$D823` waits for vblank, so the NMI runs with the new bank mapped,
  as it already does under the game's existing far calls.

## How a move would work

1. **Copy the block** to the destination and rebase every absolute operand in its code
   that falls inside `$AD0A`-`$B9A6` by the address delta. The trace gives the
   instruction boundaries; the label file gives the data ranges to leave alone.
   Placing it at the same CPU addresses in the new bank would need no rebasing, but no
   bank is known to have that range free.
2. **Stubs.** A `JSR` is 3 bytes and a far call 6, so call sites cannot be rewritten in
   place. Each crossing target gets a 7-byte stub
   (`JSR ExecuteFarCall` / `.db bank, lo, hi` / `RTS`) and the 3-byte `JSR`s are
   repointed at it: three stubs left in bank 13 for the inbound targets (21 bytes),
   four in the new bank for the outbound ones (28 bytes). Bank 13 gains about 3,200
   bytes.
3. **Registers.** `ExecuteFarCall` (`$D372`) passes A, X and Y in, and returns A, X, Y
   and the flags (`SetPrgBank` does not touch Y). It destroys the flags on entry. The
   three inbound targets open with `LDA`, `LDX` and (to confirm) a load, so none takes a
   flag; the outbound four need the same check.
4. **Write it with `golf/core/asm6502.py`** or as a computed relocation in a patch
   module, which reads the vanilla bytes and emits the rebased copy, so the patch does
   not carry a second copy of Nintendo's code.

### Destination

In a randomizer ROM the vacated UK terrain in bank 2 (`$837F`-`$A553`) is the natural
home. A sample seed build writes `scorecard_qr` at `$8400`-`$9548` and `round_stats` at
`$A400`-`$A4BE` there, leaving `$9549`-`$A3FF`, 3,767 bytes: enough for the block and its
stubs with about 500 to spare. Bank 1's terrain region is the course's overflow from
bank 0 and cannot be counted on. Whether the replay code and opponent shots in bank 3
(`$A774` on) are dead in a randomizer ROM has not been looked at.

### Patches that write into the block

From the same sample build, only `mercy_tap_in` writes inside it (`$B3DC`-`$B3E2`).
Outside the default stack, `green_slope_physics` writes at `$B1D5`. `PatchStack` refuses
two steps that write the same byte, so the move goes first and those patches target the
new addresses, or the relocation step is given the patched bytes to copy. Patches that
only splice the surrounding code (`practice_swing`, `swing_speed_hud`, `round_stats`,
`green_shortcut`, `seeded_wind`) are unaffected.

## Other regions

`uv run python -m tools.spikes.bank_split nes_open_us.nes --labels <file.mlb>` ranks
every contiguous region of the bank by the references crossing it, and `--region`
lists them for one region.

- **`$AD0A`-`$BFFF`, 4,854 bytes**: adds `CalcAimTowardFlag`, the scene ball, the swing
  aim, `SavePlayerState` and `DrawPeachPanel`. Nine inbound targets, five outbound, and
  an immediate pair at `$BC39` naming `$900C` that has not been read. It also contains
  the bytes other patches have claimed at `$BF83` on.
- **`$9164`-`$94E6`, 899 bytes**: the putting view's sprites. One caller (`$8FC8`), five
  outbound targets.
- **Not worth moving**: the course view, markers and HUD between `$8E80` and `$A499`
  are called from 25 to 40 sites each.

## Gaps

- **Nothing has been built.** No relocated ROM exists; the stub and rebasing scheme is
  untested.
- **References the trace cannot see.** A pointer held in a data table or computed at run
  time is invisible to it. The block has no known ones, but a Mesen sweep (read and
  execute breakpoints over `$AD0A`-`$B9A6` from outside the block, across a full round
  with water, bunkers, out of bounds, putting and a replay) is the confirmation.
- **Fixed-bank code that assumes bank 13.** The trace has fixed-bank code reaching bank
  13 at three places (`$8000`, `$8E02`, `$9620`) while bank 13 is mapped. None is in the
  block, and the routines the block calls do not lead to them directly, but
  `ClassifyProbePosition` and the NMI path were not read to the end.
- **Flags into the outbound targets**, and carry or zero expected back from any of the
  seven, need reading at each call site.
- **Uncalled code.** 202 bytes of bank 13 are code nothing reaches; any inside the block
  should be identified before trusting the boundary list.
- **Timing.** One extra far call a frame during a shot (roughly 150 cycles) and one for
  each outbound call is expected to be harmless; it has not been measured against the
  frame budget on the heaviest frame (bunker splash redraws the course view).
- **Replays and CPU opponents** run the same physics from recorded inputs; they need a
  playtest on the moved ROM.
- **Verification.** The Python model and its oracles (`golf/physics/`) use vanilla
  addresses. Checking a moved ROM frame for frame needs `RomGameShot` and `RomShot`
  pointed at the new bank and addresses, then the existing shot comparisons run against
  both ROMs.
- **Bank 2 budget.** The 3,767 free bytes come from one sample seed build; the QR port
  and `round_stats` sizes should be read from their modules, not a build, before the
  space is promised.
