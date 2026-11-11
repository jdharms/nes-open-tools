+++
title = "Game Changes"
nav_title = "Game Changes"
order = 100
enabled = true
listed = true
+++

This document records the changes that the randomizer makes from
the vanilla game.  Generally the randomizer works by applying a series
of patches to the vanilla game, one at a time.

## Menus

The game's menus have been significantly stripped down to remove
unnecessary features, or those that the randomizer would otherwise break.

The main menu shows the seed's three "Magic Words" where vanilla shows
"PLEASE SELECT COURSE".  This is a visual indicator to help you ensure
you have the correct ROM file loaded.

The Club House menu only contains Register Name, Choose Clubs, Options,
Training, and Clear Saved Data.  Choose Clubs will not be present if
the seed restricts club choice in any way.

Course select shows only a single option, our "RANDOM COURSE".

## The course

The 18 holes from the seed, however they were selected, are written to the
ROM.  The Scorecard screen displays the three Magic Words as well.  The
pre-hole signpost is a new custom banner created by spaces90 that reads
"RANDOM COURSE".

## During play

Several quality of life changes and bugfixes have been made:

* Shortcuts: During shot setup, press B until the "Lie Detail" popup
happens, and then press Select for the green detail view.  Press Start
instead for the scorecard.
* Mercy rule: After you take your 9th stroke on any hole you are
instantly given credit for holing out on the 10th stroke.
* Seeded wind and pins: All players will have the same pin position for each hole, as well as the same wind for each shot on each hole.
* Wind fix: All 16 wind directions affect the ball the way they should.
* Swing speed on the swing view: The "chosen club" box on the swing view HUD
displays a S, M or F after the club name to indicate what swing speed has
been selected.

## End of play

A ROM downloaded while signed-in will show a QR code after the final scorecard
for submitting stats to the randomizer site.

## Player options and defaults

Player name, club bag, BGM on/off setting, default swing speed, putt speed,
and ball spin settings are written into the ROM based on your selections
at download time.