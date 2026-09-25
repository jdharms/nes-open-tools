# Hole Difficulty Analysis: Development Plan

> **Note**: This document was written by Claude from decisions made with jdharms.
> It is the plan for rating how hard NES Open holes are, from the game's own physics:
> what is built, what is decided, and the order of work.

**Status**: phases 1 and 2 are done, apart from two phase 1 leftovers. Phase 3 has a
working solver for one pin and no wind (`golf-difficulty`): the US 1st solves to 2.906
strokes from the tee at skill 1.0, in 24 minutes on 24 cores under CPython. **The next
step is running it under PyPy** (about ten times faster, see **Next steps** in phase 3),
then a whole U.K. round, then the calibration of phase 4.

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
- **The first solver has one pin and no wind** (jdharms): the hole's first pin, wind
  speed 0. It is about a hundredth of the work of every wind and pin, and the rest of the
  machinery (`golf/physics/wind.py`, `Flag.for_pin`) waits for it. Holes play easier
  without wind, so a skill calibrated this way is recalibrated when wind comes in.
- **Only spots that play reaches are valued** (jdharms): the tee, and every spot the best
  play from it visits often enough. Most of a hole is rough nobody plays from.
- **Errors reach 2 standard deviations** (jdharms), to be revisited in phase 4.
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
7. `golf/difficulty/landing.py` and `solver.py`: the module docstrings say how the
   screen and the rounds work.
8. The `nes-open-golf-rom-peek` and `nes-open-golf-label-conventions` skills, before any
   reverse engineering. Most of this work is reading 6502 in banks 8, 9 and 13.

**Run:**

```bash
uv run pytest --physics tests/physics     # all the model's checks against the game (~2 min)
uv run pytest tests/integration/test_player_model_rom.py   # the player model (~5 s)
uv run pytest tests/integration/test_flights_rom.py        # shared flights against simulate (~5 s)
uv run pytest tests/integration/test_difficulty_solver_rom.py  # landing table, solver helpers
uv run golf-shots nes_open_us.nes         # carry/total table from the model
uv run golf-difficulty nes_open_us.nes --course us --hole 1 --output us01.json
                                          # solve one hole (builds the landing table first)
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
| `flights.py` | Not a port: `Flight` and `Flights`, a shot recorded once and finished from any start, exactly as `simulate` would play it |
| `rom_oracle.py` | Single-routine oracles: `RomShot`, `RomTerrainProbe`, `read_ball()` |
| `nes.py`, `rom_game.py` | The mini-NES, and a shot played through the whole game |

`golf/difficulty/` (our own modelling, built on the physics):

| File | What |
|------|------|
| `player.py` | `Intent`, `Skill`, `Position`, `Hole`; `outcomes()`: an intent's results with probabilities |
| `landing.py` | The landing table: every intent's perfect, windless rest from each lie at 8 base aims, cached under `.cache/difficulty/` |
| `solver.py` | `HoleSolver`: states, the screen, rounds of play in worker processes, value iteration, reach |

`tools/research/difficulty.py` is the `golf-difficulty` CLI. `golf/core/rng.py` (the
game's RNG and wind) and `golf/core/clubs.py` live outside `golf/core/patches/` so the
physics and the solver import nothing that PyPy 3.11 cannot parse.

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
- **Shared flights must follow the frame loop.** `flights.py` knows which registers the
  probe writes and which checks read the ground (see its docstring). A change to
  `ShotInFlight` that adds either must be mirrored there; `test_flights_rom.py` compares
  `Flight.finish` with `simulate` on every NES Open hole and fails when they part.
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
- **Shared flights**, `golf/physics/flights.py`. Until first contact a shot does the same
  thing from any start, except where the ground reaches in: a tree, the view switch over
  the green, the edges of the playfield. After contact it does the same over the same
  terrain. So a `Flight` plays a shot once over plain fairway, and each roll once over
  the terrain it lands on, keeping the pixels each frame's probe looked at and a snapshot
  every 8 frames. From a real start, `finish` walks those pixels over the real ground,
  works out what the probe would have written, and plays for real only from the snapshot
  before the first frame the ground changes. The result is `simulate`'s, register for
  register (`tests/integration/test_flights_rom.py`, on every NES Open hole). `Hole` holds
  a `Flights` cache, so `outcomes()` uses them.
- **The landing table**, `golf/difficulty/landing.py`. For each lie a full swing is
  played from (fairway and tee alike, rough at either depth, sand at each of three
  depths), every intent's perfect execution with no wind, played over plain fairway at 8
  base aims: 15 clubs and the putter, 3 speeds, every distinct power stop, 3 hi/lo, 3
  spins (the putter only NORMAL, straight, no hi/lo), and 5 accuracy targets (straight,
  and 8 and 16 either side of `$30`). 76,388 intents a lie, 3.7 million shots, 13 minutes
  on 23 workers; cached by a hash of the ROM's physics tables in `.cache/difficulty/`
  (gitignored), 11 MB. A shot at another aim is the nearest base aim's rest turned:
  within 2 pixels for a straight shot, 8 for a curved one (without wind a flight turns
  almost exactly; the hook and slice terms are uneven, hence the base aims).
- **The solver**, `golf/difficulty/solver.py`, and `golf-difficulty`:
  - **States**: off the green, cells of a 4-pixel grid split by lie class, the first real
    spot the ball reaches in a cell standing for it; on the green, every pixel; the tee.
  - **The screen**: from a spot off the green, every table intent with a club in the
    vanilla bag, at every other aim within a quarter turn of the pin, is scored by the
    current value of where it comes to rest, on a value map blurred by 2 pixels for
    execution's spread (water and out of bounds count a stroke and this spot again). The
    best intent of each club, speed, hi/lo and spin is kept, and the best 16 of those are
    played exactly with `outcomes()`. On the green, putts within 20 aim steps of the pin
    line are played once perfectly, every 4th aim first and then around the best, and the
    best 8 are played exactly.
  - **Rounds**: screen every state against the current values; play what is new on the
    shortlists (all of it for a new state, the top 4 for one screened before); value
    iteration from the green outward; then follow the best play forward from the tee and
    add every state it visits at least 0.001 times a hole. A state not yet valued borrows
    from valued neighbours of its class, or a guess from its distance (`guess`). Screens
    and plays are separate tasks in a process pool, the plays sorted so like shots share
    a worker. It stops when no state is added and the tee moves less than 0.002, or
    after 12 rounds.
  - **Result on the US 1st** (par 4, 328 yards), pin 0, no wind, skill 1.0: 2.906 strokes
    from the tee, from 209 states and 4,689 intents played, in 12 rounds and 1,431 s on
    24 cores under CPython. The tee's value had settled by round 9. Putts from inside
    about 7 yards are nearly always holed, and approaches from 40-80 yards average about
    1.9 strokes, so the drive to there decides the hole. (That run predates three small
    changes: the table's intents held as arrays, the screen scored a few aims at a time,
    and the edge of the map scored as out of bounds, 1 + E(here), where it had been
    2 + E(here). A rerun may differ a little.)

Assumptions to revisit in phase 4:

- Errors reach 2 standard deviations (jdharms), so one intent at skill 1.0 is 5 × 5
  timings × 5 aims × 4 RNG states: 500 shots. The three are in the ratio 1 : 1 : 1 (frames,
  frames, aim steps).
- The physics RNG is 4 fixed states, standing for all 65,534. A putt from the green is
  played from one of them: it reads the RNG only if it runs into sand or water.
- **No trees in the behind-the-golfer view**: `outcomes()` has no scene to collide with
  until the scene builder is ported or cached (below). Overhead-view trees work.
- **The solver's approximations**: the 4-pixel cells (a cell's value is its first spot's),
  the screen (only its shortlist is played; every value is exact physics), the 5
  accuracy targets, every other aim, and reach 0.001. Each is a setting of `Settings`
  or a constant in `solver.py` and `landing.py`, to vary in the sensitivity runs.

**Speed**, measured on the US 1st:

- `simulate` takes about 5 ms for a full shot under CPython (about 380 frames at 14 µs),
  under 1 ms for a putt. **Under PyPy it takes 0.55 ms** once warm, and gives exactly the
  same outcomes (compared by hash over a tee shot, an approach and a putt).
- `Flight.finish` takes 0.11 ms for a shot that lands and rolls out on uniform
  terrain, 1-1.5 ms for one whose roll runs onto something else, and 2-3 ms for one that
  comes down over the green. Recording a flight costs about as much as `simulate`.
- **In the solver, flights do not pay**: the shortlists of different spots rarely share an
  exact `ShotInput`, so a flight is only shared across the RNG states of one intent, and
  30 of the US 1st's intents took 70 s with `Flights` against 64 s with plain `simulate`
  (CPython, one core). Approach shots cost most: their roll on the green is played for
  real, about 250 frames.
- A spot's screen takes 0.1-0.2 s (0.4 s under PyPy) and peaks at 35 MB.

**Next steps**, in order:

1. **Run the solver under PyPy.** PyPy 3.11 plays shots ten times faster, and the solver
   and everything it imports is kept 3.11-clean (`tests/meta/test_pypy_ready.py`). The
   project itself needs 3.12, so PyPy gets its own environment with the few packages the
   solver needs, and the repo on `PYTHONPATH`:

   ```bash
   uv venv --python pypy@3.11 .cache/pypy
   VIRTUAL_ENV=.cache/pypy uv pip install numpy py65 pillow
   PYTHONPATH=. .cache/pypy/bin/python -m tools.research.difficulty nes_open_us.nes \
       --course us --hole 1 --workers 16 --output us01.json
   ```

   The first try, with 24 workers, was stopped by the system for low memory in its first
   round (15 GB machine). Since then a worker's table takes about 95 MB under PyPy (it
   was about 150) and the screen no longer builds whole-table arrays; a PyPy worker
   peaks around 260 MB before its flights. Start at 16 workers and watch `free -g`.
2. **Decide on flights in the solver.** Measure `Hole` with `Flights` against plain
   `simulate` under PyPy. If flights still do not pay, give `Hole` a way to play without
   them (they also hold memory: `Flights(max_flights=256)` per worker).
3. **Cut the late rounds.** On the US 1st the tee settled by round 9 while each later
   round still played 100-400 new intents. Stop once the tee has moved less than the
   tolerance for two rounds, or once the states still to add carry negligible visits.
4. **Solve the U.K. course** at skill 1.0, all 18 holes: the first round total. Look at
   the most visited states' policies (`--output`) for anything a player would never do.
5. **Calibrate** (phase 4): bisect the skill for a U.K. round of 72, with one pin and no
   wind, then predict the US and Japan courses.
6. **Wind and pins**, when the rest holds up: the per-hole cases of **The value
   function** below.

Then:

- **The value function**, per hole anchor pair and pin (256 cases, all equally likely):
  E(p) = the average, over the 4 wind jitters a shot can be dealt, of the best intent's
  average of (strokes + E(next)) over its outcomes. E = 0 in the cup. The wind is dealt
  before the player chooses, so the best intent is taken inside the average over wind.
  The solver does this today for one case with no wind; the cases share every shot whose
  wind is the same, and the pin only changes shots that reach the green.
- **The scene builder** (bank 9 `$8829`), ported or its scenes cached per start and aim,
  so the behind-the-golfer view has its trees. Shared flights assume no scene; with one,
  `Flight` would have to check the scene's collisions for each start too.
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
