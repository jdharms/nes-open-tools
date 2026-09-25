"""
The game's random number generator, `LSFR_RNG_ALGO` ($D29C), and what
`InitHole` and `WindAdjustmentRoutine` ($DA25) make of it: the pin, the wind
anchors and each swing's wind. `docs/seeded_wind.md` traces the chain.

Kept apart from the patches that use it (`golf.core.patches.seeded_wind`) so
that the ball physics (`golf.physics`) depends on nothing but plain Python:
the difficulty solver's workers can then run under PyPy
(`docs/planning/hole_difficulty.md`).
"""

from dataclasses import dataclass


def lfsr_step(state: int) -> tuple[int, int]:
    """
    One call of LSFR_RNG_ALGO ($D29C).

    `state` is ($43 << 8) | $42. Returns (new_state, A), where A is the
    routine's return value (the new $42).
    """
    lo, hi = state & 0xFF, (state >> 8) & 0xFF
    a = 0x35
    for _ in range(11):
        c = lo >> 7
        lo = (lo << 1) & 0xFF  # ASL $42
        c, hi = hi >> 7, ((hi << 1) | c) & 0xFF  # ROL $43
        c, a = a >> 7, ((a << 1) | c) & 0xFF  # ROL A
        c, a = a >> 7, ((a << 1) | c) & 0xFF  # ROL A
        a ^= lo  # EOR $42
        c, a = a >> 7, ((a << 1) | c) & 0xFF  # ROL A
        a ^= lo  # EOR $42
        a >>= 2  # LSR A; LSR A
        a = (a ^ 0xFF) & 0x01  # EOR #$FF; AND #$01
        lo |= a  # ORA $42; STA $42
    return (hi << 8) | lo, lo


def wind_jitter(a: int) -> int:
    """Map an RNG byte to WindAdjustmentRoutine's speed jitter (-1..+2)."""
    r = (a & 0x07) >> 1
    if r == 0:
        return 0
    # SBC #$01 with C = bit 0 shifted out by the LSR
    return r - 1 if (a & 1) else r - 2


def apply_jitter(
    direction_anchor: int, speed_anchor: int, jitter: int
) -> tuple[int, int]:
    """
    WindAdjustmentRoutine after its draw: the anchors plus a speed jitter, as
    (direction, speed). A negative speed turns the wind round at speed 1, and
    10 or more comes down by 5 until it is not.
    """
    direction = direction_anchor
    speed = (speed_anchor + jitter) & 0xFF
    if speed & 0x80:
        direction ^= 0x80
        speed = 1
    while speed >= 10:
        speed -= 5
    return direction, speed


def wind_adjust(
    state: int, direction_anchor: int, speed_anchor: int
) -> tuple[int, int, int]:
    """One WindAdjustmentRoutine call. Returns (new_state, direction, speed)."""
    state, a = lfsr_step(state)
    direction, speed = apply_jitter(direction_anchor, speed_anchor, wind_jitter(a))
    return state, direction, speed


@dataclass
class HoleWindForecast:
    seed: int
    pin_index: int  # 0-3, which of the hole's 4 flag positions
    direction_anchor: int  # WindDirectionAnchor ($012F): high nibble, bit 7 = reversed
    speed_anchor: int  # WindSpeedAnchor ($0130): 0-10
    slot_state: int  # value both wind slots hold after InitHole (($0527<<8)|$0525)
    winds: list[tuple[int, int]]  # per swing: (WindDirection $96, WindSpeed $97)


def predict_hole(seed: int, swings: int = 12) -> HoleWindForecast:
    """Predict a hole's pin, anchors and first `swings` wind values from its seed."""
    state, a = lfsr_step(seed)
    pin_index = a & 0x03
    state, a = lfsr_step(state)
    direction_anchor = a & 0xF0
    state, a = lfsr_step(state)
    speed_anchor = a & 0x0F
    if speed_anchor >= 0x0B:
        speed_anchor -= 8
    slot_state = state

    winds = []
    for _ in range(swings):
        state, direction, speed = wind_adjust(state, direction_anchor, speed_anchor)
        winds.append((direction, speed))

    return HoleWindForecast(
        seed=seed,
        pin_index=pin_index,
        direction_anchor=direction_anchor,
        speed_anchor=speed_anchor,
        slot_state=slot_state,
        winds=winds,
    )
