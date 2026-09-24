"""
The in-flight distance readout: `LD_A246` and `DistanceBetweenPoints` ($E522).

The yards shown while the ball flies are twice the whole-pixel distance from
the shot's origin. Its low byte, `$057D`, also decides when the behind-the-golfer
view gives way to the overhead one ($3D pixels, about 122 yards).
"""

from golf.physics.arith import MASK8, MASK16, MASK24


def integer_sqrt(target: int) -> int:
    """
    `IntegerSqrt` ($E5EE): a binary search from 256 in halving steps, stopping
    on an exact square or when the step runs out. Squares are compared on
    their low 24 bits. Not always the floor of the square root.
    """
    guess, step = 0x100, 0x100
    while True:
        square = guess * guess & MASK24
        if square == target:
            return guess
        step >>= 1
        if not step:
            return guess
        if target >= square:
            guess += step
            if guess > MASK16:
                guess = (guess - step) & MASK16
                guess = (guess - step) & MASK16
        else:
            guess -= step


def distance_between_points(x1: int, y1: int, x2: int, y2: int) -> int:
    """`DistanceBetweenPoints`: x as bytes, y as 16 bits, whole pixels."""
    dx = abs(x1 - x2) if x1 >= x2 else (x2 - x1) & MASK8
    dy = (y1 - y2) & MASK16 if y1 >= y2 else (y2 - y1) & MASK16
    target = (dx * dx + (dy * dy & MASK24)) & MASK24
    return integer_sqrt(target) if target else 0
