# Swing Speed on the Swing View HUD

The behind-the-golfer view's HUD shows the club, the hi/lo setting, the meter, the
yardage left and the lie, but not the swing speed, which is chosen on the overhead view.
Players who forget which speed they picked have to back out to the overhead view to
check, and starting a swing without knowing the speed is costly. The `swing_speed_hud`
patch (`golf/core/patches/swing_speed_hud.py`) adds an S, M or F to the club box:

```
vanilla   ┌────┬────┬──     patched   ┌────┬────┬──
          │CLUB│MID,│               │CLUB│MID │
          │ 1W │BALL│               │1W S│BALL│
```

## How the HUD is drawn

Bank 13 `$A499` runs once each time the swing view opens, from `ShotSetupSequence`
(`$8840`), and draws rows 24-27 of nametable 0 (PPU `$2300`-`$237F`):

- `NametableDescriptorDA4D5`: the top border and the label row (`CLUB`, `MID,`,
  the meter's background, `REST`);
- `NametableDescriptorTemplateDA519`: 68 bytes copied to `$0410`, the value row and the
  bottom border. The club name's two tiles go into `$0417`/`$0418`, columns 3-4 of the
  box, from `ClubNameFirstTileTableAlt` and `ClubNameSecondTileTableAlt`;
- `ShowDistanceToPin` (`$A170`), to which it tail-jumps, the yardage.

The swing loop later redraws the hi/lo label (`$A57D`, at PPU `$2327`) and the
SUPER SHOT banner (`$A5B1`), and nothing else in the club box. `SwingSpeed` (`$CE`)
cannot change while the swing view is up, so the letter is drawn once, with the club.

## The font

The tiles come from bank 4 `$A8A4` (`ChrGraphicsTable4A8A4`), loaded only by bank 5
`$BDCB` for this view. Its font is the digits at `$00`-`$09` and only the letters the
HUD's own strings use:

| Tile | `$0A` | `$0B` | `$0C` | `$0D` | `$0E` | `$0F` | `$10` | `$11` | `$12` | `$13` | `$14` | `$15` | `$16` | `$17` | `$18` | `$19` | `$1A` | `$1B` |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Glyph | A | B | C | E | G | H | I | , | L | M | O | P | R | S | T | U | W | D |

`$3B` is the blank. There is no F, so the patch redraws the comma, whose only use is
`MID,`, as one, and blanks the two commas after MID. The re-encoding of the compressed
stream, and the two lookback copies that had to move off the comma's bytes, are
described in the module docstring.

## Where the code goes

Nineteen bytes at `$BAD2`, the start of `StoreBallHeadingAndPinDistance`, a routine
nothing calls; the randomizer's stack has no padding left in bank 13 (ADR 0030).

## Not covered

- Putts: the green has its own view, and `$A499` does not run there.
- Not yet checked in Mesen: that no part of the swing view's scene draws tile `$11`.
  The scene's static nametable uses only `$1C`-`$3A`, and its tile tables are not
  letters, but nothing has proved it on screen.
