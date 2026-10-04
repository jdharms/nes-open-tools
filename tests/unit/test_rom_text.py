"""Unit tests for finding text in the ROM (golf.core.rom_text)."""

import pytest

from golf.core.rom_text import (
    encodings,
    english_score,
    find_text,
    nametable_screens,
    relative_search,
    scan,
)
from golf.core.rom_utils import PRG_BANK_SIZE

FILL = 0xEA  # decodes in no encoding, so only the bytes a test puts are text


class FakeRom:
    def __init__(self):
        self.data = bytearray([FILL]) * (16 * PRG_BANK_SIZE)
        self.prg_size = len(self.data)

    def prg(self, bank: int, cpu: int) -> int:
        return bank * PRG_BANK_SIZE + (cpu & 0x3FFF)

    def put(self, bank: int, cpu: int, data: bytes) -> None:
        start = self.prg(bank, cpu)
        self.data[start : start + len(data)] = data

    def read_prg(self, offset: int, length: int = 1) -> bytes:
        return bytes(self.data[offset : offset + length])

    def read_switched(self, cpu: int, bank: int, length: int = 1) -> bytes:
        return self.read_prg(self.prg(bank, cpu), length)


def test_text_scores_high_in_every_case():
    assert english_score("Please select the course") >= 0.9
    assert english_score("18H TOURNAMENT") >= 0.9
    assert english_score("for $200,000. Now go") >= 0.65
    assert english_score("EIJI ONOZUKA") >= 0.65


@pytest.mark.parametrize(
    "junk",
    [
        "BAIiEiMB",  # case changing inside a word
        "Dyee6iel",  # a digit inside a word
        "UUDUUDUU",  # a doubled vowel no text uses
        "SOFSSSOF",  # a letter three times running
        "EXIT",  # one short word: as likely pattern data as text
        "#$%&'()*AB",  # mostly symbols
    ],
)
def test_data_shaped_runs_score_zero(junk):
    assert english_score(junk) == 0.0


def test_scorecard_encoding_matches_the_documented_bytes():
    scorecard = encodings()["scorecard"]
    data = bytes.fromhex("13 0a 19 0a 17 24 0c 18 1e 1b 1c 0e")
    assert scorecard.encode("JAPAN COURSE") == data
    assert "".join(scorecard.decode[b] for b in data) == "JAPAN COURSE"


def test_clubhouse_font_puts_digits_after_its_punctuation():
    clubhouse = encodings()["clubhouse"]
    assert clubhouse.encode("1.Cl") == bytes([0x38, 0x35, 0x02, 0x25])
    assert clubhouse.encode("é") is None


def test_scan_reports_each_run_with_its_offset_and_bank_filter():
    rom = FakeRom()
    rom.put(12, 0x8100, b"\x00\x05PLEASE SELECT\xff")
    rom.put(3, 0x9000, b"STROKE PLAY")
    ascii_only = [encodings()["ascii"]]

    runs = [r for r in scan(rom, ascii_only) if r.score > 0.5]
    assert [(r.text, r.prg) for r in runs] == [
        ("STROKE PLAY", rom.prg(3, 0x9000)),
        ("PLEASE SELECT", rom.prg(12, 0x8102)),
    ]
    assert [r.text for r in scan(rom, ascii_only, banks={12})] == ["PLEASE SELECT"]
    assert runs[1].where() == "bank 12 $8102"


def test_find_text_tries_each_case_and_shows_the_whole_string():
    rom = FakeRom()
    rom.put(11, 0x9000, b"Please select the course")
    stats = encodings()["stats"]
    rom.put(7, 0xA000, stats.encode("BALL SPIN") or b"")

    hits = find_text(rom, "SELECT", list(encodings().values()))
    assert [(h.encoding, h.text) for h in hits] == [
        ("ascii", "Please select the course")
    ]
    hits = find_text(rom, "ball spin", list(encodings().values()))
    assert [(h.encoding, h.text, h.prg) for h in hits] == [
        ("stats", "BALL SPIN", rom.prg(7, 0xA000))
    ]


def test_relative_search_finds_a_font_without_knowing_its_base():
    rom = FakeRom()
    rom.put(5, 0x8800, bytes(0x80 + ord(c) - ord("A") for c in "DRIVER"))
    hits = relative_search(rom, "Driver")
    assert [(h.encoding, h.text, h.prg) for h in hits] == [
        ("A=$80", "DRIVER", rom.prg(5, 0x8800))
    ]


def test_relative_search_names_a_known_font_in_either_case():
    rom = FakeRom()
    rom.put(11, 0x9000, b"practice")
    hits = relative_search(rom, "PRACTICE", known=list(encodings().values()))
    assert [h.encoding for h in hits] == ["a=$61 ascii"]


def test_relative_search_needs_four_letters():
    with pytest.raises(ValueError):
        relative_search(FakeRom(), "PAR")


def put_nametable(rom: FakeRom, text: bytes) -> None:
    """A graphics table at bank 7 $9000: one literal stream to PPU $2084, loaded
    from the fixed bank by JSR LoadCompressedGraphics."""
    rom.put(15, 0xC100, bytes([0x20, 0x5F, 0xD4, 0x07, 0x00, 0x90]))
    rom.put(7, 0x9000, bytes([0x84, 0x20, 0x01, 0x05, 0x90]))
    stream = b""
    for at in range(0, len(text), 32):
        chunk = text[at : at + 32]
        stream += bytes([len(chunk) - 1]) + chunk
    rom.put(7, 0x9005, stream + b"\xff")


def test_nametable_text_is_found_decoded_and_not_twice():
    rom = FakeRom()
    clubhouse = encodings()["clubhouse"]
    put_nametable(rom, clubhouse.encode("This is the training room") or b"")

    screens = nametable_screens(rom)
    assert [(s.bank, s.cpu, s.ppu) for s in screens] == [(7, 0x9000, 0x2084)]

    runs = [r for r in scan(rom, [clubhouse], screens=screens) if r.score > 0.5]
    assert [(r.text, r.where()) for r in runs] == [
        ("This is the training room", "bank  7 $9000 PPU $2084")
    ]


def test_decoded_rows_end_at_the_nametable_row():
    rom = FakeRom()
    scorecard = encodings()["scorecard"]
    # 28 tiles fill row $2080 from column 4, so the second word starts row $20A0.
    put_nametable(rom, scorecard.encode("TOURNAMENT" + " " * 18 + "STROKE PLAY") or b"")
    runs = scan(rom, [scorecard], banks=set(), screens=nametable_screens(rom))
    assert [(r.text, r.ppu) for r in runs] == [
        ("TOURNAMENT", 0x2084),
        ("STROKE PLAY", 0x20A0),
    ]
