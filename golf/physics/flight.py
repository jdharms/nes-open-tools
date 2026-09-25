"""
Every frame, in the air or on the ground: motion, gravity and drag.

Then, in the air only, `ApplyWindEffect` ($B4FF): the wind's push, lift from
backspin and the hook or slice. Ported from bank 13 $AF46-$AFDF and $B4FF-$B6DC.
"""

from golf.physics.arith import (
    MASK8,
    MASK16,
    MASK24,
    MASK32,
    byte,
    halve,
    high_byte_of_negation,
    is_negative,
    mul8,
)
from golf.physics.state import Ball
from golf.physics.tables import PhysicsTables

#: Subtracted from `VerticalVelocity` every frame ($AF90), plus one more for
#: the `CLC / SBC` in `SubFromVerticalVelocity`.
GRAVITY = 0xE000

#: Wind strength grows with height up to this multiple of `WindSpeed`.
WIND_HEIGHT_CAP = 7


def move(ball: Ball, halvings: int = 0) -> None:
    """
    `ApplyVelocityToPosition` ($B78F): position += velocity. In the cup view
    the velocity is halved first (twice on a putt), each time rounding down.
    """
    vx, vy = ball.vx, ball.vy
    for _ in range(halvings):
        vx, vy = halve(vx), halve(vy)
    ball.x = (ball.x + vx) & MASK24
    ball.y = (ball.y + _sign_extend_y(vy)) & MASK32


def fall(ball: Ball) -> bool:
    """
    Gravity, then height += vertical speed. Returns True when the ball has
    reached the ground this frame, clamping the height to zero ($AF90-$AFA9).
    """
    ball.vz = (ball.vz - GRAVITY - 1) & MASK32
    ball.height = (ball.height + ball.vz) & MASK32
    if is_negative(ball.height, 32):
        ball.height = 0
        return True
    return False


def drag(ball: Ball) -> None:
    """
    Air resistance, applied on the ground too: each axis loses 1/256 of itself
    per frame, taken as the velocity's middle byte ($AFAC-$AFDF).
    """
    ball.vx = _drag_axis(ball.vx)
    ball.vy = _drag_axis(ball.vy)


def _drag_axis(v: int) -> int:
    if is_negative(v, 24):
        return (v + (-byte(v, 1) & MASK8)) & MASK24
    return (v - byte(v, 1)) & MASK24


def airborne(
    ball: Ball, tables: PhysicsTables, wind_direction: int, wind_speed: int
) -> None:
    """`ApplyWindEffect` ($B4FF): wind, backspin lift and curve for one air frame."""
    ball.wind_x, ball.wind_y = _wind_vector(ball, tables, wind_direction, wind_speed)

    if ball.wind_delay:
        ball.wind_delay -= 1
    if not ball.wind_delay:
        # The wind moves the ball directly, twice per frame, rather than
        # changing its velocity.
        for _ in range(2):
            ball.x = (ball.x + ball.wind_x) & MASK24
            ball.y = (ball.y + _sign_extend_y(ball.wind_y)) & MASK32

    # Lift and curve both act on the ball's speed through the air.
    air_x = (ball.vx - ball.wind_x) & MASK24
    air_y = (ball.vy - ball.wind_y) & MASK24
    _lift(ball, air_x, ball.backspin_x, ball.backspin_x_sign)
    _lift(ball, air_y, ball.backspin_y, ball.backspin_y_sign)
    _curve_from_x(ball, air_x)
    _curve_from_y(ball, air_y)


def _wind_vector(
    ball: Ball, tables: PhysicsTables, direction: int, speed: int
) -> tuple[int, int]:
    """
    The wind's push this frame, as ($EA-$EC, $ED-$EF).

    Strength is `WindSpeed` times a height factor, min(height/2 + 2, 7), using
    the height's integer byte. The Y component reads cos through `LE7C3`,
    which for directions with ($96 & $7F) >= $40 indexes past the sine table;
    see `tables.TRIG_TABLE`.
    """
    height_factor = min((byte(ball.height, 3) >> 1) + 2, WIND_HEIGHT_CAP)
    _, strength = mul8(height_factor, speed)
    angle = direction & 0x7F

    hi, lo = mul8(tables.trig[angle], strength)
    wind_x = (hi << 8 | lo) >> 3
    if wind_x and is_negative(direction, 8):
        wind_x = -wind_x & MASK24

    hi, lo = mul8(tables.cos_unmasked(angle), strength)
    wind_y = (hi << 8 | lo) >> 3
    if wind_y and not is_negative((direction + 0x40) & MASK8, 8):
        wind_y = -wind_y & MASK24
    return wind_x, wind_y


def _lift(ball: Ball, air: int, backspin: int, backspin_sign: int) -> None:
    """
    Backspin times airspeed along one axis, added to or taken from the
    vertical speed ($B5F1-$B623). Moving against the spin's direction lifts.
    """
    if is_negative(air, 24):
        moving_positive, speed = 0, -byte(air, 1) & MASK8
    else:
        moving_positive, speed = 1, byte(air, 1)
    hi, lo = mul8(speed, backspin)
    amount = ((hi << 8 | lo) << 3) & MASK16
    if moving_positive ^ backspin_sign:
        ball.vz = (ball.vz + amount) & MASK32
    else:
        ball.vz = (ball.vz - amount - 1) & MASK32


def _curve_from_x(ball: Ball, air_x: int) -> None:
    """Hook/slice: airspeed along X pushes Y velocity ($B657-$B695)."""
    if is_negative(air_x, 24):
        direction = ball.curve_direction ^ 1
        speed = high_byte_of_negation(air_x)
    else:
        direction = ball.curve_direction
        speed = byte(air_x, 1)
    hi, lo = mul8(speed, ball.curve)
    amount = hi
    if is_negative(byte(ball.vz, 2), 8):
        amount = (hi << 1 | lo >> 7) & MASK8
    if direction:
        ball.vy = (ball.vy + amount) & MASK24
    else:
        ball.vy = (ball.vy - amount) & MASK24


def _curve_from_y(ball: Ball, air_y: int) -> None:
    """
    Hook/slice: airspeed along Y pushes X velocity ($B696-$B6DC). On the way
    down this term roughly quadruples where the X-to-Y term only doubles, and
    its sign runs the other way.
    """
    if is_negative(air_y, 24):
        direction = ball.curve_direction ^ 1
        speed = high_byte_of_negation(air_y)
    else:
        direction = ball.curve_direction
        speed = byte(air_y, 1)
    hi, lo = mul8(speed, ball.curve)
    amount = hi
    if is_negative(byte(ball.vz, 2), 8):
        doubled = (hi << 1 | lo >> 7) & MASK8
        amount = (hi >> 6 & 1) << 8 | (doubled << 1) & MASK8
    if direction:
        ball.vx = (ball.vx - amount) & MASK24
    else:
        ball.vx = (ball.vx + amount) & MASK24


def _sign_extend_y(v: int) -> int:
    """A 24-bit Y term widened to 32 bits the way the game adds it: top byte twice."""
    return v | byte(v, 2) << 24
