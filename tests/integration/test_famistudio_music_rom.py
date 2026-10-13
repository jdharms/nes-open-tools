"""Integration tests: the hooks `famistudio_music` makes in the US ROM.

The FamiStudio engine and its songs are not in the repository, so the blob here
is a stand-in with the same contract: called at its first byte once a frame with
bank 3 mapped, it answers a request for its music ID and marks each frame it
plays. What is under test is everything around the blob: the NMI's call, the
bank switching, the sequencer gate, and that no other track changes.
"""

from pathlib import Path

import pytest
from py65.devices.mpu6502 import MPU

from golf.core.asm6502 import assemble
from golf.core.audio import MUSIC_REQUEST, SFX_ACTIVE, run_engine
from golf.core.famistudio_engine import BLOB_BANK, BLOB_END, BLOB_ORIGIN, MUSIC_ID
from golf.core.patches import PatchError, menu_trim_patch
from golf.core.patches.famistudio_music import (
    AUDIO_BANK,
    FRAME_ADDR,
    PLAYING_MUSIC_ID,
    famistudio_music_patch,
)
from golf.core.rom_writer import RomWriter

US_ROM = "nes_open_us.nes"

pytestmark = pytest.mark.skipif(
    not Path(US_ROM).exists(), reason="the US ROM is not present"
)

#: The triangle's linear counter register, and a value the game never writes it
MARKER_REGISTER = 0x4008
MARKER = 0x5A
#: Course themes $02 and $04 lose stream bytes to the sequencer gate
UNTOUCHED_TRACKS = [0x01, *range(0x05, 0x18)]

STAND_IN = assemble(
    """
    Tick:
        lda zp:MUSIC_REQUEST
        cmp #MUSIC_ID
        bne @playing
        sta zp:PLAYING_MUSIC_ID
        lda #0
        sta zp:MUSIC_REQUEST
    @playing:
        lda zp:PLAYING_MUSIC_ID
        cmp #MUSIC_ID
        bne @done
        lda #MARKER
        sta MARKER_REGISTER
    @done:
        rts
    """,
    BLOB_ORIGIN,
    {
        "MUSIC_REQUEST": MUSIC_REQUEST,
        "PLAYING_MUSIC_ID": PLAYING_MUSIC_ID,
        "MUSIC_ID": MUSIC_ID,
        "MARKER": MARKER,
        "MARKER_REGISTER": MARKER_REGISTER,
    },
).code


class _Mmc1Bus:
    """RAM, the APU and all sixteen PRG banks behind the MMC1's PRG register."""

    def __init__(self, rom: bytes):
        self.prg = rom[16:]
        self.ram = bytearray(0x800)
        self.bank = AUDIO_BANK
        self.shift = self.count = 0
        self.writes: list[tuple[int, int, int]] = []
        self.frame = 0

    def __getitem__(self, a: int | slice) -> int | bytes:
        if isinstance(a, slice):
            return bytes(self._read(i) for i in range(a.start, a.stop))
        return self._read(a)

    def _read(self, a: int) -> int:
        if a < 0x2000:
            return self.ram[a & 0x7FF]
        if a >= 0xC000:
            return self.prg[15 * 0x4000 + a - 0xC000]
        if a >= 0x8000:
            return self.prg[self.bank * 0x4000 + a - 0x8000]
        return 0

    def __setitem__(self, a, v):
        v &= 0xFF
        if a < 0x2000:
            self.ram[a & 0x7FF] = v
        elif 0x4000 <= a <= 0x4017:
            self.writes.append((self.frame, a, v))
        elif a >= 0x8000:
            if v & 0x80:
                self.shift = self.count = 0
                return
            self.shift |= (v & 1) << self.count
            self.count += 1
            if self.count == 5:
                if a >= 0xE000:
                    self.bank = self.shift & 0x0F
                self.shift = self.count = 0


def run_frames(rom: bytes, music_id: int, frames: int):
    """Call the NMI's audio routine for ``frames`` frames; (writes, bus)."""
    bus = _Mmc1Bus(rom)
    mpu = MPU(memory=bus)
    mpu.sp = 0xFD
    bus.ram[MUSIC_REQUEST] = music_id
    bus.ram[SFX_ACTIVE] = 1
    for frame in range(frames):
        bus.frame = frame
        bus.bank = AUDIO_BANK  # the NMI maps it before the call
        for byte in (0x00, 0x01):  # return to $0002
            bus.ram[0x100 + mpu.sp] = byte
            mpu.sp = (mpu.sp - 1) & 0xFF
        mpu.pc = FRAME_ADDR
        for _ in range(200_000):
            if mpu.pc == 0x0002:
                break
            mpu.step()
        else:
            raise AssertionError(f"frame {frame} never returned")
        assert bus.bank == AUDIO_BANK, "the audio bank is mapped on return"
    return bus.writes, bus


@pytest.fixture(scope="module")
def patched(tmp_path_factory):
    out = tmp_path_factory.mktemp("famistudio") / "famistudio.nes"
    writer = RomWriter(US_ROM, str(out))
    menu_trim_patch().apply(writer)
    famistudio_music_patch(STAND_IN).apply(writer)
    writer.save()
    return out.read_bytes()


def test_requires_menu_trim(tmp_path):
    writer = RomWriter(US_ROM, str(tmp_path / "out.nes"))
    with pytest.raises(PatchError, match="menu_trim"):
        famistudio_music_patch(STAND_IN).apply(writer)


def test_a_blob_that_does_not_fit_is_refused():
    room = BLOB_END - BLOB_ORIGIN + 1
    famistudio_music_patch(bytes(room))
    with pytest.raises(PatchError, match="1 more"):
        famistudio_music_patch(bytes(room + 1))
    with pytest.raises(PatchError, match="empty"):
        famistudio_music_patch(b"")


def test_the_blob_is_called_every_frame_with_its_bank_mapped(patched):
    writes, bus = run_frames(patched, MUSIC_ID, 120)
    marks = [
        frame
        for frame, reg, value in writes
        if (reg, value) == (MARKER_REGISTER, MARKER)
    ]
    assert marks == list(range(120))
    assert bus.ram[PLAYING_MUSIC_ID] == MUSIC_ID
    offset = BLOB_BANK * 0x4000 + BLOB_ORIGIN - 0x8000
    assert bus.prg[offset : offset + len(STAND_IN)] == STAND_IN


def test_the_games_sequencer_is_idle_while_the_blob_plays(patched):
    """Vanilla's sequencer would play its own track $03 over the blob's."""
    writes, _ = run_frames(patched, MUSIC_ID, 600)
    music = [w for w in writes if w[1] < 0x4010 and w[1:] != (MARKER_REGISTER, MARKER)]
    assert music == []
    # AudioEngineMain itself still runs: it writes $4017 and $4015 each frame
    assert sum(1 for w in writes if w[1] == 0x4017) == 600


@pytest.mark.parametrize("music_id", UNTOUCHED_TRACKS)
def test_every_other_track_sounds_exactly_as_before(patched, music_id):
    vanilla = Path(US_ROM).read_bytes()
    assert run_frames(patched, music_id, 600)[0] == run_engine(vanilla, music_id, 600)
