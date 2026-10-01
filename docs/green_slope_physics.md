# Green Slope Physics

> **Note**: This document was written by Claude based on investigation requested by jdharms.

An experimental, opt-in replacement for the vanilla green slope routine. It is not part
of the randomizer and is not applied by any recipe by default. It exists because the
vanilla model makes slope affect a putt *less* the slower the ball gets, which is the
opposite of how a real green behaves.

```bash
uv run golf-patch nes_open_us.nes -p green_slope_physics -o out.nes
uv run golf-patch nes_open_us.nes -p green_slope_physics:strength=45,friction=60 -o out.nes
```

## What vanilla does

`LD_B1D5_Green` (bank 13, `$B1D5-$B244`) runs once per contact frame while the ball is
on the green. The slope vector for the tile under the ball sits in `$EA-$EF`, written by
`LF300` (`$F300`, fixed bank) — the same six bytes `ApplyWindEffect` uses for wind, which
is free to share because wind does not act on putts.

Every term is multiplied by a speed term:

```
f(v) = min(|v_mid| * 2, $40) * 2
```

which saturates at `$80` once `|v_mid| >= 32` and falls linearly to zero below that. Four
terms are applied per frame:

| Driven by | To X | To Y |
|---|---|---|
| `f(\|vx\|)` | `hi(f * Xmag) >> 1` | `scale(hi(f * Ymag))` |
| `f(\|vy\|)` | `scale(hi(f * Xmag))` | `hi(f * Ymag) >> 1` |

`scale` is `LD_B6DD`: ×2.5 on a dark slope tile (`$30-$47`), ×2 on a light one
(`$88-$9F`), chosen by bit 6 of `$CA`. Each block then reuses whatever is left in `$20` —
the *other* axis's term, because the second `..._CheckSign` call overwrote it — as a drag
opposing that axis.

Three consequences:

- **The slope force dies with the ball.** It is constant while the ball is fast and decays
  to literally zero as it stops (integer truncation reaches 0 below a `v_mid` of about 2
  to 4). Real break builds over the last few feet because gravity stays constant while the
  ball slows; this does the reverse.
- **The cross term is five times the direct term.** A putt across the fall line feels five
  times the slope of one along it. On a cardinal tile, where one component is exactly
  zero, that is why putting up or down the slope feels like the slope is barely there.
- **Diagonals are 41% too strong.** A diagonal tile writes its full magnitude to both
  axes instead of magnitude/√2, so its resultant is √2 times the cardinal of the same
  nominal steepness.

## What the patch does

Three things per contact frame:

1. **Rest test.** If both velocity mid-bytes are zero — the ball is moving slower than
   256 low-byte units on both axes — nothing is applied. This stands in for static
   friction. Without it the constant slope acceleration creeps a resting ball forever and
   it never satisfies the stop check.
2. **Kinetic friction**, constant magnitude, applied to the *dominant axis only*.
3. **Constant slope acceleration** on both axes, read straight out of `$EB` (X) and
   `$EE` (Y).

The patch rewrites `LF300`'s magnitude table at `$F3C0` so those seven bytes *are* the
per-frame accelerations, which sets the strength and corrects the diagonals in one place —
no runtime shift, and any value is reachable rather than just powers of two.

The three steepness classes keep vanilla's exact 1:2:3 ratio, so `strength` (the steep
value) sets all three: gentle is `strength/3`, moderate `strength*2/3`, and each diagonal
component is its cardinal divided by √2 so the resultant matches. At `strength=30`, which
matches vanilla's saturated along-the-fall-line force, that is 10/20/30 with diagonal
components 7/14/21. The difference from vanilla is that the force no longer fades as the
ball slows.

`strength` and `friction` are exposed because the right values are a question for
playtesting. Note that `friction` only needs to clear `strength` to guarantee a ball
rolling down the fall line comes to rest — but if it clears it by only a little, that ball
decelerates very slowly and downhill putts run a long way.

## Why friction is split between the axes

Two earlier versions of this patch both failed in playtesting, in opposite ways, and the
shape of those failures is what the current rule is built around.

**Attempt 1: constant friction on each axis independently.** Putting across a cardinal
slope produced no break at all. Break on a cardinal slope *is* the fall-line axis
accelerating from zero — and if that axis also takes the full constant friction every
frame, with `friction` required to exceed `strength`, its velocity can never escape the
deadband. Break was capped at roughly `friction`, which is nothing next to putt speeds.

**Attempt 2: constant friction on the dominant axis only.** Cardinal slopes then worked,
but diagonal putts stopped breaking. Near 45° the two components are nearly equal, so each
frame the larger axis takes the full `friction` and the smaller takes none — which flips
which is larger, and repeats. That makes 45° a stable attractor: friction pins the
velocity direction to the diagonal and holds it there while the magnitude decays, so the
slope cannot curve the path. The vanilla "doesn't break" feel, reintroduced by the
friction model instead of by speed scaling.

The property that matters is that **friction must not rotate the velocity**. Real rolling
resistance opposes the velocity vector, so its components are in the same ratio as the
velocity's. Doing that exactly needs `friction * v_axis / |v|` — a magnitude and a divide,
neither of which fits.

The rule instead is: an axis takes the full `friction` if its `|v|` is at least
`(|vx| + |vy|) / 4`. That threshold is cheap (an add and two shifts) and gives the right
behavior at both ends:

| Angle off the axis | Friction on X | Friction on Y | Effect on direction |
|---|---|---|---|
| 0° (cardinal) | full | none | none — the cross axis is spared, so break builds |
| 10° | full | none | rotates slightly toward the smaller |
| 20°–70° | full | full | rotates slightly toward the larger |
| 40°–50° (diagonal) | full | full | **none — equal friction on equal components** |

45° is now an unstable point rather than an attractor, so a diagonal putt is free to be
steered by the slope. The cost is that diagonal putts take friction on both axes at once,
so their total deceleration is up to √2 times an axis-aligned putt's and they run roughly
a quarter shorter. That is the known artifact of an L∞ approximation and it is not worth a
divide to remove.

## Why the friction has to exist at all

`LD_B3BF_CheckStopped` (`$B3BF`) only declares the ball stopped once the roll budget
`$E4`/`$E6` is exhausted **and** both velocity mid-bytes are within ±1 of zero:

```
if ($E4 | $E6) != 0: return
if ($DB + $09) >= $09 * 2: return     ; on the green $09 = 1
if ($DE + $09) >= $09 * 2: return
-> BallStopped
```

Vanilla's rolling friction (`LD_B451`, which multiplies the velocity by `$09` = 1..3 and
subtracts) is *proportional*. Against a constant acceleration `a` it settles at a terminal
speed of `256 * a / $09`, which exceeds that threshold for any `a >= 1`, so a ball rolling
down the fall line would roll forever. Constant friction larger than the steepest slope's
acceleration is what brings it to rest — hence `friction` must exceed `strength`.
Vanilla's proportional friction still runs afterwards; together they are a reasonable
rolling-resistance-plus-drag model.

Friction acts on only one axis per frame, so putts run shorter than vanilla but not by as
much as the number suggests.

## Layout

The replaced region is self-contained. `$B1E4`, `$B1EB`, `$B21A` and `$B221` are branched
to only from inside it, and `$B245` has no references at all — it is reached purely by
falling out of the bottom. So all 112 bytes can go, provided the replacement jumps to
`$B245` when done.

The new code is 106 bytes; the remaining 6 are left as they were and are unreachable.
`$DA/$DB/$DC` (X velocity) and `$DD/$DE/$DF` (Y velocity) are three apart, as are
`$EA/$EB/$EC` and `$ED/$EE/$EF`, so one routine indexed by X = 0 or 3 handles both axes. The addend in `$20` is 8-bit
unsigned and the carry alone propagates into the mid and high bytes, so no second
addend byte is needed.

Two stale labels in the `.mlb` (`LD_B1E4_GreenSlopeX`, `LD_B21A_GreenSlopeY`) land
mid-instruction in the new code and will show up misplaced when disassembling a patched
ROM. They are correct for a vanilla ROM, so they are left alone.

## Not included

Two items from the same design do not fit an in-place patch:

- **Bilinear interpolation of the slope vector between tile centers.** Acceleration
  currently jumps as the ball crosses an 8-pixel boundary, so paths are faceted. This
  would be the biggest remaining visual improvement, but it needs more than the 6 spare
  bytes.
- **A per-course green-speed byte.** There is no data channel for it.

Vanilla's proportional friction is also left in place rather than removed, since `$09` is
computed at `$B245`, outside the replaced region.

## Status

Two rounds of playtesting, which caught both friction failures described above. The
threshold-split model is byte-verified but **not yet playtested**. `strength` and `friction` are exposed precisely because the
right values are a question for testing, not analysis.
