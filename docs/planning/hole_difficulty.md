# Hole Difficulty Analysis: Development Plan

> **Note**: This document was written by Claude from decisions made with jdharms.
> It is the plan for rating how hard NES Open holes are, from the game's own physics:
> what is built, what is decided, and the order of work.

## Goal

A strokes-to-hole map of any hole: at every point, how many strokes a scratch player
takes from there on average, minus what the same player would take from the same distance
on a featureless plane. The difference shows where a hole punishes you and by how much. A
per-hole score that summarises it could feed the randomizer's catalog.

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
- **Shot**: a choice of club, swing speed, power stop, accuracy stop, hi/lo, spin and aim.
- **Skill**: how far a player's execution scatters around the shot they meant to play.
- **Expected strokes**, E(p): the average number of strokes to hole out from spot p, lie
  included, playing the best shot from every spot.
- **Baseline**: expected strokes from the same distance on uniform fairway with a cup.
- **Difficulty**: expected strokes minus baseline, for one spot or summed over a hole.

## Decisions

- **Skill is solved for, not assumed.** A scratch player is whoever averages 72 over a
  round, with no allowance for physical strength since NES Open has none. That skill is
  then carried to other holes and courses unchanged.
- **Calibrate on the U.K. course.** It is harder than Japan ("course zero", with some
  beginner feel) and the US (the course menus put first), but easier than Mario Open's
  hardest. That leaves US and Japan as out-of-sample checks, with Mario Open as the hard
  end.
- **Perfect strategy.** The solver always picks the best shot; only execution is
  imperfect. Schoolfield's simulator did the same. A calibrated scratch player therefore
  executes a little worse than a real one, to make up for real players' strategy mistakes.
  The calibration absorbs this, and it is the same everywhere.
- **Skill is one number to start.** It scales every error source together, with their
  ratios as a stated assumption. A single target (72) can only pin down one number.
  Sensitivity runs then vary the ratios (phase 4).
- **Aim error is an error in the intended angle**, in degrees or aim steps, rounded to one
  of the 256 aim steps. The default heading is the pin. Nudging it for wind happens on the
  ready-to-swing screen, which fine-tunes within ±9 steps, and is done by counting taps.
  Aiming around doglegs or water means going back to the setup screens (full 360°) and
  judging a long line by eye. The model can give the two cases different error sizes.
- **Expected score is averaged over the game's own wind**, as `InitHole` and
  `WindAdjustmentRoutine` generate it (`docs/seeded_wind.md`), unless a question needs a
  fixed wind.

## Picking this up

**Read first**, in this order:

1. This plan.
2. `docs/shot_physics.md`: how a shot works in the game, with ROM addresses, and what the
   model does not cover yet.
3. `golf/physics/CLAUDE.md`: how to test, and the rules for code in `golf/physics/`.
4. ADR 0007 (`docs/adr/`): why the model is an exact port rather than idealized physics.
5. The `nes-open-golf-rom-peek` and `nes-open-golf-label-conventions` skills, before any
   reverse engineering. Most of this work is reading 6502 in banks 9 and 13.

**Run:**

```bash
uv run pytest --physics tests/physics     # all the model's checks against the game (~2 min)
uv run golf-shots nes_open_us.nes         # carry/total table from the model
uv run golf-rom-peek nes_open_us.nes --labels "NES Open Tournament Golf (USA).mlb" \
    disasm '$81C4' --bank 9 --count 200   # e.g. the cup routine, the next thing to port
```

The label file and its sidecar (`NES Open Tournament Golf (USA)*.mlb`) are gitignored
and local to this checkout. This work added a lot of sidecar labels; if they are missing,
the addresses in the docs still work but disassembly will be less annotated.

**Code map** (`golf/physics/`):

| File | What |
|------|------|
| `state.py` | `ShotInput`, `Ball` (the game's registers, named), `Terrain`, `Ground` |
| `tables.py` | Every ROM table the physics reads |
| `launch.py`, `flight.py`, `landing.py` | Launch, air frames, ground contact |
| `terrain.py` | `ClassifyProbePosition`: `HoleGround` |
| `perspective.py`, `distance.py` | The behind-the-golfer projection and tree collision; the distance readout |
| `shot.py` | `ShotInFlight` (one `step()` per frame, in the game's order) and `simulate()` |
| `rom_oracle.py` | Single-routine oracles: `RomShot`, `RomTerrainProbe`, `read_ball()` |
| `nes.py`, `rom_game.py` | The mini-NES, and a shot played through the whole game |

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

1. `RomGameShot(rom, course, hole)` sets the course and hole and runs the game's own
   `InitHole` (`$DA90`), which decompresses the hole into RAM exactly as the game does.
   Only vanilla holes can be loaded this way; a custom hole would need writing into a ROM
   first (`golf-write`), which has not been tried.
2. `play(shot, swing)` pokes in what earlier play would have set (ball position, RNG,
   wind, club in bag slot 0, speed, spin), then runs `ShotSetupSequence` (`$877A`),
   tapping A through the setup panels. It holds Up/Down for hi/lo for the whole shot
   (the game keeps reading it after launch), and presses A at the frames `Swing` gives to
   start the swing and stop each meter.
3. It returns a `RomShotRecord`: the shot as actually launched (`shot`, with the meter
   stops, RNG, aim, `frames_to_impact` and `scene_aim` read from RAM at launch), the ball
   after every frame (`frames`, as `Ball` via `read_ball()`), `view_modes`, the scene
   (`PerspectiveScene`, a WRAM snapshot) and the `flag`.

Things that will trip you up:

- **A frame is a pass of the swing loop** (`$AA2A`), not an NMI. Some passes wait for
  vblank twice, so NMI counts drift from the physics.
- **Read inputs at launch, not after the shot.** Display code rewrites `$D6/$D7`, and
  hi/lo changes until impact. `rom_game.py` reads them on the pass that launches.
- **Some registers are stale at launch**: scratch bytes (`$EA-$EF`) and readouts other
  code left behind. `CARRIED_FROM_LAUNCH` in `tests/physics/test_game_rom.py` copies them
  from the game's launch frame into the model before comparing.
- **A swing whose accuracy press comes too late whiffs**: the meter runs off the end and
  no ball launches (`WhiffError`). Tests skip those.
- **The flag is chosen inside `InitHole` from whatever RNG state RAM holds then** (zero,
  in `RomGameShot`). The shot's own RNG is poked in afterwards.
- **To see a new register**, add it to `Ball` and `read_ball()`, and the frame-by-frame
  comparison picks it up. That is usually the quickest way to find where the model and
  the game part.
- **Scratch scripts** that sweep hundreds of random shots and print the first differing
  frame were how every bug here was found. `tests/physics/test_game_rom.py` is the
  template.

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

Moved to later phases, because the model can already take them as inputs from the ROM:

- **The scene builder** (bank 9 `$8829`) to phase 3. The model uses scenes the ROM
  built. The solver needs one for every start and aim, so it needs either a port or a
  cache.
- **The swing animation's timing** (bank 8), which sets `frames_to_impact`, to phase 2
  with meter timing.

### 2. The rest of the rules

**Next step: the cup.** Without it the model cannot finish a hole, so everything after
depends on it.

- **Where**: `UpdateBallAtCup`, bank 9 `$81C4-$8465`, far-called by `LD_A884` (bank 13)
  each frame the main loop reaches `$AA87` in the green view (`docs/shot_physics.md`,
  **Views**). It rotates the ball's offset from the flag (`FlagX/Y`, `$A7-$AA`) by the aim
  plus `$80` with `RotateVector16`, then decides:
  - holing out: `L9_830D` sets `ShotPhaseState` 2 and `MaybeHoleCompleteFlag` once the ball
    has spent 2 or more frames over the cup (`$0594`) slowly enough (`L9_8425`, speed
    under `$1C`);
  - the lip-out: `$0593` makes `CalcLaunchVector` run only every 4th frame (`$AF3A`), and
    far-calls bank 13 `$A8B6`;
  - the flagstick: `$8445` decrements `$0595` while not putting, and `$AF49` then reverses
    and halves the velocity.
- **How**: port it into `ShotInFlight._cup` (which currently only detects "near the cup"
  and raises `UnportedBehaviourError`). Add `$0593-$0595`, `$0580-$0582` and
  `MaybeHoleCompleteFlag` to `Ball` and `read_ball()`. Then remove the `UnportedBehaviourError`
  allowance in `test_game_rom.py`, and add seeds with putts and approach shots aimed at
  the flag so the cup is reached often. `BallDropAnimationEntry` (bank 9 `$8050`, run
  after the shot) animates the drop and likely changes nothing, but confirm it.
- **Done when** `test_game_rom.py` passes with no refusals over a few hundred shots that
  end near the flag.
- **Penalties and drops**: where the ball is replayed from after water and out of bounds,
  and how many strokes each costs.
- **Wind generation** as a distribution, reusing `golf/core/patches/seeded_wind.py`'s
  model of the RNG.
- **Meter timing**: how many frames a stop takes at each swing speed (`$AB46/$AB49`), so
  timing error can be stated in frames. Also the swing animation (bank 8), which decides
  `frames_to_impact`: how long after launch the view can change, and how long hi/lo is
  still read.

### 3. The solver

- **The player model**: an intended shot plus timing error on both meters and aim error,
  all scaled by one skill number.
- **The value function**: E(p) = 1 + the best, over shots, of the average E where the ball
  finishes, with E = 0 in the cup. Solved outward from the green by value iteration over
  (pixel, lie, bunker depth) states. One pixel is two yards, so the game's own grid is fine
  enough.
- **Speed**: a ball's flight does not depend on where it starts, only on the shot and the
  wind, until it lands or meets a tree. So each flight is computed once and reused from
  every start. Only the roll, which is short, is played on the real terrain. Candidate aims
  are limited to a cone around sensible targets. If that is still too slow: a NumPy version
  that plays many shots in lockstep, checked against the model (ADR 0007's revisit
  condition), then multiprocessing.
- **The baseline**: the same solver on uniform fairway with a cup.

### 4. Calibration and validation

- Solve for the skill whose expected U.K. round is 72.
- Predict the US, Japan and Mario Open courses with that skill. The expected order is
  Japan, US, U.K., then Mario Open's hardest.
- Check against real play: per-hole averages from the scorecard QR submissions. Ranking
  the holes the same way real scores do matters more than matching the scores.
- Sensitivity: vary the ratios between timing and aim error, and see whether the hole
  rankings hold.

### 5. Output

- Difficulty heatmaps drawn over the hole renders (`golf/rendering/`).
- A per-hole difficulty score, and a proposal for how the randomizer catalog would use it.

## Open questions

- The shape of the timing error: normal in frames, or skewed? Recorded meter stops from
  real play in Mesen would settle it; until then it is an assumption.
- Should the solver's club choice be limited to a vanilla 14-club bag, or to a seed's bag?
- What single number summarises a hole: expected strokes minus par, the average
  difficulty along the best line, or something else?
