+++
status = "accepted"
date = 2026-10-06
area = "randomizer"
permanent = false
revisit_when = "players report a band or profile plays unlike its name, a profile is wanted that an intensity per hole or a cone cannot express, or the speed wrap at 10 is patched and changes what anchors 9 and 10 play like"
drafted_by = "Claude"
supersedes = []
+++

# A seed has two wind profiles, speed and direction, with speed drawn in bands by intensity

## Context

With each hole's wind anchors free to choose (ADR 0017), a seed needs a rule for
choosing them. The profiles first listed were whole-wind ones: gentle, moderate, strong,
a storm that builds, an out-and-back. Listing more showed two kinds. A building storm,
a dying wind, a storm passing through and a hard back nine are about how strong the
wind is. An out-and-back, a prevailing wind and a forced headwind are about which way
it blows. As one list, every pairing would need its own name.

A speed anchor is not a simple strength. `WindAdjustmentRoutine` adds a jitter of -1 to
+2 each swing and takes 5 off any result of 10 or more (`docs/wind.md`, **Speed by
anchor**). Anchor 10 therefore plays at 5 on half its swings and never above 9, and
anchor 9 plays at 8-9 on five swings in eight and at 5-6 on the rest.

Every hole in both ROMs plays up the screen, so direction `$80` is a headwind and `$00`
a tailwind on all 144.

## Decision

`Settings` has two fields, `wind_speed_profile` and `wind_direction_profile`, each a
plain name and each `vanilla` by default. They are drawn independently, from their own
streams of the seed (`golf/randomizer/wind.py`).

**Vanilla** gives each hole the anchor its own wind seed deals. With both profiles
vanilla a seed plays as the game deals it, the coupling of direction and speed
included.

**Speed bands.** Gentle is anchors 0-3, moderate 4, 5, 6 and 10, strong 7, 8 and 9. An
anchor is drawn uniformly within its band.

**Intensity.** Every other speed profile gives each hole an intensity *t* from 0 to 1.
The hole draws its band with odds (1-t)², 2t(1-t) and t² for gentle, moderate and
strong: always gentle at 0, always strong at 1, and 25/50/25 at one half.

| Profile | Intensity |
|---|---|
| `gentle`, `moderate`, `strong` | That band on every hole |
| `storm_rolling_in` | 0, then 1/5 to 4/5 over the four holes the storm takes to arrive, then 1; it starts arriving on a hole drawn from 6-10 |
| `dying_wind` | The same reversed: 1, four holes falling, then 0 |
| `storm_passing` | Four holes arriving, three at 1, four clearing, 0 elsewhere; centered on a hole drawn from 7-12, which keeps the whole storm inside the round and the 1st and 18th calm |
| `back_nine_pressure` | 0 on the front nine, 1 on the back |

**Direction cones.** A cone is five neighboring directions drawn with weights 1, 2, 2,
2, 1 around a center.

| Profile | Center |
|---|---|
| `prevailing` | One drawn from all 16, for the round |
| `out_and_back` | One drawn from all 16 for the front nine, its opposite for the back |
| `headwind_out` | `$80` on the front nine, `$00` on the back |
| `tailwind_out` | `$00` on the front nine, `$80` on the back |

Rolls use whole-number weights and `randrange`, with no floating point.

## Rejected alternatives

- **One profile field naming the whole wind.** Five speed shapes and four direction
  shapes would be twenty names, or most pairings would not exist. A request (ADR 0016)
  also weights fields, so two fields can be rolled independently and one could not.
- **Strong as 7-8, with 9 and 10 left out as gusty.** jdharms placed 10 with moderate
  and 9 with strong: 10 plays mostly at 5-6, and 9 mostly at 8-9.
- **A ramp of a target anchor with noise added.** The anchors are not in order of
  strength, since 10 is moderate and 9 strong, so a rising number is not a rising
  wind. Bands keep jdharms's definition of each strength.
- **Hard change-over holes**, drawn at random, between gentle, moderate and strong.
  The wind would move in blocks. Mixing the bands by intensity lets a moderate hole
  come before the last gentle one.
- **A ramp across the whole round**: gentle on holes 1-3, strong on 16-18, a straight
  line between, and for the passing storm a tent from hole 1 up to the peak and down to
  hole 18. It was built first. Ten seeds of it read as a steady climb with a long mixed
  middle, a strong hole as early as the 5th and a gentle one as late as the 12th, more
  like changeable weather than a storm arriving. jdharms chose a short ramp placed at
  random.
- **A short ramp fixed in the middle of the round.** It is as sudden, but players would
  learn the hole the weather turns on.
- **A passing storm with a single peak hole.** With a four-hole ramp either side it
  would have two or three strong holes in the round, a squall more than a storm. It
  holds for three.
- **A bell curve for the passing storm.** It would need a width of its own. The same
  four-hole ramp up and down gives a bell-shaped chance of a strong hole already,
  because that chance is the square of the intensity.
- **A parameter on the out-and-back** for which way it faces. `headwind_out` and
  `tailwind_out` as names of their own keep every profile a plain string a request can
  weight.

## Consequences

- Any speed profile combines with any direction profile, 40 pairings from 13 names.
- A new speed profile is an intensity curve, and a new direction profile a rule for a
  cone's center.
- A sudden storm has little moderate wind: about one and a half holes of a four-hole
  ramp. A `storm_rolling_in` round is otherwise about half gentle and half strong.
- When a storm arrives varies by seed, so the same profile gives rounds that differ in
  how hard they are overall: the storm can start on the 6th or the 10th.
- A band profile no longer deals anchor 10 on a "strong" day or 9 on a "moderate" one,
  which a split by number would.
- The bands rest on the wrap at 10. A patch that changed it would change what anchors
  8, 9 and 10 play like, and the bands would need looking at again.
- The profiles are judged from the anchor tables in `docs/wind.md`, not from play.

## Sources

- `docs/wind.md` (**Speed by anchor**), `docs/wind_profiles.md`, `docs/seeded_wind.md`
- `golf/randomizer/wind.py`, `golf/randomizer/manifest.py`, `golf/randomizer/generate.py`
- Session with jdharms, 2026-10-06 (session bb6fe993): jdharms's bands, the split into
  two profiles, the cone and its weights, the profiles added (dying wind, passing
  storm, back-nine pressure, prevailing wind), and the short ramp placed at random in
  place of a ramp across the round, chosen after looking at ten seeds of the first.
