"""
Relocate the terrain attribute buffer from internal RAM into reclaimed WRAM,
and grow it from 72 bytes to 90.

Vanilla copies each hole's attributes into `TerrainAttrs` at $0533-$057A
when the hole loads (`LoadTerrainAndAttrs`, `LDY #$47` down to 0). That is
6 bytes per attribute row x 12 rows, enough for 48 terrain rows; a 60-row
hole needs 15 rows, 90 bytes, and the 11 unlabeled bytes after the buffer
aren't enough to grow it in place (`SwingPhaseState` is at $0586).

The new buffer is WRAM $0F9C-$0FF5 (CPU $6F9C-$6FF5), at the start of the
226-byte gap this effort reclaimed before the relocated terrain buffer at
$107E. Nothing reads that gap during play - see docs/wram_expansion.md for
why the replay reader at $F6CE can't run. Starting at the bottom of the gap
leaves the rest of it (`$0FF6`-`$107D`) touching the terrain buffer, which
grows backward, should holes ever get taller than 60 rows.

The copy always moves 90 bytes. A shorter hole's attributes are followed in
ROM by the next hole's data or the bank's tables, so the extra bytes are
copied but never read back - the same thing vanilla does with its fixed
72-byte window.

Every site that touches the buffer is an absolute,Y instruction, so each
patch is an operand change with no length change:

- `LoadTerrainAndAttrs` copy loop ($DB96/$DB9A): the count and the store.
- `LE451` windowing routine ($E4A7/$E4B7/$E4D9): three reads.
- `LEED5` ball-lie calculation ($EF04): one read. It runs 1,280 times while
  the pre-swing perspective view builds its grid, which is why the buffer
  lives in RAM rather than being read out of the terrain bank.
"""

from ..byte_patch import BytePatch

ATTR_BUFFER_ADDR = 0x6F9C
ATTR_BUFFER_SIZE = 90

_VANILLA_OPERAND = bytes([0x33, 0x05])  # TerrainAttrs, $0533
_NEW_OPERAND = ATTR_BUFFER_ADDR.to_bytes(2, "little")

ATTR_BUFFER_COPY_COUNT_PATCH = BytePatch(
    name="wram_expansion_attr_buffer_copy_count",
    description="$DB97: LDY #$47 -> LDY #$59 (copy 90 attribute bytes)",
    prg_offset=0x3DB97,
    original=bytes([0x47]),
    patched=bytes([ATTR_BUFFER_SIZE - 1]),
)

ATTR_BUFFER_COPY_STORE_PATCH = BytePatch(
    name="wram_expansion_attr_buffer_copy_store",
    description="$DB9A: STA $0533,Y -> STA $6F9C,Y (LoadTerrainAndAttrs copy)",
    prg_offset=0x3DB9B,
    original=_VANILLA_OPERAND,
    patched=_NEW_OPERAND,
)

ATTR_BUFFER_WINDOWING_READ_PATCHES = [
    BytePatch(
        name=f"wram_expansion_attr_buffer_windowing_read_{i + 1}",
        description=f"${offset - 0x30001:04X}: LDA $0533,Y -> LDA $6F9C,Y (LE451)",
        prg_offset=offset,
        original=_VANILLA_OPERAND,
        patched=_NEW_OPERAND,
    )
    for i, offset in enumerate([0x3E4A8, 0x3E4B8, 0x3E4DA])
]

ATTR_BUFFER_BALL_LIE_READ_PATCH = BytePatch(
    name="wram_expansion_attr_buffer_ball_lie_read",
    description="$EF04: LDA $0533,Y -> LDA $6F9C,Y (LEED5 ball lie)",
    prg_offset=0x3EF05,
    original=_VANILLA_OPERAND,
    patched=_NEW_OPERAND,
)

RELOCATE_ATTR_BUFFER_PATCHES = [
    ATTR_BUFFER_COPY_COUNT_PATCH,
    ATTR_BUFFER_COPY_STORE_PATCH,
    *ATTR_BUFFER_WINDOWING_READ_PATCHES,
    ATTR_BUFFER_BALL_LIE_READ_PATCH,
]
