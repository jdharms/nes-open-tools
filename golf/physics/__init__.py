"""
A Python model of the game's ball physics: launch, flight, bounce and roll.

A port of bank 13's shot loop that reproduces the ROM frame for frame, checked
against the ROM's own code by `golf.physics.rom_oracle` (tests in `tests/physics/`). See
`docs/shot_physics.md` for how a shot works and what is not modeled yet.
"""

from golf.physics import meter, wind
from golf.physics.rules import NextShot, play_on
from golf.physics.shot import Flag, ShotResult, simulate
from golf.physics.state import (
    FLAT,
    PUTTER,
    Ball,
    Ground,
    Lie,
    ShotInput,
    Slope,
    Spin,
    Terrain,
    UniformGround,
)
from golf.physics.tables import PhysicsTables
from golf.physics.terrain import HoleGround, TerrainTables

__all__ = [
    "FLAT",
    "Flag",
    "PUTTER",
    "Ball",
    "Ground",
    "HoleGround",
    "Lie",
    "NextShot",
    "PhysicsTables",
    "ShotInput",
    "ShotResult",
    "Slope",
    "Spin",
    "Terrain",
    "TerrainTables",
    "UniformGround",
    "meter",
    "play_on",
    "simulate",
    "wind",
]
