+++
status = "proposed"
date = 2026-11-07
area = "randomizer"
permanent = false
revisit_when = "a derived hole of its base's own par is published, players ask for forward tees in full courses, or how a family's share is split between its pars changes"
drafted_by = "Claude"
supersedes = []
+++

# Only courses that are mostly par 3s draw derived holes

## Context

The derived holes being made are par 3s from the forward tees of vanilla par 4s and
par 5s (`docs/derived_holes.md`), about 47 of them on jdharms's list of candidates.
ADR 0023 lets a seed's settings `include` them; ADR 0025
had the form include them in a par 3 course only.

`golf-derive` puts a derived hole in its base's family, so a course holds a hole or the
hole derived from it, not both. `Problem.mix` draws a family and then one of its
members, which gives each member an equal part of its family's share whatever its par.
A base whose family gains a derived par 3 keeps half a share of the par 4 or par 5
slots, and the derived hole takes the other half in the par 3 slots.

Generation was surveyed over 800 seeds a case, with stand-ins for the 47 derived par 3s
added to the real pool and an expert cap of 1:

| Course | Sources | A vanilla par 3 | A base hole | Any other par 4 or 5 |
|---|---|---|---|---|
| Standard | NES Open | 33% → 19% | 33% → 25% | 33% → 43% |
| Standard | Both ROMs | 12.5% → 6.6% | 13% → 9.8% | 12% → 14% |
| Natural par | NES Open | 26% → 15% | 34% → 26% | 37% → 45% |
| Executive | Both ROMs | 44% → 21% | 3.6% → 2.3% | 3.5% → 4.5% |
| Par 3 | Both ROMs | 56% → 26% | — | — |

In a full course the holes chosen as the best candidates, the bases, come up about a
quarter less often, and the holes nobody derived from come up more often to fill their
place. A par 3 course holds no par 4 or par 5, so there the derived holes cost no base
anything. An executive course holds 2 to 6 par 4s, and draws its par 3s from a pool that
NES Open's 12 alone cannot fill. Par 3 courses have been more popular with players than
expected.

## Decision

- The generate form includes derived holes (`"include": ["derived"]`) in a par 3 course
  and an executive course, `SHORT_MODES` in `server/forms.py`.
- A standard, natural par or vanilla course from the form has no `include`, so it draws
  vanilla holes only.
- A request file and the CLI may still include derived holes in any course; that is a
  player's explicit choice (ADR 0016).
- How a family's share is split between its members is unchanged.

## Rejected alternatives

- **Derived holes in every course.** It cuts the bases' share of the full course's par 4s
  and par 5s by about a quarter, and every vanilla par 3's by nearly half (Context).
- **Every derived hole in full courses but the ones tagged `short`**
  (`exclude_tags: ["short"]`). Today every planned derived hole is a forward tee tagged
  `short`, so it gives the same pools as this decision with one more setting to carry.
  It is the way to let a same-par variant, such as a redrawn dogleg, into full courses
  once one is published.
- **A family's full share in each par it can fill**, a change to `Problem.mix` and the
  search's `_choose`. Bases would keep their share, but in a standard course the derived
  holes would take about two thirds of the par 3 slots, pushing the vanilla par 3s down
  further.
- **Derived holes in families of their own** (`golf-derive --family`). Each family keeps
  a full share, but a course could then hold a base and its own forward tee.

## Consequences

- Standard and natural par seeds from the site draw exactly as they did before the
  derived holes; publishing one changes none of their odds.
- An executive course from the site gains the derived par 3s. Its few par 4 slots draw a
  candidate's base about a third as often as before.
- Within a par 3 course a vanilla par 3 still carries a whole share and a derived hole
  half of one, so each vanilla par 3 comes up about 1.4 times as often as each derived
  one.
- Once derived holes are published, NES Open's holes alone can fill a par 3 course (34
  par 3 families) and an executive one. The form refuses both today
  (`MODES_NOT_FROM_US_ALONE` in `server/forms.py`), a check meant to last until the pool
  grows.
- A same-par derived hole would be kept out of full courses too until this is revisited.

## Sources

- `docs/derived_holes.md`, `docs/manifest.md`, `docs/thoughts_on_par_6.md`
- `server/forms.py`, `golf/randomizer/compose.py`, `golf/randomizer/pool.py`
- ADR 0016, ADR 0022, ADR 0023, ADR 0025
- Claude Code session 2026-11-07 `01Rn2bVx`: the survey above; jdharms on the bases'
  smaller share, "something I find quite worrisome", and the decision to "keep it this
  way but add in executive course, and just never let derived par 3s appear in 'full
  courses'", since par 3 courses "have been more popular amongst players than I
  expected".
