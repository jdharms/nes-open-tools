# JP ROM Map: Where to Look in Mario Open Golf

> **Note**: This document was written by Claude, at jdharms's request.

The counterpart of [rom_map.md](rom_map.md) for Mario Open Golf (`mario_open_jp.nes`): an
index from a topic to the bank and address to start reading from, and the doc that explains
it, if there is one. Add a row whenever you had to search this ROM to find something.

Every address here is a JP address. The label file covers the US ROM only, so run
`golf-rom-peek mario_open_jp.nes` without `--labels`; without labels `find-refs` reports
every hit as unverified and `disasm` decodes tables as code. The bank conventions are the
same as the US ROM's: bank 15 is the fixed bank (`$C000`-`$FFFF`), and every other address
is in the switchable window (`$8000`-`$BFFF`) of the bank named.

The course data tables (pointers, par, distances, decompression tables) are constants in
`golf/core/jp_rom_utils.py`, described in [jp_extraction.md](jp_extraction.md).

## Save and progression

| Topic | Bank | Start here | Doc |
|---|---|---|---|
| Reset to the menu | 15 | `$CD68` SRAM setup, `$CD6B` selects bank 13, `$CD70` jumps to `$8000` | `mario_open_free_play.md` |
| Save validity and initialization | 4 | `$B705` checks "5S" at `$6001` and `$6E0B`; `$B71E` clears SRAM from `$6003` | `mario_open_free_play.md` |
| Course progression | 13 | `$84FE`-`$850F` increments SRAM `$6003` (0-5) after a round on the newest course | `mario_open_free_play.md` |
| Course menu | 12 | `$80EC` picks the menu variant from progression and mode; `$89B0` maps the menu entry to a course index in `$0102` | `mario_open_free_play.md` |
| Remix course builder | 15 | `$DA22` fills the hole remap table at `$6DE7`; `$DA2C` reads progression | `jp_extraction.md` |

## Score limit

| Topic | Bank | Start here | Doc |
|---|---|---|---|
| Score limit setup | 12 | `$A264` loads RAM `$0658` from the six limits at `$A28F`-`$A294` | `mario_open_free_play.md` |
| Next-shot score check | 13 | `$8268`-`$8294`; continues at `$8297`, dismisses through `$847E` | `mario_open_free_play.md` |
| Dismissal handler | 13 | `$847E`; counts dismissals per course in SRAM `$6028`-`$602D` | `mario_open_free_play.md` |
| Round score | 13 | `$8DFC`-`$8E0E` updates the signed score relative to par at RAM `$04E6`-`$04E7` | `mario_open_free_play.md` |

## Putting and greens

| Topic | Bank | Start here | Doc |
|---|---|---|---|
| Slope vector loader | 15 | `$F229`, called from `$EDAE`; the cup-view doubling is its last block, `$F281`-`$F28F` | `jp_putting_physics.md` |
| Slope tables | 15 | `$F290` and `$F2C0` X and Y codes (48 bytes each); `$F2F0` and `$F2F7` magnitude low and high bytes (7 each) | `jp_putting_physics.md` |
| Green rolling | 13 | `$B256`-`$B2F1` slope and friction; `$B75E` cross-axis scaling | `jp_putting_physics.md` |
| Cup-view slowdown | 13 | `$AFF2` quarter-speed position update; `$B828` physics every fourth frame | `jp_putting_physics.md` |
| Putt launch | 13 | `$AD73` | `jp_putting_physics.md` |
| Putter power and timing | 13 | `$B95D` power on the green, `$B962` off it; `$B96D` swing-speed factors; `$B98A` timing curve (57 bytes) | `jp_putting_physics.md` |
| Swing meter rates | 13 | `$ABAF` low bytes, `$ABB2` high bytes | `jp_putting_physics.md` |

## Scenes and graphics

| Topic | Bank | Start here | Doc |
|---|---|---|---|
| Compressed graphics | 15 | `$D464` loader (inline bank, lo, hi), `$D689` loader from `$22/$23` and bank `$27`; same stream format as the US ROM | `golf/core/graphics_codec.py` |
| Course intro scene (the landscape after choosing stroke play) | 12 | `$A018` loads the graphics; entries `$9F41` and `$9F51` (the sunset showing); frame tick and raster split `$A122`; phase dispatch `$A161` | `course_intro_scene.md` |
| Course intro graphics | 8 | tables `$9D1A` (CHR `$0000`), `$AD1F` (CHR `$1000`), `$9483` (CHR `$1800`), `$B13B` (nametable) | `course_intro_scene.md` |
| Course intro palettes | 12 | pointer table `$A844` (entry 0 `$A906`); sunset background palette `$A9C6` | `course_intro_scene.md` |

## Commonly read RAM

| Variable | Address |
|---|---|
| View mode (`$C0` cup close-up, `$80` behind the golfer, `$40` green, `$00` overhead) | `$97` |
| Slope vector (X magnitude, X sign, Y magnitude, Y sign) | `$EA`-`$EF` |
| Game mode, course index | `$0100`, `$0102` |
| Par of the current hole, strokes taken on it | `$0109`, `$011F` |
| Score limit | `$0658` |
