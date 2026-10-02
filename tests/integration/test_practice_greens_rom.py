"""Execute the standalone hack's actual loader, selection and spawn code under MMC1."""

from pathlib import Path

import pytest

from golf.core.patches.practice_greens import build_practice_greens, load_greens
from golf.core.rom_reader import RomReader
from golf.formats.putting_surface import PUTTING_SURFACE_TILES
from golf.physics.nes import NesMachine

pytestmark = pytest.mark.skipif(
    not Path("nes_open_us.nes").exists(), reason="Vanilla USA ROM not present"
)


@pytest.fixture(scope="module")
def build():
    return build_practice_greens(Path("nes_open_us.nes").read_bytes(), Path("courses"))


@pytest.fixture(scope="module")
def greens():
    return load_greens(Path("courses"))


def machine(build, seed=1):
    result = NesMachine(RomReader.from_bytes(build.rom))
    result.memory[0x42:0x44] = seed.to_bytes(2, "little")
    return result


def select_green(m, green, index):
    m.memory[0x7100] = index
    m.memory[0x7112] = green.bank
    m.memory[0x7124] = green.address & 255
    m.memory[0x7136] = green.address >> 8
    m.memory[0x100] = m.memory[0x102] = m.memory[0x94] = 0
    m.call(0xDA90, bank=13, limit=200_000)


def test_entire_vanilla_pool(build, greens):
    assert build.manifest["vanilla_holes"] == 144
    assert len(greens) == 105
    assert build.manifest["compressed_green_bytes"] == 20194
    assert len({g.tiles for g in greens}) == len(greens)
    assert len(build.rom) == len(Path("nes_open_us.nes").read_bytes())


def test_every_green_loads_and_spawns(build, greens):
    allocated = build.manifest["greens"]
    surface_offsets = set()
    for index, green in enumerate(greens):
        green.bank = allocated[index]["bank"]
        green.address = allocated[index]["address"]
        m = machine(build, seed=index + 1)
        select_green(m, green, index)
        assert m.bank == 13
        assert m.memory[0x31] == 0  # doubled hole index survives nested far calls
        assert bytes(m.memory[0x75A6:0x77E6]) == green.tiles
        assert bytes(m.memory[0x7186 : 0x7186 + 660]) == bytes([0x25]) * 660
        assert list(m.memory[0x109:0x10D]) == [2, 0, 2, 0]
        assert (m.memory[0xA5], m.memory[0xA6]) in green.pins
        for player in (1, 0):
            m.cpu.x = player
            m.call(
                build.manifest["runtime_symbols"]["PlaceBall"], bank=2, limit=200_000
            )
            assert m.cpu.x == player
            x = m.memory[0x115 + player] - m.memory[0xA3]
            y = m.memory[0x119 + player] - m.memory[0xA4]
            assert 0 <= x < 24 and 0 <= y < 24
            assert green.tiles[y * 24 + x] in PUTTING_SURFACE_TILES
            assert (x, y) != (m.memory[0xA5] // 8, m.memory[0xA6] // 8)
            assert m.memory[0x11B + player] == 0
            assert m.memory[0x111 + player] == 2
            surface_offsets.add(m.memory[0x113 + player])
    assert surface_offsets == set(range(16, 256, 32))


def test_random_rounds_have_no_repeats_and_correct_bank_pointers(build):
    seen = set()
    rounds = set()
    for seed in range(1, 129):
        m = machine(build, seed)
        m.cpu.a = 255
        m.call(build.manifest["runtime_symbols"]["RoundInit"], bank=2, limit=200_000)
        selected = tuple(m.memory[0x7100:0x7112])
        assert len(set(selected)) == 18
        assert max(selected) < 105
        seen.update(selected)
        rounds.add(selected)
        for hole, index in enumerate(selected):
            green = build.manifest["greens"][index]
            assert m.memory[0x714B + hole] < len(green["pins"])
            assert m.memory[0x7112 + hole] == green["bank"]
            assert (
                m.memory[0x7124 + hole] | m.memory[0x7136 + hole] << 8
                == green["address"]
            )
        assert m.memory[0x4FD] == m.memory[0x4FE] == 255
    assert len(seen) == 105
    assert len(rounds) > 120


def test_spawn_fallback_is_safe_even_when_rng_never_accepts(build):
    m = machine(build)
    # A fixed bank replacement in the emulator only: RNG always yields 255.
    m.memory[0xD29C:0xD29F] = bytes.fromhex("A9 FF 60")
    m.memory[0x75A6:0x77E6] = bytes([0x29]) * 576
    m.memory[0x75A6 + 23 * 24 + 23] = 0xB0
    m.memory[0xA3] = 72
    m.memory[0xA4] = 56
    m.memory[0xA5] = m.memory[0xA6] = 0
    m.cpu.x = 0
    m.call(build.manifest["runtime_symbols"]["PlaceBall"], bank=2, limit=200_000)
    assert m.memory[0x115] == 95
    assert m.memory[0x119] == 79


def test_off_green_failure_and_genuine_completion(build, greens):
    m = machine(build)
    index = 0
    green = greens[index]
    green.bank = build.manifest["greens"][index]["bank"]
    green.address = build.manifest["greens"][index]["address"]
    select_green(m, green, index)
    m.memory[0xAE] = 30  # outside green, inside shallow rough
    m.memory[0xB1] = 40
    m.memory[0x11F] = 2
    m.call(0xB3DC, bank=13)
    assert m.memory[0x11F] == 5
    assert m.memory[0x5B9] == 255
    assert m.memory[0xD2] == 2
    m.call(0xAC92, bank=13)
    assert not (m.cpu.p & 1)  # forced completion bypasses cup animation
    m.memory[0x5B9] = 1
    m.memory[0x11F] = 1
    m.call(0xB3DC, bank=13)
    assert m.memory[0x11F] == 1
    assert m.memory[0x5B9] == 1


def test_speed_menu_always_starts_a_fresh_single_player_round(build):
    for speed in range(3):
        m = machine(build)
        m.memory[0x68D] = 0
        m.memory[0x101] = 1
        m.call(0x89A2, bank=12)
        m.memory[0x68D] = speed
        m.memory[0x102] = 2
        m.memory[0x4D7] = 1
        m.call(0x89C6, bank=12)
        assert m.memory[0x6F9A] == speed
        assert (
            m.memory[0x100]
            == m.memory[0x101]
            == m.memory[0x102]
            == m.memory[0x4D7]
            == 0
        )


class _MenuBus:
    """Add sprite-zero status edges to the CPU harness's PPU status stub."""

    def __init__(self, original):
        self.original = original

    def __getitem__(self, address):
        if address == 0x2002:
            machine = self.original.machine
            machine.ppu_status ^= 0xC0
            return machine.ppu_status
        return self.original[address]

    def __setitem__(self, address, value):
        self.original[address] = value


class _MenuMachine(NesMachine):
    """Deliver NMIs to menu loops that don't call the ordinary vblank helper."""

    def __init__(self, rom):
        super().__init__(rom)
        self.cpu.memory = _MenuBus(self.cpu.memory)
        self.menu_interrupt = False

    def step(self):
        if self.bank == 12 and self.cpu.pc == 0x80FE and not self.memory[0x13]:
            self._nmi()
        pc = self.cpu.pc
        drain = self.memory[pc : pc + 6] == bytes.fromhex("A5 3C C5 3B D0 FA")
        if (
            (self.bank == 12 and pc == 0x8497)
            or (self.bank == 13 and pc == 0x85C0)
            or drain
        ):
            if not self.menu_interrupt:
                self.menu_interrupt = True
                self._nmi()
            else:
                self.menu_interrupt = False
        super().step()


def test_boot_real_putts_18_hole_progression_and_new_round(build):
    """Play hole 1 normally, then inject aces to exercise all score/advance paths."""
    m = _MenuMachine(RomReader.from_bytes(build.rom))
    m.on_frame = lambda frame: setattr(m, "buttons", 0x80 if frame % 30 < 8 else 0)
    completed = []
    first_ids = []
    entered_putting = []
    replay_checks = []

    class FinishedError(Exception):
        pass

    def setup():
        if not first_ids:
            first_ids.extend(m.memory[0x7100:0x7112])
        if completed and m.memory[0x95] == 0:
            raise FinishedError
        assert list(m.memory[0x7100:0x7112]) == first_ids

    def putting():
        entered_putting.append(m.memory[0x94])

    def quick_ace():
        if m.memory[0x94] > 0:
            m.memory[0x11F] = 1
            m.memory[0x5B9] = 1
            m.cpu.pc = 0x82BE

    def scorecard_drawn():
        completed.extend(m.memory[0x134:0x146])
        assert m.memory[0x4DE] | m.memory[0x4DF] << 8 == sum(completed)

    def forbidden():
        pytest.fail("Practice round entered a removed cutscene or normal tee view")

    m.add_breakpoint(0x9B21, lambda: replay_checks.append(m.memory[0x94]), bank=8)
    m.add_breakpoint(0x877A, setup, bank=13)
    m.add_breakpoint(0x886E, putting, bank=13)
    m.add_breakpoint(0x82AD, quick_ace, bank=13)
    m.add_breakpoint(0x8529, scorecard_drawn, bank=13)
    m.add_breakpoint(0xB094, forbidden, bank=12)
    m.add_breakpoint(0xB7D9, forbidden, bank=12)
    m.add_breakpoint(0x87C3, forbidden, bank=13)
    reset = m.memory[0xFFFC] | m.memory[0xFFFD] << 8
    with pytest.raises(FinishedError):
        m.call(reset, limit=20_000_000)
    assert entered_putting.count(0) >= 1  # real putts before advancing
    assert 1 <= completed[0] <= 50
    assert completed[1:] == [1] * 17
    assert set(replay_checks) == set(range(18))
    assert len(set(first_ids)) == 18
    assert list(m.memory[0x7100:0x7112]) != first_ids
    assert m.memory[0x100] == m.memory[0x101] == m.memory[0x102] == 0


def test_reinitializing_a_hole_preserves_its_selected_pin(build):
    m = machine(build, seed=17)
    m.cpu.a = 255
    m.call(build.manifest["runtime_symbols"]["RoundInit"], bank=2)
    m.memory[0x94] = 6
    m.call(0xDA90, bank=13)
    pin = bytes(m.memory[0xA5:0xA7])
    green = bytes(m.memory[0x75A6:0x77E6])
    m.memory[0x42:0x44] = bytes.fromhex("21 FE")
    m.call(0xDA90, bank=13)
    assert bytes(m.memory[0xA5:0xA7]) == pin
    assert bytes(m.memory[0x75A6:0x77E6]) == green


def test_post_hole_scene_is_reachable_in_vanilla_and_skipped_with_totals_intact(build):
    from golf.core.patches.skip_hole_celebrations import skip_hole_celebrations_patch
    from golf.core.rom_writer import RomWriter

    base = Path("nes_open_us.nes").read_bytes()
    writer = RomWriter.from_bytes(base)
    skip_hole_celebrations_patch().apply(writer)

    class SceneReachedError(Exception):
        pass

    def scene():
        raise SceneReachedError

    def configured(rom):
        m = NesMachine(RomReader.from_bytes(rom))
        m.memory[0x10] = 0x80
        m.memory[0x11F] = 2
        m.memory[0x121] = 2
        m.memory[0x109] = 2
        m.memory[0x4DC] = 8  # cumulative par before accounting for this hole
        m.memory[0x4DE] = 7  # accumulated strokes
        m.memory[0x4E2] = 4  # accumulated putts
        m.add_breakpoint(0xB094, scene, bank=12)
        return m

    vanilla = configured(base)
    with pytest.raises(SceneReachedError):
        vanilla.call(0x8D8F, bank=13, limit=200_000)
    for rom in (bytes(writer.rom_data), build.rom):
        patched = configured(rom)
        patched.call(0x8D8F, bank=13, limit=200_000)
        assert patched.bank == 13
        assert patched.memory[0x4DE] == 9
        assert patched.memory[0x4E2] == 6
        assert patched.memory[0x4E6] == 1  # total strokes minus cumulative par
        assert patched.memory[0x4DD] == 1  # holes at par or better
        assert patched.memory[0x98] == 255  # original post-accounting view setup
    # The old, mistaken removal site must remain the vanilla replay-saving call.
    assert writer.read_prg(0x3434A, 6) == bytes.fromhex("20 72 D3 08 21 9B")
    assert build.rom[16 + 0x3434A : 16 + 0x34350] == bytes.fromhex("20 72 D3 08 21 9B")
