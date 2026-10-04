"""Unit tests for the bank 11 text script walker."""

from golf.core.text_script import walk_scripts


class FakeRom:
    """Bank 11 only; everything the walker reads."""

    def __init__(self):
        self.bank = bytearray(0x4000)

    def put(self, cpu: int, data: bytes) -> None:
        self.bank[cpu - 0x8000 : cpu - 0x8000 + len(data)] = data

    def read_switched(self, cpu, bank, length):
        assert bank == 11
        return bytes(self.bank[cpu - 0x8000 : cpu - 0x8000 + length])


def walk(rom, *entries, redirects: frozenset[int] = frozenset()):
    return walk_scripts(rom, {e: "test" for e in entries}, redirects)


def test_text_until_stop():
    rom = FakeRom()
    rom.put(0x9000, b"Hi\xfd" + b"junk")
    result = walk(rom, 0x9000)
    assert result.covered == {0x9000, 0x9001, 0x9002}
    assert result.problems == []


def test_jump_is_followed_and_does_not_fall_through():
    rom = FakeRom()
    rom.put(0x9000, b"\xf5\x00\x91" + b"\xf0")  # jump $9100, then bad byte
    rom.put(0x9100, b"A\xfd")
    result = walk(rom, 0x9000)
    assert {0x9100, 0x9101} <= result.covered
    assert 0x9003 not in result.covered
    assert result.problems == []


def test_branch_follows_both_ways():
    rom = FakeRom()
    rom.put(0x9000, b"\xf2\xad\x61\x00\x91" + b"B\xfd")  # if [$61AD]==0 -> $9100
    rom.put(0x9100, b"C\xfd")
    result = walk(rom, 0x9000)
    assert {0x9005, 0x9100} <= result.covered


def test_call_runs_the_subroutine_and_continues():
    rom = FakeRom()
    rom.put(0x9000, b"\xfe\x00\x91" + b"D\xfd")
    rom.put(0x9100, b"E\xff")
    result = walk(rom, 0x9000)
    assert {0x9003, 0x9100, 0x9101} <= result.covered


def test_the_ram_name_fragment_is_not_walked():
    rom = FakeRom()
    rom.put(0x9000, b"\xfe\xff\x06" + b"F\xfd")
    result = walk(rom, 0x9000)
    assert 0x9003 in result.covered
    assert result.problems == []


def test_native_call_is_recorded_and_the_script_continues():
    rom = FakeRom()
    rom.put(0x9000, b"\xf8\x00\xa0" + b"G\xfd")
    result = walk(rom, 0x9000)
    assert result.native == {0xA000: "script native call at $9000"}
    assert 0x9003 in result.covered


def test_native_code_that_picks_the_next_script_ends_the_path():
    rom = FakeRom()
    rom.put(0x9000, b"\xf8\x03\x90" + b"\xad\x03\x60")  # code follows the call
    result = walk(rom, 0x9000, redirects=frozenset({0x9003}))
    assert 0x9003 not in result.covered
    assert result.problems == []


def test_window_numbers_are_collected():
    rom = FakeRom()
    rom.put(0x9000, b"\xf9\x02\xf9\x03\xfd")
    assert walk(rom, 0x9000).windows == {2, 3}


def test_an_opcode_with_no_handler_is_a_problem():
    rom = FakeRom()
    rom.put(0x9000, b"\xf0")
    assert [p.kind for p in walk(rom, 0x9000).problems] == ["no handler for $F0"]
