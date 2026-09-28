+++
status = "accepted"
date = 2026-09-28
area = "randomizer"
permanent = true
revisit_when = "A new-save option needs a value the four-byte table does not hold"
drafted_by = "Claude"
supersedes = []
+++

# Finish ABI 2 writes new-save options into a table in PLAYER STATS' space

## Context

The download form should offer the four settings on the club house's OPTIONS screen: BGM,
swing speed, putt speed and ball spin. The game keeps them in SRAM at `$6F98-$6F9B`, and
`InitializeSram` (bank 9) fills `$6F98-$6FAF` with `$FF` on a new save in a ten-byte loop
at `$AD46`. Finish ABI 1 writes BGM by turning that loop's `BPL` into `BNE`, which leaves
`$6F98` at `$00`; no byte edit makes the loop write the other values. Rewriting the loop to
fill from a table needs one more byte than it has, and the magic writes follow directly.

ABI 1 promises the finisher only the locations it consumed then, so finishing into any new
location needs a new ABI, and seeds stored under ABI 1 must still finish.

The fixed bank has almost no free space. Bank 9 has no padding, but its PLAYER STATS
screen (`$B519` on) is reached only from the club house entry `menu_trim` removes.

## Decision

- The unfinished build (build version 4) adds `new_save_options`: the `$AD46` loop becomes
  a `JMP` to a 28-byte routine at bank 9 `$B519` that does the same `$FF` fill, copies a
  four-byte table (BGM, swing, putt, spin) over `$6F98-$6F9B`, and jumps back to `$AD50`.
  The table, at `$B531`, holds the vanilla `$FF $FF $FF $FF`. The patch requires
  `menu_trim`'s removal of PLAYER STATS.
- Finish ABI 2 writes the player's four values into that table with
  `new_save_option_values`, expecting the vanilla fill, and writes name, clubs and magic
  through `sram_defaults` as ABI 1 does, without the loop edit.
- `_finish_abi_1` stays for stored seeds. It writes BGM with the loop edit and refuses
  swing, putt or spin defaults other than off.
- The values stay SRAM defaults: the OPTIONS screen still edits them in the game.

## Rejected alternatives

- **Values in PRG ROM, read directly.** Repointing the readers (`StartCourseBgm`,
  `ShotSetupSequence`) at ROM constants would stop the OPTIONS screen from changing them,
  or need that screen patched as well, and saves no space.
- **The fixed bank.** Reachable from any bank, but it is nearly full, and `InitializeSram`
  is already in bank 9.
- **Compacting `InitializeSram` in place.** Its zero fill could be rewritten a few bytes
  shorter, but not by enough for the table and its loop without deeper changes to vanilla
  code.
- **Immediate stores per option.** Four `LDA #`/`STA` pairs need no table but take 20
  bytes and four scattered finisher locations instead of one four-byte field.

## Consequences

- Build version 4 and finish ABI 2 are the current pair. ABI 1 seeds are stored for good,
  so `_finish_abi_1` is never retired; the site omits swing, putt and spin for them.
- PLAYER STATS' code is now claimed space. Anything that brings PLAYER STATS back must
  move the routine, which is a finish ABI change.
- `sram_defaults`' `bgm=False` refuses to follow `new_save_options`, since the loop edit's
  byte is now a `NOP`.
- A new option would be a new ABI: the table has exactly four entries.

## Sources

- `docs/planning/download_settings.md`, "The ROM mechanism and the finish ABI" and
  "Placement".
- `golf/core/patches/new_save_options.py`, `golf/randomizer/build.py`.
- Planning session with Claude, 2026-09-28.
