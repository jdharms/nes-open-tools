"""Unit tests for the scene object stream and metasprite decoders."""

from golf.core.object_script import (
    ObjectWalk,
    metasprite_length,
    stream_scripts,
    walk_stream,
)


class FakeRom:
    """One switchable bank (any number) plus an empty fixed bank."""

    def __init__(self):
        self.bank = bytearray(0x4000)

    def put(self, cpu: int, data: bytes) -> None:
        self.bank[cpu - 0x8000 : cpu - 0x8000 + len(data)] = data

    def read_switched(self, cpu, bank, length):
        return bytes(self.bank[cpu - 0x8000 : cpu - 0x8000 + length])

    def read_fixed(self, cpu, length):
        return bytes(length)


class TestMetaspriteLength:
    def test_four_byte_sprites(self):
        assert metasprite_length(bytes([0x02] + [0] * 8 + [0xAA])) == 9

    def test_shared_attribute_three_byte_sprites(self):
        # bit 7: one attribute byte, then 3 bytes a sprite
        assert metasprite_length(bytes([0x83, 0x01] + [0] * 9)) == 11

    def test_chained_chunks(self):
        # bit 6 on the first header: another chunk follows
        data = bytes([0x41] + [0] * 4 + [0x81, 0x02] + [0] * 3)
        assert metasprite_length(data) == 10

    def test_empty(self):
        assert metasprite_length(bytes([0x00, 0x55])) == 1

    def test_truncated_is_malformed(self):
        assert metasprite_length(bytes([0x05, 0, 0])) is None


class TestWalkStream:
    def test_motion_steps_until_free(self):
        rom = FakeRom()
        rom.put(0x9000, bytes([0x10, 1, 2, 0x08, 3, 4, 0xFF]))
        walk = walk_stream(rom, 10, 0x9000, anim=False)
        assert walk.covered == set(range(0x9000, 0x9007))
        assert walk.problems == []

    def test_a_zero_count_halts(self):
        rom = FakeRom()
        rom.put(0x9000, bytes([0x00, 0, 0, 0x8C, 0xB9]))  # then a frame table
        walk = walk_stream(rom, 10, 0x9000, anim=False)
        assert walk.covered == {0x9000, 0x9001, 0x9002}

    def test_jump_loops_back(self):
        rom = FakeRom()
        rom.put(0x9000, bytes([0xA0, 0x00, 0xFE, 0x00, 0x90]))
        walk = walk_stream(rom, 10, 0x9000, anim=True, sprite=5)
        assert walk.uses == {(5, 0)}
        assert walk.problems == []

    def test_ef_changes_the_sprite_for_later_frames(self):
        rom = FakeRom()
        rom.put(0x9000, bytes([0x04, 0x01, 0xEF, 0x02, 0x04, 0x07, 0xFF]))
        walk = walk_stream(rom, 10, 0x9000, anim=True, sprite=5)
        assert walk.uses == {(5, 1), (2, 7)}

    def test_native_call_is_recorded(self):
        rom = FakeRom()
        rom.put(0x9000, bytes([0xED, 0x57, 0x9B, 0xFF]))
        walk = walk_stream(rom, 10, 0x9000, anim=True)
        assert walk.native == {0x9B57}

    def test_branch_and_loop_opcodes_have_their_lengths(self):
        rom = FakeRom()
        # loop 3 { step }, if [$0700] == 0 -> $9100, store, free
        rom.put(
            0x9000,
            bytes([0xFB, 0x03, 0x02, 0x01, 0xFA, 0xF9, 0x00, 0x07, 0x00, 0x91])
            + bytes([0xF6, 0x00, 0x07, 0x01, 0xFF]),
        )
        rom.put(0x9100, bytes([0xFF]))
        walk = walk_stream(rom, 10, 0x9000, anim=True)
        assert walk.problems == []
        assert {0x900E, 0x9100} <= walk.covered

    def test_an_opcode_the_engine_would_hang_on_is_a_problem(self):
        rom = FakeRom()
        rom.put(0x9000, bytes([0xE4]))
        walk = walk_stream(rom, 10, 0x9000, anim=True)
        assert walk.problems == ["no handler for $E4 at $9000"]

    def test_stores_are_recorded(self):
        rom = FakeRom()
        rom.put(0x9000, bytes([0xF6, 0xE7, 0x06, 0x97, 0xFF]))
        walk = walk_stream(rom, 10, 0x9000, anim=True)
        assert walk.stores == {0x9000: (0x06E7, 0x97)}


class TestStreamScripts:
    def test_a_store_pair_into_script_ptr_names_a_script(self):
        walk = ObjectWalk(
            stores={(10, 0xBB0A): (0x06E7, 0x97), (10, 0xBB0E): (0x06E8, 0xB9)}
        )
        assert list(stream_scripts(walk)) == [0xB997]

    def test_a_lone_low_store_names_nothing(self):
        walk = ObjectWalk(
            stores={(10, 0xBB0A): (0x06E7, 0x97), (10, 0xBB0E): (0x0700, 0xB9)}
        )
        assert stream_scripts(walk) == {}

    def test_the_pair_must_be_adjacent_in_one_bank(self):
        walk = ObjectWalk(
            stores={(10, 0xBB0A): (0x06E7, 0x97), (2, 0xBB0E): (0x06E8, 0xB9)}
        )
        assert stream_scripts(walk) == {}
