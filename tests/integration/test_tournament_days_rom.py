"""
Integration: tournament days against the real ROM, its code run under py65.

Georgia Pines' recipe (`courses/community/georgia_pines/georgia_pines.json`) is
built on the vanilla ROM, as `golf-patch` builds it; then the patched ROM's own code
is run: InitHole's pin draw, SaveSlotIndex, the menu's ApplyCourseSelection and
stroke play's scorecard title, with the real WriteNametableTiles writing to a
model PPU.
"""

from pathlib import Path

import pytest
from py65.devices.mpu6502 import MPU

from golf.core.patches import (
    COURSE_MIRRORS_PATCH,
    PatchError,
    PatchStack,
    menu_trim_patch,
    scorecard_course_name_patch,
    tournament_days_patch,
)
from golf.core.patches.byte_patch import BytePatch
from golf.core.patches.recipe import Recipe
from golf.core.patches.scorecard_course_name import title_font_tiles
from golf.core.patches.stack import StackError
from golf.core.patches.tournament_days import DAY_BYTE
from golf.core.rom_writer import RomWriter
from golf.qr.port.sim import Bus

ROOT = Path(__file__).resolve().parents[2]
ROM_PATH = ROOT / "nes_open_us.nes"
RECIPE_PATH = ROOT / "courses/community/georgia_pines/georgia_pines.json"
HEADER = 0x10
BANK = 0x4000
SENTINEL = 0xFFF0

pytestmark = pytest.mark.skipif(
    not ROM_PATH.exists(), reason=f"{ROM_PATH.name} not present"
)

#: the save slot each day plays in, for one player and two
DAY_SLOTS = [(0, 1), (9, 10), (18, 19), (4, 5)]


@pytest.fixture(scope="module")
def vanilla() -> bytes:
    return ROM_PATH.read_bytes()


@pytest.fixture(scope="module")
def patched(vanilla: bytes) -> bytes:
    """The Georgia Pines build, from its recipe."""
    recipe = Recipe.load(RECIPE_PATH)
    steps = [step.patch for step in recipe.build_steps(vanilla)]
    return PatchStack(steps, base_sha1=recipe.expected_base_sha1()).build(vanilla).rom


def machine(rom: bytes, bank: int | None = None) -> tuple[Bus, MPU]:
    """The fixed bank at $C000 and, if given, a switchable bank at $8000."""
    bus = Bus()
    prg = rom[HEADER:]
    bus.memory[0xC000:0x10000] = prg[15 * BANK : 16 * BANK]
    if bank is not None:
        bus.memory[0x8000:0xC000] = prg[bank * BANK : (bank + 1) * BANK]
    return bus, MPU(memory=bus)


def run(mpu: MPU, pc: int, stop: int | None = None, x: int = 0) -> None:
    """From `pc` until it returns, or reaches `stop`."""
    ret = SENTINEL - 1
    mpu.memory[0x1FE], mpu.memory[0x1FF] = ret & 0xFF, ret >> 8
    mpu.sp, mpu.pc, mpu.x = 0xFD, pc, x
    for _ in range(100_000):
        if mpu.pc in (SENTINEL, stop):
            return
        mpu.step()
    raise AssertionError(f"runaway at ${mpu.pc:04X}")


def pin_draw(rom: bytes, day: int, hole: int, rng: int) -> tuple[int, int]:
    """InitHole from the pin draw to the flag table read: (Y, RngState after)."""
    bus, mpu = machine(rom)
    bus.memory[DAY_BYTE] = day
    bus.memory[0x42], bus.memory[0x43] = rng & 0xFF, rng >> 8
    run(mpu, 0xDB15, stop=0xDB21, x=hole * 2)
    return mpu.y, bus.memory[0x42] | bus.memory[0x43] << 8


def save_slot(rom: bytes, day: int, players: int) -> tuple[int, int]:
    bus, mpu = machine(rom)
    bus.memory[DAY_BYTE] = day
    bus.memory[0x0100], bus.memory[0x0101], bus.memory[0x0102] = 0, players, 0
    run(mpu, 0xD962)
    return mpu.x, mpu.y


def test_the_vanilla_rom_has_every_original_the_patches_expect() -> None:
    writer = RomWriter(str(ROM_PATH), "/dev/null")
    patches = [
        *tournament_days_patch().patches,
        *menu_trim_patch(course_select=False).patches,
    ]
    for patch in patches:
        assert isinstance(patch, BytePatch)
        assert patch.can_apply(writer), patch.name


def test_requires_a_trimmed_menu(tmp_path) -> None:
    writer = RomWriter(str(ROM_PATH), str(tmp_path / "out.nes"))
    COURSE_MIRRORS_PATCH.apply(writer)
    with pytest.raises(PatchError, match="requires menu_trim"):
        tournament_days_patch().apply(writer)


def test_cannot_stack_with_menu_trims_own_course_select(vanilla: bytes) -> None:
    with pytest.raises(StackError):
        PatchStack(
            [COURSE_MIRRORS_PATCH, menu_trim_patch(), tournament_days_patch()]
        ).build(vanilla)


def test_the_menu_offers_the_days(patched: bytes) -> None:
    menu = patched[HEADER + 12 * BANK : HEADER + 13 * BANK]

    def word(cpu: int) -> int:
        return menu[cpu - 0x8000] | menu[cpu - 0x7FFF] << 8

    options = word(0x8B35 + 2 * 4 + 2)
    entries = []
    for i in range(menu[options - 0x8000]):
        entry = word(options + 1 + 2 * i) - 0x8000
        end = menu.index(0xFF, entry)
        entries.append(menu[entry + 2 : end].decode())
    destinations = word(0x8AA2 + 2 * 2) - 0x8000
    assert entries == ["THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY"]
    assert list(menu[destinations : destinations + 4]) == [0x03] * 4


def test_cannot_stack_with_a_scorecard_title(vanilla: bytes) -> None:
    steps = [
        COURSE_MIRRORS_PATCH,
        scorecard_course_name_patch("GEORGIA PINES", title="MY TITLE"),
        menu_trim_patch(course_select=False),
        tournament_days_patch(),
    ]
    with pytest.raises(StackError):
        PatchStack(steps).build(vanilla)


@pytest.mark.parametrize("day", range(4))
@pytest.mark.parametrize("hole", [0, 9, 17])
def test_the_pin_is_the_day_and_the_draw_still_happens(
    vanilla: bytes, patched: bytes, day: int, hole: int
) -> None:
    for rng in (0x1234, 0xBEEF, 0x0001):
        y, after = pin_draw(patched, day, hole, rng)
        assert y == hole * 4 + day
        assert after == pin_draw(vanilla, day, hole, rng)[1]


@pytest.mark.parametrize("day", range(4))
def test_each_day_saves_in_its_own_slots(patched: bytes, day: int) -> None:
    assert [save_slot(patched, day, players) for players in (0, 1)] == [
        (DAY_SLOTS[day][0], 0),
        (DAY_SLOTS[day][1], 1),
    ]


def test_a_stray_day_byte_still_lands_on_a_day(patched: bytes) -> None:
    assert save_slot(patched, 0xFF, 0) == (DAY_SLOTS[3][0], 0)


def test_vanilla_slots_are_by_course(vanilla: bytes) -> None:
    bus, mpu = machine(vanilla)
    found = []
    for course in range(3):
        bus.memory[0x0100], bus.memory[0x0101], bus.memory[0x0102] = 0, 0, course
        run(mpu, 0xD962)
        found.append(mpu.x)
    assert found == [0, 9, 18]


@pytest.mark.parametrize("day", range(4))
def test_the_menu_keeps_the_day_and_offers_its_own_saved_round(
    patched: bytes, day: int
) -> None:
    for saved, offered in ((DAY_SLOTS[day][0], 1), (DAY_SLOTS[(day + 1) % 4][0], 0)):
        bus, mpu = machine(patched, bank=12)
        bus.memory[0x068D] = day  # CurrentMenuSelection
        bus.memory[0x0102] = 2
        bus.memory[0x61AF + saved] = 1
        run(mpu, 0x89E1)
        assert bus.memory[DAY_BYTE] == day
        assert bus.memory[0x0102] == 0  # CurrCourse
        assert bus.memory[0x068F] == offered  # CONTINUE offered


@pytest.mark.parametrize(
    ("day", "row"),
    [
        (0, "    THURSDAY 18H STROKE PLAY    "),
        (1, "      FRIDAY 18H STROKE PLAY    "),
        (2, "    SATURDAY 18H STROKE PLAY    "),
        (3, "      SUNDAY 18H STROKE PLAY    "),
    ],
)
def test_the_scorecard_title_names_the_day(patched: bytes, day: int, row: str) -> None:
    bus, mpu = machine(patched, bank=2)
    bus.memory[DAY_BYTE] = day
    bus.vram[0x2080:0x20A0] = title_font_tiles(" " * 32)
    run(mpu, 0xB007, stop=0xB00C)
    assert bytes(bus.vram[0x2080:0x20A0]) == title_font_tiles(row)
