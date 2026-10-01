+++
status = "accepted"
date = 2026-09-23
area = "patches"
permanent = false
revisit_when = "Multi-course generation (devplan item 16) is scheduled, or a patch is wanted on a ROM that keeps its vanilla courses"
drafted_by = "Claude"
supersedes = []
+++

# One course per ROM

## Context

The vanilla ROM holds three 18-hole courses, each in its own terrain bank. Custom holes
and holes taken from Mario Open Golf often compress worse than the originals, so an
18-hole course built from them doesn't fit one bank's terrain region. The
`multi_bank_lookup` patch fixed that by looking up the terrain bank per hole, and
`CoursePatch` (then `PackedCourseWriter`) packs one course across banks.

That left open how much of the vanilla structure a written course had to coexist with:
whether the other two course slots stayed playable, whether the course mirrors were
optional steps, and whether attribute streaming applied only when a hole needed it. On
2026-09-03 the answer to the last was to detect it per write, which meant
`multi_bank_lookup` carried a special case for running with or without streaming.

The modular patch system was also meant to let small patches apply to the vanilla
game on their own, and a course writer that kept the vanilla courses around would have
kept that combination working too.

## Decision

A ROM that carries a written course carries exactly one 18-hole course, every time.
Writing a course makes it a randomizer ROM:

> Only write one course to a rom, every time, forever. […] Always apply both mirrors.
> […]
> One of the "points" of the modular patch system is that some of these smaller patches
> could in theory be applied to the vanilla game. But I think that once we write an
> entire course to the game we're basically calling it a 'rando rom'.

Concretely, `CoursePatch` requires `multi_bank_lookup`, `course_mirrors` (every course
slot plays holes 0-17) and `wram_expansion`, and never writes the slots for holes
18-53. Menu trimming reduces course select to a single RANDOM COURSE option as a
second guard.

Small patches such as seeded wind or the mercy tap-in can still be applied to a
vanilla ROM by themselves; what's no longer supported is a written course alongside
vanilla ones.

## Rejected alternatives

- **Detecting attribute streaming per write** (chosen 2026-09-03, reversed here). Two
  code paths in `multi_bank_lookup` for one feature. Attribute streaming was later
  removed altogether in favor of a larger attribute buffer inside `wram_expansion`.
- **Choosing the mirrors from the hole count.** The course patch would decide which
  slots to mirror; always applying both is simpler and leaves no slot playing
  vanilla holes.
- **Keeping the other vanilla courses playable.** Bank 2's terrain and the metadata
  for holes 18-53 would stay reserved for course data that a randomizer ROM never
  uses.
- **Two courses in one ROM, for a 36-hole round.** Deferred rather than rejected on
  2026-09-06: "For now, 1-course is fine and if we want to play a two course round we
  can generate two randomized roms."

## Consequences

- Bank 2's terrain region (`$837F`-`$A553`, 8,661 bytes) is free. The scorecard QR
  image and code live there.
- The fixed-bank metadata for holes 18-53 is free. `seeded_wind` keeps its seed table
  in the course-3 block of the flag X table, and the scorecard QR trampoline sits in
  greens pointer slots 18-53 at `$DCBD`.
- `CoursePatch` allocates terrain across banks 0 and 1 only, with a per-hole bank table
  at `$A700` in bank 3, and writes the same scorecard totals into all three course
  slots.
- A multi-course round needs one ROM per course. Reversing this decision would mean
  moving the QR patch and the seed table out of the space they now occupy.

## Sources

- `CLAUDE.md`, "One course per ROM"; `docs/multi_bank_terrain.md`
- `golf/core/patches/course.py` (module docstring), `golf/core/patches/scorecard_qr.py`,
  `docs/scorecard_qr.md`
- Claude Code sessions: 2026-09-03 `82a34228` (per-write detection);
  2026-09-06 `a5886d28` (one course for now, two ROMs for a two-course round);
  2026-09-12 `e7c41e36` ("we will not have three courses on the rom, ever");
  2026-09-13 `6f3c0621` (the decision quoted above)
