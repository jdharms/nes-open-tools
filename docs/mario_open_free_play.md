# Mario Open Golf: course unlocks, the score limit, and the free-play patch

> Note: Written by Codex & Claude

Mario Open Golf starts with one course and unlocks the rest one round at a time, and it
ends a round early when the player's score gets too far over par. This document describes
both mechanisms and the `mario_open_free_play` patch, which opens every course and removes
the score limit.

Everything here is about `mario_open_jp.nes` (SHA-1 `5464fcad88c4734567ab76d44beae903d932d236`,
`jp_rom_utils.JP_ROM_SHA1`), and every address is a JP address;
[jp_rom_map.md](jp_rom_map.md) indexes them. Bank 15 is the fixed bank.

## Course progression

SRAM `$6003` is the progression level, 0 on a new save (the initializer at bank 4 `$B71E`
clears SRAM from `$6003` on).

| Progression | Courses available |
|---|---|
| 0 | Japan |
| 1 | Japan, Australia |
| 2 | Japan, Australia, France |
| 3 | Japan, Australia, France, Hawaii |
| 4 | Japan, Australia, France, Hawaii, UK |
| 5 | All five, and the extra (remix) course |

Bank 13 `$84FE`-`$850F` raises it by one at the end of a round when all of these hold:

- single-player stroke play (`$0100` and `$0101` both zero);
- progression is below 5;
- the course just played (`$0102`) is the newest one available, its index equal to the
  progression level.

No score is compared there. Finishing the round is the condition, and the score limit
below is what stops a round from finishing.

Bank 12 `$80EC`-`$810E` picks the course menu variant from progression and game mode, and
`$89B0`-`$89CE` turns the chosen menu entry into a course index, mapping the last entry
to the extra course (index 5) where the menu has one. At progression 5 the menu has all
six entries in both modes. The extra course's builder (`$DA22`, fixed bank) also reads
progression, at `$DA2C`.

## The score limit

Bank 12 `$A264`-`$A28E` loads the limit into RAM `$0658` from
the table at `$A28F`-`$A294`:

| Course index | Course | Limit |
|---|---|---|
| 0 | Japan | +18 |
| 1 | Australia | +12 |
| 2 | France | +8 |
| 3 | Hawaii | +4 |
| 4 | UK | +2 |
| 5 | Extra | +8 |

Each course counts its dismissals in SRAM `$6028`-`$602D`. When zero-page `$15` is `$C0`
when that code runs, the limit is raised by half the course's count, by at most 10.

Bank 13 `$8268`-`$8294` checks the score before each shot. The check is skipped when
`$0101` or `$04F6` is nonzero, and for game modes 4 and up (the dispatch at
`$823B`-`$8240`). It works from:

- `$011F`, the strokes taken so far on this hole, and `$0109`, its par;
- `$04E6`-`$04E7`, the signed 16-bit score relative to par over the finished holes
  (updated at `$8DFC`-`$8E0E`).

It computes `strokes + 1 - par`, the hole's score if the coming shot were the last. While
that is negative the round continues. Otherwise it is added to the finished-hole score,
and a total at or over the limit jumps to the dismissal handler at `$847E`; anything less
continues at `$8297`.

So the limit applies to the shot about to be taken, not to the scorecard: on the UK
course (+2), a player at +1 through the finished holes is dismissed on reaching par
strokes on a hole, before the stroke that would make bogey.

The handler at `$847E` clears the saved round, increments the course's dismissal count
(stopping at 255), shows message 3 and returns to the menu.

## The patch

`mario_open_free_play` (`golf/core/patches/mario_open_free_play.py`) makes three changes
in bank 13, applied together or not at all:

| Address | Vanilla | Patched |
|---|---|---|
| `$8294` | `JMP $847E` (dismiss) | `JMP $8297` (continue the shot) |
| `$847E` | the first ten bytes of the dismissal handler | `LDA #5 / STA $6003 / LDA #0 / STA $98 / RTS` |
| `$8000` | `LDA #0 / STA $98` | `JSR $847E / NOP` |

The first removes the jump to the dismissal handler, the only reference to it found
(see below). With nothing left to reach the handler, the second writes the unlock
routine over its start, and the third calls
that routine from the top of bank 13, which the reset code enters at `$8000` (fixed bank
`$CD70`) after the save has been validated or initialized. The routine ends with the two
instructions the call replaced.

Progression is written to SRAM, so the course menu and the extra course's builder both
see level 5, on an existing save as well as a new one.

```bash
uv run golf-patch mario_open_jp.nes -p mario_open_free_play \
  -o mario_open_free_play.nes --ips mario_open_free_play.ips
```

The patch type is registered for the JP ROM, so `golf-patch` checks the base against the
JP hash rather than the US one (`docs/patch_stack.md`).

`tests/integration/test_mario_open_free_play_rom.py` runs the patched entry and the score
check, vanilla and patched, under py65.

## Not verified

The findings above come from disassembly and from running the routines under py65.
Nothing here has been run in an emulator. In particular:

- **Other ways into the handler.** The jump at `$8294` is the only reference to `$847E`
  that `golf-rom-peek find-refs` finds, and no `7E 84` pointer appears elsewhere in bank 13
  or the fixed bank. An indirect jump, or a branch into the handler past its first ten
  bytes, would not show up that way.
- **Re-entry.** Bank 13 has four `JMP $8000` (`$8046`, `$84C4`, `$858F`, `$89ED`), which
  would run the unlock again on each return to the menu, including after the save is
  cleared. Which of them run, and when, has not been traced.
- **The raised limit.** What the player does to make `$15` equal `$C0` when the limit is
  loaded.
- **A full round** on a new save, an existing save, the extra course, and with a score
  past the limit.
