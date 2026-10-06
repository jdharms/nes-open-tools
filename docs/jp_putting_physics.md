# Putting in Mario Open against NES Open

> Note: Written by Codex and Claude

Does Mario Open Golf (JP) putt differently from NES Open (US)? In one respect: **in the
cup close-up, Mario Open doubles the green's slope vector, and NES Open does not.** The
slope tables, the putter's power tables, the swing meter rates and the green rolling code
are otherwise the same in both ROMs, at different addresses.

The US side is described in [green_slope_physics.md](green_slope_physics.md) and
[shot_physics.md](shot_physics.md). JP addresses are indexed in
[jp_rom_map.md](jp_rom_map.md).

## What is the same

Tables, byte for byte:

| Data | US | JP | Length |
|---|---|---|---|
| Slope X codes | fixed `$F359` | fixed `$F290` | 48 |
| Slope Y codes | fixed `$F389` | fixed `$F2C0` | 48 |
| Slope magnitude low bytes | fixed `$F3B9` | fixed `$F2F0` | 7 |
| Slope magnitude high bytes | fixed `$F3C0` | fixed `$F2F7` | 7 |
| Putter power on the green (`$5D`, `$73`, `$A0`) | bank 13 `$B8DC` | bank 13 `$B95D` | 3 |
| Putter power off the green (`$40`, `$60`, `$80`) | bank 13 `$B8E1` | bank 13 `$B962` | 3 |
| Swing-speed power factors (`$D7`, `$E3`, `$EE`) | bank 13 `$B8EC` | bank 13 `$B96D` | 3 |
| Timing power curve | bank 13 `$B909` | bank 13 `$B98A` | 57 |
| Swing meter rates (`$0100`, `$0150`, `$01A0`; halved for putting) | bank 13 `$AB46`, `$AB49` | bank 13 `$ABAF`, `$ABB2` | 6 |

The seven slope magnitudes are:

| Class | Value |
|---|---|
| Flat | `$0000` |
| Gentle, cardinal | `$2840` |
| Gentle, diagonal component | `$28A0` |
| Moderate, cardinal | `$5080` |
| Moderate, diagonal component | `$514A` |
| Steep, cardinal | `$78C0` |
| Steep, diagonal component | `$79F4` |

Code, with the same results for the same inputs:

| Routine | US | JP |
|---|---|---|
| Slope vector loader, writing `$EA`-`$EF` | fixed `$F300` | fixed `$F229` |
| Putt launch | bank 13 `$AD0A` | bank 13 `$AD73` |
| Green slope and friction | bank 13 `$B1D5`-`$B270` | bank 13 `$B256`-`$B2F1` |
| Cross-axis scaling (dark against light slope tiles) | bank 13 `$B6DD` | bank 13 `$B75E` |
| Cup-view position update, at a quarter of the velocity | bank 13 `$AF75` | bank 13 `$AFF2` |
| Cup-view physics, every fourth frame | bank 13 `$B7A7` | bank 13 `$B828` |

Both games read the dark slope tiles `$30`-`$47` and the light ones `$88`-`$9F`. The
zero-page variables this code uses sit one byte lower in JP: the view mode is `$97` where
US has `$98`.

## The JP doubling

The US loader returns at `$F358`. The JP loader has one more block before its return:

```asm
; JP $F281-$F28F
bit $97           ; view mode
bvc done          ; bit 6 clear
bpl done          ; bit 7 clear
asl $EA
rol $EB           ; X magnitude doubled; its sign in $EC is untouched
asl $ED
rol $EE           ; Y magnitude doubled; its sign in $EF is untouched
done:
rts
```

It doubles both magnitudes when bits 6 and 7 of the view mode are both set, which is the
cup close-up (`$C0`). The green view (`$40`), the view behind the golfer (`$80`) and the
overhead view (`$00`) are left alone.

This is the vector the ball physics uses, not only the one the slope arrows are drawn
from: the JP green terrain classification calls the loader at `$EDAE`.

Doubling the vector does not exactly double its effect on the ball. The rolling code
scales the vector by the ball's velocity and truncates, and the same vector feeds the drag
term. One green update on the gentle dark tile `$31`, for a ball moving straight along Y at
`$004000`:

| ROM and view | X magnitude | X velocity after | Y velocity after |
|---|---|---|---|
| US, any view | `$2840` | 50 | 16271 |
| JP, green view | `$2840` | 50 | 16271 |
| JP, cup close-up | `$5080` | 100 | 16221 |

The cup close-up already runs slower in both games (the last two rows of the code table),
so the doubling acts on a ball moving at a quarter of its speed with physics on every
fourth frame.

Returning at JP `$F281` instead of running the block would make the JP loader match the US
one.

## Not verified

The comparison was made by comparing the tables above and by running each ROM's loader,
launch and rolling routines under py65 with matched inputs: the loader for every tile byte
in the four view modes, the launch over three swing speeds, eight power stops and eight
aim directions, and the rolling update on every slope tile. Nothing was run in an
emulator.

Not compared: cup collision, rim-ins and lip-outs, how the cup view is drawn, and the
default player settings. The Python physics model (`golf/physics/`) uses US addresses and
has no cup-view doubling, so it does not model JP putting.
