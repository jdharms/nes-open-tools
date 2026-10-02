# Practice Greens

A standalone USA-ROM hack containing all vanilla putting greens from NES Open
Tournament Golf and Mario Open Golf. This build intentionally replaces course data
and does not promise compatibility with randomizer patch stacks.

Build with both games' vanilla courses already unpacked:

```sh
uv run golf-practice-greens
# Restore the per-hole cards for comparison:
uv run golf-practice-greens --keep-signposts -o practice_greens_signposts.nes
# Equivalent without refreshing the installed command:
.venv/bin/python -m tools.practice_greens
```

The default output is `practice_greens.nes` in the repository root, accompanied by
`practice_greens.build.json`. The manifest records every source hole, deduplication,
pin, compressed address, bank, runtime entry point and ROM write. Both outputs are
local artifacts; the manifest contains extracted vanilla pin data and is ignored.
The builder requires the exact unmodified USA base ROM and all eight vanilla course
directories. Mario Open's extracted greens are recompressed with the USA lookup tables.

## Playing

Select **PRACTICE GREENS**, choose **SLOW**, **MEDIUM** or **FAST** putting speed, and
play an 18-hole stroke-play round. The main menu exposes no other game mode, player
count, course selection or clubhouse entry. Speed selection stores the vanilla putt
speed default, which the shot setup loads normally. Starting always clears the saved-game
load flag; previous saves cannot resume a round with a mismatched green selection.

Every new round draws 18 distinct greens at runtime. There is no cross-round exclusion
state. All holes are par 2 and display distance 020; the scorecard totals are par 36
and 360 yards. By default, each hole starts directly in gameplay without its signpost card or A/B
wait. With `--keep-signposts`, the card retains hole number, par and distance but
drops the old country banner. The scorecard uses the exact name PRACTICE GREENS.

The ball starts on a randomly chosen putting-surface tile, at a randomly chosen one
of its 8 by 8 green-view pixel locations. Fraction bytes are pixel centers rather than
tile centers. The whole tile containing the cup is excluded, a slightly conservative
way to prevent immediate contact with the hole. The initial player status is 2, so
any distance bookkeeping uses green coordinates from the first shot.

A putt that **stops outside the green** ends the hole with score 5. Fringe remains
playable because vanilla classifies it as a green lie. A shot that crosses the fringe
and rolls back onto the green may continue. Genuine hole-outs retain their actual
stroke count and cup animation. Forced failures skip the cup animation using the
existing mercy patch's $FF completion sentinel. The subsequent ball-retrieval/wave/results
scene and separate ace celebration are skipped for all holes; round totals are still
updated before skipping the scene. The ordinary end-of-round scorecard remains; per-hole signposts are optional.

## Pool and deduplication

There are 144 source holes: NES Open's Japan, US and UK courses, and Mario Open's
Australia, France, Hawaii, Japan and UK courses. Comparing all 576 decompressed tile
bytes yields **105 unique greens**, occupying **20,194 compressed bytes**. A shared
green retains the union of all its source holes' vanilla pin positions, with exact
pin duplicates removed. The current pool has 455 distinct green/pin pairs, at most
8 pins on one green. Selection weights each unique green equally, rather than weighting
shared greens more heavily because they appear in multiple courses.

We considered retaining one record per source hole, but that would allow the same
geometry twice in a round. Deduplicating compressed bytes alone was also rejected:
different compressed streams can describe the same tile grid. We compare decompressed
geometry, preserve every source attribution and merge its original pins.

## Terrain choice

The shared terrain is a synthetic 22-column, 30-row field of tile $25 (shallow rough),
with zero attributes. The green begins at course coordinates (72, 56), comfortably
inside the field. Every hole's terrain pointer and attribute pointer refer to the same
blob in bank 0 at $A000. Scroll limit is 1, matching a short vanilla hole. A nominal tee
at (84, 160) is kept for initialization compatibility but is replaced by the putting spawn.

US 7 was considered as a short donor. Its terrain contains trees and shaped edges near
the green; a plain shallow-rough field makes off-green behavior predictable and removes
the need to reason about hazards belonging to an unrelated source hole. An immediate
failure on crossing the edge was considered, but stopping off the green fits the game's
existing ball-stopped hook and still permits a fringe putt to roll back onto the surface.

## PRG allocation

Only obsolete terrain and green regions are reclaimed. Executable code and unrelated
graphics after those regions remain intact. There was no need to reclaim the bank,
money, clubhouse graphics or expand the mapper/ROM.

| Bank | CPU region | Purpose |
|------|------------|---------|
| 0 | $8000-$81BF | USA green decompression lookup tables, replacing old terrain |
| 0 | $81C0-$9FFF | 45 greens, 7,731 compressed bytes |
| 0 | $A000 onward, bounded by $A23D | One shared compressed terrain and attribute blob |
| 1 | $8000-$81BF | Another copy of green decompression lookup tables |
| 1 | $81C0-$A1E5 | 39 greens, 8,152 compressed bytes |
| 2 | $8400 onward, bounded by $8FFF | 374 bytes of runtime code in former UK terrain |
| 2 | $9000 onward, bounded by $A553 | 1,540 bytes of pointer/pin tables and pin lists |
| 3 | $81C0-$A773 | 21 greens, 4,311 compressed bytes; original lookup tables remain |
| 13 | $BFA0-$BFAE | Existing mercy completion animation filter |
| 15 | $CA40-$CA49 | Fixed-bank green-bank switch/decompression wrapper |

The builder checks region capacity and rejects overlapping writes. The allocation
manifest gives exact occupied lengths; these ranges describe capacities, not padding
claims. The bank 2 pre-terrain lookup tables at $8000-$837E and post-terrain tables at
$A554 onward are preserved. Bank 3's executable code at $A774 onward is preserved.
Replicating 448 bytes of decompression tables in banks 0 and 1 lets the original
fixed-bank decompressor read its bank-relative tables and source bytes together.
This is simpler than rewriting the decompressor or copying every compressed stream
through RAM. Keeping all data in bank 3 would exceed its green region.

## Optional signpost skipping

The independent `skip_hole_signpost` patch is available through `golf-patch` and is
enabled by default in Practice Greens. It replaces bank 13 $81AB's six-byte far call
to bank 12 `DrawPreHoleSignpost` ($ABA5) with NOPs. Hole initialization and the following
gameplay PPU setup still run, but the card drawing and its A/B wait never execute.
No new code or RAM is required. Keeping signposts changes exactly those six ROM bytes.

The separate bank 13 $8064 call to `InitPreHoleSignpostScene` ($AB87) remains. It runs
the round-entry/exit golfer standee scene and participates in returning a finished
round to the menu. Skipping that shared lifecycle routine was considered and avoided;
the per-hole card has its own call site and can be disabled independently. Consequently
this patch removes the 18 course signpost cards, not every appearance of the golfer
standee around round entry/exit.

Two local ROMs support comparison: `practice_greens.nes` skips cards, while
`practice_greens_signposts.nes` keeps them. Both include the corrected celebration skip.
The build manifest records `skip_signposts`; the CLI's `--keep-signposts` option restores
the prior pacing without changing the other practice features.

## RAM and hooks

The runtime uses the now-unreachable tournament-statistics portion of SRAM, below the
vanilla terrain buffer. It is regenerated at each new round, regardless of battery data.

| CPU address | Bytes | Meaning |
|-------------|-------|---------|
| $7100-$7111 | 18 | Selected unique green IDs |
| $7112-$7123 | 18 | Selected green banks |
| $7124-$7135 | 18 | Selected compressed pointer low bytes |
| $7136-$7147 | 18 | Selected compressed pointer high bytes |
| $7148-$7149 | 2 | Selected vanilla pin X/Y offsets for the current hole |
| $714A | 1 | Current selected green bank |
| $714B-$715C | 18 | Selected vanilla pin indices, one per round hole |

Stroke-play statistics end below this region; the tournament modes that use it are
unreachable. Replay data ends at $70D1, so replay recording cannot overwrite the round
selection. Vanilla terrain starts at $7186 and green tiles at $75A6; neither overlaps it.

Round selection hooks bank 13 $80CE, replacing the two saved-hole-number resets and
replicating them in the runtime. `InitHole` $DAF1 far-calls the setup routine in bank 2,
which reads the per-round pointer and pin-index tables using `HoleNumber`, resolves
the selected vanilla pin, and preserves the caller's doubled hole index in X. The existing pin conversion
reads the selected pin via $DB21/$DB3F. At $DB60 a fixed-bank wrapper switches to the
selected bank and calls the original `DecompressGreen`; vanilla terrain loading then
switches to bank 0 and eventually restores the caller's bank.

Fresh-hole position initialization hooks bank 13 $8173. Unlike the old experimental
putting-practice patch, random draws have a bounded retry count followed by a complete
raster scan, which is guaranteed to find a surface tile outside the cup tile. The
builder checks that guarantee for every vanilla pin. The old fallback could retain an
invalid last trial coordinate and silently permit an approach shot. Spawn accepts the
shared putting-surface tile ranges and rejects fringe; pixel fractions are randomized
separately after selecting the tile. RNG advances naturally; there is no seeded-wind
compatibility requirement for this standalone project.

Bank 13 $B3DC far-calls the stop handler, replicates original stopped-state writes,
recomputes the lie with the original `ProbeBallPosition`, and forces score 5/$FF
completion for non-green lies. The original velocity-clear continuation still runs.
The reusable `skip_hole_celebrations` patch lives in the main patch directory and is
available through `golf-patch`. Bank 13 $8D8F calls bank 11 $BEE5, which accumulates
round strokes, putts, versus-par totals and holes at par or better, then calls the
post-hole retrieval/results scene (bank 12 $B094) through bank 11 $BF90. The patch
replaces only that six-byte far call with NOPs. It also redirects bank 13 $8350 past
the entire ace-only block to $8379. It does not remove cup animation, score accounting,
score commit, replay saving, save handling or normal hole advancement.

The initial build mistakenly suppressed bank 13 $834A's call to bank 8 $9B21,
identifying it as the wave. That routine actually saves notable-score replays. The
user's emulator test showed the retrieval scene still played. The corrected build
restores that replay call and suppresses the actual presentation call at bank 11
$BF90 instead. A differential CPU test verifies that vanilla reaches bank 12 $B094,
while the standalone patch and the full practice ROM both return without entering it,
with the same expected stroke/putt/versus-par accounting. This preserves the scene's
preceding view/music setup and avoids skipping the whole accounting routine.

The title menu repurposes unreachable menu text and tournament-selection handler space
for the speed choices. Skipping the stroke-play intro at $804F also clears `MenuState`:
leaving its idle bit set would be interpreted as cancellation and restart the title menu.
The round-end stroke-play dialogue is suppressed separately at $8535.

## Validation and remaining review

Integration tests execute the actual patched 6502 code under the repository's MMC1/py65
harness: all 105 decompressed greens must match their sources byte for byte; both player
slots must spawn on surface, outside the cup tile; all eight pixel fractions must be
reachable; 128 round seeds must produce distinct in-round selections, consistent bank
pointers and coverage of every green. An adversarial fixed RNG tests the raster fallback.
Failure scoring, preservation of genuine hole-outs and all three speed handlers are
also checked. A reload test changes RNG state and reinitializes the same hole, verifying
that its green and pin stay fixed: pin indices are selected once in round setup, rather
than rerolled on every `InitHole` call. A boot test supplies controller presses through the actual menus and
plays the first hole with real putting physics. It then injects
17 aces to exercise every score-commit and hole-advance path, draws the round scorecard,
and starts another round with a fresh green selection. This runs both with and without
signposts; the skipped variant rejects entry to $ABA5, while the retained variant must
visit it for every hole. A byte comparison verifies that the option changes exactly
the six-byte call site. Breakpoints reject entry to the
removed retrieval/results scene at bank 12 $B094, the ace cutscene, or the normal
tee view. The original replay-saving routine must remain reachable for all 18 holes. The menu harness supplies sprite-zero
status edges and NMIs for menu/scorecard polling loops; it does not change ROM code.

This harness does not render the PPU. Visual review in a real NES emulator remains part
of testing the local ROM: menu alignment, putting HUD, cup animation, scorecard totals,
and the pacing between holes. Original branded title graphics and the original gameplay
HUD course abbreviation remain; those are presentation polish, not green loading logic.
