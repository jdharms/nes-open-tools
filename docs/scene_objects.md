# Scene Objects

> **Note**: This document was written by Claude based on investigation requested by jdharms.

Menus and cutscenes animate their sprites with a small object engine in the fixed bank.
A scene allocates objects from 9-byte records; each object then runs two byte-code
streams, one moving it and one animating it, and is drawn from metasprite data in bank 2
or bank 10. `golf-rom-peek trace` walks all of it (`golf/core/object_script.py`), and
`golf-rom-peek known-data` labels what it finds.

Which scene each object belongs to is not worked out here (`cutscene_sprites.md` does it
for the golfers); the record tables are named by
address, and their comments say which allocation site uses them.

## Records

`AllocateObjectRecords` (`$F7C0`, A = count, inline word = records) and `LF7EE` (A = count,
records at `$22/$23`) copy whole 9-byte records into free slots (`LFC2B_CopyObjectRecord`).
`LF7F3` (inline word) and `$F856` (record already in `SramPtr`) copy one 7-byte record,
entering the copy at `$FC39` past x and y: x and y come in X and Y, and A goes to
`$7921,X`. `LF826` does the same and also sets the slot's `$7AC1`-`$7B01` from the
caller's `$26`-`$2A`; a non-zero `$7AC1` puts the object under the scene callback (below).

| Byte | Slot array | Meaning |
|---|---|---|
| 0 | `$7811` | x |
| 1 | `$7841` | y |
| 2 | `$7A31` | sprite id; bit 7 marks a free slot |
| 3 | `$78F1` | OAM attribute |
| 4 | `$7A81` | clip window (bit 7: none) |
| 5-6 | `$7A41/$7A51` | motion stream |
| 7-8 | `$7A61/$7A71` | animation stream |

Records reached through tables rather than inline words are listed in
`RECORD_POINTER_TABLES`, each with the index range its loader uses and its record size:
9, or 7 for the short records `$F856` copies (`MaybeWagerChoiceRecordPtrTable`). Records reached neither way are in `RECORD_LISTS`:
`MenuSpriteInitData` (bank 12 `$8F10`), which the club house menu allocates through
`MenuEntryTablePtr` at `$85A8`, and three lists in bank 12 (`$B740`, `$B77F`, `$B7BE`) with
no allocator found, kept so the bytes their streams name are accounted for.

## Streams

`LF8CA` runs every live slot once a frame with the bank in `$3A` mapped. A stream only
advances when its countdown (`$7901` motion, `$7911` animation) runs out, so a step with
a count of 0 halts the stream for good.

**Motion** (`LF953`): bytes below `$D0` start a 3-byte step - frames, x speed, y speed.
`$DD lo hi` sets a velocity (`$FCB2`). Any other `$D0`-`$EF` byte has no handler and would
hang the engine.

**Animation** (`LFAA1`): bytes below `$E0` start a 2-byte step - frames, metasprite frame
(`$78D1`; bit 7 hides the object). `$EF n` sets the sprite id and `$ED lo hi` calls native
code through `JMP ($0C)` at `$FCF6` (`$FCD5`).

Both share the control opcodes at `LFB08`. An address operand with bit 15 set is an offset
into the object's own slot rather than an absolute address.

Native code can also point a slot at a new stream: `LDA #lo / STA $7A41,X` then
`LDA #hi / STA $7A51,X` (motion), or `$7A61/$7A71` (animation), with the stream in the
code's own bank. `code_streams` finds these stores in traced object-bank code and the
walker decodes the streams they name. The one that doesn't decode is bank 10 `$9D65`: each
branch ends in a 160-frame hold and a `$FE` to `$F798` or `$00C8`, so the scene presumably
replaces the object first.

| Op | Bytes | Meaning |
|---|---|---|
| `$F1 a` | 3 | decrement `[a]` |
| `$F2 x y` | 3 | set `$7821`/`$7851` |
| `$F6 a v` | 4 | store `v` to `[a]` |
| `$F7 a v t` | 6 | go to `t` if `[a] >= v` |
| `$F8 a t` | 5 | go to `t` if `[a] != 0` |
| `$F9 a t` | 5 | go to `t` if `[a] == 0` |
| `$FA` | 1 | loop end |
| `$FB n` | 2 | loop start, `n` times |
| `$FC` | 1 | return from a stream subroutine |
| `$FD t` | 3 | call a stream subroutine |
| `$FE t` | 3 | go to `t` |
| `$FF` | 1 | free the object |

A stream's `$F6` can start a text script: the tournament win animation (bank 10
`ObjectAnimStreamABAA9`, `$BB0A`) stores the address of `PrizeAwardTextScript` (bank 11
`$B997`) into `ScriptPtr` and 1 into `ScriptDelayCounter`, the only place that script is
named. `stream_scripts` collects such store pairs, and the trace walks the scripts they name
(`docs/text_scripts.md`).

## Sprites

`LoadObjectSpriteAttr` (`$FD54`) reads a word at `$8000 + 2 * sprite id` in the mapped
bank: a frame table, whose word at `2 * frame` points at a metasprite. Both banks start with
the same 18-word id table (`$8000`-`$8023`).

A metasprite is a run of chunks. The header's low six bits count sprites; bit 6 says
another chunk follows. With bit 7 clear each sprite is 4 bytes (dY, tile, attribute, dX);
with it set, one attribute byte follows the header and each sprite is 3 bytes. A header of
`$00` (ignoring bit 6) is an empty metasprite.

## Bank 2 or bank 10

`$3A` is only ever 2 or 10, and it is set at run time: the club house menu maps 10
(`LC_8565_ReturnToClubHouseMenu`), most of its screens 2, the fixed bank resets it to 2.
So the walker decodes each record against both banks and keeps the one where every stream
step, frame table and metasprite it reads is well formed. Bank 2's object data is only the
895 bytes before the UK terrain (`$8000`-`$837E`), so a bank 2 reading that strays past it
is rejected. Every record settles this way, or by the bank of records allocated within
`$100` bytes of it:

- bank 2: the objects of the banks 9, 11 and 14 screens (sprites `$10`, `$11`);
- bank 10: everything bank 12's cutscenes allocate (sprites `$01`-`$0E`).

## Native code

The engine reaches code two ways, both answered by the walker:

- `$ED` in an animation stream.
- The scene callback: `LF8A2`'s inline word is stored in `$7B11` and run through
  `JMP ($7B11)` at `$F950` for each object with a non-zero `$7AC1`. Its one setter, bank 12
  `$B933`, installs bank 10 `$9B57`, which dispatches on `$7AC1` through the three-entry
  `SceneCallbackHandlerPtrTable` (`$9BA4`). The wager scene's handlers place their objects
  by the wager choice (`$06BC`) from `MaybeWagerChoiceObjectXTable` (`$9C0D`).

## Open questions

- Which scene each record table belongs to. `cutscene_sprites.md` places the ones that
  draw a golfer (sprites `$01`, `$02`, `$03`, `$05`).
- What allocates the three bank 12 record lists in `RECORD_LISTS` with no allocator found.
