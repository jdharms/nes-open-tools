"""Mario Open: unlock all courses and remove the running-score dismissal.

A patch for the JP ROM; every address here is a JP address. The unlock routine is
written over the start of the dismissal handler, which is only safe once the jump to
that handler is gone, so the three changes must be applied together. See
docs/mario_open_free_play.md.
"""

from golf.core import rom_utils
from golf.core.asm6502 import assemble

from .byte_patch import BytePatch
from .composite import CompositePatch

ROUND_BANK = 13

#: where the reset code enters bank 13
ENTRY_ADDR = 0x8000
#: the jump the next-shot score check takes once the score reaches the limit
DISMISSAL_JUMP_ADDR = 0x8294
#: where the score check goes when the score is under the limit
CONTINUE_SHOT_ADDR = 0x8297
#: the dismissal handler; the jump at DISMISSAL_JUMP_ADDR is its only static reference
DISMISSAL_HANDLER_ADDR = 0x847E

#: SRAM: how many courses past the first have been unlocked, 0-5
PROGRESSION_ADDR = 0x6003
ALL_COURSES = 5


def _splice(
    name: str, description: str, addr: int, original: str, source: str
) -> BytePatch:
    return BytePatch(
        name=name,
        description=description,
        prg_offset=rom_utils.cpu_to_prg_switched(addr, ROUND_BANK),
        original=bytes.fromhex(original),
        patched=assemble(source, origin=addr).code,
    )


def mario_open_free_play_patch() -> CompositePatch[BytePatch]:
    """Force SRAM progression to 5 before the menu, and bypass dismissal."""
    return CompositePatch(
        name="mario_open_free_play",
        description="Mario Open (JP): all six courses, no score-limit dismissal",
        patches=[
            _splice(
                "jp_disable_dismissal",
                "Continue shot setup even when the score reaches the limit",
                DISMISSAL_JUMP_ADDR,
                "4C 7E 84",
                f"jmp ${CONTINUE_SHOT_ADDR:04X}",
            ),
            _splice(
                "jp_unlock_routine",
                "Set progression, in the space of the dismissal handler",
                DISMISSAL_HANDLER_ADDR,
                "20 41 D8 A9 80 85 F4 A9 00 85",
                f"""
                lda #{ALL_COURSES}
                sta ${PROGRESSION_ADDR:04X}
                lda #$00            ; the two instructions the entry call replaced
                sta $98
                rts
                """,
            ),
            _splice(
                "jp_unlock_entry",
                "Call the unlock routine on entering bank 13",
                ENTRY_ADDR,
                "A9 00 85 98",
                f"jsr ${DISMISSAL_HANDLER_ADDR:04X}\nnop",
            ),
        ],
    )
