"""
Wind anchors patch: give every hole the wind direction and speed the build names.

Vanilla `InitHole` ends by drawing the hole's two wind anchors from the RNG
(`docs/wind.md`, **Hole anchors**):

    $DBA0  JSR LSFR_RNG_ALGO
    $DBA3  AND #$F0
    $DBA5  STA WindDirectionAnchor
    $DBA8  JSR LSFR_RNG_ALGO
    $DBAB  AND #$0F
    $DBAD  CMP #$0B
    $DBAF  BCC StoreWindSpeed
    $DBB1  SBC #$08
    $DBB3  STA WindSpeedAnchor

Neighboring draws of the RNG share bits, so only 64 of the 176 (direction, speed)
pairs can come up, and which one depends on nothing a build controls but the hole's
seed. This patch replaces those 22 bytes with a read from a table:

    JSR LSFR_RNG_ALGO          ; both draws kept, their results unused
    JSR LSFR_RNG_ALGO
    LDX TempX                  ; the doubled global hole index, saved at $DAEF
    LDA WindAnchorTable,X
    STA WindDirectionAnchor
    LDA WindAnchorTable+1,X
    STA WindSpeedAnchor
    NOP
    NOP

The two draws stay so that `RngState` leaves `InitHole` exactly as it does without the
patch. Bank 13 copies that state into both players' wind slots, so a hole's pin and
every swing's jitter are what its `seeded_wind` seed gives either way; only the anchors
change source. `InitHole` itself reloads X from `TempX` at $DB8A, just before the
terrain attribute copy that ends at $DB9E, so `TempX` still holds the index here.

The table is two bytes a hole, direction then speed, for the course's 18 holes at
$E00B-$E02E: the second half of the course-3 block of `GreenFlagXTable`, whose first
half is `seeded_wind`'s seed table. The block is dead once `COURSE_MIRRORS_PATCH` is
applied, which this patch requires.

`golf.core.rng.predict_hole` models the chain: pass it the hole's `anchors`.
"""

from collections.abc import Sequence

from golf.core import rom_utils
from golf.core.asm6502 import assemble

from .byte_patch import BytePatch
from .composite import CompositePatch
from .multi_bank import COURSE_MIRRORS_PATCH

ANCHOR_TABLE_CPU_ADDR = 0xE00B  # GreenFlagXTable ($DF57) + 45 holes * 4 bytes
ANCHOR_TABLE_HOLES = 18
#: a direction is an angle byte in steps of $10, clockwise from $00, up the screen
DIRECTIONS = range(0x00, 0x100, 0x10)
#: the speed anchors vanilla deals
SPEEDS = range(11)

# Vanilla UK flag X offsets the anchor table overwrites (holes 45-53).
_ANCHOR_TABLE_VANILLA = bytes.fromhex(
    "57542D7E 68387C68 5F278738 68684048 68375F77 50308868 305F6E38 62385E36 58804080"
)
assert len(_ANCHOR_TABLE_VANILLA) == ANCHOR_TABLE_HOLES * 2

_DRAW_CPU_ADDR = 0xDBA0
_DRAW_ORIGINAL = bytes.fromhex(
    "209CD2"  # JSR LSFR_RNG_ALGO
    "29F0"  # AND #$F0
    "8D2F01"  # STA WindDirectionAnchor
    "209CD2"  # JSR LSFR_RNG_ALGO
    "290F"  # AND #$0F
    "C90B"  # CMP #$0B
    "9002"  # BCC StoreWindSpeed
    "E908"  # SBC #$08
    "8D3001"  # STA WindSpeedAnchor
)

_DRAW_SOURCE = """
    jsr LSFR_RNG_ALGO
    jsr LSFR_RNG_ALGO
    ldx TempX
    lda WindAnchorTable,x
    sta WindDirectionAnchor
    lda WindAnchorTable+1,x
    sta WindSpeedAnchor
    nop
    nop
"""
_DRAW_PATCHED = assemble(
    _DRAW_SOURCE,
    _DRAW_CPU_ADDR,
    {
        "LSFR_RNG_ALGO": 0xD29C,
        "TempX": 0x31,
        "WindAnchorTable": ANCHOR_TABLE_CPU_ADDR,
        "WindDirectionAnchor": 0x012F,
        "WindSpeedAnchor": 0x0130,
    },
).code
assert len(_DRAW_PATCHED) == len(_DRAW_ORIGINAL)


def anchor_table_bytes(anchors: Sequence[tuple[int, int]]) -> bytes:
    """Lay out (direction, speed) pairs as the ROM table, two bytes a hole."""
    if len(anchors) != ANCHOR_TABLE_HOLES:
        raise ValueError(f"need {ANCHOR_TABLE_HOLES} wind anchors, got {len(anchors)}")
    out = bytearray()
    for direction, speed in anchors:
        if direction not in DIRECTIONS:
            raise ValueError(
                f"wind direction must be a multiple of $10 from $00 to $F0, got {direction!r}"
            )
        if speed not in SPEEDS:
            raise ValueError(f"wind speed anchor must be 0-10, got {speed!r}")
        out += bytes([direction, speed])
    return bytes(out)


def wind_anchors_patches(anchors: Sequence[tuple[int, int]]) -> list[BytePatch]:
    """The table, then the read: a partly applied ROM never reads a table that isn't there."""
    return [
        BytePatch(
            name="wind_anchors_table",
            description=(
                f"Per-hole wind anchor table ({ANCHOR_TABLE_HOLES} holes) in the course-3 "
                f"block of GreenFlagXTable at ${ANCHOR_TABLE_CPU_ADDR:04X}"
            ),
            prg_offset=rom_utils.cpu_to_prg_fixed(ANCHOR_TABLE_CPU_ADDR),
            original=_ANCHOR_TABLE_VANILLA,
            patched=anchor_table_bytes(anchors),
        ),
        BytePatch(
            name="wind_anchors_init_hole",
            description="InitHole: read the wind anchors from the table instead of drawing them",
            prg_offset=rom_utils.cpu_to_prg_fixed(_DRAW_CPU_ADDR),
            original=_DRAW_ORIGINAL,
            patched=_DRAW_PATCHED,
        ),
    ]


def wind_anchors_patch(
    anchors: Sequence[tuple[int, int]],
) -> CompositePatch[BytePatch]:
    """
    The wind anchors patch set as one CompositePatch.

    `anchors` is 18 (direction, speed) pairs in hole order. Requires
    COURSE_MIRRORS_PATCH: the table overwrites the UK course's flag X offsets,
    which are live without it.
    """
    return CompositePatch(
        name="wind_anchors",
        description="Set each hole's wind direction and speed anchors from a table",
        patches=wind_anchors_patches(anchors),
        requires=[COURSE_MIRRORS_PATCH],
    )
