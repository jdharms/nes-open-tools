"""
A Python model of the game's ball physics: launch, flight, bounce and roll.

A port of bank 13's shot loop that reproduces the ROM frame for frame, checked
against the ROM's own code by `golf.physics.rom_oracle` (tests in `tests/physics/`). See
`docs/shot_physics.md` for how a shot works and what is not modelled yet.
"""

from golf.physics.shot import ShotResult, UnportedBehaviourError, simulate
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
    "PUTTER",
    "Ball",
    "Ground",
    "HoleGround",
    "Lie",
    "PhysicsTables",
    "ShotInput",
    "ShotResult",
    "Slope",
    "Spin",
    "Terrain",
    "TerrainTables",
    "UniformGround",
    "UnportedBehaviourError",
    "simulate",
]
