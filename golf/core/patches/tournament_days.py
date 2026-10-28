"""
Tournament days: a course whose four pin positions are Thursday to Sunday.

The course select offers four days in place of courses and keeps the one picked,
0-3, at `DAY_BYTE`, and the day counts for three things after it:

1. **The menu.** `menu_trim` with `course_select=False` leaves the course select
   to this patch. Four entries and four destinations outgrow the vanilla lists,
   so they go in text and a destination list only unreachable menus used, menu
   $0D's tournament prompt at $8CEE and a list at $8BF9, and menu $02's two
   pointers ($8B3F, $8AA6) are repointed. `ApplyCourseSelection` ($89E1) is
   rewritten in its first 15 bytes to keep the selection at `DAY_BYTE`, set
   `CurrCourse` to 0 and check for a saved game (`$D939`) as before. `DAY_BYTE`
   ($622E) is the first header byte of save slot 2 (match play, one player,
   course 1), which a trimmed menu never saves to.
2. **The pin.** `InitHole` draws the pin at `$DB15`: `JSR LSFR_RNG_ALGO`, then
   `AND #$03` picks one of the hole's four flag offsets. Both become a call to
   `PinDay`, which still makes the draw, so `RngState` moves exactly as before and
   `seeded_wind` and `wind_anchors` give the same winds, and then answers the day.
   Flag offset 1 is Thursday's pin, offset 4 Sunday's.
3. **The save slot.** Each saved round has its own slot: `LD962` (`SaveSlotIndex`)
   gives X = `$D976[GolfGameMode]` + the two-player flag + `$D97E[CurrCourse]`,
   where `$D97E` is 0, 9, 18, the nine slots of each course. Every slot has a
   50-byte header at `$61CA + 50 X`, a saved flag at `$61AF,X` and its own
   strokes and putts. Its last three instructions jump to `SaveSlotTail`, which
   adds the day's offset in place of the course's, so each day saves and
   continues on its own: Thursday, Friday and Saturday on the stroke play slots
   of courses 1-3, Sunday on course 1's 18- and 36-hole tournament slots (4 and 5),
   which hold the same 36 and 72 bytes of scores as stroke play's one- and
   two-player slots. A CONTINUE after picking a day resumes that day's round.
4. **The scorecard.** Stroke play's title handler (`$AFFE`, bank 2) ends with
   `JSR WriteNametableTiles` / `.dw $B00D`, "18H STROKE PLAY" at column 9 of
   row 4. That becomes `JSR DayTitle`, which draws the same 15 tiles further
   right, through a descriptor pointing at the vanilla ones (`$B011`), and the
   day's name right before them, so a screenshot says which day was played:
   "THURSDAY 18H STROKE PLAY".

Only stroke play is right about the day, which is all a trimmed menu reaches;
any other mode would land in the wrong slots, and the title handler of other
modes is not changed. The day byte is set before any of the three is reached:
the menu sets it, then offers CONTINUE or NEW GAME for that day's slot.

Writes
------

    fixed   $DB15       InitHole's pin draw -> JSR PinDay / NOP / NOP
    fixed   $D96D       SaveSlotIndex's course offset -> JMP SaveSlotTail
    bank 2  $B007       stroke play's title -> JSR DayTitle / NOP / NOP
    fixed   $E077       the routines and their data
    bank 12 $89E1       ApplyCourseSelection -> keep the day
    bank 12 $8CEE       the day list, over menu $0D's text
    bank 12 $8BF9       the day destinations, over an unreachable list
    bank 12 $8B3F       menu $02's options pointer -> the day list
    bank 12 $8AA6       menu $02's destinations pointer -> the day destinations

The routines go in the flag Y offsets of holes 19-54 (`TABLE_FLAG_Y_OFFSET` +
72), which only `InitHole` reads, by hole: with `course_mirrors` every course
slot plays holes 1-18, so the patch requires it, and a trimmed menu with its
course select left alone (`MENU_TRIMMED`; the course select's own bytes would
not match otherwise). `scorecard_course_name` with a
`title` writes the same title pointer and cannot be stacked with this; without
one it can, and gives the course its name on the row above.
"""

import string
from collections.abc import Sequence

from golf.core import rom_utils
from golf.core.asm6502 import Program, assemble

from .byte_patch import BytePatch
from .composite import CompositePatch
from .menu_trim import MENU_TRIMMED
from .multi_bank import COURSE_MIRRORS_PATCH
from .scorecard_course_name import TITLE_ROW_PPU, title_font_tiles

#: Where the course select keeps the day it was given, 0-3: the first header byte
#: of save slot 2 (match play, one player, course 1), which a trimmed menu never
#: saves to.
DAY_BYTE = 0x622E
DEFAULT_DAYS = ("THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY")
#: the scorecard sets a day before "18H STROKE PLAY", in the 9 columns left of it
MAX_DAY_LENGTH = 9
#: what both the menu font and the scorecard's title font draw
DAY_CHARS = string.ascii_uppercase + string.digits + " "

MENU_BANK = 12
#: Menu $02's options and destinations, with four days, move into text and a list
#: only the unreachable menus used: menu $0D's static text and options
#: ($8CEE-$8D63, 118 bytes) and a list at $8BF9 ($8BF9-$8C56, 94 bytes).
DAY_LIST_ADDR = 0x8CEE
DAY_LIST_VANILLA = bytes.fromhex(
    "05F98C098D198D2A8D408D040824313030302057494C4C204245FF040A4445445543"
    "5445442046524F4DFF040C594F55522057494E4E494E47"
)
DAY_DESTINATIONS_ADDR = 0x8BF9
_DAY_DESTINATIONS_VANILLA = bytes.fromhex("02FE8B0C")
#: `MenuTextListPtrTable` + 4 x 2 + 2, and `MenuSubmenuIdPtrTable` + 2 x 2
_MENU_02_OPTIONS_PTR = 0x8B3F
_MENU_02_DESTINATIONS_PTR = 0x8AA6
#: every day goes on to menu $03, CONTINUE / NEW GAME
_CONTINUE_MENU = 0x03
#: the menu's column and first row for the options, as the vanilla course list
_OPTION_X, _OPTION_FIRST_Y = 0x0C, 0x0E

#: `ApplyCourseSelection`, as far as it is rewritten: the selection + 1 through an
#: inline `LookupInlineByteTable` table to `CurrCourse`
COURSE_HANDLER_ADDR = 0x89E1
_COURSE_HANDLER_VANILLA = bytes.fromhex("AD8D0618690120148A010102000302")

#: The routines, in the flag Y offsets of holes 19-54, which no course slot reads.
CODE_ORIGIN = rom_utils.TABLE_FLAG_Y_OFFSET + rom_utils.HOLES_PER_COURSE * 4
CODE_LIMIT = rom_utils.TABLE_FLAG_Y_OFFSET + rom_utils.TOTAL_HOLES * 4
#: The vanilla flag Y offsets of holes 19-54, which the routines cover.
CODE_REGION_VANILLA = bytes.fromhex(
    "435B73803A757F68465F88884C4D738E566C508A4E5D8668903F657D45698A5E5043747D"
    "5674685E4050774C58765D88405D8868505567844170667C5E4E6795467E7862746B8054"
    "535B738C36557F8846687088544D737E466F558A585D86685078787D88696A5E46435C7D"
    "56746D5E9060774C3E625D90407060985055678F3D9868805E4E678846906E6288405080"
)
assert len(CODE_REGION_VANILLA) == CODE_LIMIT - CODE_ORIGIN

SCORECARD_BANK = 2

#: `JSR LSFR_RNG_ALGO` / `AND #$03` in `InitHole`.
PIN_DRAW_ADDR = 0xDB15
_PIN_DRAW_VANILLA = bytes.fromhex("209CD22903")
#: `LDX CurrCourse` in `SaveSlotIndex`, after `TAY`; the CLC / ADC / TAX / RTS
#: after it are no longer reached.
SAVE_SLOT_COURSE_ADDR = 0xD96D
_SAVE_SLOT_COURSE_VANILLA = bytes.fromhex("AE0201")
#: `JSR WriteNametableTiles` / `.dw $B00D` in stroke play's title handler.
TITLE_CALL_ADDR = 0xB007
_TITLE_CALL_VANILLA = bytes.fromhex("2084CE0DB0")

#: The vanilla "18H STROKE PLAY" descriptor's tiles, in bank 2.
STROKE_PLAY_TILES = 0xB011
STROKE_PLAY_TEXT = "18H STROKE PLAY"

#: Each day's slot offset, in place of the course's 0, 9 or 18: the stroke play
#: slots of courses 1, 2 and 3, then course 1's 18-hole tournament slot, which
#: the two-player flag makes its 36-hole one.
DAY_SLOT_OFFSETS = (0, 9, 18, 4)

SYMBOLS = {
    "DayByte": DAY_BYTE,
    "LsfrRngAlgo": 0xD29C,
    "WriteNametableTiles": 0xCE84,
    "StrokePlayTiles": STROKE_PLAY_TILES,
}


def normalize_days(days: Sequence[str] | None = None) -> tuple[str, ...]:
    """Four day names, uppercased; DEFAULT_DAYS when none are given."""
    days = tuple(day.upper() for day in (DEFAULT_DAYS if days is None else days))
    if len(days) != len(DEFAULT_DAYS):
        raise ValueError(
            f"days must be exactly {len(DEFAULT_DAYS)} names, got {days!r}"
        )
    for day in days:
        if not 1 <= len(day) <= MAX_DAY_LENGTH:
            raise ValueError(
                f"each day must be 1-{MAX_DAY_LENGTH} characters, got {day!r} ({len(day)})"
            )
        bad = sorted(set(day) - set(DAY_CHARS))
        if bad:
            raise ValueError(
                f"day {day!r} contains characters the menu and scorecard cannot both "
                f"render: {''.join(bad)!r}. Allowed: A-Z, 0-9 and space"
            )
    return days


def day_list_bytes(days: Sequence[str] | None = None) -> bytes:
    """Menu $02's options text list with one entry per day, down the course list's rows."""
    days = normalize_days(days)
    entries = [
        bytes([_OPTION_X, _OPTION_FIRST_Y + 2 * i]) + day.encode("ascii") + b"\xff"
        for i, day in enumerate(days)
    ]
    pointers = bytearray([len(entries)])
    address = DAY_LIST_ADDR + 1 + 2 * len(entries)
    for entry in entries:
        pointers += address.to_bytes(2, "little")
        address += len(entry)
    return bytes(pointers) + b"".join(entries)


def course_handler_bytes() -> bytes:
    """ApplyCourseSelection for days: keep the selection as the day, play course 1."""
    return bytes(
        [
            0xAD, 0x8D, 0x06,  # LDA CurrentMenuSelection
            0x8D, DAY_BYTE & 0xFF, DAY_BYTE >> 8,  # STA DayByte
            0xA9, 0x00,  # LDA #0
            0x8D, 0x02, 0x01,  # STA CurrCourse
            0x20, 0x39, 0xD9,  # JSR $D939, as before: is there a saved game?
            0x60,  # RTS
        ]
    )  # fmt: skip


def title_layout(days: Sequence[str]) -> tuple[int, list[int]]:
    """
    The column "18H STROKE PLAY" starts at, and each day's first column.

    The longest day and the title are centered on row 4 the way vanilla centers
    its short titles; each day ends one column before the title.
    """
    longest = max(len(day) for day in days)
    start = (32 + 1 - (longest + 1 + len(STROKE_PLAY_TEXT))) // 2
    title_column = start + longest + 1
    return title_column, [title_column - 1 - len(day) for day in days]


def _bytes(data: bytes) -> str:
    return ", ".join(f"${b:02X}" for b in data)


def code_source(days: Sequence[str] | None = None) -> str:
    """The routines and data at CODE_ORIGIN, as assembly."""
    days = normalize_days(days)
    title_column, day_columns = title_layout(days)
    title_ppu = TITLE_ROW_PPU + title_column
    stubs = "\n".join(
        f"""DayStub{i}:
        jsr WriteNametableTiles
        .word Day{i}
        rts"""
        for i in range(len(days))
    )
    descriptors = "\n".join(
        f"Day{i}:  .byte {_bytes((TITLE_ROW_PPU + column).to_bytes(2, 'little') + bytes([len(day), 1]) + title_font_tiles(day))}"
        for i, (day, column) in enumerate(zip(days, day_columns, strict=True))
    )
    return f"""
; InitHole's pin: draw as vanilla, so RngState moves the same, then answer the day.
PinDay:
        jsr LsfrRngAlgo
        lda DayByte
        and #$03
        rts

; SaveSlotIndex from its TAY on: X = A + the day's slot offset. Y, the slot's
; kind, is as vanilla.
SaveSlotTail:
        lda DayByte
        and #$03
        tax
        tya
        clc
        adc DaySlotOffset,x
        tax
        rts

; Stroke play's scorecard title: "18H STROKE PLAY", then the day before it.
DayTitle:
        jsr WriteNametableTiles
        .word StrokePlayTitle
        lda DayByte
        and #$03
        asl a
        tax
        lda DayStubs+1,x
        pha
        lda DayStubs,x
        pha
        rts                     ; on to the day's stub, which returns to our caller
{stubs}

DaySlotOffset:
        .byte {", ".join(str(offset) for offset in DAY_SLOT_OFFSETS)}
DayStubs:
        .word {", ".join(f"DayStub{i} - 1" for i in range(len(days)))}
; one row of 15 tiles, read from the vanilla descriptor's (bit 7: a pointer)
StrokePlayTitle:
        .byte ${title_ppu & 0xFF:02X}, ${title_ppu >> 8:02X}, ${0x80 | len(STROKE_PLAY_TEXT):02X}, $01
        .word StrokePlayTiles
{descriptors}
"""


def build_code(days: Sequence[str] | None = None) -> Program:
    program = assemble(code_source(days), CODE_ORIGIN, SYMBOLS)
    if program.end > CODE_LIMIT:
        raise ValueError(
            f"tournament days code ends at ${program.end:04X}, past ${CODE_LIMIT:04X}"
        )
    return program


def _jsr(address: int) -> bytes:
    return bytes([0x20]) + address.to_bytes(2, "little")


def _menu(cpu_addr: int) -> int:
    return rom_utils.cpu_to_prg_switched(cpu_addr, MENU_BANK)


def menu_patches(days: Sequence[str] | None = None) -> list[BytePatch]:
    """The course select's days, in bank 12."""
    days = normalize_days(days)
    day_list = day_list_bytes(days)
    return [
        BytePatch(
            name="tournament_days_menu_options",
            description=f"Course select options: {', '.join(days)}, in menu $0D's unreachable text",
            prg_offset=_menu(DAY_LIST_ADDR),
            original=DAY_LIST_VANILLA[: len(day_list)],
            patched=day_list,
        ),
        BytePatch(
            name="tournament_days_menu_options_ptr",
            description="Point menu $02's options list at the days",
            prg_offset=_menu(_MENU_02_OPTIONS_PTR),
            original=bytes([0x65, 0x8C]),
            patched=DAY_LIST_ADDR.to_bytes(2, "little"),
        ),
        BytePatch(
            name="tournament_days_menu_destinations",
            description="Every day goes on to CONTINUE / NEW GAME",
            prg_offset=_menu(DAY_DESTINATIONS_ADDR),
            original=_DAY_DESTINATIONS_VANILLA,
            patched=bytes([_CONTINUE_MENU] * len(days)),
        ),
        BytePatch(
            name="tournament_days_menu_destinations_ptr",
            description="Point menu $02's destinations at the four-entry list",
            prg_offset=_menu(_MENU_02_DESTINATIONS_PTR),
            original=bytes([0xD4, 0x8A]),
            patched=DAY_DESTINATIONS_ADDR.to_bytes(2, "little"),
        ),
        BytePatch(
            name="tournament_days_menu_handler",
            description=f"ApplyCourseSelection: keep the day at ${DAY_BYTE:04X} and play course 1",
            prg_offset=_menu(COURSE_HANDLER_ADDR),
            original=_COURSE_HANDLER_VANILLA,
            patched=course_handler_bytes(),
        ),
    ]


def tournament_days_patches(days: Sequence[str] | None = None) -> list[BytePatch]:
    days = normalize_days(days)
    program = build_code(days)
    nop = bytes([0xEA])
    return [
        *menu_patches(days),
        BytePatch(
            name="tournament_days_code",
            description="PinDay, SaveSlotTail, DayTitle and the day titles, in the flag Y offsets of holes 19-54",
            prg_offset=rom_utils.cpu_to_prg_fixed(CODE_ORIGIN),
            original=CODE_REGION_VANILLA[: len(program.code)],
            patched=program.code,
        ),
        BytePatch(
            name="tournament_days_pin",
            description="InitHole: the pin is the day's, after the vanilla draw",
            prg_offset=rom_utils.cpu_to_prg_fixed(PIN_DRAW_ADDR),
            original=_PIN_DRAW_VANILLA,
            patched=_jsr(program.symbol("PinDay")) + nop * 2,
        ),
        BytePatch(
            name="tournament_days_save_slot",
            description="SaveSlotIndex: the day's slots in place of the course's",
            prg_offset=rom_utils.cpu_to_prg_fixed(SAVE_SLOT_COURSE_ADDR),
            original=_SAVE_SLOT_COURSE_VANILLA,
            patched=bytes([0x4C])
            + program.symbol("SaveSlotTail").to_bytes(2, "little"),
        ),
        BytePatch(
            name="tournament_days_title",
            description="Stroke play's scorecard title names the day",
            prg_offset=rom_utils.cpu_to_prg_switched(TITLE_CALL_ADDR, SCORECARD_BANK),
            original=_TITLE_CALL_VANILLA,
            patched=_jsr(program.symbol("DayTitle")) + nop * 2,
        ),
    ]


def tournament_days_patch(
    days: Sequence[str] | None = None,
) -> CompositePatch[BytePatch]:
    days = normalize_days(days)
    return CompositePatch(
        name="tournament_days",
        description=(
            f"The course select offers {', '.join(days)}; pins, save slots and the "
            "scorecard title follow the day picked"
        ),
        patches=tournament_days_patches(days),
        requires=(COURSE_MIRRORS_PATCH, MENU_TRIMMED),
    )


assert MAX_DAY_LENGTH + 1 + len(STROKE_PLAY_TEXT) <= 26
assert len(day_list_bytes(["W" * MAX_DAY_LENGTH] * 4)) <= len(DAY_LIST_VANILLA)
