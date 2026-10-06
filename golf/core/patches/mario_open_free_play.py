"""Mario Open: unlock all courses and remove the running-score dismissal.

The disabled dismissal handler supplies space for the entry hook; these changes
must be applied together. See docs/mario_open_free_play.md for the ROM evidence.
"""

from golf.core.asm6502 import assemble

from .byte_patch import BytePatch
from .composite import CompositePatch


def mario_open_free_play_patch() -> CompositePatch[BytePatch]:
    """Force SRAM progression to 5 before the menu, and bypass dismissal."""
    return CompositePatch(
        name="mario_open_free_play",
        description="Mario Open (JP): all six courses, no score-limit dismissal",
        patches=[
            BytePatch(
                name="jp_unlock_entry",
                description="Run the unlock hook before entering the title/menu",
                prg_offset=0x34000,
                original=bytes.fromhex("A9 00 85 98"),
                patched=assemble("jsr $847E\nnop", origin=0x8000).code,
            ),
            BytePatch(
                name="jp_unlock_hook",
                description="Reuse the disabled dismissal entry to set progression",
                prg_offset=0x3447E,
                original=bytes.fromhex("20 41 D8 A9 80 85 F4 A9 00 85"),
                patched=assemble(
                    "lda #$05\nsta $6003\nlda #$00\nsta $98\nrts",
                    origin=0x847E,
                ).code,
            ),
            BytePatch(
                name="jp_disable_dismissal",
                description="Continue shot setup even when the score exceeds the limit",
                prg_offset=0x34294,
                original=bytes.fromhex("4C 7E 84"),
                patched=assemble("jmp $8297", origin=0x8294).code,
            ),
        ],
    )
