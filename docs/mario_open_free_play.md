# Mario Open Golf: course unlocks and score dismissal

Investigation of `mario_open_jp.nes`, whole-file SHA-1
`5464fcad88c4734567ab76d44beae903d932d236`. Addresses here are JP addresses,
not the addresses in the US label file. Bank 15 is fixed; other banks use
$8000-$BFFF. Findings come from targeted `golf-rom-peek` reads and execution
of the affected ROM code under py65, not a full graphical emulator playthrough.

## Course progression

SRAM $6003 is a progression level, initially zero. The save initializer in
bank 4 at $B71E clears $6003 onward. Save validity checks at $B705 require
"5S" at both $6001-$6002 and $6E0B-$6E0C.

Bank 13 $84FE-$850F advances progression after completing the frontier course
in single-player stroke play: $0100 OR $0101 must be zero, progression must
be below 5, and the course index at $0102 must equal progression. Then it
increments $6003 and selects the course-unlocked message. It does not require
an additional final-score comparison here: surviving the round is the gate.

| Progression | Regular courses available |
|---|---|
| 0 | Japan |
| 1 | Japan, Australia |
| 2 | Japan, Australia, France |
| 3 | Japan, Australia, France, Hawaii |
| 4 | Japan, Australia, France, Hawaii, UK |
| 5 | All five, plus the extra/remix course |

Bank 12 $80EC-$810E chooses the course-menu variant from progression and game
mode. $89B0-$89CE translates the last extra-course menu entry to course index
5; its position changes with progression and mode. For example, stroke play
at level 4 already has a final extra entry, whereas level 0 only has Japan.
Level 5 gives all six entries in either mode. The remix builder at fixed-bank
$DA22 reads progression at $DA2C; setting the actual SRAM byte, rather than
merely expanding the menu, also gives it the final progression level.

## Running-score dismissal

Bank 12 $A264-$A28E loads the limit into RAM $0658 from the six-byte table at
$A28F-$A294:

| Course index | Course | Normal limit |
|---|---|---|
| 0 | Japan | +18 |
| 1 | Australia | +12 |
| 2 | France | +8 |
| 3 | Hawaii | +4 |
| 4 | UK | +2 |
| 5 | Extra/remix | +8 |

When input byte $15 equals $C0, the setup code adds
`min(dismissals[course] // 2, 10)` to the normal limit. The six dismissal counters
are at SRAM $6028-$602D. This investigation has not verified the physical
button timing needed to activate that input condition.

Bank 13 $8268-$8294 checks the score before allowing the next shot. It skips
the check when $0101 or $04F6 is nonzero; the surrounding $823B-$8240 dispatch
also bypasses this path for game modes at least 4. For the checked player:

- $011F is strokes already taken on the current hole; $0109 is its par.
- $04E6-$04E7 is the signed 16-bit score relative to par on completed holes.
  The update is at bank 13 $8DFC-$8E0E.
- It first calculates `strokes + 1 - par`. A borrow skips dismissal while
  the next stroke is still below the current hole's par.
- Otherwise it adds that value to the completed-hole score. Negative totals
  continue. A nonnegative total at least $0658 jumps to $847E.

Consequently the UK limit is +2, but a player already at +1 cannot take a
next stroke that would reach +2. This is a shot-time check, not just a check
of the scorecard at the end of each hole. The current-hole borrow exemption
also means it is not an unconditional check of the displayed running score.

The dismissal handler $847E clears round-resume state, increments the course's
counter (saturating at 255), selects message 3, shows the result and returns
to the menu. `find-refs` finds its direct incoming jump at $8294; disassembly
from $8268 confirms that instruction boundary. The tests execute both sides
of the score comparison, including negative and multi-byte positive scores.

## Patch

The registered `mario_open_free_play` patch applies three changes together:

| Bank:address | Change |
|---|---|
| 13:$8000 | Replace `LDA #0 / STA $98` with a call to $847E and a NOP |
| 13:$847E | Replace the first ten bytes of the disabled dismissal handler with `LDA #5 / STA $6003 / LDA #0 / STA $98 / RTS` |
| 13:$8294 | Replace `JMP $847E` with `JMP $8297`, continuing shot setup |

Reset initializes SRAM at $CD68, selects bank 13 at $CD6B, and jumps to $8000
at $CD70. The hook therefore runs after save validation and before the first
menu. It runs again on returns to that menu. Existing saves get progression 5
as well; clearing the save is followed by unlocking again on entry. The new
routine reuses the obsolete dismissal entry, without adding code in presumed
unused padding. These changes are coupled: installing only the hook would
turn dismissal into a call to code that ends in RTS, despite being entered
by JMP. The composite validates every splice before writing any of them.

```bash
uv run golf-patch mario_open_jp.nes --any-base -p mario_open_free_play \
  -o mario_open_free_play.nes --ips mario_open_free_play.ips
```

`--any-base` is needed because the CLI defaults to validating the US ROM hash.
The patch checks original bytes at all three sites and rejects the US ROM.
Use the JP hash above to identify the researched base; matching splice bytes
alone do not establish compatibility with other releases or existing hacks.

`tests/integration/test_mario_open_free_play_rom.py` executes the entry hook,
all six course selections in both mode branches, and vanilla versus patched
score decisions under py65. A graphical emulator check of a fresh save,
existing save, remix round, and poor-score round remains useful validation
of the complete user experience and any indirect references static tools
cannot identify. No Mesen breakpoint sweep was performed.
