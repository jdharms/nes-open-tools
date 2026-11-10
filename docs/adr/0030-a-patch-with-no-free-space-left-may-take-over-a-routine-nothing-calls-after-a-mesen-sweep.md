+++
status = "proposed"
date = 2026-11-10
area = "patches"
permanent = false
revisit_when = "a patch needs more room than the dead routines left, a Mesen session hits one of them, or a vanilla caller of one turns up"
drafted_by = "Claude"
supersedes = []
+++

# A patch with no free space left may take over a routine nothing calls, after a Mesen sweep

## Context

`swing_speed_hud` needs 19 bytes of new code in bank 13, where the swing view HUD is
drawn. The randomizer's stack (`golf/randomizer/build.py`) already fills all of the
known free space there, and nearly all of it in the fixed bank:

- bank 13's tail padding, `$BF83`-`$BFF2` (112 bytes): `mercy_tap_in` 44,
  `seeded_wind` 16 and `green_shortcut` 52;
- the fixed bank's `CA40_FreeSpace192` (192 bytes): `wram_expansion` 164 and
  `green_shortcut` 27, one byte left.

`golf-rom-peek trace` finds no other gap in bank 13, but 202 bytes of code that only
unreached labels lead to: three routines, each labeled "maybe dead" with a Mesen sweep
(2026-10-04) that saw none of them execute through the credits combo, every club house
screen, a tournament bet, practice, 2P stroke play and 1P match play.

| Routine | Range | Bytes |
|---|---|---|
| `TestBallScreenYVisible` | `$8FA3`-`$8FC1` | 31 |
| `NegateWord00IfMinus` | `$B942`-`$B951` | 16 |
| `StoreBallHeadingAndPinDistance` | `$BAD2`-`$BB6C` | 155 |

`wram_expansion` rewrites an operand inside `TestBallScreenYVisible` (`$8FAF`), because
the routine reads a table that patch moved.

## Decision

- A patch that has no free space left in the bank its code must run from may overwrite
  a routine that `golf-rom-peek trace` reports as uncalled, if the routine's label
  records a Mesen sweep that never saw it execute.
- The patch checks the routine's vanilla bytes as its `original`, like any other
  `BytePatch`, so a stack that has already used them fails loudly.
- `swing_speed_hud` takes the first 19 bytes of `StoreBallHeadingAndPinDistance`
  (`$BAD2`-`$BAE4`), leaving 136 contiguous bytes at `$BAE5`-`$BB6C` for the next
  patch.
- `TestBallScreenYVisible` stays as it is while `wram_expansion` writes inside it.

## Rejected alternatives

- **Moving another patch's code to make room.** Every block in the stack is already
  packed, and moving one changes a shipped patch's bytes for no gain to it.
- **Drawing the F at runtime with a 16-byte pattern upload.** It needs about 25 more
  bytes of new code than re-encoding the tile in the compressed stream, and new code is
  exactly what is short.
- **`NegateWord00IfMinus`.** At 16 bytes it holds the hook's code but not its 3-byte
  table.

## Consequences

- A static search plus one Mesen sweep is now enough to spend a routine. If a path the
  sweep missed does call one, the game jumps into patch code. Overwriting the start of
  a routine, not its middle, at least makes such a call fail at once.
- The labels of a routine a patch takes should say so, so the next agent does not count
  its bytes as free.
- Bank 13 has 136 bytes at `$BAE5`, 31 at `$8FA3` (around `wram_expansion`'s splice)
  and 16 at `$B942` left this way.

## Sources

- `golf/core/patches/swing_speed_hud.py`, `docs/swing_speed_hud.md`
- Session of 2026-11-10 (Claude Code), which surveyed bank 13 space against the stack
  of a full seed built with mercy tap-in.
