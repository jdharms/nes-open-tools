# golf/physics

A Python model of the game's ball physics, ported from bank 13 and the fixed bank so that
it matches the ROM register for register, frame for frame. `docs/shot_physics.md` explains
how a shot works; `docs/planning/hole_difficulty.md` is what the model is for and what
comes next; ADR 0007 is why it is an exact port.

## Tests

The model's checks against the ROM live in `tests/physics/`. The default `pytest` run
leaves them out because they are slow (every pixel of every hole, hundreds of shots through
an emulated 6502). **Run them whenever you change anything in `golf/physics/`**, and only
then:

```bash
uv run pytest --physics tests/physics
```

## The references

- `rom_oracle.py`: one routine at a time. `RomShot` runs `CalcLaunchVector` alone;
  `RomTerrainProbe` runs `ClassifyProbePosition` over a hole poked into RAM.
- `nes.py` and `rom_game.py`: the whole game. `NesMachine` emulates MMC1 banking, the
  controller and vblank (running the game's NMI handler), and `RomGameShot` plays a shot
  through the game's own `InitHole` and `ShotSetupSequence` by pressing buttons. Prefer
  this for anything that happens between frames of the physics; a routine-level oracle
  misses code that runs elsewhere in the frame.

## Rules for new code here

- **Check it against the ROM before building on it.** Every ported routine gets an oracle
  in `rom_oracle.py`, which runs the ROM's own code under py65 with the same inputs, and a
  test in `tests/physics/` that compares the results exactly, not approximately. Plant a
  few deliberate bugs to make sure the test can fail.
- **Keep the game's units and widths.** Registers stay ints at their real width, in the
  game's fixed point. Convert to pixels or yards only at the edges (`ShotResult`,
  `golf-shots`).
- **Port the quirks.** An 8-bit wrap, a lost carry or an out-of-bounds table read is part
  of the game. Keep it, and say in the docstring why the code looks odd.
- **Read tables from the ROM** you are given, not from copies in `data/` or the code.
