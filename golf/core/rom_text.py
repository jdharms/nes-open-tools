"""
Finding text in the ROM, in each of the encodings it is stored in.

The game stores text several ways, and a plain ASCII scan finds only some of it:

- **ASCII**: the dialogue scripts in bank 11 and the menu strings in bank 12,
  remapped to tiles only as they are drawn (`docs/text_scripts.md`,
  `docs/menu_system.md`).
- **Tile indices**, already in a font's order, in nametable descriptors and in
  the nametables the graphics codec decompresses. Each font puts its letters at
  a different base, set by which pattern tiles the screen loaded, so the same
  word is different bytes on different screens.

`encodings()` names the fonts confirmed so far, and `relative_search` finds text
in a font nobody has named yet: it matches the *differences* between letters,
so any font that keeps A-Z in order is found without knowing where A is.

Text inside a compressed nametable is broken up by the codec's opcodes, so
`nametable_screens` decodes every nametable graphics table the way the game
would and the scans run over the decoded tiles as well as the raw PRG.

Nothing here can tell text from data that happens to decode as letters;
`english_score` ranks a run by how English (or romanized Japanese) its letter
pairs look, and the caller picks the threshold.
"""

import re
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass

from golf.core.graphics_codec import load_graphics_table
from golf.core.known_data import GRAPHICS_POINTER_TABLES
from golf.core.rom_utils import PRG_BANK_SIZE, prg_to_bank_and_cpu

LOAD_COMPRESSED_GRAPHICS = 0xD45F


@dataclass(frozen=True)
class Encoding:
    """A byte -> character map, and where in the ROM it has been seen."""

    name: str
    decode: dict[int, str]
    seen: str

    def encode(self, text: str) -> bytes | None:
        """`text` in this encoding, or None if a character has no byte."""
        inverse = {char: byte for byte, char in sorted(self.decode.items())}
        try:
            return bytes(inverse[char] for char in text)
        except KeyError:
            return None


def _font(digit0: int | None, letter_a: int, space: int) -> dict[int, str]:
    table = {letter_a + i: chr(ord("A") + i) for i in range(26)}
    if digit0 is not None:
        table.update({digit0 + i: str(i) for i in range(10)})
    table[space] = " "
    return table


def _clubhouse_font() -> dict[int, str]:
    """The font the club house screens draw in, read from its glyphs.

    Letters match `PrintScriptCharacter`'s range table (`$90B1`), but the rest
    doesn't: the table puts '-' at `$35` and '0' at `$38`, while these glyphs
    are '.' at `$35`, '-' at `$36` and '0'-'9' at `$37`-`$40` (`$41` is a "10"
    ligature). Read from bank 7's `$A050` pattern table, loaded at `$1000`.
    """
    table = {i: chr(ord("A") + i) for i in range(26)}
    table.update({0x1A + i: chr(ord("a") + i) for i in range(26)})
    table.update({0x37 + i: str(i) for i in range(10)})
    table.update({0x34: ",", 0x35: ".", 0x36: "-", 0x42: "?", 0xFF: " "})
    return table


def _stats_font() -> dict[int, str]:
    """The stats and options screens' font: A-Z from `$9E`, space `$45`.

    The digits 1-9 follow Z at `$B8` (the stats are numbered `$B8`-`$BD` and the
    spin options read TOP `$B9`/`$B8` for TOP 2/TOP 1); no 0 has been seen.
    """
    table = _font(None, 0x9E, 0x45)
    table.update({0xB7 + i: str(i) for i in range(1, 10)})
    return table


def encodings() -> dict[str, Encoding]:
    """Every encoding confirmed in the ROM, by name."""
    found = [
        Encoding(
            "ascii",
            {b: chr(b) for b in range(0x20, 0x7F)},
            "dialogue scripts (bank 11), menu strings (bank 12), roster names (bank 9)",
        ),
        Encoding(
            "clubhouse",
            _clubhouse_font(),
            "club house screens (bank 7 nametables), ClearSavedDataMessages and the "
            "hall of fame names (bank 14)",
        ),
        Encoding(
            "scorecard",
            _font(0x00, 0x0A, 0x24),
            "the scorecard (bank 2, docs/scorecard.md), the in-game menu (bank 4)",
        ),
        Encoding(
            "digits30",
            _font(0x30, 0x3A, 0x03),
            "the tournament screens: bank 2 descriptors, bank 6 nametable, "
            "CONGRATULATIONS (bank 1 nametables)",
        ),
        Encoding(
            "stats", _stats_font(), "player stats and options screens (banks 7, 9)"
        ),
    ]
    return {e.name: e for e in found}


# --- Scoring ------------------------------------------------------------------

# The most common letter pairs in English, then every consonant-vowel pair of
# romanized Japanese, for the roster and credits names.
_COMMON_PAIRS = (
    frozenset(
        [
            "TH",
            "HE",
            "IN",
            "ER",
            "AN",
            "RE",
            "ON",
            "AT",
            "EN",
            "ND",
            "TI",
            "ES",
            "OR",
            "TE",
            "OF",
            "ED",
            "IS",
            "IT",
            "AL",
            "AR",
            "ST",
            "TO",
            "NT",
            "NG",
            "SE",
            "HA",
            "AS",
            "OU",
            "IO",
            "LE",
            "VE",
            "CO",
            "ME",
            "DE",
            "HI",
            "RI",
            "RO",
            "IC",
            "NE",
            "EA",
            "RA",
            "CE",
            "LI",
            "CH",
            "LL",
            "BE",
            "MA",
            "SI",
            "OM",
            "UR",
            "CA",
            "EL",
            "TA",
            "LA",
            "NS",
            "DI",
            "FO",
            "HO",
            "PE",
            "EC",
            "PR",
            "NO",
            "CT",
            "US",
            "AC",
            "OT",
            "IL",
            "TR",
            "LY",
            "NC",
            "ET",
            "UT",
            "SS",
            "SO",
            "RS",
            "UN",
            "LO",
            "WA",
            "GE",
            "IE",
            "WH",
            "EE",
            "WI",
            "EM",
            "AD",
            "OL",
            "RT",
            "PO",
            "WE",
            "NA",
            "UL",
            "NI",
            "TS",
            "MO",
            "OW",
            "PA",
            "IM",
            "MI",
            "AI",
            "SH",
            "IR",
            "SU",
            "ID",
            "OS",
            "IV",
            "IA",
            "AM",
            "FI",
            "CI",
            "VI",
            "PL",
            "IG",
            "TU",
            "EV",
            "LD",
            "RY",
            "MP",
            "FE",
            "BL",
            "AB",
            "GH",
            "TY",
            "OP",
            "WO",
            "SA",
            "AY",
            "EX",
            "KE",
            "FR",
            "OO",
            "AV",
            "AG",
            "IF",
            "AP",
            "GR",
            "OD",
            "BO",
            "SP",
            "RD",
            "DO",
            "UC",
            "BU",
            "EI",
            "OV",
            "BY",
            "RM",
            "EP",
            "TT",
            "OC",
            "FA",
            "EF",
            "CU",
            "RN",
            "SC",
            "GI",
            "DA",
            "YO",
            "CR",
            "CL",
            "DU",
            "GA",
            "QU",
            "UE",
            "FF",
            "BA",
            "EY",
            "LS",
            "VA",
            "UM",
            "PP",
            "UA",
            "UP",
            "LU",
            "GO",
            "HT",
            "RU",
            "UG",
            "DS",
            "LT",
            "PI",
            "RC",
            "RR",
            "EG",
            "AU",
            "CK",
            "EW",
            "MU",
            "BR",
            "BI",
            "PT",
            "AK",
            "PU",
            "UI",
            "RG",
            "IB",
            "TL",
            "NY",
            "KI",
            "RK",
            "YS",
            "OB",
            "MM",
            "FU",
            "PH",
            "OG",
            "MS",
            "YE",
            "UD",
            "MB",
            "IP",
            "UB",
            "OI",
            "RL",
            "GU",
            "DR",
            "HR",
            "CC",
            "TW",
            "FT",
            "WN",
            "NU",
            "AF",
            "HU",
            "NN",
            "EO",
            "VO",
            "RV",
            "NF",
            "XP",
            "GN",
            "SM",
            "FL",
            "IZ",
            "OK",
            "NL",
            "MY",
            "GL",
            "AW",
            "JU",
            "OA",
            "EQ",
            "SY",
            "SL",
            "PS",
            "JO",
            "LF",
            "NV",
            "JE",
            "NK",
            "KN",
            "GS",
            "DY",
            "HY",
            "ZE",
            "KS",
            "XT",
            "BS",
            "IK",
            "DD",
            "CY",
            "RP",
            "SK",
            "XI",
            "OE",
            "OY",
            "WS",
            "LV",
            "DL",
            "RF",
            "EU",
            "DG",
            "WR",
            "XA",
            "YI",
            "NM",
            "EB",
            "RB",
            "TM",
            "XC",
            "EH",
            "TC",
            "GY",
            "JA",
            "HN",
            "YP",
            "ZA",
            "UK",
        ]
    )
    | frozenset(c + v for c in "KSTNHMYRWGZJBPDF" for v in "AIUEO")
    | frozenset(v + c for v in "AIUEO" for c in "KSTNHMYRWGZJBPDF")
)

_PUNCTUATION = set(" .,'!?-$:/")


# A token text is made of: a word in one case (or capitalized), a number, or a
# number with a unit ("18H", "36HOLE", "1st").
_TOKEN = re.compile(r"[A-Z]+|[A-Z]?[a-z]+|[0-9]+[A-Za-z]*")
_UNLIKELY_PAIRS = frozenset({"AA", "II", "UU", "YY", "QQ", "JJ", "XX", "VV"})


def english_score(text: str) -> float:
    """0-1: the share of letter pairs common in English or romanized Japanese.

    0 outright for the shapes graphics data takes when it happens to land on
    letters: case changing inside a word, digits inside a word, a letter three
    times running, a doubled vowel no text uses, mostly symbols, or too few
    letters to judge (three pairs, four distinct letters, one 3-letter word with
    a vowel), and a lone word under six letters or with any uncommon pair.
    """
    tokens = re.findall(r"[A-Za-z0-9]+", text)
    if any(not _TOKEN.fullmatch(t) for t in tokens):
        return 0.0
    words = re.findall(r"[A-Za-z]{2,}", text)
    pairs = [w[i : i + 2].upper() for w in words for i in range(len(w) - 1)]
    letters = {c.upper() for c in text if c.isalpha()}
    if len(pairs) < 3 or len(letters) < 4:
        return 0.0
    if not any(len(w) >= 3 and re.search("[AEIOUYaeiouy]", w) for w in words):
        return 0.0
    if re.search(r"([A-Za-z])\1\1", text) or _UNLIKELY_PAIRS & set(pairs):
        return 0.0
    symbols = sum(not (c.isalnum() or c in _PUNCTUATION) for c in text)
    if symbols > len(text) * 0.2:
        return 0.0
    score = sum(p in _COMMON_PAIRS for p in pairs) / len(pairs)
    if len(words) == 1 and (len(words[0]) < 6 or score < 0.9):
        return 0.0  # one short word is as likely to be pattern data as text
    return score


# --- Where text can be ----------------------------------------------------------


@dataclass(frozen=True)
class Screen:
    """A nametable graphics table, decoded: `tiles[i]` is at PPU `ppu + i`."""

    bank: int
    cpu: int
    ppu: int
    tiles: bytes
    compressed: frozenset[int] = frozenset()  # PRG offsets of the header and streams


def _graphics_tables(rom) -> dict[tuple[int, int], None]:
    """Every (bank, address) a `JSR LoadCompressedGraphics` names, plus the
    pointer tables `known_data` knows. A raw scan, so no trace is needed; a
    stray match is weeded out when its header doesn't decode."""
    data = rom.read_prg(0, rom.prg_size)
    lo, hi = LOAD_COMPRESSED_GRAPHICS & 0xFF, LOAD_COMPRESSED_GRAPHICS >> 8
    found: dict[tuple[int, int], None] = {}
    for prg in range(len(data) - 5):
        if data[prg] == 0x20 and data[prg + 1] == lo and data[prg + 2] == hi:
            bank, addr = data[prg + 3], data[prg + 4] | (data[prg + 5] << 8)
            if bank < 15 and 0x8000 <= addr < 0xC000:
                found[(bank, addr)] = None
    for table in GRAPHICS_POINTER_TABLES:
        base = table.bank * PRG_BANK_SIZE + table.cpu - 0x8000
        for i in range(table.count):
            addr = data[base + 2 * i] | (data[base + 2 * i + 1] << 8)
            found[(table.target_bank, addr)] = None
    return found


def nametable_screens(rom) -> list[Screen]:
    """Every graphics table that decodes into a nametable, decoded."""
    screens = []
    for bank, cpu in sorted(_graphics_tables(rom)):
        header = rom.read_switched(cpu, bank, 3)
        dest, count = header[0] | (header[1] << 8), header[2]
        if not (0x2000 <= dest < 0x3000 and 1 <= count <= 16):
            continue
        try:
            table, vram = load_graphics_table(rom, bank, cpu)
        except IndexError:
            continue  # a stray match whose streams run off the bank
        end = min(table.end_ppu_addr, 0x3000)
        base = bank * PRG_BANK_SIZE - 0x8000
        compressed = set(range(base + cpu, base + cpu + 3 + 2 * count))
        for stream in table.streams:
            first = base + stream.cpu_addr
            compressed.update(range(first, first + stream.compressed_length))
        tiles = bytes(vram.data[dest:end])
        screens.append(Screen(bank, cpu, dest, tiles, frozenset(compressed)))
    return screens


# --- Scanning -----------------------------------------------------------------


@dataclass(frozen=True)
class TextRun:
    """A run of bytes that decode as text.

    `prg` is set for text in the PRG itself; text in a decoded nametable has
    `screen` and its PPU address instead.
    """

    encoding: str
    text: str
    length: int
    prg: int | None = None
    screen: Screen | None = None
    ppu: int | None = None

    @property
    def score(self) -> float:
        return english_score(self.text)

    def where(self) -> str:
        if self.screen is not None:
            s = self.screen
            return f"bank {s.bank:2} ${s.cpu:04X} PPU ${self.ppu:04X}"
        assert self.prg is not None
        bank, cpu = prg_to_bank_and_cpu(self.prg)
        return f"bank {bank:2} ${cpu:04X}"


def _runs(data: bytes, enc: Encoding, min_length: int) -> Iterator[tuple[int, str]]:
    start = None
    for i in range(len(data) + 1):
        if i < len(data) and data[i] in enc.decode:
            if start is None:
                start = i
            continue
        if start is not None:
            text = "".join(enc.decode[b] for b in data[start:i]).strip()
            if len(text) >= min_length:
                yield start, text
            start = None


def _nametable_rows(screen: Screen) -> Iterator[tuple[int, bytes]]:
    """(PPU address, tiles) per 32-tile row, so text never wraps across rows."""
    first = screen.ppu
    while first < screen.ppu + len(screen.tiles):
        end = (first | 0x1F) + 1
        offset = first - screen.ppu
        yield first, screen.tiles[offset : offset + end - first]
        first = end


def scan(
    rom,
    encs: list[Encoding],
    min_length: int = 5,
    banks: set[int] | None = None,
    screens: list[Screen] | None = None,
) -> list[TextRun]:
    """Every run of at least `min_length` characters, in the PRG and in `screens`.

    `banks` limits the PRG read (None for all of it); every screen given is read.

    A run in the PRG that starts inside a screen's compressed bytes is left out:
    the decoded screen has the same text without the codec's opcodes in it.
    """
    found = []
    decoded = set().union(*(s.compressed for s in screens or []))
    data = rom.read_prg(0, rom.prg_size)
    for bank in sorted(banks if banks is not None else range(16)):
        base = bank * PRG_BANK_SIZE
        chunk = data[base : base + PRG_BANK_SIZE]
        for enc in encs:
            for start, text in _runs(chunk, enc, min_length):
                if base + start not in decoded:
                    found.append(TextRun(enc.name, text, len(text), prg=base + start))
    for screen in screens or []:
        for ppu, row in _nametable_rows(screen):
            for enc in encs:
                for start, text in _runs(row, enc, min_length):
                    found.append(
                        TextRun(
                            enc.name, text, len(text), screen=screen, ppu=ppu + start
                        )
                    )
    return found


# --- Searching ----------------------------------------------------------------


def _spellings(text: str) -> list[str]:
    forms = [text, text.upper(), text.lower(), text.capitalize(), text.title()]
    return list(dict.fromkeys(forms))


def _context(data: bytes, start: int, length: int, decode: Callable) -> str:
    """The match widened to the whole run of decodable bytes around it."""
    lo, hi = start, start + length
    while lo > 0 and decode(data[lo - 1]) is not None:
        lo -= 1
    while hi < len(data) and decode(data[hi]) is not None:
        hi += 1
    return "".join(decode(b) or "?" for b in data[lo:hi]).strip()


def _regions(rom, banks, screens) -> Iterator[tuple[bytes, int | None, Screen | None]]:
    """(bytes, PRG offset of byte 0, screen) for each bank in `banks` (None for
    all) and each screen."""
    data = rom.read_prg(0, rom.prg_size)
    for bank in sorted(banks if banks is not None else range(16)):
        base = bank * PRG_BANK_SIZE
        yield data[base : base + PRG_BANK_SIZE], base, None
    for screen in screens or []:
        yield screen.tiles, None, screen


def _hit(enc, text, offset, base, screen, length) -> TextRun:
    if screen is not None:
        return TextRun(enc, text, length, screen=screen, ppu=screen.ppu + offset)
    return TextRun(enc, text, length, prg=base + offset)


def find_text(
    rom,
    query: str,
    encs: list[Encoding],
    banks: set[int] | None = None,
    screens: list[Screen] | None = None,
) -> list[TextRun]:
    """`query` encoded in each of `encs`, matched exactly.

    The query is tried as typed, upper case, lower case and capitalized. Each hit
    reports the whole run of text around it.
    """
    found = []
    for data, base, screen in _regions(rom, banks, screens):
        for enc in encs:
            patterns = {enc.encode(form) for form in _spellings(query)} - {None}
            for pattern in patterns:
                assert pattern is not None
                at = data.find(pattern)
                while at != -1:
                    text = _context(data, at, len(pattern), enc.decode.get)
                    found.append(_hit(enc.name, text, at, base, screen, len(pattern)))
                    at = data.find(pattern, at + 1)
    return found


def relative_search(
    rom,
    query: str,
    banks: set[int] | None = None,
    screens: list[Screen] | None = None,
    known: Sequence[Encoding] = (),
) -> list[TextRun]:
    """`query`'s letters in any font that keeps A-Z in order.

    Matches the differences between the query's letters, so the font's base
    doesn't need to be known; every other character matches any byte. A hit's
    encoding is reported as `A=$xx`, the byte the letter A would be, or as the
    encoding in `known` that puts an A or an a there (`a=$61 ascii`). The query needs at
    least four letters, or nearly everything matches.
    """
    names = {}
    for enc in known:
        for byte, char in enc.decode.items():
            if char in "Aa":
                names.setdefault(byte, f"{char}=${byte:02X} {enc.name}")
    letters = [
        (i, ord(c) - ord("A")) for i, c in enumerate(query.upper()) if c.isalpha()
    ]
    if len(letters) < 4:
        raise ValueError("a relative search needs at least four letters")
    first_at, first = letters[0]
    found = []
    for data, base, screen in _regions(rom, banks, screens):
        for at in range(len(data) - len(query) + 1):
            letter_a = (data[at + first_at] - first) & 0xFF
            if all(
                (data[at + i] - letter_a) & 0xFF == value for i, value in letters[1:]
            ):

                def decode(b: int, a: int = letter_a) -> str | None:
                    return chr(ord("A") + b - a) if 0 <= b - a < 26 else None

                text = "".join(decode(b) or "." for b in data[at : at + len(query)])
                font = names.get(letter_a, f"A=${letter_a:02X}")
                found.append(_hit(font, text, at, base, screen, len(query)))
    return found
