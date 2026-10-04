# Text Scripts

> **Note**: This document was written by Claude based on investigation requested by jdharms.

The dialogue in the course intro and the money cutscenes is a byte-code program in bank 11,
not a string table. Text is stored as **plain mixed-case ASCII** inline in the script (a
search for `TRY TO GOLF WELL` finds nothing; it is stored as `Try to golf well`), mixed with
opcodes that branch on RAM, call script subroutines and call into 6502 code.
`golf-rom-peek trace` walks every script (`golf/core/text_script.py`) and
`golf-rom-peek known-data` labels them.

The scenes that run scripts are documented in `docs/course_intro_scene.md` and
`docs/prize_money.md`; this document is the interpreter and its data.

## The interpreter

`RunTextScript` is bank 11 `$9033`, reached by `ExecuteFarCall` once a frame from four
bank 12 scene loops:

| Tick site | Scene entry | Entered from |
|---|---|---|
| `$9039` | `$8F34` / `$8F38` (Prize Money) | club house `$85`; bank 9 `$B0CC` |
| `$96A0` | `$9262` (course intro) | bank 13 `$804F` |
| `$A462` | `$A35F` / `$A4A4` | bank 9 `$B1A6`, `$B2C8` / `$B1A0` (around `CurrentWager` `$6018`) |
| `$A87F` | `$A7BF` | bank 9 `$B0D7` (`TotalMoney` high byte) |

Each frame it does one of these, in order:

1. if `ScriptResumePtr` (`$06E9/$06EA`) has a non-zero high byte, `JMP ($20)` to it (`$90AB`)
   instead of stepping - the per-frame callback `$F7` installs;
2. if `ScriptDelayCounter` (`$06E5`) is 0, nothing: the script has stopped (`$FD`);
3. bit 7 of `$06E5`: wait for a button (`$FC`), then clear the window;
4. bit 6: run the portrait animation `$F1` started (`$93D1`);
5. `$06EB` non-zero: clear the next window row (`$FA`, `$FC`);
6. otherwise count `$06E5` down and, at zero, set it back to 1 and run one token at
   `ScriptPtr` (`$06E7/$06E8`).

So after the scene seeds `$06E5` (`$16` in the course intro: a pause before the first
character), one token runs a frame - the typewriter effect.

`ScriptPtr` is a **bank 11** address: the far call has switched bank 11 in before the
interpreter reads it, even though the scene that set it runs in bank 12.

## Opcodes

Bytes below `$F0` print a character (`$90AE`). `$F1`-`$FF` dispatch through
`DispatchInlineJumpTable` at `$906C`; `$F0` has no entry, and as the dispatcher returns past
its table on no match, a `$F0` would be skipped without advancing - the interpreter would
hang on it. Addresses are little-endian; `[a]` is the byte at RAM address `a`.

| Op | Bytes | Handler | Meaning |
|---|---|---|---|
| `$00`-`$EF` | 1 | `$90AE` | print a character |
| `$F1 n` | 2 | `$9373` | start portrait animation `n` from `ScriptAnimationPtrTable` (`$947C`, 2 entries); sets bit 6 of `$06E5` |
| `$F2 a t` | 5 | `$9343` | go to `t` if `[a] == 0` |
| `$F3 x y` | 3 | `$9324` | set the cursor (`$06EC`, `$06ED`) |
| `$F4 a v t` | 6 | `$92E7` | go to `t` if `v >= [a]` |
| `$F5 t` | 3 | `$9162` | go to `t` |
| `$F6 a v` | 4 | `$92C3` | store `v` to `[a]` |
| `$F7 t` | 3 | `$92A4` | install `t` as the per-frame native callback (`ScriptResumePtr`), then continue |
| `$F8 t` | 3 | `$9285` | call native code at `t` (`JMP ($22)` at `$92A1`), with `ScriptPtr` already past the operand |
| `$F9 n` | 2 | `$924E` | select window `n` from `ScriptWindowGeometryTable` |
| `$FA` | 1 | `$91F4` | clear the window |
| `$FB` | 1 | `$91D0` | newline: x back to `ScriptWindowLeft`, y += 2 |
| `$FC` | 1 | `$9176` | wait for a button (bit 7 of `$06E5`), then continue |
| `$FD` | 1 | `$9170` | stop: clears `$06E5` without advancing |
| `$FE t` | 3 | `$914B` | call a script subroutine; the return address goes to `ScriptReturnPtr` (`$06FB/$06FC`) |
| `$FF` | 1 | `$913E` | return from it |

There is one level of script subroutine: a second `$FE` overwrites the return address.
Natives that need a nested call save it to `$06FD/$06FE` first (see `$B84E` below).

## Characters

`PrintScriptCharacter` (`$90AE`) maps ASCII to a tile with the inline `(lo, hi, delta)`
range table at `$90B1` (`ScriptCharRangeTable`, read by `LookupInlineRangeTableBank11`):

```
41 5A BF   ; 'A'-'Z'  -> $00-$19
61 7A B9   ; 'a'-'z'  -> $1A-$33
2C 3A 08   ; ','-':'  -> $34-$42   (covers '.', '/' and '0'-'9')
21 24 22   ; '!'-'$'  -> $43-$46
3F 3F 08   ; '?'      -> $47
27 27 21   ; '\''     -> $48
00
```

This differs from the menu system's uppercase-only remapping (`docs/menu_system.md`).

## Windows

`ScriptWindowGeometryTable` (`$9648`) holds left, top, right and bottom for each window.
The scripts select windows 0-3, so the table is 16 bytes and ends where the first DK
script starts (`$9658`).

## Where scripts start

A scene stores a script address in `ScriptPtr` and lets the interpreter run. 18 are
immediate stores in bank 12:

| Script | Set at | | Script | Set at |
|---|---|---|---|---|
| `$9658` | `$8FAA` | | `$AFDB` | `$9464` |
| `$96EA` | `$8FB9` | | `$B105` | `$936D` |
| `$A0EE` | `$9293` | | `$B656` | `$946F` |
| `$A2D5` | `$929E` | | `$B6A3` | `$9378` |
| `$A33C` | `$92A9` | | `$B6F3` | `$93B9` |
| `$A8A2` | `$92E3` | | `$B75F` | `$944D` |
| `$AA2F` | `$931F` | | `$B8DD` | `$A3F2` |
| `$ABED` | `$93A3` | | `$B93C` | `$A403` |
| | | | `$BBAF` / `$BC7D` | `$A95D` / `$A96C` |

The rest come from pointer tables, each sized by the index its loader uses
(`SCRIPT_POINTER_TABLES` in `golf/core/text_script.py`):

| Table | Entries | Indexed by |
|---|---|---|
| bank 12 `$92C3` `OpponentIntroScriptPtrTable` | 12 | `(OpponentGolferIdentity - 1) * 4`, plus 0 or 2 at random (`$93DF`) |
| bank 12 `$940A`, `$9422` | 12 each | the same, chosen by the score against par at `$93C8` |
| bank 12 `$9402`, `$9406` | 2 each | 0 or 2 at random from `$93F0`, based at `$938B` / `$9396` |
| bank 12 `$A9A5` | 6 | `A * 2` at `$A8DC`, whose callers pass 0-5 |
| bank 11 `$962E` | 13 | the `TotalMoney` bracket 0-12 at `$95F9` |
| bank 11 `$A072` | 3 | `(A AND 3) * 2` at `$A061`; a fourth entry would be the next script's first bytes |
| bank 11 `$B812` | 3 | `CurrCourse`: the course names |
| bank 11 `$B83E` | 2 | `(GolfGameMode AND 3) - 1`: "18" or "36" |
| bank 11 `$B8C1` | 4 | the ordinal suffix, "st" to "th" |

The bank 11 tables are read by native code that a script calls with `$F8`, which then
picks the next script itself; the script doesn't continue after that `$F8`.

`FE FF 06` calls the fragment natives build in RAM at `$06FF`, which is how the player's
registered name and formatted numbers get into a sentence.

## Native code

`$F8` and `$F7` operands are bank 11 code, reached no other way:

| Code | Called from | What it does |
|---|---|---|
| `$94DC`, `$9511`, `$9554`, `$956B`, `$95D5`, `$95DE` | the DK scripts | not yet read individually |
| `$95BD` | `$972A` (`$F7`) | the per-frame callback |
| `$95E7` | `$97B3` | picks the money-bracket script from `$962E` |
| `$9F1E` | `$A13E` | money to a digit string (repeated subtraction of `$64` and `$0A`); the stroke-play intro calls it too |
| `$9F99`-`$A0DC` (nine entry points) | the course intro and match scripts | not yet read individually |
| `$A05B`, `$A099` | `$A058`, `$A096` | pick the next script from `$A072` |
| `$B800`, `$B827` | `$B7FD`, `$B824` | pick the course name / "18" or "36" |
| `$B84E` | `$B848` | formats a number into the `$06FF` fragment through bank 12 `$9FC0`, saves `ScriptReturnPtr` to `$06FD`, and calls the fragment |
| `$B883` | `$B84B` | picks the ordinal suffix from `$B8C1` and restores `ScriptReturnPtr` from `$06FD` |

## Layout

| Bank 11 | Contents |
|---|---|
| `$9033`-`$9657` | the interpreter, its handlers, the native routines above, `$962E` and the window table |
| `$9658`-`$9F1D` | the DK dialogue (Prize Money): the winnings-milestone ladder from `$100,000` up |
| `$9F1E`-`$A0ED` | money formatting and the other shared natives |
| `$A0EE`-`$BEE4` | the course intro, match, opponent and money-scene scripts |

The ending scene's last scripts are "Thank you..." (`$BBAF`, set at bank 12 `$A95D`) and
the credits (`$BC7D`, `$A96C`), which the title screen's button combo jumps to
(`docs/title_screen.md`).

## Open questions

- The prize-award script at `$B997` ("We hereby award you...") follows a `$FD` and nothing
  the walker finds points at it.
- What `$070F`, poked by `F6 0F 07 00` / `F6 0F 07 FF` around lines of text, controls.

## Example: the stroke-play intro

`$A0EE`, the script the course intro runs for stroke play:

```
$A0EE  F9 02              ; select window 2
$A0F0  F2 AD 61 F8 A0     ; if [$61AD] == 0 -> $A0F8
$A0F5  F5 FD A0           ; go to $A0FD
$A0F8  F2 AE 61 77 A1     ; if [$61AE] == 0 -> $A177
$A0FD  F6 0F 07 00        ; store $00 to $070F
$A101  "The following are your latest 2 scores" ...
...
$A177  F4 03 60 02 80 A1  ; if $02 >= [$6003] -> $A180
$A180  F6 0F 07 00
$A184  "Try to golf well, as a" FB "lower score may give "
       "youa higher player rank." F6 0F 07 FF FC
```

`$61AD/$61AE` are the cumulative-score words in SRAM, so a save with no rounds played gets
the "Try to golf well..." line and an established save gets its last two scores, its
average and its rank instead.
