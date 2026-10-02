"""
Constant-acceleration green slope physics.

An "alternate history" replacement for the vanilla green slope routine
`LD_B1D5_Green` (bank 13, $B1D5-$B244). Not part of the randomizer; it exists
to make putts behave the way a real green does.

What vanilla does
-----------------

Every slope term is multiplied by a speed term,
`f(v) = min(|v_mid| * 2, $40) * 2`, which saturates at `$80` for
`|v_mid| >= 32` and falls linearly to zero below that. The routine then applies
four terms per frame::

    from f(|vx|):  hi(f * Xmag) >> 1          -> vx        (the "direct" term)
                   scale(hi(f * Ymag))        -> vy        (the "cross" term)
    from f(|vy|):  scale(hi(f * Xmag))        -> vx
                   hi(f * Ymag) >> 1          -> vy

where `scale` is `LD_B6DD` - x2.5 on a dark slope tile ($30-$47), x2 on a light
one ($88-$9F), selected by bit 6 of `$CA`. Each block then reuses whatever
`$20` holds - which is the *other* axis's term, because the second
`..._CheckSign` call overwrote it - as a drag opposing that axis.

Three consequences, all of which this patch removes:

- **Slope force dies with the ball.** It is constant while the ball is fast and
  fades to literally zero as it stops (integer truncation takes it to 0 below
  `v_mid` of about 2-4). Real break builds over the last few feet, because
  gravity stays constant while the ball slows. Here it does the opposite.
- **The cross term is 5x the direct term.** A putt across the fall line feels
  five times the slope of one along it, which is why cardinal slopes - where
  one component is exactly zero - read as "barely there" when you putt up or
  down them.
- **Diagonals are 41% too strong.** A diagonal tile writes the full magnitude
  to *both* axes instead of magnitude/sqrt(2), so its resultant is sqrt(2)
  times a cardinal of the same nominal steepness.

What this does instead
----------------------

Three things per contact frame:

1. **Rest test.** If both velocity mid-bytes are zero - that is, the ball is
   moving slower than 256 low-byte units on both axes - nothing is applied at
   all. This stands in for static friction: without it the constant slope
   acceleration would creep a resting ball forever, and it would never satisfy
   `LD_B3BF_CheckStopped`.
2. **Kinetic friction**, constant magnitude, applied to the *dominant axis
   only* - an approximation of "opposite the direction of travel".
3. **Constant slope acceleration** on both axes, straight from `$EB` (X) and
   `$EE` (Y).

`slope_accel` is the high byte of the slope magnitude that `LF300` ($F300,
fixed bank) writes from the tile under the ball. This patch rewrites `LF300`'s
magnitude table at `$F3C0` so those bytes *are* the per-frame acceleration,
which both sets the strength and fixes the diagonals in one place - no runtime
shift needed, and the strength is tunable to any value rather than a power of
two.

Why friction is split between the axes
--------------------------------------

Two earlier versions failed in playtesting, in opposite ways.

**Constant friction on each axis independently.** Putting across a cardinal
slope produced no break at all. Break on a cardinal slope *is* the fall-line
axis accelerating from zero, and if that axis also takes the full constant
friction every frame - with `friction` required to exceed `strength` - its
velocity can never escape the deadband.

**Constant friction on the dominant axis only.** Cardinal slopes then worked,
but diagonal putts stopped breaking. Near 45 degrees the components are nearly
equal, so each frame the larger axis takes the full `friction` and the smaller
takes none, which flips which is larger, and repeats. 45 degrees becomes a
stable attractor: friction pins the direction to the diagonal while the
magnitude decays, so the slope cannot curve the path.

The property that matters is that **friction must not rotate the velocity**.
Real rolling resistance opposes the velocity vector, so its components are in
the same ratio as the velocity's. Doing that exactly needs
`friction * v_axis / |v|` - a magnitude and a divide, neither of which fits.

The rule instead is: an axis takes the full `friction` if its `|v|` is at least
`(|vx| + |vy|) / 4`, which costs an add and two shifts. On a cardinal the cross
axis falls under the threshold and is spared, so the slope builds break there.
Near a diagonal both clear it and are decelerated equally, so the direction is
untouched and the slope is free to steer. 45 degrees is now an unstable point
rather than an attractor.

The cost is that a diagonal putt takes friction on both axes at once, so its
total deceleration is up to sqrt(2) times an axis-aligned putt's and it runs
about a quarter shorter. That is the usual L-infinity artifact and not worth a
divide to remove.

Why the friction has to exist at all
-------------------------------------

`LD_B3BF_CheckStopped` ($B3BF) only declares the ball stopped once the roll
budget `$E4`/`$E6` is exhausted *and* both velocity mid-bytes are within +-1 of
zero. Vanilla's rolling friction (`LD_B451`, which multiplies the velocity by
`$09` = 1..3 and subtracts) is proportional, so against a constant acceleration
`a` it settles at a terminal speed of `256 * a / $09` and the ball would roll
forever. Constant friction larger than the steepest slope's acceleration is
what lets a ball rolling down the fall line come to rest - hence `friction` must
exceed `strength`. Vanilla's proportional friction still runs afterwards; the
two together are a reasonable rolling-resistance-plus-drag model.

Layout
------

The replaced region is self-contained: `$B1E4`, `$B1EB`, `$B21A` and `$B221`
are only branched to from inside it, and `$B245` has no references at all - it
is reached purely by falling out of the bottom. So the whole 112 bytes can go,
provided the replacement jumps to `$B245` when it is done. The new code is 106
bytes; the remaining 6 are left as they were, unreachable.

`$DA/$DB/$DC` (X velocity) and `$DD/$DE/$DF` (Y velocity) are three apart, and
so are `$EA/$EB/$EC` and `$ED/$EE/$EF` (the slope vector), so one routine
indexed by X = 0 or 3 handles both axes. The addend in `$20` is 8-bit unsigned
and the carry alone propagates into the mid and high bytes, so no second
addend byte is needed.

Not included
------------

Two things from the same design that do not fit an in-place patch: bilinear
interpolation of the slope vector between tile centers (which would smooth the
faceting at 8-pixel boundaries), and a per-course green-speed byte. Vanilla's
proportional friction is also left in place rather than removed, since `$09` is
computed at `$B245`, outside the replaced region.
"""

from dataclasses import dataclass

from golf.core.asm6502 import assemble

from .byte_patch import BytePatch
from .composite import CompositePatch

# --- The replaced region ------------------------------------------------------

#: CPU $B1D5 in bank 13 (LD_B1D5_Green).
SLOPE_PRG_OFFSET = 0x371D5
SLOPE_START = 0xB1D5
#: CPU $B245, the fall-through target: the friction/air-drag tail of the green
#: branch, which this patch leaves alone.
SLOPE_END = 0xB245
SLOPE_LEN = SLOPE_END - SLOPE_START  # 112

SLOPE_ORIGINAL = bytes.fromhex(
    "a9 00 85 21 a5 db a4 dc 10 05 a9 00 38 e5 db 0a"
    "c9 40 90 02 a9 40 0a 85 00 a6 eb 20 43 e7 4a 24"
    "ec 20 30 b7 a5 00 a6 ee 20 43 e7 20 dd b6 24 ef"
    "20 04 b7 a5 dc 49 80 20 32 b7 a5 de a4 df 10 05"
    "a9 00 38 e5 de 0a c9 40 90 02 a9 40 0a 85 00 a6"
    "ee 20 43 e7 4a 24 ef 20 04 b7 a5 00 a6 eb 20 43"
    "e7 20 dd b6 24 ec 20 30 b7 a5 df 49 80 20 06 b7".replace(" ", "")
)

# --- LF300's magnitude table --------------------------------------------------

#: CPU $F3C0 in the fixed bank: the high byte of each of the 7 slope magnitude
#: classes, which LF300 writes to $EB / $EE. Index 0 is the zero component; 1/3/5
#: are the cardinal gentle/moderate/steep magnitudes and 2/4/6 the diagonal ones.
MAGNITUDE_PRG_OFFSET = 0x3F3C0
MAGNITUDE_ORIGINAL = bytes([0x00, 0x28, 0x28, 0x50, 0x51, 0x78, 0x79])

#: Vanilla's three steepness classes are 40 / 80 / 120 - exactly 1:2:3 - so one
#: `strength` (the steep value) sets all three.
DEFAULT_STRENGTH = 80
#: Must exceed `strength` or the ball never comes to rest on the steepest tile.
DEFAULT_FRICTION = 90


@dataclass(frozen=True)
class GreenSlopeTuning:
    """Per-frame accelerations, in low-byte velocity units."""

    #: acceleration on the steepest tiles; gentle and moderate scale 1:2:3
    strength: int = DEFAULT_STRENGTH
    #: constant deceleration applied to the dominant axis, opposing travel
    friction: int = DEFAULT_FRICTION

    def __post_init__(self) -> None:
        if not (1 <= self.strength <= 80):
            raise ValueError(f"strength must be 1-80, got {self.strength}")
        if self.friction <= self.strength:
            raise ValueError(
                f"friction ({self.friction}) must exceed strength "
                f"({self.strength}), or a ball on the steepest slope never stops"
            )
        if self.friction > 0xFF:
            raise ValueError(
                f"friction must fit in a byte, got {self.friction}; it is "
                f"assembled as an immediate operand"
            )

    def magnitude_table(self) -> bytes:
        """The 7 bytes LF300 indexes at $F3C0."""
        # A class that rounds to zero would silently turn those tiles flat, so
        # every class stays at 1 or above.
        cardinals = [
            max(1, round(self.strength / 3)),
            max(1, round(self.strength * 2 / 3)),
            self.strength,
        ]
        table = [0x00]
        for cardinal in cardinals:
            # A diagonal tile writes its magnitude to both axes, so each
            # component must be magnitude/sqrt(2) for the resultant to match the
            # cardinal of the same steepness. Vanilla stores the full value.
            table.append(cardinal)
            table.append(max(1, round(cardinal / 2**0.5)))
        return bytes(table)


def _build_code(tuning: GreenSlopeTuning) -> bytes:
    source = f"""
        ; --- rest test, and a friction threshold ------------------------
        ; $DC / $DF hold the sign of each 24-bit velocity, so EORing the mid
        ; byte with it is a one-instruction |v| for the two cases that matter
        ; ($00 and $FF). Above that it is approximate, which only nudges the
        ; threshold.
        GreenSlope:
            lda $DB
            eor $DC
            sta $00                 ; ~|vx|
            lda $DE
            eor $DF
            sta $03                 ; ~|vy|, three along so ApplyAxis can index
            ora $00
            beq @done               ; both under 256: at rest, so nothing acts.
                                    ; Static friction holds the ball; without
                                    ; this the slope would creep it forever.
            lda $00
            clc
            adc $03
            ror a                   ; carry is the 9th bit of the sum
            lsr a
            sta $02                 ; (|vx| + |vy|) / 4
            ldx #$00
            jsr ApplyAxis
            ldx #$03
            jsr ApplyAxis
        @done:
            jmp ${SLOPE_END:04X}

        ApplyAxis:                  ; X = axis offset
            ; An axis takes friction only if it carries a real share of the
            ; motion. The larger axis always clears the threshold; the smaller
            ; clears it from about 1:3 upward. So near a diagonal both are
            ; decelerated equally and friction cannot rotate the velocity,
            ; while on a cardinal the cross axis is spared and the slope is
            ; free to build break there.
            lda $00,x
            cmp $02
            bcc @slope
            lda #${tuning.friction:02X}
            sta $20
            lda $DC,x               ; friction opposes travel, so invert the
            eor #$80                ; velocity's sign before dispatching
            jsr AddOrSub
        @slope:
            lda $EB,x               ; 0 on a flat tile, so this is a no-op there
            sta $20
            lda $EC,x               ; bit 7 = downhill direction
            jmp AddOrSub            ; tail call

        ; N set subtracts, N clear adds. Falls through into AddAxis rather
        ; than jumping to it, so the dispatch costs one branch.
        AddOrSub:
            bmi SubAxis

        ; $20 is an 8-bit unsigned addend; the carry alone propagates into the
        ; mid and high bytes, so no second addend byte is needed.
        AddAxis:                    ; ($DC:$DB:$DA),x += $20
            lda $DA,x
            clc
            adc $20
            sta $DA,x
            lda $DB,x
            adc #$00
            sta $DB,x
            lda $DC,x
            adc #$00
            sta $DC,x
            rts

        SubAxis:                    ; ($DC:$DB:$DA),x -= $20
            lda $DA,x
            sec
            sbc $20
            sta $DA,x
            lda $DB,x
            sbc #$00
            sta $DB,x
            lda $DC,x
            sbc #$00
            sta $DC,x
            rts
    """
    code = assemble(source, SLOPE_START).code
    if len(code) > SLOPE_LEN:
        raise ValueError(
            f"{len(code)} bytes of code do not fit the {SLOPE_LEN} bytes "
            f"LD_B1D5_Green occupies"
        )
    return code


def green_slope_physics_patch(
    strength: int = DEFAULT_STRENGTH, friction: int = DEFAULT_FRICTION
) -> CompositePatch:
    """
    Replace the green slope routine with a constant-acceleration model.

    Args:
        strength: per-frame acceleration on the steepest slope tiles, in
            low-byte velocity units. Gentle and moderate tiles scale 1:2:3, as
            they do in vanilla. 30 matches vanilla's saturated along-the-fall-line
            force, which vanilla then lets decay to zero as the ball slows.
        friction: constant per-frame deceleration applied to whichever axis
            the ball is moving along faster, opposing that motion. Must
            exceed `strength`, or a ball rolling down the fall line never
            comes to rest.
    """
    tuning = GreenSlopeTuning(strength=strength, friction=friction)
    code = _build_code(tuning)

    routine = BytePatch(
        name="green_slope_physics_routine",
        description=(
            f"Constant-acceleration green slope physics at $B1D5 "
            f"(strength {tuning.strength}, friction {tuning.friction})"
        ),
        prg_offset=SLOPE_PRG_OFFSET,
        original=SLOPE_ORIGINAL[: len(code)],
        patched=code,
    )

    magnitudes = BytePatch(
        name="green_slope_physics_magnitudes",
        description=(
            "Per-frame slope accelerations in LF300's magnitude table at $F3C0, "
            "with diagonals divided by sqrt(2)"
        ),
        prg_offset=MAGNITUDE_PRG_OFFSET,
        original=MAGNITUDE_ORIGINAL,
        patched=tuning.magnitude_table(),
    )

    return CompositePatch(
        name="green_slope_physics",
        description=(
            "Green slopes as constant acceleration plus constant friction, "
            "with corrected diagonals"
        ),
        patches=[routine, magnitudes],
    )
