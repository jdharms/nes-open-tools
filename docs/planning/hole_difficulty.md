# Hole Difficulty Analysis: Development Plan

> **Note**: This document was written by Claude from decisions made with jdharms.
> It is the plan for rating how hard NES Open holes are, from the game's own physics:
> what is built, what is decided, and the order of work.

**Status**: phases 1 and 2 are done, apart from two phase 1 leftovers. Phase 3 has a
working solver for one pin and no wind (`golf-difficulty`), run under PyPy, with each
green solved whole from a table of every putt. The US 1st solves to 3.66 strokes from the
tee at skill 3 and 4.09 at skill 4, in 5-7 minutes with the default settings; searching
more widely was worth about 0.03 at skill 3 (**How widely to search**, phase 3). All three NES Open courses are solved
at skill 3, and come out within half a stroke of one another (**The three courses**,
phase 3). **The next step** is solving them again with the fixes that run turned up,
then the calibration of phase 4.

## Goal

The expected score of any hole: how many strokes a scratch player takes from the tee on
average, with no wind, over the hole's four pins. The solver works this out from every
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
- **No wind** (jdharms, for now): every shot is played at wind speed 0. The game deals
  wind to every hole and every player alike, headwind as often as tailwind, so its effect
  is taken to average out across holes, and the calibration absorbs what is left. Calm is
  rare in the game (a speed-0 anchor is 4 in 64), so this is a modelling choice, not the
  typical case. Revisit if the hole rankings disagree with real scores; the machinery for
  it is `golf/physics/wind.py`.
- **The first solver has one pin** (jdharms): the hole's first pin. The other three
  (`Flag.for_pin`) come after the U.K. round holds up.
- **Only spots that play reaches are valued** (jdharms): the tee, and every spot the best
  play from it visits often enough. Most of a hole is rough nobody plays from.
- **Errors reach 2 standard deviations** (jdharms), to be revisited in phase 4.
- **Expected score is averaged over the hole's four pins**, all equally likely, as
  `InitHole` deals them (`docs/seeded_wind.md`, `golf/physics/wind.py`).

## Picking this up

**Read first**, in this order:

1. This plan.
2. `docs/shot_physics.md`: how a shot works in the game, with ROM addresses: the swing,
   the flight, the cup, penalties, and what the model does not cover.
3. `golf/physics/CLAUDE.md`: how to test, and the rules for code in `golf/physics/`.
4. ADR 0007 (`docs/adr/`): why the model is an exact port rather than idealized physics.
5. `docs/seeded_wind.md`, **The vanilla wind as probabilities**.
6. `golf/difficulty/player.py`: the player model, which the solver builds on.
7. `golf/difficulty/landing.py`, `green.py` and `solver.py`: the module docstrings say
   how the screen, the green and the rounds work.
8. The `nes-open-golf-rom-peek` and `nes-open-golf-label-conventions` skills, before any
   reverse engineering. Most of this work is reading 6502 in banks 8, 9 and 13.

**Run:**

```bash
uv run pytest --physics tests/physics     # all the model's checks against the game (~2 min)
uv run pytest tests/integration/test_player_model_rom.py   # the player model (~5 s)
uv run pytest tests/integration/test_flights_rom.py        # shared flights against simulate (~5 s)
uv run pytest tests/integration/test_difficulty_solver_rom.py  # landing table, solver helpers
uv run pytest tests/integration/test_green_rom.py          # the green table against outcomes()
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
| `landing.py` | The landing table: every intent's perfect, windless rest from each lie at 8 base aims, cached under `.cache/difficulty/`; `scatter`, an intent's rests under a skill's timing errors |
| `green.py` | A green solved whole: `build_pixel` plays every putt from a pixel once, `GreenSolver` values the green by lookups alone, at any skill |
| `solver.py` | `HoleSolver`: states, the screen, racing, rounds of play in worker processes, value iteration, reach |

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
  through `meter.swing`, the physics and `play_on`, in the wind the shot was dealt, from
  four RNG states chosen to stand for all of them (**The model's own approximations**). It returns `Result`s (where the next shot is played from,
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
  register (`tests/integration/test_flights_rom.py`, on every NES Open hole). The solver
  does not use them: with the player's errors few shots share a flight, and recording one
  costs more than playing it (see **Speed**). `Hole` takes a `Flights` to share, and
  plays every shot with `simulate` without one.
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
  - **The green**, `golf/difficulty/green.py`, solved whole. A putt from the green reads
    the RNG only in sand or water, and feels no wind: wind acts on air frames alone, a
    putt never leaves the ground, and on the green the probe writes the slope over the
    wind registers (`Ball.observe`). So its result depends only on the start pixel, the
    putt speed, the power stop and the aim, and the press frame decides the stop.
    `build_pixel` plays every speed, stop and aim within 48 steps of the pin line from
    every pixel of the green, once: 266 pixels and 3.8 million putts on the US 1st, 200 s
    on 16 workers, cached per ROM, hole and pin in `.cache/difficulty/`. The player's
    errors, press frames and aim steps either way, are other entries of the same table,
    so `GreenSolver` values the green by value iteration over lookups alone, at any
    skill, and every intent is scored under the errors, every unit of them: all three speeds, every aimed
    press and every aim that leaves room in the window for the aim errors. The solver
    values the green again at the start of each round against what the rest of the hole
    is then worth (putts that leave the green), and keeps each pixel's best 3 intents
    as its transitions. `test_green_rom.py` checks the table's outcome distributions
    against `outcomes()`, exactly, at skill 1 and 3, and that putts ignore wind. The
    table's putts are played from `RNG_STATES[0]`, which is part of its cache key.
  - **The screen**, off the green, in two passes. First, every table intent with a club
    in the vanilla bag, at every other aim within a quarter turn of the pin, is scored by
    the current value of where its perfect execution comes to rest, on a value map
    blurred by 2 pixels (water and out of bounds count a stroke and this spot again). The
    best intent of each club, speed, hi/lo and spin is kept. Second, the best 32 of those
    (`candidates`) are scored under the player's own errors: each intent's timing errors
    are played on the hole from this spot (`landing.scatter`, kept per worker), the aim
    errors turn that scatter, and the intent is scored at every aim again, on the map
    blurred by 1 pixel. The best 16 (`shortlist`) go on. The second pass is what makes
    the screen see skill: at skill 3 it moves the US 1st's drive from a fast swing to a
    medium one, which the first pass cannot tell apart. BACK 2 is not screened where it
    plays exactly as BACK 1: for the woods, and from the rough (it differs only when the
    first bounce is on the green, for clubs 4 and up, not from the rough).
  - **Racing**: when more than 6 intents (`race`) are new on a spot's shortlist, all are
    played roughly first, with one RNG state and 5 errors a draw (`RACE_POINTS`), scored
    on the current values, and only the best 6 are played exactly. The rough results only
    choose; no value comes from them.
  - **Rounds**: value the green; screen every state off it that is new, or that the best
    play visits at least 0.01 times a hole (`refresh_reach`); race and play what is new on
    the shortlists (all of it for a new state, the top 4, `refresh`, for one screened
    before); value iteration from the green outward; then follow the best play forward
    from the tee and add every state it visits at least 0.001 times a hole. A state not
    yet valued borrows from valued neighbours of its class, or a guess from its distance
    (`guess`). A state whose value has moved half a stroke since it was screened is
    screened again however rarely play reaches it (`rescreen_move`, **Loops** below).
    Value iteration stops at 300 sweeps a round (`ROUND_SWEEPS`), as values carry over,
    and the solve ends with a full run. Screens, races and plays are separate tasks in a
    process pool. It stops when no state is added, none is due to be screened again and
    the tee moves less than 0.002. After 12 rounds no state is added, and up to 6 more
    screen again only (`CLEANUP_ROUNDS`).
  - **Results on the US 1st** (par 4, 328 yards), pin 0, no wind, under PyPy with 16
    workers, the green's table already built:

    | Skill | Settings | Tee | Intents played | Rounds | Time |
    |-------|----------|-----|----------------|--------|------|
    | 1.0 | default | 2.928 | 1,228 | 9 | 152 s |
    | 1.0 | shortlist 32 | 2.924 | 1,048 | 6 | 131 s |
    | 1.0 | shortlist 32, no racing | 2.914 | 3,013 | 6 | 161 s |
    | 1.0 | wide (below) | 2.860 | 5,209 | 9 | 338 s |
    | 3.0 | default | 3.609 | 1,601 | 5 | 305 s |
    | 3.0 | 2 RNG states | 3.595 | 1,598 | 6 | 242 s |
    | 3.0 | 5 errors a draw | 3.623 | 1,406 | 5 | 153 s |
    | 3.0 | wide (below) | 3.578 | 7,863 | 6 | 1,127 s |

    Every value is exact play, so with the same model a missed intent can only raise the
    tee's value: lower is better, between runs that differ only in how they search. (2
    RNG states and 5 errors a draw change the model itself, so their gap is the size of
    that approximation plus the search's own noise, about 0.01-0.02, not a better or
    worse search.) Putts from inside about 7 yards
    are nearly always holed at skill 1.0, and approaches from 40-80 yards average about
    1.8-2.0 strokes, so the drive to there decides the hole.
  - **How widely to search.** The answer depends on how much the solver searches, by
    about 0.07 strokes a hole at skill 1 and 0.03 at skill 3 between the default and the
    wide settings (`--shortlist 32 --candidates 64 --refresh 8 --race 0 --refresh-reach 0
    --tolerance 0.0005`). The screen ranks approach shots badly: near the green, intents
    differ by a tenth of a stroke, less than the screen's own error, and the wide run's
    chosen approaches were mostly 13th-25th on its screen, often another club from the
    default run's (a 2-iron where the default chose a 3-wood, 0.13 strokes better). The
    wide run's later rounds keep finding them, as each re-screen against slightly moved
    values proposes intents not yet played: the tee went from 2.907 to 2.860 over rounds
    3-8 at skill 1. A longer shortlist, more candidates and racing each closed only part
    of the gap on their own. `--output` keeps every intent played from each state with
    its screen rank and score, and the CLI prints how the screen ranked the chosen ones.
    These runs predate the RNG states and the green's errors below.
  - **Rounds of holes**: `golf-difficulty --hole 1-18` solves each hole in turn and prints
    the round's total; `--output` is then a directory of one file per hole.
- **The model's own approximations**, measured on real play with `HoleSolver.recheck`
  (`--recheck-error-points`, `--recheck-rng-states`): the policy a solve chose is played
  again under a finer model, at every state it visits at least 0.001 times a hole, with
  the green solved again, and valued with the policy held fixed. The gap to the solve's
  own value is how far its model flattered its own choices. At the solve's own settings
  it gives back the solve's value exactly. On the US 1st, pin 0:
  - **The RNG sample** was the largest. The old four states (`$0001 $4E6C $9A3B $D5C2`)
    drew the rough and bunker power variance at −0.53, +0.10, +0.14 and +0.74 of its
    reach, the same four on every shot: long on average, and never short by more than
    about half. At skill 3 their policy played from 32 evenly spread states cost 0.033
    strokes more, all of it from states in the rough (+0.035); tee and fairway starts
    moved −0.002. `player.rng_sample(n)` picks states whose draws sit at the middles of
    `n` equal slices, with both coin flips balanced (the fairway's, read before the draw
    and after it) and low bytes spread (a landing in sand reads its depth from it). 4, 8,
    32 and 64 such states agreed within 0.003, so `RNG_STATES` is now `rng_sample(4)`, at
    no extra cost. Solving again with them gave 3.639, so re-choosing the policy won back
    only 0.003 of the 0.033: the old states' error was bias, not exploitation.
  - **The error grid**: at skill 4 (a stride of 3 units) the old model flattered its
    policy by 0.071 strokes against every unit played, 0.068 of it on the green alone.
    The green is lookups, so `GreenSolver` now plays every unit. Off the green the stride
    grid stays: with the green at every unit, the US 1st solves to 3.661 at skill 3 and
    4.093 at skill 4, and every unit played moves those policies by −0.009 and +0.014,
    no steady direction, so no sign of the solver leaning on the grid.
  - **Turned down: a phase per RNG state.** Taking each RNG state's errors at another
    offset of the stride, so that between them every unit is played at no extra cost,
    made the model pessimistic instead: 0.019 at skill 3 and 0.010 at skill 4 against
    every unit, with a slightly worse policy (3.656 played at every unit, where the old
    grid's policy gave 3.647). A shifted grid never plays the intended press, and its
    outermost points fall past the 2σ reach.
  - **The screen against exact play**, by distance to the pin (`--output`, skill 3,
    weighted by visits; the screen's score leaves out the shot's own stroke):

    | Yards | Screen − exact | Mean error | Best played − screen's first |
    |-------|----------------|------------|------------------------------|
    | 0-40 | +0.21 | 0.22 | 0.040 |
    | 40-80 | +0.05 | 0.06 | 0.004 |
    | 80-120 | −0.03 | 0.06 | 0.011 |
    | 120-160 | −0.12 | 0.13 | 0.023 |
    | 160-200 | −0.09 | 0.09 | 0.017 |

    The screen is pessimistic about short shots around the green, optimistic about
    approaches from 120 yards and more, and good from 40-120 yards. Around the green it
    proposed only woods from the fringe, which do chip well (speedrunners play them
    too, jdharms), but played exactly, short irons and wedges it never proposed beat
    them by 0.08 and 0.13 strokes at the U.K. 18th's and 4th's most visited fringe
    spots. The table's rests are over plain fairway; a chip that stops on the green
    rolls farther there, and backspin bites only on the green, for clubs 4 and up. So
    from spots within 40 pixels of the pin, the first pass now plays on the hole every
    intent whose fairway rest stops within 24 of the pin (`NEAR_PIN`): the U.K. 18th
    solved 0.038 lower and the 4th 0.007, for about twice the screening on the 18th.
    Playing only the straight ones on the hole kept 0.022 of the 18th's 0.038.
- **Loops the solver builds.** The US 12th would not settle: over 12 rounds the tee
  swung between 4.9 and 5.8, and one round took 20 minutes of value iteration. Spots
  first screened against their neighbours' borrowed values chose short hops onto one
  another, and once played, each spot's value was a stroke more than the next's: no
  finite answer, so value iteration climbed to its cap, 44 spots reached 24 strokes,
  and their neighbours borrowed from them. Such spots are rarely visited, so they were
  never screened again. Screening a spot again once its value moves, and not stopping
  while any is due, settled the 12th at 5.412 in 16 rounds, highest value 6.5. No
  U.K. or Japan hole had any such spot. Turned down on the way: escape shots round the
  whole circle (scored on the same stale values, they hop too), policy iteration (under
  PyPy a dense solve of 1,000 states takes 2-3 s, and filling the matrix is slow), and
  holding the borrowed values fixed within a round (no difference).
- **The three courses** at skill 3, pin 0, before the fringe screen and the loops were
  fixed, the default settings otherwise:

  | Course | Out | In | Round |
  |--------|-----|----|-------|
  | U.K. | 36.01 | 37.35 | 73.36 |
  | US | 35.89 | 38.28 | 74.17; 73.77 with the 12th's loops fixed |
  | Japan | 36.61 | 36.86 | 73.47 |

  By hole, U.K.: 4.22, 3.76, 5.05, 2.96, 4.30, 3.73, 4.27, 2.98, 4.75; 3.81, 4.99, 2.96,
  4.82, 4.19, 4.10, 4.89, 3.08, 4.53. US: 3.66, 4.46, 3.98, 2.85, 4.07, 4.06, 3.18, 5.44,
  4.19; 3.10, 4.24, 5.41, 4.02, 4.01, 4.35, 3.73, 3.88, 5.14. Japan: 4.07, 4.06, 4.87,
  2.99, 4.13, 2.87, 4.94, 4.13, 4.56; 3.77, 4.29, 4.64, 2.97, 4.26, 4.15, 3.14, 4.35,
  5.30. The three rounds come out within half a stroke of one another, where the
  expected order is Japan, US, U.K. (phase 4); holes differ far more than courses. The
  hardest against par: U.K. 11th (+0.99), US 8th and 16th (+0.44, +0.73), Japan 9th
  (+0.56).

Assumptions to revisit in phase 4:

- Errors reach 2 standard deviations (jdharms), so one intent at skill 1.0 is 5 × 5
  timings × 5 aims × 4 RNG states: 500 shots. The three are in the ratio 1 : 1 : 1 (frames,
  frames, aim steps).
- **About 7 errors a draw off the green** (`ERROR_POINTS` in `player.py`,
  `error_points` in the solver's settings). Past 7 whole units (skill above 1.5), every
  2nd, 3rd, ... unit stands for the units nearest it, which keeps the spread within a
  few percent and a shot's cost near 7 × 7 × 7 × 4 = 1,372 at any skill, where every
  unit would be 8,788 at skill 3 and 37,044 at skill 5. Measured at about ±0.01 strokes
  a hole at skills 3 and 4 (**The model's own approximations**). The green plays every
  unit.
- The physics RNG is 4 states, standing for all 65,534 (`rng_sample`; `rng_states` plays
  another number). A putt from the green is played from one of them: it reads the RNG
  only if it runs into sand or water. The landing table's perfect shots and racing use
  one state each (`$0001`, and `rng_sample(1)`); they only choose.
- **The green's table** plays aims within 48 steps of the pin line, and follows late
  presses 40 frames past the latest a player aims for; intents stay far enough inside
  the window for their aim errors. A putt starts from the pixel the last one stopped on,
  as every state does.
- **No trees in the behind-the-golfer view**: `outcomes()` has no scene to collide with
  until the scene builder is ported or cached (below). Overhead-view trees work.
- **The solver's approximations**: the 4-pixel cells (a cell's value is its first spot's),
  the screen and racing (only what they keep is played; every value is exact physics),
  the 5 accuracy targets, every other aim, and reach 0.001. Each is a setting of `Settings`
  or a constant in `solver.py` and `landing.py`, to vary in the sensitivity runs.

**Speed**, measured on the US 1st:

- `simulate` takes about 5 ms for a full shot under CPython (about 380 frames at 14 µs),
  under 1 ms for a putt. Under PyPy, warm, a full swing takes 0.15-0.25 ms and a putt
  0.6-1 ms (a putt across or off the green rolls a long way), with exactly the same
  outcomes. PyPy's JIT takes several seconds to warm up in each worker.
- **`Flights` cost more than they save in the solver**: at skill 3 real intents took
  2.3-3.4 ms a shot with `Flights` against 0.15-0.23 ms with plain `simulate`. Each
  timing and aim error is a flight of its own, shared only across the RNG states, and
  recording one costs more than playing it. So `Hole` plays with `simulate` unless given
  `Flights`.
- The machine is 12 cores with two threads each, so 16 workers share the cores: a
  worker's times run about twice the single-process ones.
- A spot's screen takes 0.5-0.9 s under PyPy on one process, about 3-5 s of worker time
  in the solver (shared cores, warm-up). With the default settings screening is about a
  third of the work; with the wide settings, every state screened every round, it is
  over half.
- **A U.K. hole** (the 1st, par 4, and the 13th, par 5) takes 450-710 s on 16 workers
  at skill 3 or 4, after its green's table. The main process peaks at 1.7-1.8 GB at
  skill 3 and 2.3-2.7 GB at skill 4 (800 against 1,000-1,100 states); the workers
  together at 4-8 GB resident, much of it shared. Free memory never fell below 8.8 GB
  of 15.6.
- The green's table is 200 s on 16 workers, once per hole and pin. Valuing the green
  takes 1-4 s a round in the main process.
- **Reading one element of a numpy array costs microseconds under PyPy** (it goes
  through cpyext). Value iteration read each borrowed value that way, hundreds of
  thousands a sweep, which made some rounds' iteration take minutes; the borrowed grids
  are now lists (`HoleSolver._borrowed`), about 5 times faster. Code in the main loop
  should keep scalars out of arrays.
- `Flight.finish` takes 0.11 ms for a shot that lands and rolls out on uniform
  terrain, 1-1.5 ms for one whose roll runs onto something else, and 2-3 ms for one that
  comes down over the green. Recording a flight costs about as much as `simulate`.

**Running under PyPy.** The project needs 3.12, so PyPy 3.11 gets its own environment
with the few packages the solver needs, and the repo on `PYTHONPATH`. The solver and
everything it imports is kept 3.11-clean (`tests/meta/test_pypy_ready.py`). A worker
peaks around 400 MB; 16 workers fit the 15 GB machine easily. The workers are spawned,
not forked: forked from a main process that had solved a few holes, each worker's
collector touched and so copied the parent's heap, and by the U.K. 4th 16 workers held
24 GB resident.

```bash
uv venv --python pypy@3.11 .cache/pypy
VIRTUAL_ENV=.cache/pypy uv pip install numpy py65 pillow
PYTHONPATH=. .cache/pypy/bin/python -u -m tools.research.difficulty nes_open_us.nes \
    --course us --hole 1 --workers 16 --output us01.json
```

**Next steps**, in order:

1. **Solve the three courses again** with the fringe screen and the loop fix: the
   table above predates both, and the calibration needs them.
2. **Trees in the behind-the-golfer view.** Every U.K. hole has tree tiles near its
   fairways (4 to 74 within about 30 yards). To measure what they cost: for each state
   the policy visits, capture the ROM's scene along the chosen aim (`RomGameShot`) and
   play the chosen intent with and without it (`ShotInFlight(..., scene=...)`).
3. **The approach screen from 120 yards out**, where it is 0.1 optimistic, and the
   search settings for the calibration (jdharms).
4. **Calibrate** (phase 4): bisect the skill for a U.K. round of 72, then predict the US
   and Japan courses. At skill 3 the U.K. round is 73.4; at skill 4 its 1st and 13th
   solve to 4.73 and 5.44, so 72 wants a skill a little under 3.
5. **The other three pins.**

Then:

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
