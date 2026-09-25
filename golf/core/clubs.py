"""
The game's clubs, by the ids the choose-clubs screen and the physics use.

Kept apart from the patches that write a bag (`golf.core.patches.sram_defaults`,
which re-exports these) so the difficulty solver can name clubs without
importing the patch machinery.
"""

from enum import IntEnum


class Club(IntEnum):
    """Club ids, in the choose-clubs screen's order."""

    W1 = 0x00
    W2 = 0x01
    W3 = 0x02
    W4 = 0x03
    I1 = 0x04
    I2 = 0x05
    I3 = 0x06
    I4 = 0x07
    I5 = 0x08
    I6 = 0x09
    I7 = 0x0A
    I8 = 0x0B
    I9 = 0x0C
    PW = 0x0D
    SW = 0x0E
    PT = 0x0F

    @property
    def label(self) -> str:
        """The name `parse_club` reads: 1W-4W, 1I-9I, PW, SW or PT."""
        if self.name[0] in "WI":
            return self.name[1] + self.name[0]
        return self.name


VANILLA_CLUBS = tuple(club for club in Club if club not in (Club.W4, Club.I1))


def parse_club(label: str) -> Club:
    """A club from its label, case-insensitive. Raises ValueError for anything else."""
    clubs = {club.label: club for club in Club}
    try:
        return clubs[label.strip().upper()]
    except KeyError:
        raise ValueError(
            f"unknown club {label!r}; clubs are {', '.join(clubs)}"
        ) from None
