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

Fresh-hole position initialization hooks bank 13 $8173. Random draws have a bounded
retry count followed by a complete raster scan, which is guaranteed to find a surface
tile outside the cup tile. The builder checks that guarantee for every vanilla pin;
an invalid fallback coordinate would otherwise permit an approach shot. Spawn accepts
the shared putting-surface tile ranges and rejects fringe; pixel fractions are randomized
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

## Putting initialization and coordinate reference

The executable implementation is in `golf/core/patches/practice_greens/runtime.asm`.
These reverse-engineering findings explain its hooks and coordinate model; the
assembled code and current tests are the reference for the spawn algorithm.

### Why placing the ball is enough

Bank 13 `ShotSetupSequence` ($877A) recomputes the ball's lie at $87B5 by calling
`ProbeBallPosition` ($EDBC). At $87BA-$87C0 it compares `BallLie` ($C9) with 6,
sets the putting flag ($D4), and jumps to the putting path at $886E when the lie is
GREEN. That jump bypasses the normal tee/course presentation at $87C3-$87E0.
Putting equipment, view and physics therefore follow from the position; the hack
does not need to force the putting flag or suppress the tee sequence separately.
Player hole status ($0111,X) is bookkeeping, not the gate into putting: setting it
to 2 makes bank 13 $870C use green-space distance from the first shot.

`InitHole` ($DA90) loads metadata, pin, terrain and green tiles but does not place
the player's ball. The fresh-hole loop at bank 13 $8155-$8190 initializes player 1
then player 0; its $8173-$8184 tee-coordinate copies are the 18-byte spawn hook.
The other `InitHole` call sites ($813C, $8D13 and $8D66 in bank 13) reload a hole
while restoring saved positions. They must retain their saved ball positions rather
than respawn. The loader modifications inside `InitHole` apply to these reloads,
which is why both selected green and pin must stay fixed for the round hole.

| Player-indexed address | Meaning |
|------------------------|---------|
| $0113,X | Ball X fraction |
| $0115,X | Ball X integer coordinate |
| $0117,X | Ball Y fraction |
| $0119,X | Ball Y integer low byte |
| $011B,X | Ball Y integer high byte |

Bank 13 $86C8 loads the saved position into the active ball registers at $AD-$B2;
$86ED saves it back. Vanilla writes $80 fractions immediately before the spawn hook,
at $816B-$8172. The new `PlaceBall` overwrites those fractions after choosing a valid
tile, so the spawn is not confined to that tile's center.

### Geometry, lie classification and pixel fractions

The green occupies a 24 by 24 box in course coordinates, with origin `GreenX` ($A3)
and `GreenY` ($A4). The bounds test starts at fixed-bank $EE13. Its 576-byte row-major
tile buffer is $75A6-$77E5, indexed as `$75A6 + 24 * tileY + tileX`.
`DecompressGreen` ($E3AC) fills it before the fresh-hole spawn hook runs.

The lie classifier reads the tile at $EE7F. Tiles below $30 fall through to the
underlying course terrain; tiles at or above $30 give lie 6. Spawn eligibility is
narrower than that test:

| Tile values | Meaning and spawn eligibility |
|-------------|-------------------------------|
| Below $30 | Underlying terrain; reject |
| $30-$47 | Dark putting slopes; accept |
| $48-$87 | Fringe/edge transitions; reject for spawning, remain playable |
| $88-$A7 | Putting surface in the editor's light-slope tile range; accept |
| $B0 | Flat putting surface; accept |
| Other values | Reject for spawning |

The fringe band sets bit 7 of $CA at $EE90-$EE92, the slow-green flag modeled in
`golf/physics/terrain.py`. This distinguishes a legal putting lie from the interior
surface where practice should start. Interior tiles vary across greens: US 10 uses
$3B extensively, while UK 10 uses $44/$46. A shortcut such as accepting only tiles
at or above $88 would exclude their putting surfaces. The authoritative editor and
Python surface set is `PUTTING_SURFACE_TILES` in `golf/formats/putting_surface.py`.
The current assembly's `ValidTile` encodes the same ranges explicitly; if that set
changes, update the assembly too, or generate its comparison chain from the sorted
contiguous runs of the set.

Pin offsets and green-view pixel coordinates range from 0 to 191 on each axis,
with eight pixel locations per green tile. Bank 13 $9523 onward performs the
course-to-green conversion; fixed-bank $DB21-$DB5B converts vanilla pin offsets
back into course coordinates. For a spawn tile `(tileX, tileY)` and pixel offsets
`(pixelX, pixelY)` in 0-7, the new runtime writes:

```text
BallX        = GreenX + tileX
BallXfraction = 32 * pixelX + 16
BallY        = GreenY + tileY       (16-bit sum)
BallYfraction = 32 * pixelY + 16
```

The extra 16 centers the ball within the chosen pixel's fraction interval. Ball Y
high is the carry from the Y addition; it is zero for this synthetic hole. Do not
infer it from the tee's Y high byte: vanilla tees can lie below row 255 even when
their greens lie near the top of the hole. Excluding `(pinX // 8, pinY // 8)` removes
the entire cup-containing tile, avoiding a dependence on the cup's exact fractional
center or capture radius. There is no additional minimum-distance or slope bias.

### Far calls, scratch registers and randomness

`ExecuteFarCall` ($D372) consumes six bytes at the hook: `JSR $D372` followed by
three inline bytes `[bank, address-low, address-high]`. It restores the caller's bank
and skips those inline arguments on return. The target receives the incoming A/X/Y;
the target's returned A/X and status flags survive the bank restoration. It does
not preserve the caller's original X if the target changes it, and Y is not restored.
`SetupGreen` therefore explicitly saves/restores X, while `PlaceBall` keeps the player
index in X throughout. The fresh-hole loop does not need Y after the spawn call.

Far calls use $30-$32 and $4C-$4F as scratch. In particular, `InitHole` keeps its doubled
hole index in $31; preserving X in `SetupGreen` ensures the far-call return writes
that index back into $31 before terrain lookup. The apparent $0102,X/$0103,X reads
inside $D372 are stack-relative return-address reads after TSX, not indexed accesses
to course metadata. A banked payload may call fixed-bank routines directly; calls
to another switchable bank must use an appropriate bank-switch/far-call mechanism.

`LSFR_RNG_ALGO` ($D29C) advances the state at $42/$43, returns the low byte in A,
and preserves X/Y. `PlaceBall` uses $26/$27 for tile coordinates, $28/$29 for the
tile-buffer pointer, $2A for retries, and $2C/$2D for the excluded pin tile. These
scratch bytes are not live at the fresh-hole splice. Random tile draws mask to 0-31
and reject 24-31 rather than fold them into the 24-wide box. After 255 rejected
attempts the raster scan finds a valid surface tile; sparse custom greens were the
reason to retain a guaranteed fallback instead of assuming rejection always succeeds.

Player 1 and player 0 get separate spawn draws. Their wind RNG slots are captured at
$8185 after each spawn, so those slots can differ. Wind does not affect putting here.
A future patch intended to coexist with seeded wind would need to define an RNG
preservation contract; this standalone hack deliberately advances the shared state.

Bank 13 $BF83-$BFF2 and fixed $CA40-$CAFF can be claimed by mercy, seeded-wind,
practice-swing and WRAM-expansion patches in other builds. Availability depends on
the complete patch stack; neither an $FF scan nor an outdated occupancy list
establishes it. Use this build's verified data-region boundaries and complete write manifest; its
reuse of $CA40 is one reason it is incompatible with general randomizer stacks.

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
