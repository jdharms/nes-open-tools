+++
status = "accepted"
date = 2026-10-02
area = "rom"
permanent = false
revisit_when = "Course-wide difficulty maps need more shots per second than the exact model gives, or a patch changes bank 13's physics code rather than its tables"
drafted_by = "Claude"
supersedes = []
+++

# The shot physics model reproduces the ROM exactly, checked against its own code

## Context

The goal is a "digital twin" of the game's ball physics in Python. It should answer
questions like how far each club carries, and eventually drive strokes-to-hole difficulty
maps of real holes: many simulated shots from every point on a hole, as in
[Matthew Schoolfield's course-strategy simulator](https://golfcoursewiki.substack.com/p/i-spent-the-last-month-and-a-half).
The model has to be readable, and it has to be trustworthy: a map drawn with the wrong
physics is worse than no map.

The game's physics is integer arithmetic on multi-byte registers. Much of what it does
comes from byte-level detail, not from any physical law. Examples: a term taken from a
velocity's middle byte, an 8-bit add whose carry is lost, a cos lookup that reads past the
end of its table for six wind directions. py65 is already a dependency and runs bank 13's
shot loop in about 0.2 s per shot.

## Decision

`golf/physics/` is a literal port of bank 13's shot loop. It uses the game's registers, at
their natural widths and in the game's units, and it reproduces every byte-level quirk,
with named helpers and docstrings to keep that readable. It reads its tables from the ROM
it is given. `golf/physics/rom_oracle.py` runs the ROM's own `CalcLaunchVector` under
py65, and `tests/physics/test_shot_rom.py` requires the two to agree on every
register after every frame, for hundreds of randomized shots.

## Rejected alternatives

- **An idealized float model** (gravity, drag, lift and friction as continuous physics,
  fitted to the game). It would be simpler to read and easy to vectorize. But it could not
  reproduce the quirks (the distorted wind directions, the RNG coin flip on first contact,
  plugged bunker lies), and there would be no exact test of it, only "close enough".
- **Using the py65 run as the model.** Exact by construction, but about 100 times slower
  (0.2 s against 2 ms a shot), and it explains nothing.
- **Committing the physics tables to `data/`.** Reading them from the ROM costs nothing
  and makes the model follow any patch that retunes a table, as the randomizer's patches
  may.
- **Golden values recorded from the model itself.** That would only show that the model
  hasn't changed, not that it matches the game.

## Consequences

- Any disagreement with the ROM's code is a test failure with the frame and register
  named. Planting deliberate bugs in the model showed the test catches every change to
  reachable behavior.
- The model runs about 2 ms a shot on one core. A difficulty map with around 10,000
  points and 100 shots each is about half an hour per hole, so maps may need parallelism,
  or a vectorized second implementation checked against this one.
- A patch that rewrites bank 13's physics code (e.g. `green_slope_physics`) is not
  reflected until the model ports the change too. The oracle runs any ROM, so it shows the
  difference immediately.
- The model matches the ROM's code, not yet the running game. Nothing in the test covers
  code outside the shot loop that might touch these registers mid-shot. An emulator check
  is listed in `docs/shot_physics.md`.

## Sources

- `docs/shot_physics.md`: how a shot works, and what is not modeled yet.
- `golf/physics/`, `tests/physics/test_shot_rom.py`.
- Session of 2026-09-24 (session_01WUdmVYMPc81NbQ2YyroK9x).
