# Hole Difficulty Analysis: Development Plan

> **Note**: This document was written by Claude from decisions made with jdharms.
> It is the plan for rating how hard NES Open holes are, from the game's own physics:
> what is built, what is decided, and the order of work.

**Status**: phases 1 and 2 are done, apart from two phase 1 leftovers. Phase 3 has the
player model. **The next step is speed** (phase 3): making one intent cheap enough for
the solver to evaluate thousands per spot.

## Goal

The expected score of any hole: how many strokes a scratch player takes from the tee on
average, over every wind and pin the game can deal. The solver works this out from every
spot on the hole, so strokes-to-hole maps, difficulty against a featureless baseline and
per-hole summaries can be derived from it afterwards. Any of them could feed the
randomizer's catalog.

The idea comes from Matthew Schoolfield's course-strategy simulator
([I spent the last month and a half...](https://golfcoursewiki.substack.com/p/i-spent-the-last-month-and-a-half)).
Its weakest parts were approximate physics and no putting. Here the physics is the game's
own, reproduced exactly, and putting is part of the same model.

In scope: the vanilla NES Open and Mario Open (JP) courses, and any hole in the course
JSON format. Out of scope for now: rating whole randomizer seeds, and any change to the
site.

## Terms

- **Model**: `golf/physics/`, the Python port of the game's shot loop. It agrees with the
  game on every register every frame (`docs/shot_physics.md`, ADR 0007).
- **Oracle**: the game's own code run under py65, to check the model against. There are
  two kinds (see **The mini-NES**): single routines (`rom_oracle.py`) and the whole game
  (`nes.py`, `rom_game.py`). Every new ported piece is checked against one before
  anything is built on it.
- **Ground**: what the model asks "what is under the ball?": `UniformGround` for a driving
  range, `HoleGround` (`golf/physics/terrain.py`) for a hole from course JSON.
- **Intent**: the shot a player means to play (`golf/difficulty/player.py`): club, swing
  speed, spin, hi/lo, aim, and the power and accuracy stops they want.
- **Skill**: how far a player's execution scatters around their intent: normal errors
  in frames on each meter press, and in aim steps on the aim.
- **Anchors**: a hole's wind direction and speed, dealt once by `InitHole`. Each shot's
  wind is the anchors plus a speed jitter, dealt at shot setup.
- **Expected strokes**, E(p): the average number of strokes to hole out from spot p,
  playing the best intent from every spot.
- **Baseline**: expected strokes from the same distance on uniform fairway with a cup.
- **Difficulty**: expected strokes minus baseline, for one spot or summed over a hole.

## Decisions

- **The output is expected strokes from the tee** (jdharms). Difficulty maps, baselines
  and per-hole summaries are derived from the value function later.
- **Skill is solved for, not assumed.** A scratch player is whoever averages 72 over a
  round, with no allowance for physical strength since NES Open has none. That skill is
  then carried to other holes and courses unchanged.
- **Calibrate on the U.K. course.** It is harder than Japan ("course zero", with some
  beginner feel) and the US (the course menus put first), but easier than Mario Open's
  hardest. That leaves US and Japan as out-of-sample checks, with Mario Open as the hard
  end.
- **Perfect strategy.** The solver always picks the best intent; only execution is
  imperfect. Schoolfield's simulator did the same. A calibrated scratch player therefore
  executes a little worse than a real one, to make up for real players' strategy mistakes.
  The calibration absorbs this, and it is the same everywhere.
- **Skill is one number to start.** It scales every error source together, with their
  ratios as a stated assumption. A single target (72) can only pin down one number.
  Sensitivity runs then vary the ratios (phase 4).
- **Timing error is normal in frames about the intended press** (jdharms): a bell curve,
  rounded to whole frames, around the frame the player meant to press on. The intended
  accuracy stop is part of the intent, since hooks and slices on purpose are part of the
  game, so the error is measured from it, not from `$30`.
- **Aim error is normal in aim steps**, rounded to one of the 256, and one size for
  every aim: left and right move the aim the same amount a frame wherever the player
  aims (jdharms).
- **The solver plays from the vanilla 14-club bag**, not a seed's bag (jdharms).
- **Expected score is averaged over the game's own wind and pins**, as `InitHole` and
  `WindAdjustmentRoutine` deal them (`docs/seeded_wind.md`). A hole's anchors and pin hold
  for every shot on it: 64 anchor pairs × 4 pins, all equally likely
  (`golf/physics/wind.py`). Each shot's jitter is independent. It is dealt before the
  player chooses, so the player plays to the wind they are given.

## Picking this up

**Read first**, in this order:

1. This plan.
2. `docs/shot_physics.md`: how a shot works in the game, with ROM addresses: the swing,
   the flight, the cup, penalties, and what the model does not cover.
3. `golf/physics/CLAUDE.md`: how to test, and the rules for code in `golf/physics/`.
4. ADR 0007 (`docs/adr/`): why the model is an exact port rather than idealized physics.
5. `docs/seeded_wind.md`, **The vanilla wind as probabilities**.
6. `golf/difficulty/player.py`: the player model, which the solver builds on.
7. The `nes-open-golf-rom-peek` and `nes-open-golf-label-conventions` skills, before any
   reverse engineering. Most of this work is reading 6502 in banks 8, 9 and 13.

**Run:**

```bash
uv run pytest --physics tests/physics     # all the model's checks against the game (~2 min)
uv run pytest tests/integration/test_player_model_rom.py   # the player model (~5 s)
uv run golf-shots nes_open_us.nes         # carry/total table from the model
uv run golf-rom-peek nes_open_us.nes --labels "NES Open Tournament Golf (USA).mlb" \
    disasm '$81C4' --bank 9 --count 200   # e.g. the cup routine
```

The label file and its sidecar (`NES Open Tournament Golf (USA)*.mlb`) are gitignored
and local to this checkout. This work added a lot of sidecar labels; if they are missing,
the addresses in the docs still work but disassembly will be less annotated.

**Code map**, `golf/physics/` (exact ports, each checked against the game):

| File | What |
|------|------|
| `state.py` | `ShotInput`, `Ball` (the game's registers, named), `Terrain`, `Ground` |
| `tables.py` | Every ROM table the physics reads |
| `meter.py` | The swing meters and animation: the frames A is pressed on to meter stops and `frames_to_impact` |
| `launch.py`, `flight.py`, `landing.py` | Launch, air frames, ground contact |
| `terrain.py` | `ClassifyProbePosition`: `HoleGround` |
| `perspective.py`, `distance.py` | The behind-the-golfer projection and tree collision; the distance readout |
| `cup.py` | `UpdateBallAtCup`: holing out, lip-outs, rim-ins and the flagstick |
| `shot.py` | `ShotInFlight` (one `step()` per frame, in the game's order), `simulate()`, and `Flag` (`Flag.for_pin`: a hole's pins) |
| `rules.py` | `play_on`: where the next shot is played from, and the strokes it cost |
| `wind.py` | The winds and pins a hole deals, as probabilities |
| `rom_oracle.py` | Single-routine oracles: `RomShot`, `RomTerrainProbe`, `read_ball()` |
| `nes.py`, `rom_game.py` | The mini-NES, and a shot played through the whole game |

`golf/difficulty/` (our own modelling, built on the physics):

| File | What |
|------|------|
| `player.py` | `Intent`, `Skill`, `Position`, `Hole`; `outcomes()`: an intent's results with probabilities |

### The mini-NES

`golf/physics/nes.py` (`NesMachine`) is just enough of an NES to run the game's own frame
loop under py65. It exists because single-routine oracles kept missing code that runs
elsewhere in the same frame: the swing animation in bank 8 gates the view switch, bank 9
builds the scene and runs the cup, and the NMI reads the pad. It gives the game:

- **MMC1 PRG banking**: writes to `$8000-$FFFF` shift into the mapper's register, and the
  fifth write to the PRG register swaps `$8000-$BFFF`. The game only changes banks through
  `SetPrgBank` (`$D35A`), so far calls (`ExecuteFarCall`, `$D372`) just work.
- **The controller** at `$4016`: set `machine.buttons` (the `BUTTON_*` constants), and the
  game's NMI reads it like a real pad.
- **Frames**: when the game reaches `WaitForVblank`'s busy loop (`$CD7D`), the machine
  calls `on_frame(frame)` and then runs the game's own NMI handler (`$D2BF`).
- **Breakpoints**: `machine.add_breakpoint(address, callback, bank)` runs Python before an
  instruction. `rom_game.py` uses them to set the aim before the scene is built, snapshot
  the ball once per pass of the swing loop, capture the scene, and stop.

Not emulated: the picture (PPU writes land in plain memory; `$2002` reads alternate the
vblank bit so polling loops end), sprite 0, IRQs, the second pad. Nothing in a shot is
known to depend on them. That is what the Mesen spot checks in phase 1 are for.

`golf/physics/rom_game.py` (`RomGameShot`) uses the machine to play one shot:

1. `RomGameShot(rom, course, hole, rng_state=0)` sets the course and hole and runs the
   game's own `InitHole` (`$DA90`), which decompresses the hole into RAM exactly as the
   game does and deals the pin and wind anchors from `rng_state`. Only vanilla holes can
   be loaded this way; a custom hole would need writing into a ROM first (`golf-write`),
   which has not been tried.
2. `play(shot, swing)` pokes in what earlier play would have set (ball position, RNG,
   wind, club in bag slot 0, swing and putt speed, spin), then runs `ShotSetupSequence`
   (`$877A`), tapping A through the setup panels. It holds Up/Down for hi/lo for the
   whole shot (the game keeps reading it after launch), and presses A at the frames
   `Swing` gives to start the swing and stop each meter.
3. It returns a `RomShotRecord`: the shot as actually launched (`shot`, with the meter
   stops, RNG, aim, `frames_to_impact` and `scene_aim` read from RAM at launch), the ball
   after every frame (`frames`, as `Ball` via `read_ball()`), `view_modes`, the scene
   (`PerspectiveScene`, a WRAM snapshot) and the `flag`.
4. With `follow_through=True` it starts from the play loop (`$82AD`) instead, and runs on
   past the shot until the loop has dealt with the lie. It records the ball then
   (`after`: dropped after water, back after out of bounds) and the strokes the shot
   added (`strokes`). The ball's position before the shot, which out of bounds goes back
   to, is poked in as `LD_86ED` would have left it.

Things that will trip you up:

- **A frame is a pass of the swing loop** (`$AA2A`), not an NMI. They are one to one
  through the swing; after launch some passes wait for vblank twice, so NMI counts drift
  from the physics.
- **Read inputs at launch, not after the shot.** Display code rewrites `$D6/$D7`, and
  hi/lo changes until impact. `rom_game.py` reads them on the pass that launches.
- **Some registers are stale at launch**: scratch bytes (`$EA-$EF`) and readouts other
  code left behind. `CARRIED_FROM_LAUNCH` in `tests/physics/test_game_rom.py` copies them
  from the game's launch frame into the model before comparing.
- **A swing whose accuracy press comes too late whiffs**: the meter runs off the end and
  no ball launches (`WhiffError`). The tests check that `meter.swing` whiffs too, then
  skip the shot.
- **A putt's backswing starts by itself**, so `Swing` gives it one press, at
  `start + power`, which is backswing pass `start + power − 1`. It uses the putt speed
  (`$0125`), not the swing speed, and launches with spin TOP 2.
- **Presses need gaps.** The game ignores a press 1 or 2 frames after the last one, so
  a `Swing` with `power` or `accuracy` under 3 does not do what it says.
- **`$63-$68` are scratch outside the cup view.** `Ball` carries them (`cup_x` and so on)
  but does not compare them. What they decide shows up in `$0580-$0582` and `$0593-$0595`.
- **The pin and wind anchors come from the RNG state when `InitHole` runs**
  (`RomGameShot`'s `rng_state`). The shot's own RNG and wind are poked in afterwards.
- **To see a new register**, add it to `Ball` and `read_ball()`, and the frame-by-frame
  comparison picks it up. That is usually the quickest way to find where the model and
  the game part.
- **Scratch scripts** that sweep hundreds of random shots and print the first differing
  frame were how every bug here was found. `tests/physics/test_game_rom.py` is the
  template.
- **The at-the-flag seeds are pinned.** `test_shot_at_the_flag` names the outcome each
  seed must produce. A change to its picker, or to the model near the cup, can move
  them. Find them again by running the picker over seeds until each outcome has enough
  cases.

## Phases

### 1. Real holes under the model

Done:

- **`ClassifyProbePosition`** (`$EDEA`), as `HoleGround` in `golf/physics/terrain.py`.
  It matches the ROM at every pixel of all 54 NES Open holes and at sampled pixels of 83
  Mario Open holes.
- **Views, trees and the bunker lip rule**: the view switch, the overhead tree probe, the
  behind-the-golfer projection and scene collision, the distance readout and the lip
  rule, in `golf/physics/shot.py`, `perspective.py` and `distance.py`.
- **The game itself as the oracle**: `golf/physics/nes.py` and `rom_game.py` play shots
  through the game's own frame loop. The model matches it on every register, every frame,
  for random shots from random lies on random holes (`tests/physics/test_game_rom.py`).
- **View mode confirmed in Mesen** (jdharms): `$80` from the swing, then `$00`.

Left:

- **Holes over 46 rows**: read `TerrainBottomY` and the row tables from a
  `wram_expansion` ROM, so the 7 tall Mario Open holes work too.
- **Emulator spot checks** (jdharms, in Mesen): a perfect medium 1W drive (235 carry, 268
  total), and the `$40` wind distortion (`docs/shot_physics.md`). What they check now is
  the emulated machine: that nothing it leaves out (the PPU, sprite 0, IRQs) changes a
  shot.

The scene builder (bank 9 `$8829`) belongs to phase 3.

### 2. The rest of the rules

Done:

- **The cup** (`UpdateBallAtCup`, bank 9 `$81C4`), as `golf/physics/cup.py`: the cup
  view (`$C0`) and the physics it slows, holing out, rim-ins, lip-outs and the flagstick
  (`docs/shot_physics.md`, **The cup**). `test_shot_at_the_flag` plays putts and chips
  that the model predicts will reach the cup, and pins the outcome each case must
  produce. A scratch sweep of 291 more such shots (25 rim-ins, 11 lip-outs, 8 holed, 2
  off the flagstick) matched the game on every frame.
- **Penalties and drops**, as `play_on` in `golf/physics/rules.py` (`docs/shot_physics.md`,
  **After the shot**). Water costs a stroke and drops the ball where it was on the last
  frame it was over anything but water or out of bounds, in the air or not. Out of bounds
  is stroke and distance. `RomGameShot.play(follow_through=True)` runs on into the play
  loop, and every shot in `test_game_rom.py` checks where the game puts the ball next,
  and the strokes it counts, against `play_on`.
- **Wind generation** as probabilities, in `golf/physics/wind.py`: 64 equally likely
  anchor pairs (not 176, because neighbouring draws share bits), an independent pin, and
  an independent jitter per shot. `test_wind_rom.py` checks `InitHole` and
  `WindAdjustmentRoutine` against it.
- **Meter timing**, in `golf/physics/meter.py` (`docs/shot_physics.md`, **The swing**):
  the frames A is pressed on give the meter stops and `frames_to_impact` exactly,
  bounces, auto-stops and whiffs included. Every shot in `test_game_rom.py` checks it,
  and `test_meter_rom.py` covers every kind of backswing.

### 3. The solver

Done:

- **The player model**, `golf/difficulty/player.py`. The player means to press on the
  frame whose meter reading comes nearest each target of their `Intent`, the earlier of
  two equally near. The accuracy target is taken on the meter as the swing actually
  went, so a late power press does not also spoil the accuracy. `Skill` gives the
  errors. `outcomes(intent, position, hole, wind, skill)` plays every combination
  through `meter.swing`, the physics and `play_on`, in the wind the shot was dealt, for a
  sample of four RNG states. It returns `Result`s (where the next shot is played from,
  what this one cost, or `HOLED`) with probabilities. A whiff costs a stroke and leaves
  the ball where it was. The game hands over the putter on the green, so any other club
  there is refused. Tests are in `tests/integration/test_player_model_rom.py`.
- **`Flag.for_pin`**: a hole's four pin positions from its JSON, as `InitHole` computes
  them (checked against it in `test_wind_rom.py`).

Assumptions to revisit in phase 4:

- Errors reach 3 standard deviations. The three are in the ratio 1 : 1 : 1 (frames,
  frames, aim steps).
- The physics RNG is 4 fixed states, standing for all 65,534.
- **No trees in the behind-the-golfer view**: `outcomes()` has no scene to collide with
  until the scene builder is ported or cached (below). Overhead-view trees work.

**Next step: speed.** One intent at skill 1.0 is 7 × 7 power and accuracy errors, × 7
aim errors, × 4 RNG states: 1,372 simulations at about 7 ms each for a full shot (under
1 ms for a putt). One intent with club 8 from the US 1st's fairway measured 8 s. The
solver needs many intents from every spot, every pass of value iteration, for each of 256
cases. What is known that bears on it:

- **The intent space**: 15 clubs × 3 speeds × 3 spins (TOP 1 and TOP 2 play exactly
  like NORMAL) × 3 hi/lo × 256 aims × about 49 power targets × about 30 accuracy
  targets. It has to be pruned: aims in a cone around sensible targets, power targets
  that reach somewhere useful, and so on.
- **Cache by shot, not by intent.** Every intent from a spot is a distribution over the
  same kind of `ShotInput`s, and neighbouring intents share most of them. Simulating
  each distinct `ShotInput` once per spot, and weighting, is likely the first large win.
- **Reusing flights across starts** holds only in part. Up to first contact, a flight
  depends on the shot, the wind, the RNG and the launch lie (rough and sand change the
  power), not on the start's position, with these exceptions, all of which read the
  ground:
  - trees: the overhead probe reads the terrain under the ball's sprite, and the
    behind-the-golfer scene is built from the start and aim;
  - the view switch, which picks the tree rule, reads the scene depth and the distance
    readout;
  - out of bounds at the playfield's edge (`BallX >= $B0`) is an absolute position;
  - the cup view, near the flag.

  A cache of flights by shot is valid for starts where none of these apply. It must be
  checked against the full `simulate` on sampled cases before use.
- If that is still too slow: a NumPy version that plays many shots in lockstep, checked
  against the model (ADR 0007's revisit condition), then multiprocessing.

Then:

- **The value function**, per hole anchor pair and pin (256 cases, all equally likely):
  E(p) = the average, over the 4 wind jitters a shot can be dealt, of the best intent's
  average of (strokes + E(next)) over its outcomes. E = 0 in the cup. The wind is dealt
  before the player chooses, so the best intent is taken inside the average over wind.
  States are (pixel, bunker depth); the lie follows from the pixel. One pixel is two
  yards, so the game's own grid is fine enough. The values depend on each other in
  cycles: a shot can finish farther from the hole, a whiff or out of bounds brings the
  ball back to where it started, and water drops it behind. So it is solved by value
  iteration, repeating the update until nothing changes, starting from the green outward
  so it settles quickly. E from the tee, averaged over the 256 cases, is the hole's
  expected score.
- **The scene builder** (bank 9 `$8829`), ported or its scenes cached per start and aim,
  so the behind-the-golfer view has its trees.
- **The baseline**, later: the same solver on uniform fairway with a cup.

### 4. Calibration and validation

- Solve for the skill whose expected U.K. round is 72.
- Predict the US, Japan and Mario Open courses with that skill. The expected order is
  Japan, US, U.K., then Mario Open's hardest.
- Check against real play: per-hole averages from the scorecard QR submissions. Ranking
  the holes the same way real scores do matters more than matching the scores.
- Sensitivity: vary the ratios between the three errors, the error reach and the RNG
  sample, and see whether the hole rankings hold.

### 5. Output, derived from the value function

- Strokes-to-hole and difficulty heatmaps drawn over the hole renders
  (`golf/rendering/`).
- A per-hole difficulty score, and a proposal for how the randomizer catalog would use
  it.
