"""
Wind fix: make the wind push the ball the way its arrow points.

`TrigLookupTable` (fixed `$E7CB`) holds 128 bytes of |sin| over a half turn. `LE7C3`
(`$E7C3`) reads cos(a) from it as `table[a + $40]` and never wraps the index, so an
angle of `$40`-`$7F` reads up to 64 bytes past the table, into the opcodes of
`Divide16`. `ApplyWindEffect` (bank 13 `$B55F`) passes it `WindDirection & $7F`, so the
wind's Y component is wrong for the eight directions `$40`-`$70` and `$C0`-`$F0`
(`docs/wind.md`, **The crosswind bug**).

For an angle of `$00`-`$7F`, `(a + $40) mod $80` is `a EOR $40`, and the EOR is a byte
shorter than the add it replaces:

    $E7C3  18 69 40   CLC / ADC #$40    ->    49 40 EA   EOR #$40 / NOP

`LE7C6` (`TAX / LDA TrigLookupTable,X / RTS`) stays at `$E7C6`, where `RotateVector16`
calls it with indexes it has already masked.

`LE7C3` has one other caller, `CalcLaunchVector` at bank 13 `$AEA2`, which passes the
launch angle: `ClubLoftIndexTable[club]` plus or minus `ClubHiLoStepTable[club]`,
`$00`-`$27`. Below `$40` the add and the EOR give the same index, so launches are
unchanged. `find-refs` shows no third reference, which is static analysis only. jdharms
played a build 6 seed with the wind at 9 left and 9 right, and the drift looked correct
(`docs/wind.md`, **Not verified**).

The Python physics model (`golf/physics/`) ports the vanilla lookup, overrun included,
so it does not describe the wind on a ROM with this patch (`docs/shot_physics.md`).
"""

from golf.core import rom_utils

from .byte_patch import BytePatch

COS_LOOKUP_ADDR = 0xE7C3  # LE7C3
VANILLA_COS_LOOKUP = bytes([0x18, 0x69, 0x40])  # CLC / ADC #$40
FIXED_COS_LOOKUP = bytes([0x49, 0x40, 0xEA])  # EOR #$40 / NOP

WIND_FIX_PATCH = BytePatch(
    name="wind_fix",
    description="Wrap the cos lookup so crosswinds push the way their arrow points",
    prg_offset=rom_utils.cpu_to_prg_fixed(COS_LOOKUP_ADDR),
    original=VANILLA_COS_LOOKUP,
    patched=FIXED_COS_LOOKUP,
)
