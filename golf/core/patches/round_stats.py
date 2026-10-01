"""
Round stats patch: count fairways hit and penalty strokes during play.

The game keeps neither. This patch keeps both, per player, for the scorecard QR
payload (protocol version 2, `docs/scorecard_qr.md`), which copies them into
bytes 32-34. They are kept in exactly that wire order, three bytes per player at
`layout.ROUND_STATS`:

    fairway bits for holes 1-18, least significant bit first, by GameProgress
    penalty strokes in bits 2-7 of the third byte, held at 63

**A fairway is hit** when, at the end of a shot, the player has taken exactly one
stroke on a par 4 or longer and the ball lies on the fairway or the green. A
whiff counts its stroke without moving the ball, so the next shot is stroke 2
and the hole can no longer be hit. A tee shot into water or out of bounds is a
miss: the hook runs before the penalty and the drop. A tee shot that holes out
takes the hole-complete path and never reaches the hook; the server counts that
one from the stroke count.

**A penalty stroke** is one the game adds itself, for water (`$8641`) or out of
bounds (`$866F`): the two `JSR IncrementStrokeCount` sites in
`LD_8601_AnnounceBallLie`. Each goes through a trampoline that counts a penalty
only when the stroke count actually went up, so the game's own guards (the CPU
flag in `$D5`, `MaybeForceStrokeCountMask`, the 50-stroke cap) apply unchanged.

Both are counted only in 18-hole stroke play (`GolfGameMode` 0), and never in
training or a replay.

Save and continue
-----------------

The game saves the round after every shot (`LDA17` -> `LD94C` -> bank 9 `$AE31`)
and a CONTINUE restores it at round setup (`$80FC` -> `LD95B` -> bank 9
`$AEEC`). Counters held only in RAM would be lost on a continue, and counters
written straight to battery RAM would drift whenever a shot is replayed after a
power cut. So both far calls are repointed at wrappers that run the vanilla
routine and then copy the six live bytes to, or from, a snapshot for the save
slot. Only stroke play on course 1 is snapshotted: save slots 0 (one player) and
1 (two players), the only ones a `menu_trim`med ROM can reach.

The live bytes and both snapshots fill `$6C0E`-`$6C1F` exactly, the one gap in
the vanilla save layout (`layout.ROUND_STATS`).

Writes
------

    bank 2  $A400       the routines (unverified: vacated UK course data, like
                        scorecard_qr's image)
    fixed   $DCC7       two trampolines, in dead greens pointer slots 23-
    bank 13 $80CE       round setup: two stores -> far call that also zeroes
    bank 13 $832C       post-shot JMP $85E9 -> fairway trampoline
    bank 13 $8642       water JSR IncrementStrokeCount -> penalty trampoline
    bank 13 $8670       out-of-bounds JSR IncrementStrokeCount -> the same
    fixed   $D94F       the save far call's target -> save wrapper
    fixed   $D95E       the load far call's target -> load wrapper

The trampolines sit in greens pointer slots that only exist for course 3, so the
patch requires `COURSE_MIRRORS_PATCH`, as `scorecard_qr` does for its own.
"""

from golf.core import rom_utils
from golf.core.asm6502 import Program, assemble
from golf.qr.port import layout

from .base import PatchError, ROMPatch
from .byte_patch import BytePatch
from .composite import CompositePatch
from .multi_bank import COURSE_MIRRORS_PATCH

CODE_BANK = 2
HOOK_BANK = 13

#: The routines, in bank 2's reclaimed region after the scorecard QR image.
CODE_ORIGIN = 0xA400

#: Right after scorecard_qr's ten-byte trampoline at `$DCBD`.
TRAMPOLINE_ORIGIN = 0xDCC7
TRAMPOLINE_LIMIT = rom_utils.TABLE_PAR

#: The vanilla UK greens pointers (slots 23-53) the trampolines may cover.
TRAMPOLINE_VANILLA = bytes.fromhex(
    "6A913D92D792B39377941095BA956E961F97D89774983D99F899999A509B3D9C"
    "F39C999D379E009FA89F35A0D9A076A128A2CCA295A365A41FA5D5A5C0A6"
)

PRG_BANK_SIZE = 0x4000

#: Game addresses the routines use.
SYMBOLS = {
    "CurrentPlayerIndex": 0x99,
    "GameProgress": layout.GAME_PROGRESS,
    "BallLie": 0xC9,
    "GolfGameMode": layout.GOLF_GAME_MODE,
    "Par": 0x0109,
    "CurrentHoleStrokes": 0x011F,
    "ManualWindModeFlag": 0x04F6,
    "ReplayPlaybackFlag": 0x04F7,
    "PlayerSavedHoleNumber": 0x04FD,
    "RoundStats": layout.ROUND_STATS,
    "RoundStatsSnapshots": layout.ROUND_STATS_SNAPSHOTS,
    "RoundStatsLiveLen": layout.ROUND_STATS_LIVE_LEN,
    "RoundStatsSnapshotSlots": layout.ROUND_STATS_SNAPSHOT_SLOTS,
    "HoleCount": 18,
    "BallLieGreen": 6,
    "ExecuteFarCall": 0xD372,
    "SaveSlotIndex": 0xD962,  # LD962: X = the save slot for this mode and course
    "SaveGameBank": 0x09,
    "SaveGameState": 0xAE31,
    "LoadGameState": 0xAEEC,
    "IncrementStrokeCount": 0x868C,
    "PostShotLie": 0x85E9,  # LD_85E9
}

CODE_SOURCE = """
; Carry set when this shot should not count: anything but 18-hole stroke play,
; training (manual wind) or a replay.
RsSkip:
        lda GolfGameMode
        bne @skip
        bit ManualWindModeFlag
        bmi @skip
        bit ReplayPlaybackFlag
        bmi @skip
        clc
        rts
@skip:
        sec
        rts

; After every shot that did not hole out, from the fairway trampoline.
RsCheckFairway:
        jsr RsSkip
        bcs @done
        lda Par
        cmp #4
        bcc @done
        ldx CurrentPlayerIndex
        lda CurrentHoleStrokes,x
        cmp #1
        bne @done
        lda BallLie
        beq @hit
        cmp #BallLieGreen
        bne @done
@hit:
        lda GameProgress
        cmp #HoleCount
        bcs @done
        lsr a                           ; byte GameProgress / 8 of this player's
        lsr a
        lsr a
        clc
        adc RsPlayerOffset,x
        tay
        lda GameProgress                ; bit GameProgress % 8
        and #$07
        tax
        lda RsBit,x
        ora RoundStats,y
        sta RoundStats,y
@done:
        rts

; After the game added a water or out-of-bounds stroke, from the penalty
; trampoline. Penalties are the top six bits of the player's third byte.
RsAddPenalty:
        jsr RsSkip
        bcs @done
        ldx CurrentPlayerIndex
        ldy RsPlayerOffset,x
        lda RoundStats + 2,y
        cmp #$FC                        ; 63 already
        bcs @done
        adc #$04                        ; carry is clear
        sta RoundStats + 2,y
@done:
        rts

; Round setup, in place of the two stores it replaced. A is $FF.
RsResetRound:
        sta PlayerSavedHoleNumber
        sta PlayerSavedHoleNumber + 1
        lda #0
        ldx #RoundStatsLiveLen - 1
@zero:
        sta RoundStats,x
        dex
        bpl @zero
        rts

; The game's save, then a snapshot of the live bytes for the save slot.
RsSaveGame:
        jsr ExecuteFarCall
        .byte SaveGameBank, <SaveGameState, >SaveGameState
        jsr SaveSlotIndex
        cpx #RoundStatsSnapshotSlots
        bcs @done
        ldy RsSnapshotOffset,x
        ldx #0
@copy:
        lda RoundStats,x
        sta RoundStatsSnapshots,y
        iny
        inx
        cpx #RoundStatsLiveLen
        bne @copy
@done:
        rts

; The game's load, then the live bytes back from the save slot's snapshot.
RsLoadGame:
        jsr ExecuteFarCall
        .byte SaveGameBank, <LoadGameState, >LoadGameState
        jsr SaveSlotIndex
        cpx #RoundStatsSnapshotSlots
        bcs @done
        ldy RsSnapshotOffset,x
        ldx #0
@copy:
        lda RoundStatsSnapshots,y
        sta RoundStats,x
        iny
        inx
        cpx #RoundStatsLiveLen
        bne @copy
@done:
        rts

RsPlayerOffset:
        .byte 0, 3
RsSnapshotOffset:
        .byte 0, 6
RsBit:
        .byte $01, $02, $04, $08, $10, $20, $40, $80
"""

TRAMPOLINE_SOURCE = """
; In place of the post-shot JMP $85E9.
RsFairwayHook:
        jsr ExecuteFarCall
        .byte CodeBank, <RsCheckFairway, >RsCheckFairway
        jmp PostShotLie

; In place of the water and out-of-bounds JSR IncrementStrokeCount. Bank 13 is
; still paged in: both callers are there.
RsPenaltyStroke:
        ldx CurrentPlayerIndex
        lda CurrentHoleStrokes,x
        pha
        jsr IncrementStrokeCount
        ldx CurrentPlayerIndex
        pla
        cmp CurrentHoleStrokes,x
        beq @done
        jsr ExecuteFarCall
        .byte CodeBank, <RsAddPenalty, >RsAddPenalty
@done:
        rts
"""


def _prg_offset(cpu_addr: int, bank: int) -> int:
    return bank * PRG_BANK_SIZE + (cpu_addr - 0x8000)


def build_code() -> Program:
    """The bank 2 routines."""
    return assemble(CODE_SOURCE, CODE_ORIGIN, SYMBOLS)


def build_trampolines(code: Program) -> Program:
    """The fixed-bank trampolines, far-calling into `code`."""
    symbols = {
        **SYMBOLS,
        "CodeBank": CODE_BANK,
        "RsCheckFairway": code.symbol("RsCheckFairway"),
        "RsAddPenalty": code.symbol("RsAddPenalty"),
    }
    return assemble(TRAMPOLINE_SOURCE, TRAMPOLINE_ORIGIN, symbols)


class _CodeImage(ROMPatch):
    """
    The routines in bank 2. Like scorecard_qr's image, the bytes they cover are
    vacated course 3 terrain and are not compared before writing.
    """

    name = "round_stats_code"
    description = f"Round stats routines in bank {CODE_BANK} at ${CODE_ORIGIN:04X}"

    def __init__(self, code: Program) -> None:
        self.code = code.code
        self.offset = _prg_offset(CODE_ORIGIN, CODE_BANK)
        end = CODE_ORIGIN + len(self.code) - 1
        if end > layout.REGION_END:
            raise PatchError(
                f"the round stats routines end at ${end:04X}, past the reclaimed "
                f"region's ${layout.REGION_END:04X}"
            )

    def can_apply(self, rom_writer) -> bool:
        return True

    def is_applied(self, rom_writer) -> bool:
        return rom_writer.read_prg(self.offset, len(self.code)) == self.code

    def apply(self, rom_writer) -> None:
        rom_writer.write_prg(self.offset, self.code)


def _jsr_far(target: int) -> bytes:
    return bytes([0x20, 0x72, 0xD3, CODE_BANK, target & 0xFF, target >> 8])


def _word(value: int) -> bytes:
    return bytes([value & 0xFF, value >> 8])


def round_stats_patch() -> CompositePatch[ROMPatch]:
    """The routines and trampolines first, then the splices that reach them."""
    code = build_code()
    trampolines = build_trampolines(code)
    if len(trampolines.code) > len(TRAMPOLINE_VANILLA):
        raise PatchError("the round stats trampolines overrun the dead greens slots")
    assert TRAMPOLINE_ORIGIN + len(TRAMPOLINE_VANILLA) == TRAMPOLINE_LIMIT

    fairway_hook = trampolines.symbol("RsFairwayHook")
    penalty_stroke = trampolines.symbol("RsPenaltyStroke")
    increment = _word(SYMBOLS["IncrementStrokeCount"])

    def hook(name: str, bank: int, cpu: int, original: bytes, patched: bytes):
        return BytePatch(
            name=f"round_stats_{name}",
            description=f"bank {bank} ${cpu:04X}: {name.replace('_', ' ')}",
            prg_offset=_prg_offset(cpu, bank)
            if bank != 15
            else rom_utils.cpu_to_prg_fixed(cpu),
            original=original,
            patched=patched,
        )

    patches: list[ROMPatch] = [
        _CodeImage(code),
        hook(
            "trampolines",
            15,
            TRAMPOLINE_ORIGIN,
            TRAMPOLINE_VANILLA[: len(trampolines.code)],
            trampolines.code,
        ),
        hook(
            "round_reset",
            HOOK_BANK,
            0x80CE,
            bytes.fromhex("8DFD048DFE04"),  # STA $04FD / STA $04FE
            _jsr_far(code.symbol("RsResetRound")),
        ),
        hook(
            "fairway",
            HOOK_BANK,
            0x832C,
            _word(SYMBOLS["PostShotLie"]),  # JMP LD_85E9's operand
            _word(fairway_hook),
        ),
        hook("water_penalty", HOOK_BANK, 0x8642, increment, _word(penalty_stroke)),
        hook("oob_penalty", HOOK_BANK, 0x8670, increment, _word(penalty_stroke)),
        hook(
            "save",
            15,
            0xD94F,
            bytes([0x09, 0x31, 0xAE]),  # LD94C's far call: bank 9 $AE31
            bytes([CODE_BANK]) + _word(code.symbol("RsSaveGame")),
        ),
        hook(
            "load",
            15,
            0xD95E,
            bytes([0x09, 0xEC, 0xAE]),  # LD95B's far call: bank 9 $AEEC
            bytes([CODE_BANK]) + _word(code.symbol("RsLoadGame")),
        ),
    ]
    return CompositePatch(
        name="round_stats",
        description="Count fairways hit and penalty strokes for the scorecard QR",
        patches=patches,
        requires=(COURSE_MIRRORS_PATCH,),
    )


ROUND_STATS_PATCH = round_stats_patch()
