"""
Swing speed on the swing view HUD.

Quality-of-life patch: the club box at the bottom left of the behind-the-golfer
view shows the swing speed chosen on the overhead view, as S, M or F after the
club name (`1W S`), so a player who has forgotten it does not have to back out
to the course view to check. See docs/swing_speed_hud.md.

The HUD
-------

Bank 13 `$A499` draws the HUD once each time the swing view opens. It copies the
68-byte descriptor template at `$A519` to `$0410` (rows 26-27, PPU `$2340`),
pokes the club name's two tiles into `$0417`/`$0418` (columns 3-4 of the 4-tile
box), and flushes it with `WriteNametableTiles`. This patch moves the club name
to columns 2-3 and puts the speed letter in column 5 (`$0419`).

`SwingSpeed` (`$CE`) is set by the overhead view's speed panel and never changes
inside the swing view: B backs out only as far as the club and spin panels, and
reaching the speed panel again means returning to the overhead view, which runs
`$A499` again on the way back. So drawing the letter once is enough.

The F
-----

The swing view's background tiles (bank 4 `$A8A4`, loaded only at bank 5
`$BDCE`) hold digits and only the letters the HUD's own strings use, with no F.
Tile `$11`, a comma, is used only by the `MID,` hi/lo label, so this patch turns
it into an F and blanks the label's two commas (`$A503` in the static label row,
`$A5A0` in the hi/lo descriptor `$A57D` redraws).

The tile is stored in a compressed stream (`golf/core/graphics_codec.py`), so the
edit is a re-encoding of the 8 bytes at `$AA92` that write PPU `$110F`-`$1127`,
at the same length so nothing after it moves:

    vanilla  2D 00        run of 14 zeros       $110F-$111C
             02 18 18 08  3 literal bytes       $111D-$111F  (the comma)
             27 00        run of 8 zeros        $1120-$1127
    patched  8D 00 CF     copy 14 from $10CF    $110F-$111C  (the E's top half)
             21 80        run of 2 x $80        $111D-$111E  (the F's stem)
             E4 08 00     long run of 9 zeros   $111F-$1127

The copy works because the E (tile `$0D`) shares its top five rows with an F,
and the eight zero bytes before them match the comma's empty first plane.

Two later lookback copies in the same stream read bytes of the old comma, so
they are pointed at identical bytes earlier in the table: `$AB85` (part of tile
`$2B`, the HUD's divider) and `$AE2D` (part of scene tile `$84`). Their offsets
are relative to the stream's base, `$1000`, and wrap below it; the decoder's
16-bit `ADC` at `$D5A3` wraps the same way. Decoding the patched table changes
exactly PPU `$1118`-`$111F`, the comma's second plane
(tests/integration/test_swing_speed_hud_rom.py).

Where the new code goes
-----------------------

The randomizer's stack already fills bank 13's tail padding and the fixed bank's
`$CA40` block, so the hook takes the start of `StoreBallHeadingAndPinDistance`
(`$BAD2`-`$BB6C`), a routine with no caller that a Mesen sweep never saw run
(ADR 0030). `TestBallScreenYVisible` (`$8FA3`) is also dead but
`wram_expansion` rewrites an operand inside it.
"""

from golf.core import rom_utils
from golf.core.asm6502 import Program, assemble

from .byte_patch import BytePatch
from .composite import CompositePatch

# --- The tile -----------------------------------------------------------------

TILE_BANK = 4

#: The opcodes in `ChrGraphicsTable4A8A4`'s second stream that write PPU
#: $110F-$1127, tile $11 (the comma) and its neighbors' zero bytes.
TILE_STREAM_ADDR = 0xAA92
TILE_STREAM_ORIGINAL = bytes([0x2D, 0x00, 0x02, 0x18, 0x18, 0x08, 0x27, 0x00])
TILE_STREAM_PATCHED = bytes([0x8D, 0x00, 0xCF, 0x21, 0x80, 0xE4, 0x08, 0x00])

#: Lookback copies that read the old comma, and where they read from instead.
#: (address, original, patched); the operand is a big-endian offset from $1000.
LOOKBACK_REPOINTS = (
    # backwards copy of 4 into tile $2B: $111E-$111B -> $0FE9-$0FE6 (18 18 00 00)
    (0xAB85, bytes([0xC3, 0x01, 0x1E]), bytes([0xC3, 0xFF, 0xE9])),
    # forward copy of 6 into tile $84: $1118-$111D -> $0FB3-$0FB8 (00 x5, 18)
    (0xAE2D, bytes([0x85, 0x01, 0x18]), bytes([0x85, 0xFF, 0xB3])),
)

COMMA_TILE = 0x11
BLANK_TILE = 0x3B
#: The tiles for SwingSpeed 0-2: S, M, and F (the comma's tile, redrawn).
SPEED_TILES = bytes([0x17, 0x13, COMMA_TILE])

#: The comma after MID: the static label row (`NametableDescriptorDA4D5`) and
#: the hi/lo descriptor `$A57D` writes when SwingHiLo is 0 (`DA599`).
MID_COMMA_ADDRS = (0xA503, 0xA5A0)

# --- The HUD code -------------------------------------------------------------

HUD_BANK = 13

#: `LD_A499`'s club name writes and the flush after them, through the `JSR`.
CLUB_SPLICE_ADDR = 0xA4B5
CLUB_SPLICE_ORIGINAL = bytes(
    [
        0xA6, 0xCD,  # LDX ClubSelection
        0xBD, 0x5D, 0xA5,  # LDA ClubNameFirstTileTableAlt,X
        0x8D, 0x17, 0x04,  # STA $0417
        0xBD, 0x6D, 0xA5,  # LDA ClubNameSecondTileTableAlt,X
        0x8D, 0x18, 0x04,  # STA $0418
        0x20, 0x84, 0xCE,  # JSR WriteNametableTiles (.dw $0410 follows)
    ]
)  # fmt: skip

#: The start of `StoreBallHeadingAndPinDistance` ($BAD2-$BB6C, maybe dead).
HOOK_ADDR = 0xBAD2
HOOK_LIMIT = 0xBB6D - HOOK_ADDR  # 155
#: Its first bytes, for the 19 the hook replaces.
HOOK_SITE_ORIGINAL = bytes.fromhex(
    "A5 DA 85 00 A5 DB 85 05 A5 DC 85 01 A5 DD 85 02 A5 DE 85"
)

_VANILLA = {
    "SwingSpeed": 0xCE,
    "WriteNametableTiles": 0xCE84,  # fixed bank; 2-byte inline descriptor pointer
    "ShowDistanceToPin": 0xA170,  # where LD_A499 tail-jumps after the flush
    "HudValueRow": 0x0410,  # the descriptor CopyInlineMemoryBlock built from $A519
    "SpeedCell": 0x0419,  # column 5 of the club box
}


def _hook_program() -> Program:
    """
    Write the speed letter into the value row, flush it, and finish `LD_A499`.

    Entered by `JMP` from the club splice, in place of the vanilla flush, so the
    stack is untouched and the tail jump is the one `LD_A499` ended with.
    """
    source = """
        SwingSpeedHud:
            ldx SwingSpeed
            lda SpeedTiles,x
            sta SpeedCell
            jsr WriteNametableTiles
            .word HudValueRow
            jmp ShowDistanceToPin
        SpeedTiles:
            .byte SPEED_S, SPEED_M, SPEED_F
    """
    program = assemble(
        source,
        HOOK_ADDR,
        {
            **_VANILLA,
            "SPEED_S": SPEED_TILES[0],
            "SPEED_M": SPEED_TILES[1],
            "SPEED_F": SPEED_TILES[2],
        },
    )
    if program.size > HOOK_LIMIT:
        raise ValueError(
            f"SwingSpeedHud is {program.size} bytes; StoreBallHeadingAndPinDistance "
            f"has {HOOK_LIMIT}"
        )
    return program


def _club_splice() -> bytes:
    patched = bytearray(CLUB_SPLICE_ORIGINAL)
    patched[6] = 0x16  # STA $0416: the first tile one column left
    patched[12] = 0x17  # STA $0417: the second tile one column left
    patched[14:17] = bytes([0x4C, HOOK_ADDR & 0xFF, HOOK_ADDR >> 8])  # JMP hook
    return bytes(patched)


def _bank4(addr: int) -> int:
    return rom_utils.cpu_to_prg_switched(addr, TILE_BANK)


def _bank13(addr: int) -> int:
    return rom_utils.cpu_to_prg_switched(addr, HUD_BANK)


def swing_speed_hud_patch() -> CompositePatch[BytePatch]:
    """Build the patch: the F tile, the comma blanks, the club splice and the hook."""
    hook = _hook_program().code
    if len(hook) > len(HOOK_SITE_ORIGINAL):
        raise ValueError(
            f"the hook is {len(hook)} bytes; extend HOOK_SITE_ORIGINAL to cover them"
        )

    patches = [
        BytePatch(
            name="swing_speed_hud_f_tile",
            description="Re-encode tile $11 (the comma) as an F in the swing view tiles",
            prg_offset=_bank4(TILE_STREAM_ADDR),
            original=TILE_STREAM_ORIGINAL,
            patched=TILE_STREAM_PATCHED,
        ),
        *(
            BytePatch(
                name=f"swing_speed_hud_lookback_{addr:04x}",
                description=f"Point the lookback at ${addr:04X} off the old comma",
                prg_offset=_bank4(addr),
                original=original,
                patched=patched,
            )
            for addr, original, patched in LOOKBACK_REPOINTS
        ),
        *(
            BytePatch(
                name=f"swing_speed_hud_mid_comma_{addr:04x}",
                description=f"Blank the comma after MID at ${addr:04X}",
                prg_offset=_bank13(addr),
                original=bytes([COMMA_TILE]),
                patched=bytes([BLANK_TILE]),
            )
            for addr in MID_COMMA_ADDRS
        ),
        BytePatch(
            name="swing_speed_hud_club_splice",
            description="Move the club name one tile left and jump to the speed hook",
            prg_offset=_bank13(CLUB_SPLICE_ADDR),
            original=CLUB_SPLICE_ORIGINAL,
            patched=_club_splice(),
        ),
        BytePatch(
            name="swing_speed_hud_hook",
            description=(
                f"Draw the speed letter, in StoreBallHeadingAndPinDistance "
                f"(maybe dead) at ${HOOK_ADDR:04X}"
            ),
            prg_offset=_bank13(HOOK_ADDR),
            original=HOOK_SITE_ORIGINAL[: len(hook)],
            patched=hook,
        ),
    ]
    return CompositePatch(
        name="swing_speed_hud",
        description="Show the swing speed (S/M/F) next to the club on the swing view HUD",
        patches=patches,
    )


SWING_SPEED_HUD_PATCH = swing_speed_hud_patch()
