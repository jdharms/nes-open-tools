# Tournament Days

> **Note**: This document was written by Claude based on design and ideas by jdharms.

A course whose four pin positions are the four days of a tournament: flag offset 1 is
Thursday's pin, 4 Sunday's. The course select asks for the day instead of a course,
and the day decides the pins, which saved round CONTINUE resumes, and the scorecard's
title, so a screenshot of a card says which day was played.

`tournament_days` (`golf/core/patches/tournament_days.py`) does all of it: the day
select, and the pins, save slots and scorecard title that follow the day. It requires
the course mirrors and `menu_trim` with `course_select: false`, which trims the menus
but leaves the course select to this patch. Georgia Pines' full recipe is
`courses/community/georgia_pines/georgia_pines.json`; its tournament steps are:

```json
{"patch": "scorecard_course_name", "name": "GEORGIA PINES"},
{"patch": "menu_trim", "words": ["PINES", "OPEN", "GOLF"], "course_select": false},
{"patch": "tournament_days", "days": ["THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY"]}
```

Day names are A-Z, 0-9 and space, at most 9 characters: the scorecard sets the day in
the columns left of "18H STROKE PLAY". They default to THURSDAY-SUNDAY.

## The day

`DAY_BYTE` is the first header byte of save slot 2 (match play, one player, course 1).
A trimmed menu reaches only stroke play, so nothing saves to that slot, and the byte sits
in battery RAM, which no round setup clears. The menu always sets it before any of the
three readers runs: `ApplyCourseSelection` (`$89E1`, bank 12) is rewritten to store the
selection at `DAY_BYTE`, set `CurrCourse` to 0, and check for a saved game as before
(`$D939`). `menu_trim`'s requirement `MENU_TRIMMED` makes sure stroke play is the only
mode a player can reach.

The new course list and its destinations are longer than the vanilla ones, so they move
into text only unreachable menus used: menu `$0D`'s tournament prompt (`$8CEE`) and a list
at `$8BF9`, with menu `$02`'s pointers repointed at them.

## The pin

`InitHole` draws the pin at `$DB15`: `JSR LSFR_RNG_ALGO`, then `AND #$03`. Both become
`JSR PinDay`, which makes the same draw and then answers the day, so `RngState` moves
exactly as in vanilla and `seeded_wind` and `wind_anchors` still give their winds.

## Save slots

Every saved round has its own slot. `SaveSlotIndex` (`$D962`) gives

    X = $D976[GolfGameMode] + two-player flag + $D97E[CurrCourse]   ($D97E: 0, 9, 18)

and each slot has a saved flag at `$61AF,X`, a 50-byte header at `$61CA + 50 X` and its
scores at bank 9 `$AFF1[X]`, sized by its kind, Y. The routine's last instructions jump
to `SaveSlotTail`, which adds a day offset in place of the course's:

| Day | Slot offset | One player | Two players |
|---|---|---|---|
| 1 | 0 | 0, course 1 stroke play | 1 |
| 2 | 9 | 9, course 2 stroke play | 10 |
| 3 | 18 | 18, course 3 stroke play | 19 |
| 4 | 4 | 4, course 1 18-hole tournament (36 bytes of scores) | 5, the 36-hole tournament (72 bytes) |

Y is unchanged, so the save and load still write and read stroke play's 36 or 72 bytes,
which every slot used holds. Each day saves and continues on its own: picking Friday
offers CONTINUE only for a saved Friday round, and a CONTINUE plays that day's pins.

## The scorecard

Stroke play's title handler (`$AFFE`, bank 2) ends with `JSR WriteNametableTiles` /
`.dw $B00D`, "18H STROKE PLAY" at column 9 of row 4. That becomes `JSR DayTitle`, which
draws the same 15 tiles further right, through a descriptor that points at the vanilla
ones (`$B011`), and then the day's name, ending a column before them. The longest day
and the title are centered together:

    GEORGIA PINES COURSE
    THURSDAY 18H STROKE PLAY
      FRIDAY 18H STROKE PLAY

## Space

The routines and day titles (129 bytes with the default days, at most 137) go in the flag
Y offsets of holes 19-54, `$E077`-`$E106`. Only `InitHole` reads that table, by hole,
and with the course mirrors every slot plays holes 1-18.

| Where | What |
|---|---|
| fixed `$DB15` | the pin draw -> `JSR PinDay` / `NOP` / `NOP` |
| fixed `$D96D` | `SaveSlotIndex`'s course offset -> `JMP SaveSlotTail` |
| bank 2 `$B007` | stroke play's title -> `JSR DayTitle` / `NOP` / `NOP` |
| fixed `$E077` | `PinDay`, `SaveSlotTail`, `DayTitle` and the titles |
| bank 12 `$89E1`, `$8CEE`, `$8BF9`, `$8B3F`, `$8AA6` | the day select: the handler, the list, the destinations and their pointers |

## Limits

- Only stroke play knows about the day; another mode would save to the wrong slots. A
  trimmed menu reaches no other.
- `scorecard_course_name` with a `title` writes the same title pointer, and a stack
  refuses the two together. Without a title it stacks, and names the course above.
- `round_stats` snapshots only save slots 0 and 1, so with this its stats would be lost
  on a CONTINUE of a Friday to Sunday round. The two are not meant to be stacked: this is
  for a download with no QR code.
- Checked by running the patched ROM's code under py65
  (`tests/integration/test_tournament_days_rom.py`): the pin, the save slot of every day,
  the menu's list, its handler and the scorecard row. Whole rounds on an emulator are still to be
  played.
