"""
Ground contact: bounce, roll and stopping.

`ProcessLanding` ($B11F) runs on every frame the ball touches the ground, which
once it is rolling is every frame: gravity pulls the vertical speed below zero,
the height goes negative, and the frame counts as a landing again.

Each contact frame:

1. **First contact only**: a small random sideways kick on fairway or light
   rough, and on the green the extra stopping power of BACK 1/BACK 2.
2. **Bounce**: vertical speed reverses and keeps 3/8 of itself. Once that
   leaves nothing in its top byte the ball is rolling.
3. **Lie**: friction takes k/256 of the velocity, with k set by the lie, and a
   larger one-off k on first contact. On the green the slope pushes the ball.
   The remaining backspin brakes the roll, and a per-lie amount is spent.
4. **Stop test**: no backspin left and both velocities within a few 256ths of
   a pixel per frame of zero.
"""

from golf.core.rng import lfsr_step
from golf.physics.arith import (
    MASK8,
    MASK16,
    MASK24,
    MASK32,
    byte,
    is_negative,
    mul8,
)
from golf.physics.state import Ball, Lie, ShotInput, Spin
from golf.physics.tables import PhysicsTables

#: `BounceState` once the ball has touched down.
IN_CONTACT = 1

#: Backspin budgets at or above this after spending are treated as underflowed.
SPIN_UNDERFLOW = 0xF0

#: Lowest club number that gets the green backspin bonus.
FIRST_SPIN_CLUB = 4


def contact(ball: Ball, shot: ShotInput, tables: PhysicsTables, hi_lo: int) -> None:
    """One ground-contact frame of `ProcessLanding`."""
    first = ball.bounce_state == 0
    if first:
        _first_contact(ball, shot, tables)
    ball.curve = 0
    ball.landing_processed = 1
    _bounce(ball)

    if ball.lie == Lie.GREEN:
        _green(ball, first, hi_lo)
    elif ball.lie < Lie.ROUGH:
        _fairway(ball, first, hi_lo, shot.spin)
    elif ball.lie == Lie.ROUGH:
        friction = 4
        k = ball.rough_depth * 4 + 0x0F
        if first:
            k = ball.penalty + 0x40
            if k > MASK8:
                k = 0xF0
        _roll(ball, friction, k, hi_lo, spend=5)
    elif ball.lie == Lie.BUNKER:
        _bunker(ball, first, tables, hi_lo)
    elif ball.lie == Lie.WATER:
        _water(ball, hi_lo)
    elif ball.lie == Lie.OUT_OF_BOUNDS:
        _roll(ball, 6, 0x70 if first else 0x14, hi_lo, spend=8)
    else:
        raise ValueError(f"no landing behaviour for lie {ball.lie}")


def _first_contact(ball: Ball, shot: ShotInput, tables: PhysicsTables) -> None:
    """$B12C-$B17E: the one-off effects of the first bounce."""
    if ball.lie < Lie.ROUGH:
        _kick(ball, 0, tables)
    elif ball.lie == Lie.ROUGH and ball.rough_depth == 0:
        _kick(ball, 3, tables)

    # BACK 1/BACK 2 bite on the green, but only for the irons and wedges and
    # only for shots that did not start in the rough (`LD_B14A_CheckSpinEffect`).
    if (
        shot.club >= FIRST_SPIN_CLUB
        and shot.spin >= Spin.BACK_1
        and ball.lie == Lie.GREEN
        and ball.launch_lie != Lie.ROUGH
    ):
        if shot.spin == Spin.BACK_2:
            ball.backspin_x = ball.backspin_x << 1 & MASK8
            ball.backspin_y = ball.backspin_y << 1 & MASK8
        else:
            ball.backspin_x = _one_and_a_half(ball.backspin_x)
            ball.backspin_y = _one_and_a_half(ball.backspin_y)


def _one_and_a_half(v: int) -> int:
    """
    `ASL / ADC / LSR` at $B16F: roughly 1.5x, but the ASL's carry feeds the ADC
    and the ADC's carry is lost, so large budgets wrap.
    """
    return ((((v << 1) & MASK8) + v + (v >> 7)) & MASK8) >> 1


def _kick(ball: Ball, row: int, tables: PhysicsTables) -> None:
    """
    `LD_B952`: a random sideways nudge proportional to the ball's Y speed.
    Reads the RNG state without advancing it.
    """
    strength, _ = mul8(tables.landing_kick[row + ball.launch_depth], ball.rng_state)
    speed_y = byte(ball.vy, 1)
    if is_negative(ball.vy, 24):
        speed_y = -speed_y & MASK8
    hi, lo = mul8(strength, speed_y)
    amount = hi << 8 | lo
    if not amount:
        return
    if is_negative(ball.rng_state, 16):
        amount = -amount & MASK24
    ball.vx = (ball.vx + amount) & MASK24


def _bounce(ball: Ball) -> None:
    """`LD_B17F_ApplyBounce`: reverse the fall and keep 3/8 of it."""
    ball.vz = -ball.vz & MASK32
    if is_negative(ball.vz, 32):
        return
    # Only the low three bytes are shifted and subtracted; $E3 is left alone.
    top = ball.vz & ~MASK24 & MASK32
    half = (ball.vz & MASK24) >> 1
    low = (half - (half >> 2)) & MASK24
    if not byte(low, 2):
        low = 0
    ball.vz = top | low


def _green(ball: Ball, first: bool, hi_lo: int) -> None:
    """`LD_B1D5_Green`: slope, then friction 1, with a first-contact grab."""
    _green_slope_axis(ball, x_axis=True)
    _green_slope_axis(ball, x_axis=False)
    k = 1
    if not is_negative(hi_lo, 8):
        k = 2 if hi_lo == 0 else 3
        if first:
            k = (ball.penalty + 0x20) & MASK8
    if is_negative(ball.green_flags, 8):
        k = (k + 7) & MASK8
    _roll(ball, 1, k, hi_lo, spend=1)


def _green_slope_axis(ball: Ball, x_axis: bool) -> None:
    """
    One half of the vanilla slope push (see `docs/green_slope_physics.md`):
    a direct term along this axis, a five-times cross term on the other, then
    the cross term reused as drag on this axis.
    """
    own = ball.vx if x_axis else ball.vy
    own_slope, cross_slope = (
        (ball.wind_x, ball.wind_y) if x_axis else (ball.wind_y, ball.wind_x)
    )
    speed = byte(own, 1)
    if is_negative(own, 24):
        speed = -speed & MASK8
    factor = min(speed << 1 & MASK8, 0x40) << 1

    hi, _ = mul8(factor, byte(own_slope, 1))
    own = _add_signed(own, hi >> 1, is_negative(own_slope, 24))
    hi, lo = mul8(factor, byte(cross_slope, 1))
    cross_term = _slope_scale(hi, lo, ball.green_flags)
    cross = ball.vy if x_axis else ball.vx
    cross = _add_signed(cross, cross_term, is_negative(cross_slope, 24))
    own = _add_signed(own, cross_term, not is_negative(own, 24))

    if x_axis:
        ball.vx, ball.vy = own, cross
    else:
        ball.vy, ball.vx = own, cross


def _slope_scale(hi: int, lo: int, green_flags: int) -> int:
    """`LD_B6DD`: x2 with bit 6 of $CA set, otherwise x2.5, all in 8 bits."""
    if green_flags & 0x40:
        return (hi << 1 | lo >> 7) & MASK8
    half = hi >> 1 | hi & 0x80
    return ((hi << 1 & MASK8) + half) & MASK8


def _add_signed(v: int, amount: int, subtract: bool) -> int:
    """`AddToVelocityDelta*_CheckSign`: an 8-bit amount, added or subtracted."""
    return (v - amount if subtract else v + amount) & MASK24


def _fairway(ball: Ball, first: bool, hi_lo: int, spin: Spin) -> None:
    """`LD_B271_Fairway`: friction 2, with a random grab on first contact."""
    if hi_lo == 0:
        k = 6
    elif is_negative(hi_lo, 8):
        k = 4
    else:
        k = 7
    if first:
        # A coin flip on the RNG's low bit, which the ADCs below also carry.
        coin = ball.rng_state & 1
        k = 0x30 if coin else 0x50
        if is_negative(hi_lo, 8):
            k += 0x10 + coin
        else:
            if hi_lo:
                k += 0x40 + coin
            if spin >= Spin.BACK_1:
                k = ball.penalty
    _roll(ball, 2, k, hi_lo, spend=2)


def _bunker(ball: Ball, first: bool, tables: PhysicsTables, hi_lo: int) -> None:
    """
    `LD_B2DF_Bunker`: sand kills the bounce and the spin. A hard enough
    landing plugs the ball where it is; otherwise it skids to a stop.
    """
    impact = byte(ball.vz, 2)
    ball.vz = 0
    ball.backspin_x = ball.backspin_y = 0
    severity = 0 if impact < 0x0C else 1 if impact < 0x19 else 2
    draw = ball.rng_state & MASK8
    ball.bunker_depth = 0
    if draw >= tables.bunker_plug_first[severity]:
        ball.bunker_depth = 1
        if draw >= tables.bunker_plug_second[severity]:
            ball.bunker_depth = 2
    if severity:
        # Plugged: the splash animation, then `DrawCourseGameplayView`, whose
        # `LD_9AEF` sets the overhead view and `LD_A170` zeroes the readout.
        ball.view = 0
        if not ball.pixel_y & 0x8000 and ball.pixel_x < 0xB0:
            ball.shot_distance = 0
        stop(ball)
        return
    _friction(ball, 0x60 if first else 0x14, hi_lo)
    _finish(ball, friction=6)


def _water(ball: Ball, hi_lo: int) -> None:
    """`LD_B342_Water`: one chance in ten or so of a skip off a shallow landing."""
    state = ball.water_skip_state
    if state == 0:
        stop(ball)
        return
    if is_negative(state, 8):
        if byte(ball.vz, 2) >= 0x30:
            stop(ball)
            return
        ball.rng_state, draw = lfsr_step(ball.rng_state)
        if draw < 0xE6:
            stop(ball)
            return
        state = 1
    ball.water_skip_state = state - 1
    ball.vz = (ball.vz & MASK24) >> 1 | ball.vz & ~MASK24 & MASK32
    _roll(ball, 3, 3, hi_lo, spend=4)


def _roll(ball: Ball, friction: int, k: int, hi_lo: int, spend: int) -> None:
    """Friction k/256, the backspin brake, spend the spin, then the stop test."""
    _friction(ball, k, hi_lo)
    _backspin_brake(ball)
    ball.backspin_x = (ball.backspin_x - spend) & MASK8
    ball.backspin_y = (ball.backspin_y - spend) & MASK8
    _finish(ball, friction)


def _friction(ball: Ball, k: int, hi_lo: int) -> None:
    """
    `LD_B451`: each axis loses k/256 of itself. A low shot softens a big
    first-contact k by up to $3F.
    """
    if k >= 0x40 and is_negative(hi_lo, 8):
        k = (k - min(-hi_lo << 4 & MASK8, 0x3F)) & MASK8
    ball.vx = _friction_axis(ball.vx, k)
    ball.vy = _friction_axis(ball.vy, k)


def _friction_axis(v: int, k: int) -> int:
    negative = is_negative(v, 24)
    magnitude = (-v if negative else v) & MASK16
    carry_in, _ = mul8(magnitude & MASK8, k)
    hi, lo = mul8(magnitude >> 8, k)
    amount = (hi << 8 | lo) + carry_in
    amount &= MASK16
    return (v + amount if negative else v - amount) & MASK24


def _backspin_brake(ball: Ball) -> None:
    """`LD_B4B2`: 1.5x the remaining backspin pushes against the roll."""
    for axis in ("x", "y"):
        spin = getattr(ball, f"backspin_{axis}")
        amount = ((spin >> 1) + spin + (spin & 1)) & MASK8
        v = getattr(ball, f"v{axis}")
        if getattr(ball, f"backspin_{axis}_sign"):
            v = (v + amount) & MASK24
        else:
            v = (v - amount) & MASK24
        setattr(ball, f"v{axis}", v)


def _finish(ball: Ball, friction: int) -> None:
    """`LD_B3A6_Finalize` and `LD_B3BF_CheckStopped`."""
    ball.bounce_state = IN_CONTACT
    if ball.backspin_x >= SPIN_UNDERFLOW:
        ball.backspin_x = 0
    if ball.backspin_y >= SPIN_UNDERFLOW:
        ball.backspin_y = 0
    if ball.backspin_x or ball.backspin_y:
        return
    window = friction * 2
    if (byte(ball.vx, 1) + friction) & MASK8 >= window:
        return
    if (byte(ball.vy, 1) + friction) & MASK8 >= window:
        return
    stop(ball)


def stop(ball: Ball) -> None:
    """`LD_B3DC_BallStopped`, which also zeroes both ground velocities."""
    ball.bounce_state = 2
    ball.stopped = True
    ball.vx = ball.vy = 0
