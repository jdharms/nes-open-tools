"""
FamiStudio course theme patch. A proof of concept; see docs/famistudio_music.md.

Runs the FamiStudio sound engine beside the game's own, for one music ID: the
course theme of course 0, the only one a `menu_trim` ROM plays. Every other
track, and every sound effect, is still the game's.

The engine and its song are a blob built by `golf-famistudio-build`
(`golf/core/famistudio_engine.py`). This patch places it and makes three hooks:

  * The NMI's `JSR $8000` (AudioEngineMain) at `$D2F7` calls `FamiStudioFrame`
    in the fixed bank instead, which maps bank 3, calls the blob, maps bank 14
    again and jumps to AudioEngineMain. The blob runs first because
    AudioEngineMain clears `MusicRequest` on its way out.
  * AudioEngineMain's `JSR MusicSequencerTick` at bank 14 `$8044` calls
    `SequencerUnlessFamiStudio`, which returns without running the sequencer
    while `PlayingMusicID` is the engine's track. Sound effects and `DmcUpdate`
    are called from AudioEngineMain itself and run as before.
  * The blob, at the start of the CPU opponents' recorded shots.

Space, all of it out of reach in a `menu_trim` ROM:

  bank 3  $A923-$BEE7  the blob (opponent shot tables and lists; match play only)
  bank 14 $9379-$9382  SequencerUnlessFamiStudio (the first bytes of the vanilla
                       course themes' stream data; no track that still plays
                       points there)
  fixed   $CAE4-$CAF3  FamiStudioFrame (free, docs/wram_expansion.md)
  SRAM    $677C on     the engine's RAM (score records of save slots 2-26)
"""

from pathlib import Path
from typing import TYPE_CHECKING

from golf.core import rom_utils
from golf.core.asm6502 import assemble
from golf.core.famistudio_engine import (
    BLOB_BANK,
    BLOB_END,
    BLOB_ORIGIN,
    MUSIC_ID,
)

from .base import PatchError
from .byte_patch import BytePatch
from .composite import CompositePatch
from .menu_trim import PLAYER_STATS_REMOVED

if TYPE_CHECKING:
    from golf.core.rom_writer import RomWriter

AUDIO_BANK = 14
AUDIO_ENGINE_MAIN = 0x8000
MUSIC_SEQUENCER_TICK = 0x8899
SET_PRG_BANK = 0xD35A
PLAYING_MUSIC_ID = 0xF9

#: the NMI's `JSR $8000`
NMI_CALL_ADDR = 0xD2F7
#: AudioEngineMain's `JSR MusicSequencerTick`
SEQUENCER_CALL_ADDR = 0x8044

FRAME_ADDR = 0xCAE4
FRAME_ROOM = 0xCAFF - FRAME_ADDR + 1
GATE_ADDR = 0x9379
#: The vanilla bytes the gate replaces, the start of the course themes' streams
GATE_ORIGINAL = bytes.fromhex("84272625852425292784")

_FRAME = assemble(
    """
    FamiStudioFrame:
        lda #BLOB_BANK
        jsr SET_PRG_BANK
        jsr BLOB_ORIGIN
        lda #AUDIO_BANK
        jsr SET_PRG_BANK
        jmp AUDIO_ENGINE_MAIN
    """,
    FRAME_ADDR,
    {
        "BLOB_BANK": BLOB_BANK,
        "BLOB_ORIGIN": BLOB_ORIGIN,
        "AUDIO_BANK": AUDIO_BANK,
        "SET_PRG_BANK": SET_PRG_BANK,
        "AUDIO_ENGINE_MAIN": AUDIO_ENGINE_MAIN,
    },
)
assert _FRAME.size <= FRAME_ROOM

_GATE = assemble(
    """
    SequencerUnlessFamiStudio:
        lda zp:PLAYING_MUSIC_ID
        cmp #MUSIC_ID
        beq @ours
        jmp MUSIC_SEQUENCER_TICK
    @ours:
        rts
    """,
    GATE_ADDR,
    {
        "PLAYING_MUSIC_ID": PLAYING_MUSIC_ID,
        "MUSIC_ID": MUSIC_ID,
        "MUSIC_SEQUENCER_TICK": MUSIC_SEQUENCER_TICK,
    },
)
assert _GATE.size == len(GATE_ORIGINAL)


def _jsr(addr: int) -> bytes:
    return bytes([0x20, addr & 0xFF, addr >> 8])


class _BlobPatch(BytePatch):
    """The blob, over whatever the opponent shot data holds in this ROM."""

    def can_apply(self, rom_writer: "RomWriter") -> bool:
        # The shot data is not the same in every ROM this could be applied to
        # (Mario Open has its own), and nothing here depends on what it was.
        return True


def famistudio_music_patch(blob: bytes) -> CompositePatch[BytePatch]:
    """Build the patch from a `golf-famistudio-build` blob."""
    room = BLOB_END - BLOB_ORIGIN + 1
    if not blob:
        raise PatchError("the FamiStudio blob is empty")
    if len(blob) > room:
        raise PatchError(
            f"the FamiStudio blob is {len(blob):,} bytes, {len(blob) - room:,} more "
            f"than fit at bank {BLOB_BANK} ${BLOB_ORIGIN:04X}-${BLOB_END:04X}"
        )
    fixed = rom_utils.cpu_to_prg_fixed

    def audio(addr: int) -> int:
        return rom_utils.cpu_to_prg_switched(addr, AUDIO_BANK)

    return CompositePatch(
        name="famistudio_music",
        description=(
            f"Play music ${MUSIC_ID:02X} with the FamiStudio sound engine "
            f"({len(blob):,} of {room:,} bytes in bank {BLOB_BANK})"
        ),
        patches=[
            _BlobPatch(
                name="famistudio_music_blob",
                description=(
                    f"the engine and its song at bank {BLOB_BANK} ${BLOB_ORIGIN:04X}, "
                    "over the CPU opponents' recorded shots"
                ),
                prg_offset=rom_utils.cpu_to_prg_switched(BLOB_ORIGIN, BLOB_BANK),
                original=bytes(len(blob)),
                patched=blob,
            ),
            BytePatch(
                name="famistudio_music_frame",
                description=f"FamiStudioFrame at ${FRAME_ADDR:04X}",
                prg_offset=fixed(FRAME_ADDR),
                original=b"\xff" * _FRAME.size,
                patched=_FRAME.code,
            ),
            BytePatch(
                name="famistudio_music_nmi_call",
                description=f"the NMI's audio call at ${NMI_CALL_ADDR:04X}",
                prg_offset=fixed(NMI_CALL_ADDR),
                original=_jsr(AUDIO_ENGINE_MAIN),
                patched=_jsr(FRAME_ADDR),
            ),
            BytePatch(
                name="famistudio_music_gate",
                description=(
                    f"SequencerUnlessFamiStudio at bank {AUDIO_BANK} ${GATE_ADDR:04X}"
                ),
                prg_offset=audio(GATE_ADDR),
                original=GATE_ORIGINAL,
                patched=_GATE.code,
            ),
            BytePatch(
                name="famistudio_music_sequencer_call",
                description=(
                    f"AudioEngineMain's sequencer call at ${SEQUENCER_CALL_ADDR:04X}"
                ),
                prg_offset=audio(SEQUENCER_CALL_ADDR),
                original=_jsr(MUSIC_SEQUENCER_TICK),
                patched=_jsr(GATE_ADDR),
            ),
        ],
        # Match play, tournaments and their save slots are what free the blob's
        # space and the engine's RAM; menu_trim removes them from the menus.
        # PLAYER_STATS_REMOVED is that patch's marker.
        requires=[PLAYER_STATS_REMOVED],
    )


def load_blob(path: Path) -> bytes:
    """Read a blob file, with an error that says how to make one."""
    try:
        return Path(path).read_bytes()
    except FileNotFoundError:
        raise PatchError(
            f"no FamiStudio blob at {path}: build one with golf-famistudio-build"
        ) from None
