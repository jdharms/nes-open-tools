"""Unit tests for comparing known data regions with a label file."""

from golf.core.known_data import KnownRegion, padding_regions, plan_labels
from golf.core.mlb_labels import Label, LabelIndex, LabelStore
from golf.core.rom_trace import OPCODE, TraceResult

SIZE = 0x40000


def store(*labels) -> LabelStore:
    return LabelStore(LabelIndex(list(labels)), LabelIndex([]))


def traced(*ranges) -> TraceResult:
    """A trace result whose data names come from the given range labels."""
    result = TraceResult(bytearray(SIZE), [None] * SIZE)
    for label in ranges:
        for prg in range(label.start, label.end + 1):
            result.data_names[prg] = label.name
    return result


def region(start, end, name="ChrGraphicsTable08000", table=None) -> KnownRegion:
    return KnownRegion(start, end, "graphics", name, "graphics table", 0, 0x8000, table)


class TestPlanLabels:
    def test_an_unlabeled_region_is_new(self):
        plan = plan_labels([region(0x100, 0x1FF)], store(), traced())
        assert [(r.start, r.end, r.name) for r in plan.new] == [
            (0x100, 0x1FF, "ChrGraphicsTable08000")
        ]

    def test_bytes_inside_a_range_label_are_left_alone(self):
        header = Label("NesPrgRom", 0x100, 0x104, "LuigiSpriteChrTable")
        plan = plan_labels([region(0x100, 0x1FF)], store(header), traced(header))
        assert plan.labeled_bytes == 5
        assert [(r.start, r.name) for r in plan.new] == [
            (0x105, "LuigiSpriteChrStreams")
        ]

    def test_a_single_address_label_at_the_start_is_widened(self):
        single = Label("NesPrgRom", 0x100, None, "ScorecardChrTable")
        plan = plan_labels([region(0x100, 0x1FF)], store(single), traced())
        assert [(label.name, r.end) for label, r in plan.widen] == [
            ("ScorecardChrTable", 0x1FF)
        ]
        assert plan.new == []

    def test_a_single_address_label_inside_is_reported(self):
        inner = Label("NesPrgRom", 0x150, None, "SomethingInside")
        plan = plan_labels([region(0x100, 0x1FF)], store(inner), traced())
        assert [label.name for label, _ in plan.inside] == ["SomethingInside"]

    def test_a_region_the_trace_decoded_is_a_contradiction(self):
        result = traced()
        result.marks[0x180] = OPCODE
        plan = plan_labels([region(0x100, 0x1FF)], store(), result)
        assert plan.code and not plan.new

    def test_streams_take_the_name_of_their_labeled_table(self):
        header = Label("NesPrgRom", 0x100, 0x104, "MarioSpriteChrTable")
        streams = region(0x200, 0x2FF, "ChrGraphicsStreams08200", table=0x100)
        plan = plan_labels([streams], store(header), traced(header))
        assert plan.new[0].name == "MarioSpriteChrStreams"

    def test_adjacent_streams_of_one_plural_label_merge(self):
        headers = Label("NesPrgRom", 0x100, 0x109, "ClubSpriteChrTables")
        first = region(0x200, 0x27F, "ChrGraphicsStreams08200", table=0x100)
        second = region(0x280, 0x2FF, "ChrGraphicsStreams08280", table=0x105)
        plan = plan_labels([first, second], store(headers), traced(headers))
        assert [(r.start, r.end, r.name) for r in plan.new] == [
            (0x200, 0x2FF, "ClubSpriteChrStreams")
        ]


class FakeRom:
    def __init__(self):
        self.data = bytearray(SIZE)

    def read_switched(self, cpu, bank, length):
        start = bank * 0x4000 + (cpu - 0x8000)
        return bytes(self.data[start : start + length])


class TestPaddingRegions:
    def test_the_ff_run_before_the_reset_stub(self):
        rom = FakeRom()
        rom.data[0x3FE0:0x3FF3] = b"\xff" * 0x13  # bank 0 $BFE0-$BFF2
        rom.data[0x3FF3] = 0xEE  # the stub itself is not padding
        regions = {r.bank: r for r in padding_regions(rom)}
        assert (regions[0].cpu, regions[0].length) == (0xBFE0, 0x13)
        assert regions[0].name == "MaybeBank0TailPadding"
        assert 1 not in regions  # bank 1 has no $FF tail


def test_regions_that_claim_the_same_bytes_are_a_contradiction():
    first = region(0x100, 0x107, "TextScriptPtrTableBA072")
    second = region(0x106, 0x10F, "TextScriptBA078")
    plan = plan_labels([first, second], store(), traced())
    assert [(a.name, b.name) for a, b in plan.overlaps] == [
        ("TextScriptPtrTableBA072", "TextScriptBA078")
    ]


def test_a_triples_metasprite_is_a_count_and_three_bytes_a_sprite():
    from golf.core.known_data import CHUNKED, TRIPLES_ONLY, _metasprite_size

    assert _metasprite_size(bytes([0x04] + [0] * 12), TRIPLES_ONLY) == 13
    assert _metasprite_size(bytes([0x04] + [0] * 16), CHUNKED) == 17
