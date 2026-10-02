# Green Detail View and Scorecard Shortcuts

> **Note**: This document was written by Claude based on investigation requested by jdharms.

From the shot-setup view, press **B** to bring up the ball lie panel, then **Select** for
the green detail view or **Start** for the scorecard.

Implemented as `golf/core/patches/green_shortcut.py`, applied as the `green_shortcut` step
of `golf-patch`. The rest of this document is the analysis of the vanilla input and
shot-setup code it is built on.

## Why

Green slopes are invisible from the course-level view - the greens are drawn opaque, and
the only way to read the break before a shot is the green detail view. That makes it the
most-used entry in the Select menu, and `RunInGameMenu` (`$96B1`) resets
`InGameMenuSelection` to 0 every time it opens (`$96B3`), so reaching it always costs
Select, Down, A. The scorecard is item 0 of the same menu.

Start rides the same poll for free. It is bit `$10`, next to Select's `$20` in the byte the
poll already reads, and the existing `sta ShortcutFlag` stores the *isolated* bit - so the
flag records which button was pressed without one extra instruction. Only the two masks
widened; the poll is still 27 bytes.

## How input actually reaches a scene

The main loop never reads the controller. `NMIHandler` (`$D2BF`, fixed bank) runs once a
frame and does, in order: flush the PPU buffer, apply scroll, sprite DMA,
`INC VblankFlag`, `JSR ProcessBothControllers`, `INC FrameCounter`, then `CLI` and a call
into bank 14 `$8000` for music.

`ProcessBothControllers` (`$D1A7`) is the only caller of `ReadBothControllers` (`$D0CD`),
which maintains:

| RAM | Meaning |
|---|---|
| `$14`/`$15` `Controller_Current` | raw held state this frame |
| `$16`/`$17` `Controller_NewPress` | edge-detected new presses |
| `$0474`/`$0475` `Controller_Previous` | last frame |
| `$1E` `Controller_RepeatTimer` | auto-repeat, `$0F` then `$02` |

Bit order is standard: `$80` A, `$40` B, `$20` Select, `$10` Start, `$08` Up, `$04` Down,
`$02` Left, `$01` Right. `$D112` masks the repeat with `#$0F`, so **only the four
direction bits auto-repeat** - A, B, Select and Start each fire exactly once per press.

`ProcessBothControllers` then translates each *new press* into a one-byte action code via
`ButtonBitMasks` (`$D1FB`) and `FirstControllerActions` (`$D203`), and pushes it onto a
16-byte ring buffer, `InputEventQueue` at `$0400`-`$040F`:

```
A=$41 'A'   B=$42 'B'   Start=$53 'S'   Select=$58 'X'
Up=$55 'U'  Down=$44 'D'  Left=$4C 'L'   Right=$52 'R'
```

Player 2 gets the lowercase codes from `SecondControllerActions` (`$D20B`).

Every gameplay scene then has the same shape:

```
Loop:   JSR WaitForVblank            ; $CD74 - spins on VblankFlag, which the NMI INCs
        ...render work...
Poll:   JSR PopInputEvent            ; $D188 - A = action code, $00 = nothing queued
        BEQ Loop
        JSR DispatchInlineJumpTableFF ; $D267
        .db $41,lo,hi, $42,lo,hi, ..., $FF
```

`$D267` pops its own return address to find the table, then **pushes the post-table
address back** before `JMP ($0024)`. So a handler ending in `RTS` resumes after the table,
and one that does `PLA PLA` first returns out of the enclosing routine - the trick behind
every "A advances / B backs out" handler.

`FlushInputEvents` (`$D222`) sets the tail to the head, discarding everything queued; scenes
call it whenever they don't want stale presses.

The consequence: **the main loop sees edges, one at a time, in arrival order, with no
notion of a held button.** Reading `Controller_Current` directly is the only way to see a
chord, and essentially nothing in the game does it.

## The shot-setup view is three loops

`ShotSetupSequence` (bank 13 `$877A`) runs a chain of panels rather than one screen:

```
ShotSetupSequence $877A
  └─ $87F2 → RunSwingSpeedPanel  $88C9   ShotSetupPanelId=1   Up/Down = SwingSpeed
       └─ $8803 → RunClubSelectPanel $8ADF   =2   Up/Down = ClubSelection
            └─ $8811 → RunSpinSelectPanel $8BBD   =3   Up/Down = ShotSpinSetting
                 └─ $884F → SwingSequenceEntry $AA09   (third-person, three-button swing)
```

A walks forward, B walks back. `$04EA` (`ShotSetupPanelId`) selects which HUD panel is
drawn, which is why all three read as "the same screen" while playing. `BallLie == 6` (on
the green) diverts at `$87C0` to `LD_886E` instead, so none of this runs while putting.

All three dispatch tables share two entries:

- `$58` Select → `$89B0` `OpenInGameMenuFromPlay`
- `$53` Start → `$89E5` `OpenSaveAndQuitFromPlay`

B from the *first* panel (`$8993`) sets `ShotSetupPanelId = 0` and returns carry set;
`$8801 BCS` sends control to `$87EF → ShowBallLiePopup ($A5DE)`.

## Why a "B held + Select" chord doesn't work

B's own press is dispatched first, which puts the player inside `ShowBallLiePopup` before
Select is ever touched. That routine animates the panel open in four steps, holds 90 frames
at `$A690`, and animates it closed - about 1.8 seconds. Its per-frame poll
(`RunLiePopupFrames` `$A6C1`, at `$A6DD`) tests only `#$80`, the A button. On the way out,
`$A6BB JSR FlushInputEvents` discards the whole queue.

So a Select pressed while B is down is queued by the NMI, ignored by the popup, and thrown
away - it never reaches `$89B0` at all. A `Controller_Current & $40` test in the Select
handler would only fire if the player kept holding B through the full popup and then
pressed Select *again*.

The splice therefore goes where the player actually is: inside the lie panel's own poll.

## Confirmation

With a Mesen breakpoint at `$A6DD` conditioned on `[$0016] & $20`, pressing Select during
the hold stops there with:

| | |
|---|---|
| `A` | `$20` |
| `X` | `$00` |
| `$16` | `$20` |
| `$0B` | `$58` (two frames into the 90-frame hold) |
| `$3F`/`$40` | `$07`/`$08` - the unread `$58` in `InputEventQueue`, about to be discarded |
| `$0010` | `$90` |

`$0010` having bit 7 set means `WaitForVblank` is NMI-driven, so the poll runs exactly once
per frame and cannot miss the single frame where `$16` holds `$20`. It is a single frame:
the next frame the raw state is unchanged, so `ReadBothControllers` takes the repeat path
at `$D107` and zeroes `$16`, and Select isn't in the `#$0F` repeat mask.

`$0099` and `$0133` both read `$00` in a one-player round, which is what keeps `X` at 0
through the `$A6D5`-`$A6DC` branch.

Reading `$16` directly also can't be starved: `ReadBothControllers` runs at `$D1A7` *before*
the gate at `$D1AA` that suppresses queue pushes while the queue is non-empty, so `$16` is
current regardless of what else is pending.

`$14` reads `$60` or `$20` depending on whether B is still held at that moment. The patch
deliberately does not test it - on a controller, whether B is still down when Select
registers is not something the player controls precisely.

## Only `$A695` acts on the carry

`ShowBallLiePopup` calls the poll ten times, and **only the 90-frame hold at `$A692` tests
the carry it returns** (`$A695 BCS $A6AB`). The four open steps at
`$A641`/`$A646`/`$A64B`/`$A650`, the four close steps at `$A699`-`$A6A8`, and the
out-of-bounds blink at `$A66F` all discard it.

So aborting the current step is not enough. A Select caught during the *open* animation
sets the flag and ends that one step, then the remaining ~98 frames of animation and hold
play out in full before anything reads it - which is exactly the "press it early and you
wait for the whole animation, press it late and it cuts straight there" jank the first
version shipped with. `LiePopupPoll` therefore also checks the flag on its
nothing-pressed path and bails immediately once it is set, so each remaining step costs one
frame instead of its full count: about four frames rather than ninety-eight.

## Four ways into the panel, not two

`find_code_references` reports four confirmed `JSR ShowBallLiePopup` sites in the ROM:

| Site | Reached when |
|---|---|
| `$861E` | automatic announcement once a shot comes to rest |
| `$865D` | the same, after a water penalty (`BallLie` 4) |
| `$87EF` | B from the shot-setup view - the one that owns the shortcut |
| `$9785` | in-game menu item 2 |

A raw byte search for `20 DE A5` over bank 13 finds six hits; two are coincidences inside
other instructions. This is the case the `nes-open-golf-rom-peek` skill warns about, and an
integration test asks the reference finder rather than counting bytes.

The three sites that aren't `$87EF` never read the flag, but they all run the patched poll.
So the flag is cleared on the way *in*, by `ClearFlagThenLie`, which every site now goes
through. Clearing after use instead would leave a Select pressed during (say) the automatic
post-shot announcement set, to fast-forward whichever panel opened next.

At those three sites Select and Start now just dismiss the panel early and do nothing
else - which is what A already did there in vanilla.

## The implementation

Five byte-neutral splices: the poll, `$87EF`, and a flag clear on each of the other three
call sites.

**1. `$A6DF`, inside `RunLiePopupFrames`.** This poll is shared by all ten calls that make
up the lie panel: four open steps, the hold, four close steps, and the out-of-bounds blink
at `$A66F`. Its `AND #$80 / BNE $A6E9` becomes a `JMP` into `LiePopupPoll`, which is
entered with A holding `Controller_NewPress,X` and the stack still holding
`ShowBallLiePopup`'s return address, so its `RTS` lands exactly where `$A6E9`'s would:

```
LiePopupPoll:                    ; fixed bank $CAE4, 27 bytes
    and #$A0                     ; either button that ends the frame wait?
    beq Continue                 ; neither: fall back into the countdown
    and #$20
    beq Abort                    ; A button: vanilla behavior, carry set
    sta ShortcutFlag             ; Select: A is $20, so this is nonzero
Abort:
    sec
    rts
Continue:
    lda ShortcutFlag             ; already bound for the green: stop waiting
    bne Abort
    dec LiePopupFrames           ; $0B
    beq Done
    jmp LiePopupWait             ; $A6D0
Done:
    clc
    rts
```

Select is isolated and branched away from before A is tested, because `AND #$20` leaves Z
set for an A-only press - testing A on the already-masked value would report "no button".

**2. `$87EF`, `ShotSetupSequence`'s `JSR ShowBallLiePopup`,** becomes a `JMP` into the
wrapper. The stack is untouched, so both exits are jumps back into `ShotSetupSequence`:

```
GreenShortcutEntry:              ; bank 13 $BFBF, 36 bytes with the tail below
    jsr ClearFlagThenLie
    lda ShortcutFlag
    beq Resume

    jsr FadeOut                  ; $D83C
    jsr DrawGreenDetailView      ; $95A9
    jsr FadeIn                   ; $D823
Wait:
    jsr PopInputEvent            ; $D188
    beq Wait
    jmp RestoreCourseView        ; $87E3
Resume:
    jmp ResumeShotSetup          ; $87F2

ClearFlagThenLie:                ; $BFDB - every call site enters the panel here
    lda #$00
    sta ShortcutFlag
    jmp ShowBallLiePopup         ; tail call: its RTS returns to our caller
```

**3. The other three lie panel call sites** become `JSR ClearFlagThenLie`, same three
bytes.

`$20` falls through to the green view; anything else nonzero takes the scorecard branch,
which far-calls bank 2's `DrawScorecardScreen` with the same inline arguments in-game menu
item 0 carries at `$9770`. Both branches rejoin at `AfterDraw` to share the fade-in and the
dismiss wait.

Returning is largely free. A Select abort returns carry set, so `$A695 BCS $A6AB` runs the
panel's own tail - including the `FlushInputEvents` at `$A6BB` - *before* the green view is
drawn. That clears the queued `$58`, so it can't leak through and open the in-game menu
afterwards, and the green view's "press anything to dismiss" wait can't be satisfied
instantly by a stale event. Coming back out reuses `$87E3`, which already fades out, calls
`DrawCourseGameplayView`, fades in and jumps to `$87F2`; `RunSwingSpeedPanel` redraws its
own panel at `$88EA`, so nothing else needs restoring.

## Space, and the practice_swing conflict

| Routine | Home | Size | Region |
|---|---|---|---|
| `LiePopupPoll` | fixed bank `$CAE4` | 27 of 28 | `CA40_FreeSpace192`, ends at `$CB00` (`HalfSquareTableLo`) |
| `GreenShortcutEntry` + `ClearFlagThenLie` | bank 13 `$BFBF` | 36 of 52 | tail padding, ends at `$BFF3` (`LD_BFF3_Mmc1ResetStub`) |

Both are `practice_swing`'s allocations, and the flag byte `$05BB` is `practice_swing`'s
`PracticeSwingOffset` - the one byte this project has established as untouched by the
vanilla ROM (`find-refs --type ram` reports no direct references).

**`green_shortcut` and `practice_swing` are therefore mutually exclusive.** `PatchStack`
refuses a recipe naming both, since two steps would write the same bytes.

The fixed bank is always mapped, so `LiePopupPoll` living there is safe from either splice,
and its `JMP $A6D0` back into bank 13 is fine because bank 13 is what's switched in
whenever the lie panel is on screen.

Bank 13 alone could not hold both routines: after `mercy_tap_in` (`$BF83`-`$BF9F`,
`$BFA0`-`$BFAE`) and `seeded_wind` (`$BFAF`-`$BFBE`), the tail has 52 bytes left and the two
routines need 63.

## The scorecard needs no PPU preamble

`DrawScorecardScreen` (bank 2 `$AE76`) does no PPU setup of its own - it goes straight to
`LCDB3`, clears OAM and starts loading graphics. Its two vanilla callers do it for it:
`RunInGameMenu` writes `NametableY = 0` and `PpuCtrl_Cache = $B0` at `$96BC` before it ever
reaches the dispatch.

Entered from `$87EF` we arrive instead with gameplay's `$10 = $90` (set by
`LoadCourseViewTileset`) and whatever `$1C`/`$1D` the scrolled course view left behind. `$90`
and `$B0` differ only in bit 5, sprite size, and the scorecard blanks all 256 OAM bytes at
`$AE79`, so no sprite is visible either way.

**Playtested: it renders correctly.** Neither the pattern table nor the leftover scroll is a
problem, so the preamble the menu performs is not actually required here. That was the one
open question, and it mattered: the preamble costs 8 bytes and `GreenShortcutEntry` is at
**exactly 52 of the 52 bytes** bank 13's tail has, so needing it would have meant taking
space from `mercy_tap_in`'s `$BF83`-`$BFAE` or reclaiming this bank's dead
`LD_BFF3_Mmc1ResetStub`.

There is no slack left at all. A future change to this routine has to find bytes elsewhere.

## Status

Both halves are playtested and work: the green detail view (including the fast-forward fix
above, which a first pass got wrong) and the scorecard. Unit and integration tests cover the
layout, all five splices, that no route into the lie panel bypasses `ClearFlagThenLie`, and
the `practice_swing` conflict in both orders.
