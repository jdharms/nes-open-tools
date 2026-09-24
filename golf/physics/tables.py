"""
The constant tables the shot physics reads, loaded from a ROM.

Reading them from the ROM rather than copying them here keeps the model honest
for patched ROMs too: a patch that retunes a club's distance changes the model's
answer the same way it changes the game's.

Every address is in bank 13 unless it says fixed bank. Names follow the label
file where it has one.
"""

from dataclasses import dataclass
from typing import Self

from golf.core.rom_reader import RomReader

PHYSICS_BANK = 13

#: `TrigLookupTable` (fixed $E7CB) is 128 bytes: sin over a half turn, scaled
#: to 255. `LE7C3` looks up cos(a) as table[a + $40] without masking, so a
#: caller passing a >= $40 reads past the end into the code that follows. The
#: wind routine does exactly that for half the compass, so the model loads 256
#: bytes to read the same code bytes the game does.
TRIG_TABLE = 0xE7CB
TRIG_TABLE_READ_LENGTH = 0x100


@dataclass(frozen=True)
class PhysicsTables:
    trig: bytes
    """`TrigLookupTable`; entries 128+ are code bytes, see `TRIG_TABLE`."""
    club_loft: bytes
    """`ClubLoftIndexTable` $B8B1: launch angle per club, in 1/256 turns."""
    penalty_to_first_bounce: bytes
    """`PenaltyMultiplierTable` $B8C1: `PenaltyAccumulator` to a first-bounce friction."""
    club_distance: bytes
    """`ClubDistanceBaseTable` $B8CD: power multiplier per club (not the putter)."""
    putter_distance: bytes
    """`PutterDistanceBySpeedTable` $B8DC: putter multiplier on the green, per swing speed."""
    putter_distance_off_green: bytes
    """`PutterDistAltTable` $B8E1: putter multiplier anywhere else."""
    rough_penalty_wood: bytes
    """`RoughPenaltyWood` $B8E6, by `RoughDepth`."""
    rough_penalty_iron: bytes
    """`RoughPenaltyIrons` $B8E8, by `RoughDepth`."""
    rough_variance: bytes
    """`RoughVariance` $B8EA, by `RoughDepth`."""
    swing_speed_power: bytes
    """`SwingSpeedMult` $B8EC, by `SwingSpeed`."""
    bunker_penalty_wood: bytes
    """`BunkerPenaltyWood` $B8EF, by `BunkerDepth`."""
    bunker_penalty_iron: bytes
    """`BunkerPenaltyIron` $B8F2, by `BunkerDepth`."""
    bunker_variance: bytes
    """`BunkerVariance` $B8F5, by `BunkerDepth`; woods read one entry further on."""
    club_forgiveness: bytes
    """`ClubAimForgivenessTable` $B8F9: accuracy-meter error each club ignores."""
    timing_power: bytes
    """`TimingPowerCurve` $B909, indexed by $38 minus the power-meter stop."""
    club_hi_lo: bytes
    """$ACFA: how far Up/Down moves each club's loft index."""
    landing_kick: bytes
    """$B9A1: sideways kick strength on first contact, by landing lie and launch depth."""
    bunker_plug_first: bytes
    """$B33C: RNG thresholds for a landing bunker depth of at least 1, by impact speed."""
    bunker_plug_second: bytes
    """$B33F: the same for a depth of 2."""

    @classmethod
    def from_rom(cls, rom: RomReader) -> Self:
        def bank(addr: int, length: int) -> bytes:
            return rom.read_switched(addr, PHYSICS_BANK, length)

        return cls(
            trig=rom.read_fixed(TRIG_TABLE, TRIG_TABLE_READ_LENGTH),
            club_loft=bank(0xB8B1, 16),
            penalty_to_first_bounce=bank(0xB8C1, 12),
            club_distance=bank(0xB8CD, 15),
            putter_distance=bank(0xB8DC, 3),
            putter_distance_off_green=bank(0xB8E1, 3),
            rough_penalty_wood=bank(0xB8E6, 2),
            rough_penalty_iron=bank(0xB8E8, 2),
            rough_variance=bank(0xB8EA, 2),
            swing_speed_power=bank(0xB8EC, 3),
            bunker_penalty_wood=bank(0xB8EF, 3),
            bunker_penalty_iron=bank(0xB8F2, 3),
            bunker_variance=bank(0xB8F5, 4),
            club_forgiveness=bank(0xB8F9, 16),
            timing_power=bank(0xB909, 0x39),
            club_hi_lo=bank(0xACFA, 16),
            landing_kick=bank(0xB9A1, 6),
            bunker_plug_first=bank(0xB33C, 3),
            bunker_plug_second=bank(0xB33F, 3),
        )

    def sin(self, angle: int) -> int:
        """|sin| over a half turn: `TrigLookupTable[angle & $7F]`."""
        return self.trig[angle & 0x7F]

    def cos_unmasked(self, angle: int) -> int:
        """`LE7C3`: table[angle + $40], reading past the table when angle >= $40."""
        return self.trig[(angle + 0x40) & 0xFF]
