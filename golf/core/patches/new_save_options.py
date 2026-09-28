"""
New-save options: start a new save with chosen BGM, swing speed, putt speed and
ball spin defaults.

These are the four settings on the club house's OPTIONS screen, kept in SRAM:

| SRAM | Label | Values |
|---|---|---|
| $6F98 | `BGMOnFlag` | $FF on, $00 off |
| $6F99 | `SwingSpeedDefault` | $FF off, $00 slow, $01 medium, $02 fast |
| $6F9A | `PuttSwingSpeedDefault` | as swing speed |
| $6F9B | `BallSpinDefault` | $FF off, $00 TOP 2, $01 TOP 1, $02 normal, $03 BACK 1, $04 BACK 2 |

`StartCourseBgm` ($DA05) skips the course music when `BGMOnFlag` is $00.
`ShotSetupSequence` (bank 13 $8793-$87A8) copies each of the other three over
the current player's setting at the start of every shot unless it is negative:
`PlayerSwingSpeed`, `PlayerPuttSwingSpeed` and `PlayerBallSpin`. So a default
resets its setting on every shot, and off ($FF) leaves it as the player last
chose it. TOP 1 and TOP 2 play as normal spin (docs/topspin.md), but the
OPTIONS screen offers them, through `OptionsSpinValueTable` (bank 11 $8FEF).

The OPTIONS screen (`RunOptionsScreen`, bank 11 $8B1B) edits all four in SRAM,
so the ROM only decides where a new save starts; a player can still change them
in the game.

`InitializeSram` (bank 9) fills $6F98-$6FAF with $FF on a new save, in a
ten-byte loop at $AD46 that the magic writes at $AD50 follow directly. A byte
edit can turn the loop's `BPL` into `BNE` to leave `BGMOnFlag` at $00 from the
earlier zero fill (`sram_defaults`' `bgm` parameter), but cannot produce any
other value. So this patch replaces the loop with a `JMP` to `NewSaveOptions`,
which does the same $FF fill, copies `NewSaveOptionTable` over $6F98-$6F9B and
jumps back to $AD50.

Two patches, one per build stage:

- `NEW_SAVE_OPTIONS_PATCH` installs the routine with the table holding the
  vanilla values, $FF $FF $FF $FF. The unfinished randomizer build applies it.
- `new_save_option_values_patch` writes the four values into the table,
  expecting the vanilla ones. The finisher applies it (finish ABI 2).

The routine sits in bank 9 at $B519, the start of the club house's PLAYER STATS
screen (`RunPlayerStatsScreen`), which `menu_trim` removes from the club house.
Every static reference into that screen's code, $B519-$BF89, comes from inside
it, so the patch requires `menu_trim`. The `wram_expansion` stubs in the same
screen ($BA92-$BBA9) are well clear of it.
"""

from enum import IntEnum

from golf.core import rom_utils
from golf.core.asm6502 import Program, assemble

from .byte_patch import BytePatch
from .composite import CompositePatch
from .menu_trim import PLAYER_STATS_REMOVED

BANK = 9

SPLICE_ADDR = 0xAD46
#: `InitializeSram`'s $FF fill: LDX #$17 / LDA #$FF / STA $6F98,X / DEX / BPL
SPLICE_ORIGINAL = bytes([0xA2, 0x17, 0xA9, 0xFF, 0x9D, 0x98, 0x6F, 0xCA, 0x10, 0xF8])
#: where `InitializeSram` continues after the fill: the magic writes
RESUME_ADDR = 0xAD50

ROUTINE_ADDR = 0xB519
#: The vanilla bytes the routine replaces, the start of `RunPlayerStatsScreen`
ROUTINE_ORIGINAL = bytes.fromhex(
    "20c3bd2032b5a5704a9006200bb64c1cb5a9018dff074c3cd820c8b5"
)

OPTIONS_SRAM = 0x6F98
#: $6F98-$6FAF, what `InitializeSram` fills with $FF
FILL_LENGTH = 0x18

BGM_ON = 0xFF
BGM_OFF = 0x00


class SwingSpeed(IntEnum):
    """`SwingSpeedDefault` and `PuttSwingSpeedDefault` values."""

    OFF = 0xFF
    SLOW = 0x00
    MEDIUM = 0x01
    FAST = 0x02


class BallSpin(IntEnum):
    """`BallSpinDefault` values. TOP 1 and TOP 2 play as NORMAL."""

    OFF = 0xFF
    TOP2 = 0x00
    TOP1 = 0x01
    NORMAL = 0x02
    BACK1 = 0x03
    BACK2 = 0x04


#: What a new save holds in vanilla, in table order: BGM, swing, putt, spin
VANILLA_VALUES = bytes([BGM_ON, SwingSpeed.OFF, SwingSpeed.OFF, BallSpin.OFF])


def _prg(cpu_addr: int) -> int:
    return rom_utils.cpu_to_prg_switched(cpu_addr, BANK)


def _program() -> Program:
    source = """
        NewSaveOptions:
            ldx #FILL_LENGTH - 1
            lda #$FF
        @fill:
            sta OPTIONS_SRAM,x
            dex
            bpl @fill
            ldx #OPTION_COUNT - 1
        @copy:
            lda NewSaveOptionTable,x
            sta OPTIONS_SRAM,x
            dex
            bpl @copy
            jmp RESUME_ADDR
        NewSaveOptionTable:
            .byte $FF, $FF, $FF, $FF
    """
    program = assemble(
        source,
        ROUTINE_ADDR,
        {
            "FILL_LENGTH": FILL_LENGTH,
            "OPTIONS_SRAM": OPTIONS_SRAM,
            "OPTION_COUNT": len(VANILLA_VALUES),
            "RESUME_ADDR": RESUME_ADDR,
        },
    )
    assert program.size <= len(ROUTINE_ORIGINAL)
    return program


_PROGRAM = _program()
#: the table the finisher fills: BGM, swing, putt, spin
TABLE_ADDR = _PROGRAM.symbol("NewSaveOptionTable")
TABLE_OFFSET = _prg(TABLE_ADDR)


NEW_SAVE_OPTIONS_PATCH = CompositePatch(
    name="new_save_options",
    description=(
        "Start a new save's BGM, swing, putt and spin defaults from a table, "
        "filled with the vanilla values"
    ),
    patches=[
        BytePatch(
            name="new_save_options_routine",
            description=(
                f"NewSaveOptions and its table at bank {BANK} ${ROUTINE_ADDR:04X}, "
                "over the unreachable PLAYER STATS screen"
            ),
            prg_offset=_prg(ROUTINE_ADDR),
            original=ROUTINE_ORIGINAL[: _PROGRAM.size],
            patched=_PROGRAM.code,
        ),
        BytePatch(
            name="new_save_options_splice",
            description=(
                f"InitializeSram's $FF fill at ${SPLICE_ADDR:04X} jumps to "
                "NewSaveOptions"
            ),
            prg_offset=_prg(SPLICE_ADDR),
            original=SPLICE_ORIGINAL,
            # the rest of the loop is unreachable; NOPs keep the length, and
            # make sram_defaults' bgm edit at $AD4E refuse to apply
            patched=bytes([0x4C, ROUTINE_ADDR & 0xFF, ROUTINE_ADDR >> 8])
            + bytes([0xEA] * (len(SPLICE_ORIGINAL) - 3)),
        ),
    ],
    requires=[PLAYER_STATS_REMOVED],
)


def option_values(
    bgm: bool = True,
    swing: SwingSpeed = SwingSpeed.OFF,
    putt: SwingSpeed = SwingSpeed.OFF,
    spin: BallSpin = BallSpin.OFF,
) -> bytes:
    """The table's four bytes. Raises ValueError for a value the game does not use."""
    if not isinstance(bgm, bool):
        raise ValueError(f"bgm must be true or false, got {bgm!r}")
    return bytes(
        [
            BGM_ON if bgm else BGM_OFF,
            SwingSpeed(swing),
            SwingSpeed(putt),
            BallSpin(spin),
        ]
    )


def new_save_option_values_patch(
    bgm: bool = True,
    swing: SwingSpeed = SwingSpeed.OFF,
    putt: SwingSpeed = SwingSpeed.OFF,
    spin: BallSpin = BallSpin.OFF,
) -> CompositePatch[BytePatch]:
    """Fill `NewSaveOptionTable`, which `NEW_SAVE_OPTIONS_PATCH` installs."""
    values = option_values(bgm, swing, putt, spin)
    description = (
        f"Start a new save with BGM {'on' if bgm else 'off'}, swing "
        f"{SwingSpeed(swing).name.lower()}, putt {SwingSpeed(putt).name.lower()}, "
        f"spin {BallSpin(spin).name.lower()}"
    )
    return CompositePatch(
        name="new_save_option_values",
        description=description,
        patches=[
            BytePatch(
                name="new_save_option_values_table",
                description=description,
                prg_offset=TABLE_OFFSET,
                original=VANILLA_VALUES,
                patched=values,
            )
        ],
        requires=[NEW_SAVE_OPTIONS_PATCH],
    )
