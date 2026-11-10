+++
title = "Wind"
nav_title = "Wind"
order = 20
enabled = true
listed = true
+++

## How wind works in this game

Each time a new hole is started, the game's random number generator (RNG) is
used to create a wind "anchor" or base.  This anchor is both a **direction**
and a **magnitude** or wind strength. For each shot, including the first,
a "variance" is calculated from the RNG stream. The breakdown of this variance
effect is roughly:

* 50% chance to have the anchor's wind
* 25% chance to have 1 MPH stronger wind
* 12.5% chance to have 1 MPH weaker wind
* 12.5% chance to have 2 MPH stronger wind

If the 1 MPH weaker case would push the wind "negative", the wind
direction is reversed.  Otherwise the wind direction will remain the same
for the entire hole.

If after applying the variance the wind magnitude is 10 or greater, the
game lops off 5 MPH to bring it back to single digits.

Due to the game's RNG algorithm, anchor directions and magnitude are
not completely independent.  Each direction can only be paired with
four of the possible magnitude values.  This is true for the vanilla
game and for the randomizer with the "Vanilla" profiles selected.
The other randomizer profiles do not have this constraint.

## The Wind Fix

In the vanilla game, there is a buffer overrun on a table read that
causes wind in certain directions to behave wrongly.  The clearest
examples of this are that due east and due west crosswinds have
a strong south or north (respectively) component.

The randomizer, since v4.0.0, fixes this programming issue in the
vanilla game.  All wind pushes exactly the direction the in-game arrow
points, at exactly the strength the game's UI indicates.

## Seeded wind

In order to ensure that every player of a seed has to deal with the
same wind conditions, the wind RNG is seeded for all randomizer ROMs
at seed generation time.  This includes both the wind anchor for each
hole, as well as the variance for each individual shot.

## Randomizer wind profiles

The randomizer includes the ability to pre-set the wind anchor for
each hole according to a pair of "wind profiles".  A wind profile
is essentially the rule that seed generation uses to assign wind anchors
for each hole.  There are two types of profiles: speed profiles and
direction profiles.  Each is responsible for one component of the wind
anchors.  Each can be chosen independently.

### Speed profiles

We bucket the 11 possible wind anchor magnitudes (0-10) into three
strength categories:
* Gentle: 0-3
* Moderate: 4, 5, 6, 10
* Strong: 7-9

10 is lumped into "Moderate" because after applying the -5 MPH reduction
to get into single digits it ends up playing more like "moderate with
occasional gusts".

You can choose a speed profile in the "Roll Seed" page to determine
what category/categories (Gentle, Moderate, Strong) the wind will anchor at
for the course.

* Vanilla: The base speed the game would have used without any patches
beyond the seeding required to provide everyone the same conditions.
* Gentle / Moderate / Strong: every hole will have an anchor in that category.
* Storm rolling in: Holes 1-5 will be gentle, and holes 14-18 will be
strong.  The storm will "roll in" somewhere in between, over a handful
of holes.
* Storm falling off: Holes 1-5 will always be strong, and holes 14-18
will always be gentle.  The storm will "fall off" somewhere in between,
over a handful of holes.
* Storm passing through: The storm builds over four holes, holds full
strength for three holes, and clears over four holes.
* Back nine pressure: Holes 1-9 are gentle, holes 10-18 are strong.

The ramps and transitions mentioned above are deliberately rough. It's
meant to simulate some gusts or windy moments preceding or following a
larger storm.

### Direction profiles

In the non-vanilla options below, the directions are always somewhat
"loose".  If a tailwind needs to be picked as an anchor direction
for a hole, a direction in a cone of five compass points, centered around
due North, would be chosen.  The middle three directions are twice
as likely to be chosen as the outer two directions.

* Vanilla: The base direction the game would have used without any
patches beyond the seeding required to provide everyone the same
conditions.
* Prevailing: A random direction is chosen and used for the cone's
center for the full round, so you'll have roughly the same direction
wind all day.
* Out and back: A random center for the front nine, and the opposite
direction for the back nine.
* Headwind out: This is "Out and back" but with a headwind for the front nine
and a tailwind for the back nine.
* Tailwind out: This is "Out and back" but with a tailwind for the front nine
and a headwind for the back nine.