"""Unit tests for the recursive-descent code tracer."""

from golf.core.mlb_labels import Label, LabelIndex, LabelStore
from golf.core.rom_trace import (
    INLINE,
    NONE,
    OPCODE,
    CodePointerTable,
    Seed,
    trace,
    unreached_roots,
)

BANK_SIZE = 0x4000
BANKS = 16
FIXED = 0x3C000


class MockReader:
    """A 256KB PRG image whose vectors all point at an RTI unless set."""

    def __init__(self):
        self.data = bytearray(BANKS * BANK_SIZE)
        self.write_fixed(0xFF00, [0x40])  # RTI
        # The bank switch, far call and dispatcher bodies are traced too.
        for helper in (0xD352, 0xD35A, 0xD372, 0xD227):
            self.write_fixed(helper, [0x60])
        self.vectors(nmi=0xFF00, reset=0xFF00, irq=0xFF00)

    @property
    def prg_size(self) -> int:
        return len(self.data)

    def read_prg(self, offset: int, length: int) -> bytes:
        return bytes(self.data[offset : offset + length])

    def write_fixed(self, cpu: int, code):
        prg = FIXED + (cpu - 0xC000)
        self.data[prg : prg + len(code)] = bytes(code)
        return prg

    def write_bank(self, bank: int, cpu: int, code):
        prg = bank * BANK_SIZE + (cpu - 0x8000)
        self.data[prg : prg + len(code)] = bytes(code)
        return prg

    def vectors(self, nmi: int, reset: int, irq: int):
        raw = [nmi & 0xFF, nmi >> 8, reset & 0xFF, reset >> 8, irq & 0xFF, irq >> 8]
        self.data[FIXED + BANK_SIZE - 6 : FIXED + BANK_SIZE] = bytes(raw)


def store(*labels) -> LabelStore:
    return LabelStore(LabelIndex(list(labels)), LabelIndex([]))


def run(rom, code, at=0xC000, **kwargs):
    """Put `code` at `at` in the fixed bank and trace from the reset vector."""
    prg = rom.write_fixed(at, code)
    rom.vectors(nmi=0xFF00, reset=at, irq=0xFF00)
    return prg, trace(rom, pointer_tables=(), **kwargs)


def kinds(result) -> list[str]:
    return [f.kind for f in result.conflicts]


class TestControlFlow:
    def test_follows_a_jsr_and_stops_at_rts(self):
        rom = MockReader()
        rom.write_fixed(0xC100, [0xA9, 0x01, 0x60])  # LDA #$01 / RTS
        prg, result = run(rom, [0x20, 0x00, 0xC1, 0x60, 0xFF])  # JSR $C100 / RTS
        assert result.marks[prg] == OPCODE
        assert result.marks[FIXED + 0x100] == OPCODE
        assert result.marks[prg + 4] == NONE  # the byte after RTS
        assert FIXED + 0x100 in result.entries

    def test_both_sides_of_a_conditional_branch(self):
        rom = MockReader()
        # BEQ +1 / RTS / RTS
        prg, result = run(rom, [0xF0, 0x01, 0x60, 0x60])
        assert result.marks[prg + 2] == OPCODE
        assert result.marks[prg + 3] == OPCODE

    def test_complementary_branch_pair_is_unconditional(self):
        rom = MockReader()
        # BEQ +3 / BNE +1 / table byte $02 / RTS
        prg, result = run(rom, [0xF0, 0x03, 0xD0, 0x01, 0x02, 0x60])
        assert result.marks[prg + 4] == NONE
        assert kinds(result) == []

    def test_load_immediate_then_bne_is_unconditional(self):
        rom = MockReader()
        # LDA #$38 / BNE +1 / table byte $02 / RTS
        prg, result = run(rom, [0xA9, 0x38, 0xD0, 0x01, 0x02, 0x60])
        assert result.marks[prg + 4] == NONE
        assert kinds(result) == []

    def test_undocumented_opcode_is_a_conflict(self):
        rom = MockReader()
        prg, result = run(rom, [0xEA, 0x02])  # NOP / undocumented
        assert result.conflicts[0].prg == prg + 1
        assert "undocumented" in result.conflicts[0].kind

    def test_entering_the_middle_of_an_instruction_is_a_conflict(self):
        rom = MockReader()
        # LDA $C002 / BEQ -3 (into the LDA's operand) / RTS
        _, result = run(rom, [0xAD, 0x02, 0xC0, 0xF0, 0xFC, 0x60])
        assert "enters the middle of an instruction" in kinds(result)

    def test_indirect_jump_is_unresolved(self):
        rom = MockReader()
        prg, result = run(rom, [0x6C, 0x22, 0x00])
        assert [(f.kind, f.prg) for f in result.unresolved] == [("JMP (indirect)", prg)]


class TestBanks:
    def test_bank_switch_with_an_immediate_maps_that_bank(self):
        rom = MockReader()
        target = rom.write_bank(13, 0x8000, [0x60])
        # LDA #$0D / JSR BankSwitchRoutine / JSR $8000 / RTS
        _, result = run(rom, [0xA9, 0x0D, 0x20, 0x52, 0xD3, 0x20, 0x00, 0x80, 0x60])
        assert result.marks[target] == OPCODE

    def test_bank_switch_without_an_immediate_leaves_the_bank_unknown(self):
        rom = MockReader()
        # LDA $27 / JSR BankSwitchRoutine / JSR $8000 / RTS
        _, result = run(rom, [0xA5, 0x27, 0x20, 0x52, 0xD3, 0x20, 0x00, 0x80, 0x60])
        assert [f.kind for f in result.unresolved] == [
            "switchable-bank target, bank unknown"
        ]

    def test_switchable_code_calls_within_its_own_bank(self):
        rom = MockReader()
        rom.write_bank(4, 0x8000, [0x20, 0x10, 0x80, 0x60])  # JSR $8010 / RTS
        callee = rom.write_bank(4, 0x8010, [0x60])
        result = trace(rom, seeds=[Seed(0x8000, 4, "test")], pointer_tables=())
        assert result.marks[callee] == OPCODE
        assert result.marks[0x8010 - 0x8000] == NONE  # not bank 0


class TestInlineArguments:
    def test_far_call_traces_the_target_and_skips_the_arguments(self):
        rom = MockReader()
        target = rom.write_bank(11, 0x9033, [0x60])
        # JSR ExecuteFarCall / .db $0B, $33, $90 / RTS
        prg, result = run(rom, [0x20, 0x72, 0xD3, 0x0B, 0x33, 0x90, 0x60])
        assert result.marks[target] == OPCODE
        assert [result.marks[prg + i] for i in (3, 4, 5)] == [INLINE] * 3
        assert result.marks[prg + 6] == OPCODE
        assert kinds(result) == []

    def test_inline_dispatch_table_entries_are_traced(self):
        rom = MockReader()
        rom.write_fixed(0xC200, [0x60])
        rom.write_fixed(0xC300, [0x60])
        # JSR DispatchInlineJumpTable / key 1 -> $C200 / key 2 -> $C300 / end
        prg, result = run(
            rom, [0x20, 0x27, 0xD2, 0x01, 0x00, 0xC2, 0x02, 0x00, 0xC3, 0x00, 0x60]
        )
        assert result.marks[FIXED + 0x200] == OPCODE
        assert result.marks[FIXED + 0x300] == OPCODE
        # A handler's RTS comes back after the table, so the RTS there is code.
        assert result.marks[prg + 10] == OPCODE


class TestLabels:
    def test_falling_into_a_data_range_is_a_conflict(self):
        rom = MockReader()
        labels = store(Label("NesPrgRom", FIXED + 1, FIXED + 4, "Table"))
        _, result = run(rom, [0xEA, 0x01, 0x02], labels=labels)
        assert kinds(result) == ["runs into data range"]

    def test_a_branch_falling_into_a_data_range_is_taken_as_always_taken(self):
        rom = MockReader()
        labels = store(Label("NesPrgRom", FIXED + 2, FIXED + 4, "Table"))
        # BNE +3 / table / RTS
        prg, result = run(rom, [0xD0, 0x03, 0x01, 0x02, 0x03, 0x60], labels=labels)
        assert kinds(result) == []
        assert result.marks[prg + 5] == OPCODE

    def test_coverage_counts_code_and_data(self):
        rom = MockReader()
        labels = store(Label("NesPrgRom", FIXED + 0x10, FIXED + 0x1F, "Table"))
        _, result = run(rom, [0xEA, 0x60], labels=labels)
        coverage = result.coverage(15)
        assert coverage["code"] == 3  # NOP, RTS, and the RTI at $FF00
        assert coverage["data"] == 16
        assert coverage["both"] == 0


class TestPointerTables:
    def test_table_entries_are_traced_and_zero_is_skipped(self):
        rom = MockReader()
        rom.write_bank(12, 0x8B00, [0x10, 0x80, 0x00, 0x00, 0x20, 0x80])
        first = rom.write_bank(12, 0x8010, [0x60])
        second = rom.write_bank(12, 0x8020, [0x60])
        table = CodePointerTable("Handlers", 12, 0x8B00, 3)
        result = trace(rom, seeds=[], pointer_tables=(table,))
        assert result.marks[first] == OPCODE
        assert result.marks[second] == OPCODE
        assert result.marks[12 * BANK_SIZE] == NONE  # the $0000 entry


class TestUnreachedRoots:
    def test_a_label_reached_from_another_is_under_it(self):
        rom = MockReader()
        rom.write_fixed(0xC400, [0x4C, 0x00, 0xC5])  # JMP $C500
        rom.write_fixed(0xC500, [0x60])
        seeds = [Seed(0xC400, None, "label A"), Seed(0xC500, None, "label B")]
        upstream = unreached_roots(rom, None, seeds)
        assert upstream[FIXED + 0x400] == set()
        assert upstream[FIXED + 0x500] == {FIXED + 0x400}
