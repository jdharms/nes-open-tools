# FamiStudio Music

> **Note**: This document was written by Claude based on investigation requested by jdharms.

A proof of concept: the [FamiStudio sound engine](https://famistudio.org/doc/soundengine/)
runs beside the game's own audio engine and plays one music ID, so a course theme can be
any song exported from FamiStudio. Every other track and every sound effect is still the
game's. `music_format.md` describes the game's engine; this document covers only the second
one.

Nothing here is settled for the randomizer. The engine source and the songs are not in the
repository, the build needs cc65, and the space and RAM it uses are confirmed free by
static analysis and one Mesen write-breakpoint session, not by a full sweep.

## Building a ROM

```bash
# 1. Export the song from FamiStudio 4.5.3 (File > Export > FamiStudio Music Code, CA65),
#    or from its command line, which runs headless under .NET 8:
dotnet FamiStudio.dll song.fms famistudio-asm-export song.s -famistudio-asm-format:ca65

# 2. Assemble the engine and the song into a blob. --engine is the SoundEngine/ directory
#    of the FamiStudio source at the same version (famistudio_ca65.s and NoteTables/).
golf-famistudio-build --engine SoundEngine/ song.s -o song.fsblob

# 3. Patch it in. menu_trim is required.
golf-patch nes_open_us.nes -p menu_trim -p famistudio_music:blob=song.fsblob -o out.nes
```

The song must be in FamiStudio tempo mode (the engine is built for one tempo mode, and
cannot play both) and must not use DPCM samples. One song per blob; the first song of the
export is the one played.

## What is built

`golf/core/famistudio_engine.py` assembles the engine's ca65 source with every 2A03 feature
on, and with three settings that are about sharing the APU with the game:

| Setting | Value | Why |
|---|---|---|
| `FAMISTUDIO_CFG_SFX_SUPPORT` | 1, with 0 streams | The engine then writes to an 11-byte output buffer and copies it to the APU in one place. That copy is where the game's effects are given way to. No FamiStudio effect is ever played. |
| `FAMISTUDIO_CFG_DPCM_SUPPORT` | 0 | The engine writes `$4010`-`$4013` and `$4015` directly, not through the buffer, and the sample channel belongs to the game's `DmcUpdate`. |
| `FAMISTUDIO_CFG_SMOOTH_VIBRATO` | 0 | With it on, the engine also drives the sweep units and `$4017`, which the game's effects use. Off costs an occasional pulse phase reset when a note's high period byte changes. |

The engine source is edited in two places (`gate_engine_source`).

**The pulse channels are swapped.** The engine's eight pulse register names are given each
other's addresses, so FamiStudio's Square 1 plays on the hardware's pulse 2 and Square 2 on
pulse 1. Every menu effect (cursor, confirm, back out, denied: all of `$F0`) takes pulse 1,
the confirm ring for 35 frames, and a song's tune is usually on Square 1. The game's own
music is arranged the same way: a track's first stream, the melody, drives pulse 2
(`music_format.md`). The two channels differ only in their sweep units, which this build
does not use.

**The copy from the output buffer to the APU gives way to the game's effects.** The game's
three effect slots each hold one channel, and the byte that names the effect a slot is
playing is what the game's own sequencer checks:

| Channel | FamiStudio channel | Held while | When it is free again |
|---|---|---|---|
| Pulse 1 | Square 2 | `$F5` is non-zero | `$4001` is written `$08` each frame (an effect may leave the sweep unit on), and the cached high period byte is invalidated so `$4003` is rewritten |
| Pulse 2 | Square 1 | `$F6` is non-zero | the same, `$4005` and `$4007` |
| Noise | Noise | `$F7` is non-zero | `$400F` is written each frame, reloading a length counter an effect may have run out |
| Triangle | Triangle | never | no effect uses it |

A held note comes back on the first free frame. The game's sequencer instead keeps the
channel silent until that voice's next note.

A wrapper, `Tick`, is the blob's first byte and is called once a frame:

- `MusicSuspendFlag` (`$FF`) set: nothing runs, as with the game's sequencer. The cached
  high period bytes are invalidated, because `AudioEngineMain` empties the length counters
  through `$4015` when the flag changes.
- `MusicRequest` (`$F4`) is the engine's ID: the engine's RAM is cleared, the song is
  initialized and started, `PlayingMusicID` (`$F9`) is set to the ID and the request is
  cleared so the game's sequencer does not start its own track.
- `MusicRequest` is anything else: if the engine's track was playing, `PlayingMusicID` is
  cleared. The game's sequencer then answers the request and silences the channels, which
  it does for a stop and for a new track alike.
- Otherwise, while `PlayingMusicID` is the engine's ID, `famistudio_update` runs.

Callers that compare `PlayingMusicID` before requesting a track, as `StartCourseBgm` does,
behave as they do in vanilla, because the ID is held while the song plays. Effects that stop
the music (requests `$01` and `$02` in `$F1`) clear `PlayingMusicID` themselves and silence
the channels, and that stops the engine too.

The engine's eight zero page bytes are `$00`-`$07`. It uses them only inside its own
routines, so `Tick` saves them before each call and restores them after.

## The patch

`famistudio_music` (`golf/core/patches/famistudio_music.py`):

| Where | What |
|---|---|
| Bank 3 `$A923`-`$BEE7` | The blob, over the CPU opponents' recorded shots (5,573 bytes; `opponent_shots.md`). All four readers of those tables are in the opponent's turn at `$A869`, reached only from match play. |
| Fixed `$CAE4`-`$CAF3` | `FamiStudioFrame`: map bank 3, call the blob, map bank 14, `JMP AudioEngineMain`. |
| Fixed `$D2F7` | The NMI's `JSR $8000` calls `FamiStudioFrame`. The blob runs first because `AudioEngineMain` clears `MusicRequest` on its way out. |
| Bank 14 `$9379`-`$9382` | `SequencerUnlessFamiStudio`: `RTS` while `PlayingMusicID` is the engine's ID, else `JMP MusicSequencerTick`. It sits on the first bytes of the vanilla course themes' stream data. |
| Bank 14 `$8044` | `AudioEngineMain`'s `JSR MusicSequencerTick` calls the gate. The effect handlers and `DmcUpdate` are called from `AudioEngineMain` itself and are not affected. |
| SRAM `$677C` on | The engine's RAM: the score records of save slots 2-26 (`$677C`-`$6C0D`), which a `menu_trim` ROM never selects (`rom_map.md`, "Round save slots"). |

The engine answers music `$03`, what `CourseBgmTable` gives course 0. Music `$02` and `$04`
lose the first ten bytes of their streams to the gate; `menu_trim` leaves no way to
request either. `music_import` writes the same stream space, so the two patches cannot be
stacked.

## Sizes

Measured on the FamiStudio 4.5.3 engine with the configuration above:

| | Bytes |
|---|---|
| Wrapper and engine | 3,017 |
| RAM | 183 (8 of them the saved zero page) |
| Zero page | 8, borrowed |
| Room for the song | 2,556 |

The demo song "The Moon" (three melodic channels and noise, with the volume track, slide
notes and vibrato) exports to 1,635 bytes. Its frame costs about 1,500 CPU cycles on
average and 4,000 at worst, against 940 and 2,640 for the game's engine on a course theme.

## How it was checked

Under py65, with an MMC1 bus so the bank switches are real:

- For 3,600 frames the pulse, triangle and noise register state the ROM produces matches
  FamiStudio's own NSF export of the same song on every frame, with the two pulse channels
  exchanged. That includes starting from
  battery RAM full of garbage.
- Every track but `$02`-`$04` produces the write log it does in the vanilla ROM.
- For every effect request in `$F0`, `$F1` and `$F2`, the slot is held for the same frames
  and the music ID ends the same as in the vanilla ROM. While a slot is held the engine
  writes nothing to that channel, and it writes it again on the first frame after.
- A stop, a request for another track and a suspend each leave the engine writing nothing.

`tests/integration/test_famistudio_music_rom.py` checks the patch's hooks with a stand-in
blob, and `tests/unit/test_famistudio_engine.py` the source edit. The checks against the
real engine are not in the test suite, since the engine is not in the repository.

## Open

- **Not yet heard on hardware or in Mesen.** py65 says the registers are right; it does not
  say how an effect cutting in and out of a pulse channel sounds.
- **CLEAR SAVED DATA.** Its full wipe (`$ACCB`, reached from bank 14 `$B8E9`) zeroes
  `$6003`-`$7185` without a reset, the engine's RAM included. That is harmless while another
  track plays, since the engine's RAM is cleared at each start anyway, and untested while
  the engine's track is playing.
- **The phase reset effect** writes `$4003`/`$4007` directly, not through the output buffer,
  so it is not held back while an effect has the channel.
- **Drum samples.** The game's three recordings are raw DPCM at `$C000`, `$C340` and
  `$C540`, all on the 64-byte boundaries the engine wants. Using them needs a `.dmc` export
  for the composer, the song's sample table pointed at the copies in the ROM, and a way for
  the engine and `DmcUpdate` to share the channel.
- **One song.** A second song in the same blob has about 900 bytes; more than that needs
  the engine to be given a different bank, or its own.
- **How the engine is built for the site**, and whether its source is vendored.
- **The space and RAM** are worth an execute and read breakpoint sweep in Mesen before
  anything ships on them.
