"""
Green detail view and scorecard shortcuts.

Quality-of-life patch: from the shot-setup view, press B to bring up the ball
lie panel and then Select for the green detail view, or Start for the
scorecard - instead of walking the in-game menu to either one.

Why these two views are worth a shortcut
----------------------------------------

Green slopes are invisible from the course-level view - the greens are drawn
opaque, and the only way to read the break is the green detail view. That
makes it the most-used entry in the Select menu, and `RunInGameMenu` ($96B1)
resets `InGameMenuSelection` to 0 every time it opens ($96B3), so reaching it
always costs Select, Down, A. The scorecard is item 0 of the same menu.

Why the gesture is "B then Select" and not a chord
--------------------------------------------------

The main loop never reads the controller. `NMIHandler` ($D2BF) calls
`ProcessBothControllers` ($D1A7) once a frame, which edge-detects new presses
and pushes a one-byte action code per button onto `InputEventQueue`
($0400-$040F). Scenes consume those with `PopInputEvent` ($D188) and
`DispatchInlineJumpTableFF`. The queue carries *edges*, one at a time, with no
notion of a held button - so a genuine B+Select chord is not expressible
there.

It gets worse for a naive "is B held?" test in the Select handler
(`OpenInGameMenuFromPlay`, $89B0): B's own press has already been dispatched
by then. It sends `ShotSetupSequence` to `ShowBallLiePopup` ($A5DE), which
holds for 90 frames polling only the A button, and then discards everything
else pressed meanwhile via the `FlushInputEvents` at $A6BB. A Select pressed
while B is down never reaches $89B0 at all.

So the splice goes where the player actually is: inside the lie panel's own
per-frame poll. B brings up the panel, Select while it is up jumps to the
green. Physically that is the same gesture, and it is the one the engine can
see.

Confirmed in Mesen with a breakpoint at $A6DD conditioned on
`[$0016] & $20`: pressing Select during the hold stops there with `A = $20`,
`X = $00`, `$16 = $20`, `$0B = $58` (two frames into the 90-frame hold), and
`$3F`/`$40` at `$07`/`$08` - the unread `$58` event sitting in
`InputEventQueue`, about to be thrown away. `$0010` reads `$90`, so
`WaitForVblank` is NMI-driven and the poll runs exactly once per frame, which
is what makes the single frame where `$16` holds `$20` impossible to miss.

Reading `$16` directly rather than the queue also can't be starved:
`ReadBothControllers` runs at $D1A7 *before* the gate at $D1AA that suppresses
queue pushes while the queue is non-empty, so `$16` is current regardless of
what else is pending.

What gets spliced
-----------------

1. `$A6DF`, inside `RunLiePopupFrames` ($A6C1) - the poll shared by all ten
   calls that make up the lie panel (four open steps, the hold, four close
   steps, and the out-of-bounds blink at $A66F). Its `AND #$80 / BNE $A6E9`
   becomes a `JMP` into `LiePopupPoll`, which adds the Select case and then
   reproduces the original three outcomes exactly.

2. `$87EF`, `ShotSetupSequence`'s `JSR ShowBallLiePopup`, becomes a `JMP` into
   `GreenShortcutEntry`, which runs the panel and, on a set flag, fades to the
   green view (Select) or far-calls `DrawScorecardScreen` (Start).

   Start rides the poll for free: it is bit $10, next to Select's $20 in the
   byte the poll already reads, and the existing `sta ShortcutFlag` stores the
   isolated bit, so the flag records which button without a single extra
   instruction. Only the two masks widened.

3. The three other `JSR ShowBallLiePopup` sites become `JSR ClearFlagThenLie`,
   which zeroes the flag and tail-calls the panel. See `CLEAR_ONLY_SPLICES`.

Only $A695 acts on the carry
----------------------------

`ShowBallLiePopup` calls the poll ten times and **only the 90-frame hold at
$A692 tests the carry it returns** ($A695 `BCS $A6AB`). The four open steps at
$A641/$A646/$A64B/$A650, the four close steps at $A699-$A6A8 and the
out-of-bounds blink at $A66F all discard it.

So aborting the current step is not enough: a Select caught during the *open*
animation would set the flag, end that step, and then sit through the
remaining ~98 frames of animation and hold before `GreenShortcutEntry` ever
read it. `LiePopupPoll` therefore also checks the flag on its
nothing-pressed path and returns immediately once it is set, so every
remaining step costs one frame instead of its full count - about four frames
total, rather than ninety-eight.

The flag is cleared on the way *in* rather than on the way out, by
`ClearFlagThenLie`, which every call site now goes through. Clearing after use
would not be enough: the other three sites never read the flag, so a Select
pressed during, say, the automatic post-shot announcement would otherwise
survive to fast-forward the next panel.

Returning is free: a Select abort returns carry set, so $A695's `BCS $A6AB`
runs the panel's own tail - including the `FlushInputEvents` at $A6BB - before
the green view is drawn. That clears the queued `$58`, so it can't leak
through and open the in-game menu afterwards, and the green view's
"press anything to dismiss" wait can't be satisfied instantly by a stale
event. Select doesn't auto-repeat either (`ReadBothControllers` masks the
repeat with `#$0F` at $D112), so a held Select can't double-fire.

At the three clear-only sites Select and Start now dismiss the panel early and
do nothing else, which is what A already did there in vanilla.

The scorecard needs no PPU preamble
-----------------------------------

`DrawScorecardScreen` (bank 2 $AE76) does no PPU setup of its own - it goes
straight to `LCDB3`, clears OAM and starts loading graphics. Its two vanilla
callers set things up for it: `RunInGameMenu` writes `NametableY = 0` and
`PpuCtrl_Cache = $B0` at $96BC before it ever reaches the dispatch.

Entered from $87EF we arrive instead with gameplay's `$10 = $90` (from
`LoadCourseViewTileset`) and whatever `$1C`/`$1D` the scrolled course view left.
Playtested: it renders correctly anyway. `$90` and `$B0` differ only in bit 5,
sprite size, and the scorecard blanks all 256 OAM bytes at $AE79, so no sprite
is visible either way.

That mattered for space: the preamble would cost 8 bytes and
`GreenShortcutEntry` is at **exactly 52 of the 52** bytes bank 13's tail has.
There is no slack left - a future change here has to find bytes elsewhere,
from `mercy_tap_in`'s $BF83-$BFAE or by reclaiming this bank's dead
`LD_BFF3_Mmc1ResetStub`.

Coming back out reuses the code already at $87E3: fade out,
`DrawCourseGameplayView`, fade in, `JMP $87F2`. `RunSwingSpeedPanel` redraws
its own panel at $88EA, so nothing else needs restoring.

Space
-----

`LiePopupPoll` goes in the fixed bank at $CAE4 and `GreenShortcutEntry` in
bank 13 at $BFBF. Both are `practice_swing`'s allocations, and `$05BB` - the
flag byte - is `practice_swing`'s `PracticeSwingOffset`, the one byte the
project has established as untouched by the vanilla ROM. **This patch and
`practice_swing` are mutually exclusive**; `PatchStack` refuses a recipe
naming both, because two steps would write the same bytes.

The fixed bank is always mapped, so `LiePopupPoll` living there is safe from
either splice, and its `JMP $A6D0` back into bank 13 is fine because bank 13
is what's switched in whenever the lie panel is on screen.
"""

from golf.core.asm6502 import Program, assemble

from .byte_patch import BytePatch
from .composite import CompositePatch

# --- Vanilla addresses this patch is assembled against ------------------------

#: `RunLiePopupFrames`' per-frame poll, one instruction past `LDA $16,X`.
POLL_SPLICE_ADDR = 0xA6DF
POLL_SPLICE_PRG_OFFSET = 0x366DF
#: `AND #$80 / BNE $A6E9`
POLL_SPLICE_ORIGINAL = bytes([0x29, 0x80, 0xD0, 0x06])

#: `ShotSetupSequence`'s call to `ShowBallLiePopup`.
ENTRY_SPLICE_ADDR = 0x87EF
ENTRY_SPLICE_PRG_OFFSET = 0x347EF
#: `JSR $A5DE`
ENTRY_SPLICE_ORIGINAL = bytes([0x20, 0xDE, 0xA5])

#: The other three `JSR ShowBallLiePopup` sites, which only need the flag
#: cleared. `find_code_references` reports exactly these four in the whole ROM:
#:
#:   $861E  the automatic announcement after a shot comes to rest
#:   $865D  the same, after a water penalty (BallLie 4)
#:   $9785  in-game menu item 2
#:
#: None of them reads the flag, but all of them run the patched poll, so a
#: Select pressed during any of them would otherwise leave the flag set and
#: fast-forward whichever panel came next.
CLEAR_ONLY_SPLICES = {
    "shot_result": (0x861E, 0x3461E),
    "water_penalty": (0x865D, 0x3465D),
    "menu": (0x9785, 0x35785),
}
#: `JSR $A5DE`
LIE_CALL_ORIGINAL = bytes([0x20, 0xDE, 0xA5])

_VANILLA = {
    # bank 13
    "LiePopupWait": 0xA6D0,  # top of the poll's per-frame loop
    "LiePopupAbort": 0xA6E9,  # SEC / RTS
    "LiePopupFrames": 0x0B,  # zero page countdown RunLiePopupFrames owns
    "ShowBallLiePopup": 0xA5DE,
    "DrawGreenDetailView": 0x95A9,
    "RestoreCourseView": 0x87E3,  # fade out / DrawCourseGameplayView / fade in / JMP $87F2
    "ResumeShotSetup": 0x87F2,
    # fixed bank
    "ControllerNewPress": 0x16,
    "ExecuteFarCall": 0xD372,
    "FadeIn": 0xD823,
    "FadeOut": 0xD83C,
    "PopInputEvent": 0xD188,
    # WRAM
    "ShortcutFlag": 0x05BB,
}

_SELECT_BIT = 0x20
_START_BIT = 0x10
_A_BIT = 0x80

#: `ExecuteFarCall` inline arguments for bank 2's `DrawScorecardScreen` ($AE76),
#: the same three bytes in-game menu item 0 carries at $9770.
_SCORECARD_FAR_CALL = (0x02, 0x76, 0xAE)

# --- Where the new code goes --------------------------------------------------

#: CPU $CAE4 in the fixed bank, inside `CA40_FreeSpace192` ($CA40-$CAFF).
POLL_CODE_ADDR = 0xCAE4
POLL_CODE_PRG_OFFSET = 0x3CAE4
POLL_CODE_LIMIT = 0xCB00 - POLL_CODE_ADDR  # 28; $CB00 starts the fast math tables

#: CPU $BFBF in bank 13, tail padding that ends at `LD_BFF3_Mmc1ResetStub`.
ENTRY_CODE_ADDR = 0xBFBF
ENTRY_CODE_PRG_OFFSET = 0x37FBF
ENTRY_CODE_LIMIT = 0xBFF3 - ENTRY_CODE_ADDR  # 52


def _poll_code() -> bytes:
    """
    Replace `RunLiePopupFrames`' A-button poll with one that also sees Select.

    Entered by `JMP` from $A6DF with A holding `Controller_NewPress,X`, so the
    stack still holds `ShowBallLiePopup`'s return address and an `RTS` here
    lands exactly where $A6E9's would.
    """
    source = """
        LiePopupPoll:
            and #SELECT_BIT+START_BIT+A_BIT   ; a button that ends the frame wait?
            beq Continue            ; none: fall back into the countdown
            and #SELECT_BIT+START_BIT
            beq Abort               ; A button: vanilla behavior, carry set
            sta ShortcutFlag        ; A is the isolated bit, so it records which
        Abort:
            sec
            rts

        Continue:
            lda ShortcutFlag        ; already bound for the green: stop waiting
            bne Abort               ; (only $A695 acts on the carry, so every
            dec LiePopupFrames      ; other step has to cut its own wait short)
            beq Done
            jmp LiePopupWait
        Done:
            clc
            rts
    """
    program = assemble(
        source,
        POLL_CODE_ADDR,
        {
            **_VANILLA,
            "SELECT_BIT": _SELECT_BIT,
            "START_BIT": _START_BIT,
            "A_BIT": _A_BIT,
        },
    )
    if program.size > POLL_CODE_LIMIT:
        raise ValueError(
            f"LiePopupPoll is {program.size} bytes; only {POLL_CODE_LIMIT} are "
            f"free at ${POLL_CODE_ADDR:04X} before the fast math tables"
        )
    return program.code


def _entry_program() -> Program:
    """
    Run the lie panel, then take the flag it may have set to the green view.

    `GreenShortcutEntry` is entered by `JMP` from $87EF, so the stack is
    untouched and every exit is a jump back into `ShotSetupSequence` rather
    than a return. The flag says which screen to show: $20 (Select) is the
    green, anything else nonzero is the scorecard.

    `ClearFlagThenLie` is the other half: both routes into the lie panel go
    through it, so the flag is always zero when the panel opens and a Select
    pressed in the in-game menu's own lie view can never survive into a later
    panel and fast-forward it.
    """
    source = """
        GreenShortcutEntry:
            jsr ClearFlagThenLie
            lda ShortcutFlag
            beq Resume
            cmp #SELECT_BIT
            bne Scorecard           ; Start (or both at once): the scorecard

            jsr FadeOut
            jsr DrawGreenDetailView
        AfterDraw:
            jsr FadeIn
        Wait:
            jsr PopInputEvent       ; queue was flushed at $A6BB, so this waits
            beq Wait
            jmp RestoreCourseView

        Resume:
            jmp ResumeShotSetup

        Scorecard:
            jsr FadeOut
            jsr ExecuteFarCall
            .byte SCORECARD_BANK, SCORECARD_LO, SCORECARD_HI
            jmp AfterDraw

        ClearFlagThenLie:
            lda #$00
            sta ShortcutFlag
            jmp ShowBallLiePopup    ; tail call: its RTS returns to our caller
    """
    bank, lo, hi = _SCORECARD_FAR_CALL
    program = assemble(
        source,
        ENTRY_CODE_ADDR,
        {
            **_VANILLA,
            "SELECT_BIT": _SELECT_BIT,
            "SCORECARD_BANK": bank,
            "SCORECARD_LO": lo,
            "SCORECARD_HI": hi,
        },
    )
    if program.size > ENTRY_CODE_LIMIT:
        raise ValueError(
            f"GreenShortcutEntry is {program.size} bytes; only "
            f"{ENTRY_CODE_LIMIT} are free at ${ENTRY_CODE_ADDR:04X} before "
            f"LD_BFF3_Mmc1ResetStub"
        )
    return program


def _entry_code() -> bytes:
    return _entry_program().code


def _jmp(target: int) -> bytes:
    return bytes([0x4C, target & 0xFF, target >> 8])


def _jsr(target: int) -> bytes:
    return bytes([0x20, target & 0xFF, target >> 8])


def green_shortcut_patch() -> CompositePatch[BytePatch]:
    """
    Build the green detail view shortcut.

    Returns a `CompositePatch` of seven `BytePatch` steps: the two new
    routines, the poll splice, the `$87EF` splice that owns the shortcut, and
    a flag-clearing splice on each of the other three lie panel call sites.
    """
    poll_code = _poll_code()
    entry_program = _entry_program()
    entry_code = entry_program.code
    clear_flag_then_lie = entry_program.symbol("ClearFlagThenLie")

    poll_routine = BytePatch(
        name="green_shortcut_poll_routine",
        description=(
            "Select-aware replacement for RunLiePopupFrames' A-button poll, "
            f"in fixed-bank free space at ${POLL_CODE_ADDR:04X}"
        ),
        prg_offset=POLL_CODE_PRG_OFFSET,
        original=bytes([0xFF] * len(poll_code)),
        patched=poll_code,
    )

    poll_splice = BytePatch(
        name="green_shortcut_poll_splice",
        description=f"Redirect the lie panel's per-frame poll at ${POLL_SPLICE_ADDR:04X}",
        prg_offset=POLL_SPLICE_PRG_OFFSET,
        original=POLL_SPLICE_ORIGINAL,
        # the displaced BNE's slot is unreachable; NOP keeps the length equal
        patched=_jmp(POLL_CODE_ADDR) + bytes([0xEA]),
    )

    entry_routine = BytePatch(
        name="green_shortcut_entry_routine",
        description=(
            "Lie panel wrapper that fades to the green detail view, in bank13 "
            f"free space at ${ENTRY_CODE_ADDR:04X}"
        ),
        prg_offset=ENTRY_CODE_PRG_OFFSET,
        original=bytes([0xFF] * len(entry_code)),
        patched=entry_code,
    )

    entry_splice = BytePatch(
        name="green_shortcut_entry_splice",
        description=(
            "Route ShotSetupSequence's ShowBallLiePopup call through the wrapper"
        ),
        prg_offset=ENTRY_SPLICE_PRG_OFFSET,
        original=ENTRY_SPLICE_ORIGINAL,
        patched=_jmp(ENTRY_CODE_ADDR),
    )

    clear_only = [
        BytePatch(
            name=f"green_shortcut_clear_{site}",
            description=(
                f"Clear the shortcut flag on the lie panel call at ${addr:04X} ({site})"
            ),
            prg_offset=prg_offset,
            original=LIE_CALL_ORIGINAL,
            patched=_jsr(clear_flag_then_lie),
        )
        for site, (addr, prg_offset) in CLEAR_ONLY_SPLICES.items()
    ]

    return CompositePatch(
        name="green_shortcut",
        description=(
            "B then Select on the shot-setup view jumps straight to the green "
            "detail view, B then Start to the scorecard"
        ),
        patches=[
            poll_routine,
            poll_splice,
            entry_routine,
            entry_splice,
            *clear_only,
        ],
    )
