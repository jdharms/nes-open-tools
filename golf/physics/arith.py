"""
The handful of byte-level operations the physics code is built from.

The game keeps every quantity as a little-endian multi-byte register and does
its arithmetic a byte at a time. Most of that is ordinary integer arithmetic
modulo 2^n, and the port writes it that way. These helpers cover the places
where the byte structure itself changes the answer: an 8x8 multiply that keeps
only one half of its product, a term taken from the middle byte of a register,
a negation that only reaches two of three bytes.
"""

MASK8 = 0xFF
MASK16 = 0xFFFF
MASK24 = 0xFFFFFF
MASK32 = 0xFFFFFFFF


def mul8(a: int, b: int) -> tuple[int, int]:
    """`Mult8x8to16` ($E743): the unsigned product of two bytes, as (hi, lo)."""
    product = (a & MASK8) * (b & MASK8)
    return product >> 8, product & MASK8


def byte(value: int, index: int) -> int:
    """Byte `index` of a register, 0 being the lowest ($DA of $DA-$DC)."""
    return (value >> (8 * index)) & MASK8


def is_negative(value: int, bits: int) -> bool:
    """Whether a two's-complement register of `bits` width has its sign bit set."""
    return bool(value >> (bits - 1) & 1)


def signed(value: int, bits: int) -> int:
    """A two's-complement register as a Python int."""
    return value - (1 << bits) if is_negative(value, bits) else value


def high_byte_of_negation(value: int) -> int:
    """
    `LDA #0 / SEC / SBC lo / LDA #0 / SBC mid`: the middle byte of a 16-bit
    negation, the game's way of taking |v| of a negative velocity's mid byte.
    """
    return byte(-value & MASK16, 1)
