# Seasonal Terrain Palettes

> **Note**: This document was written by Claude based on investigation requested by jdharms.

Recoloring the course for "seasons" (spring, fall, snow) by rewriting palette bytes. This
is a spike: two proof-of-concept ROMs (fall, and winter with an orange ball) were built
from `BytePatch` steps through `PatchStack` but have not been reviewed screen by screen,
and there is no patch module yet. The *sites* below were found by static reading with
`golf-rom-peek`; most are labeled in the `.mlb`, so read them with `--labels` rather than
from the byte values quoted here.

## Why it is safe for gameplay

The lie never depends on a color. `ClassifyProbePosition` (`$EDEA`) and `LEFA7` read the
attribute *palette index* of the supertile (1 fairway, 2 bunker, 0 or 3 water) and the
tile's mask; see `golf/physics/terrain.py`. The editor's feature detection
(`golf/algorithms/features.py`) also works from palette indices and tile pixels. Any
color value can change without touching play or the editor.

## The background palette's roles

`CourseViewPaletteData` (bank 13 `$8DE2`, 32 bytes, loaded by `LoadCourseViewTileset`)
holds the overhead view's palettes. Its background half, vanilla
`0F 1A 30 21 | 0F 1A 0A 2A | 0F 1A 0A 28 | 0F 1A 0A 21`:

| | Color 1 | Color 2 | Color 3 |
|---|---|---|---|
| Palette 0 | rough | HUD text (`$30`) | water |
| Palette 1 | rough | trees, deep-rough speckle | fairway (and tee box) |
| Palette 2 | rough | trees | sand |
| Palette 3 | rough | trees | water |

So a season is five values: rough, trees, fairway, sand, water. Constraints:

- **Rough is color 1 of all four palettes**, including the HUD's palette 0, because rough
  pixels sit in every supertile. It must be one value.
- **Palette 0 color 2 is the HUD text.** No vanilla hole (US, UK, Japan) puts a color-2
  pixel under palette 0, which is what keeps trees from drawing as HUD white.
- HUD font tiles use only colors 0 and 2 (white on black), so the rough color never
  touches text. A handful of HUD graphic tiles in the course tileset (about `$D2-$F0`)
  do use colors 1 and 3, so some HUD icons change with the rough and water colors.
- **In the green detail view the putting surface is color 1** (the rough color) and the
  fringe is color 3 (the fairway color); the slope arrows draw in color 3.
  `GreenDetailPaletteData` (`$95FE`) is a *separate copy* of the background half, so a
  season can keep the putting surface green while the overhead rough changes. Both
  spike ROMs do this.

## Sites a season writes

Each row is a role a season must decide. Addresses are bank:CPU.

| Role | Site | Vanilla | Notes |
|---|---|---|---|
| Overhead background | `CourseViewPaletteData` bg half, 13:`$8DE2` | as above | |
| Green view background | `GreenDetailPaletteData` bg half, 13:`$95FE` | same 16 bytes | independent copy |
| Water (palette 0 color 3) reset | immediate at 14:`$AF3A` (`LDA #$21 : STA $0479`) | `$21` | when this runs is unknown |
| Lie popup surface color | `LiePopupColorTable`, 13:`$A87D-$A883` | `2A 2A 1A 28 21 12 0A` | by `BallLie`: fairway, tee, rough, bunker, water, OOB, green; stored to sprite palette 1 color 3 |
| Swing-view ground sprites, fairway | `ShotScreenSpritePalettes` palette 3 color 1, 5:`$BEAD`; immediate 5:`$BF28` (color 2) | `$2A`, `$0A` | |
| Swing-view ground sprites, rough | immediates 5:`$BF42`, 5:`$BF47` | `$1A`, `$0A` | |
| Swing-view ground sprites, sand | immediates 5:`$BF5E`, 5:`$BF63` | `$28`, `$18` | |
| Cup close-up background | `CupViewPaletteData` bg half, 9:`$801A` | `0F 1A 20 21 \| 0F 2A 1B 1A \| ...` | own art; not yet given season values |

The swing-view ground sprites are the bank 5 dispatch at `$BDEA` (targets `$BF27`,
`$BF33`, `$BF41`, `$BF5D`), which set sprite palette 3 colors 1 and 2 and load a ground
graphic. The mapping of its four keys to lies (tee/fairway, ?, rough, sand) is inferred
from the colors and `RoughDepth`/`BunkerDepth` tests, not traced.

## The ball, and sprites that assume white is visible

The active ball's color is a different palette slot in each view. All are labeled.

| View | Ball's color slot | Source byte | Also drawn with that slot |
|---|---|---|---|
| Overhead (`DrawBallSprites`, `BallSpriteData`) | sprite palette 0 color 1 | 13:`$8DF3` | the `$C8` marker at `$913E`, the water splash (`$D8-$DA`) |
| Swing view (`DrawSceneBallSprite`, `SceneBallTileData`) | sprite palette 1 color 3; color 2 is a black outline | 5:`$BEA7` | club highlight pixels, power meter markers (`$CB`/`$CC`/`$E0`), and the lie popup, which overwrites it from `LiePopupColorTable` |
| Green view, small ball (`GreenViewBallSpritePtrLoTable`) | sprite palette 2 color 1 | 13:`$9617` | not enumerated |
| Green view, close ball; cup close-up | sprite palette 1 color 3 (black outline) | 13:`$9621` (`$961E` copy, not putting); 9:`$8031` | in the putting view palette 1 is Peach's |

The inactive player's ball is a separate metasprite in palette 2 color `$16` red
(`InactiveBallSpriteData`, `GreenViewInactiveBallSpriteData`), so it does not move with
the active ball. The swing and close-up balls have outlines and read on any ground; the
overhead and small green-view balls are solid single-color dots.

This is where seasons get expensive. Summer works because every sprite that shares the
ball's white also wants white. A snow rough breaks that: the overhead ball, the green
view's white sprites (ball, aim marker tile `$3D` in sprite palette 3 color 3), and the
swing-view aim crosshair all vanish. Recoloring one slot recolors everything sharing it;
separating them means changing a metasprite's attribute byte or retiling it. That fix is
made once and serves every season. Spring and fall mostly swap greens for greens or
browns, and collide with far fewer sprites.

## The spike ROMs

Both were built by a scratch script: one `BytePatch` per site, run through `PatchStack`
against the vanilla US ROM, so each step checked its vanilla bytes.

- **Fall**: rough `$18`, trees `$17`, fairway `$28`, sand `$37`, water `$11`; green view
  putting surface kept `$1A`; lie popup table and swing-view ground sprites recolored;
  ball untouched.
- **Winter (snow)**: rough `$30`, trees `$0B`, fairway `$3C`, sand `$3D`, water `$11`;
  green view putting surface kept `$1A`; overhead ball (13:`$8DF3`) and green-view ball
  (13:`$9617`) set to orange `$27`; swing-view ball left white. The lie popup table was
  not recolored in this build.

Reported from play of the winter ROM: the swing-view aim crosshair (a white sprite) is
invisible on snow, and the lie popup showed summer green (the table above was found
afterwards).

Mock-ups come from `golf/rendering/pil_renderer.py`: overwrite `PALETTES` and
`GREENS_PALETTE` in `golf/core/palettes.py` in place, then call
`render_hole_to_image` and `render_greens_to_image`. Drop the hole's `greens` key first:
the renderer's green overlay is an editor convention, not game art.

## Unknowns

- **The swing view's background palette.** Its loader (bank 5 `$BDBD`) copies only the
  sprite half (`$BDDC`), and no background load was found, so it presumably keeps the
  course view's. Unconfirmed; check the PPU palette in Mesen during a swing.
- **The swing-view aim crosshair**: which sprite and palette slot.
- **The lie popup's art**: whether the popup graphic has other summer greens besides the
  `LiePopupColorTable` color. Also the `LDA #$1A : STA $048D` at 13:`$A688`, which
  writes the same slot for some other popup.
- **The `$0479` write at 14:`$AF39`**: what screen or event runs it.
- **The `$0488 = $2A` write at 14:`$AF40`** (overhead sprite palette 0 color 2, the
  ball shadow's color): when it runs.
- **Sprites drawn by the object engine** (`LoadObjectSpriteAttr`, `$FD54`) were not
  enumerated; the shared-slot lists above cover only `RenderMetasprite` call sites.
- **What else uses sprite palette 2 color 1 in the green view.**
- **The `$C8` overhead marker at `$913E`**: what it marks.
- **Other screens with terrain colors**: bank 11 `$8A8F` loads course tileset tiles
  (bank 4 `$8009`) with a palette at 11:`$8AFB` containing `1A 0A 2A`; the screen is
  unidentified. The course intro scene, prehole signpost and scorecard were not checked
  for terrain-matching colors.
- `golf/core/patches/peach_dress.py` says the putting view's ball is sprite palette 3;
  the green-view ball metasprites read here use palette 2 (and a palette 3 ball would
  draw black). One of them is wrong.

## Plan

1. **Inventory every screen in Mesen** with one season (snow is the strictest): overhead,
   swing view including aiming, lie popup, green view putting and chipping, cup
   close-up, HUD, in-game menu, scorecard, hole transitions. For each wrong color,
   record its site and role in the tables above and label the address.
2. **Fix shared slots** found in step 1 where a season needs two sharers to differ, by
   moving a sprite to an unshared palette entry. These are code-level patches, made
   once.
3. **Write the patch module**: a role table (site, bank, address, role, vanilla value)
   and a season as a role-to-color mapping, built as a `CompositePatch` of
   `BytePatch`es and registered in `golf/core/patches/registry.py`. A site whose role a
   season leaves out keeps its vanilla byte, so incomplete seasons are visible.
4. **Contrast check**: for each sprite role, test its color against the background roles
   it can sit on, so a season like "orange ball on a gold fairway" fails before play.
5. **Seasons**: fall, spring, snow, each a mapping plus a playtest.
