"""
The round stats patch: the routines and trampolines, run.

The bank 2 routines and the fixed-bank trampolines are assembled exactly as the
patch writes them and run under py65, with the game routines they reach stubbed
at their real addresses: `ExecuteFarCall`, the save slot lookup, the bank 9 save
and load, `IncrementStrokeCount` and the post-shot code the fairway hook returns
to. The stubs record what they were asked to do in `$5FE0`-`$5FE5`.
"""

import pytest

from golf.core.asm6502 import assemble
from golf.core.patches import COURSE_MIRRORS_PATCH, ROUND_STATS_PATCH
from golf.core.patches.byte_patch import BytePatch
from golf.core.patches.round_stats import (
    CODE_ORIGIN,
    SYMBOLS,
    TRAMPOLINE_ORIGIN,
    TRAMPOLINE_VANILLA,
    build_code,
    build_trampolines,
)
from golf.core.patches.scorecard_qr import (
    SCORECARD_QR_PATCH,
)
from golf.core.patches.scorecard_qr import (
    TRAMPOLINE_CPU_ADDR as QR_TRAMPOLINE,
)
from golf.qr.payload import pack_stats, unpack_stats
from golf.qr.port import layout
from golf.qr.port.sim import Machine

LIVE = layout.ROUND_STATS
SNAPSHOTS = layout.ROUND_STATS_SNAPSHOTS

FAR_CALL_BANK = 0x5FE0  # the last far call's bank
SAVE_SLOT = 0x5FE1  # what the save slot lookup returns
SAVES = 0x5FE2  # bank 9 save calls
LOADS = 0x5FE3  # bank 9 load calls
STROKE_COUNTS = 0x5FE4  # nonzero: IncrementStrokeCount adds the stroke
POST_SHOT = 0x5FE5  # times the fairway hook went on to $85E9

#: Each stub assembled on its own: one source with several `.org`s would fill the
#: gaps between them, over the code under test.
STUBS = {
    0x85E9: """
PostShotLie:
        inc $5FE5
        rts
""",
    0x868C: """
IncrementStrokeCount:
        lda $5FE4
        beq @refused
        ldx $99
        inc $011F,x
@refused:
        rts
""",
    0xAE31: """
SaveGameState:
        inc $5FE2
        rts
""",
    0xAEEC: """
LoadGameState:
        inc $5FE3
        rts
""",
    # Records the bank, steps the return address past the inline bytes and
    # tail-jumps to the target, whose RTS then returns past them. Memory is flat,
    # so no bank actually changes.
    0xD372: """
ExecuteFarCall:
        sta $30
        stx $31
        sty $32
        tsx
        lda $0101,x
        sta $4C
        lda $0102,x
        sta $4D
        ldy #1
        lda ($4C),y
        sta $5FE0
        iny
        lda ($4C),y
        sta $4E
        iny
        lda ($4C),y
        sta $4F
        clc
        lda $0101,x
        adc #3
        sta $0101,x
        lda $0102,x
        adc #0
        sta $0102,x
        lda $30
        ldx $31
        ldy $32
        jmp ($004E)
""",
    0xD962: """
SaveSlotIndex:
        ldx $5FE1
        rts
""",
}

PLAYER = SYMBOLS["CurrentPlayerIndex"]
GAME_PROGRESS = SYMBOLS["GameProgress"]
BALL_LIE = SYMBOLS["BallLie"]
MODE = SYMBOLS["GolfGameMode"]
PAR = SYMBOLS["Par"]
STROKES = SYMBOLS["CurrentHoleStrokes"]
MANUAL_WIND = SYMBOLS["ManualWindModeFlag"]
REPLAY = SYMBOLS["ReplayPlaybackFlag"]
SAVED_HOLE = SYMBOLS["PlayerSavedHoleNumber"]

FAIRWAY, TEE, ROUGH, BUNKER, WATER, OUT_OF_BOUNDS, GREEN = range(7)


@pytest.fixture(scope="module")
def code():
    return build_code()


@pytest.fixture(scope="module")
def trampolines(code):
    return build_trampolines(code)


@pytest.fixture
def machine(code, trampolines) -> Machine:
    machine = Machine(code)
    machine.write(trampolines.origin, trampolines.code)
    for origin, source in STUBS.items():
        machine.write(origin, assemble(source, origin).code)
    return machine


def stats(machine: Machine, player: int = 0) -> tuple[tuple[bool, ...], int]:
    """A player's live bytes, as (fairways, penalty strokes)."""
    return unpack_stats(machine.read(LIVE + player * layout.ROUND_STATS_STRIDE, 3))


def tee_shot(
    machine: Machine,
    lie: int,
    *,
    player: int = 0,
    hole: int = 0,
    strokes: int = 1,
    par: int = 4,
) -> None:
    """The state at the end of a shot that did not hole out, then the hook."""
    machine.poke(PLAYER, player)
    machine.poke(GAME_PROGRESS, hole)
    machine.poke(BALL_LIE, lie)
    machine.poke(PAR, par)
    machine.poke(STROKES + player, strokes)
    machine.call(trampoline(machine, "RsFairwayHook"))


def trampoline(machine: Machine, name: str) -> int:
    return build_trampolines(machine.program).symbol(name)


def penalty(machine: Machine, *, player: int = 0, counted: bool = True) -> None:
    machine.poke(PLAYER, player)
    machine.poke(STROKE_COUNTS, 1 if counted else 0)
    machine.call(trampoline(machine, "RsPenaltyStroke"))


# --------------------------------------------------------------------------
# Layout
# --------------------------------------------------------------------------


def test_the_stats_fill_the_gap_in_the_save_layout_exactly() -> None:
    """Between the last save slot's per-hole scores and the first tournament region."""
    assert LIVE == 0x6C0E
    assert SNAPSHOTS == 0x6C14
    assert layout.ROUND_STATS_END == 0x6C20


def test_the_stats_are_clear_of_the_qr_scratch_ram() -> None:
    """Player 2's code is built after player 1's matrix has been written."""
    assert layout.ROUND_STATS_END <= layout.SCRATCH_START


def test_the_routines_fit_after_the_qr_image(code) -> None:
    qr_end = layout.TABLE_ORIGIN + len(SCORECARD_QR_PATCH.image)
    assert qr_end <= CODE_ORIGIN
    assert CODE_ORIGIN + len(code.code) - 1 <= layout.REGION_END


def test_the_trampolines_follow_the_qr_trampoline(trampolines) -> None:
    assert QR_TRAMPOLINE + len(SCORECARD_QR_PATCH.trampoline) == TRAMPOLINE_ORIGIN
    assert len(trampolines.code) <= len(TRAMPOLINE_VANILLA)


def test_requires_the_course_mirrors() -> None:
    assert list(ROUND_STATS_PATCH.requires) == [COURSE_MIRRORS_PATCH]


def test_scorecard_qr_requires_round_stats() -> None:
    assert ROUND_STATS_PATCH in SCORECARD_QR_PATCH.requires


def test_the_hooks_replace_what_the_doc_says(code, trampolines) -> None:
    hooks = {
        patch.name: patch
        for patch in ROUND_STATS_PATCH.patches
        if isinstance(patch, BytePatch)
    }
    far = 0xD372
    reset = code.symbol("RsResetRound")
    assert hooks["round_stats_round_reset"].original == bytes.fromhex("8dfd048dfe04")
    assert hooks["round_stats_round_reset"].patched == bytes(
        [0x20, far & 0xFF, far >> 8, 2, reset & 0xFF, reset >> 8]
    )
    hook = trampolines.symbol("RsFairwayHook")
    assert hooks["round_stats_fairway"].original == bytes([0xE9, 0x85])
    assert hooks["round_stats_fairway"].patched == bytes([hook & 0xFF, hook >> 8])
    stroke = trampolines.symbol("RsPenaltyStroke")
    for name in ("round_stats_water_penalty", "round_stats_oob_penalty"):
        assert hooks[name].original == bytes([0x8C, 0x86])
        assert hooks[name].patched == bytes([stroke & 0xFF, stroke >> 8])
    save, load = code.symbol("RsSaveGame"), code.symbol("RsLoadGame")
    assert hooks["round_stats_save"].original == bytes([0x09, 0x31, 0xAE])
    assert hooks["round_stats_save"].patched == bytes([2, save & 0xFF, save >> 8])
    assert hooks["round_stats_load"].original == bytes([0x09, 0xEC, 0xAE])
    assert hooks["round_stats_load"].patched == bytes([2, load & 0xFF, load >> 8])


# --------------------------------------------------------------------------
# Round setup
# --------------------------------------------------------------------------


def test_round_setup_zeroes_the_live_bytes_and_keeps_its_stores(machine) -> None:
    machine.write(LIVE, bytes([0xAA] * 6))
    machine.write(SNAPSHOTS, bytes([0x55] * 12))
    machine.call("RsResetRound", a=0xFF)
    assert machine.read(LIVE, 6) == bytes(6)
    assert machine.read(SNAPSHOTS, 12) == bytes([0x55] * 12)
    assert machine.read(SAVED_HOLE, 2) == b"\xff\xff"


# --------------------------------------------------------------------------
# Fairways
# --------------------------------------------------------------------------


@pytest.mark.parametrize("lie", [FAIRWAY, GREEN])
def test_a_tee_shot_on_the_fairway_or_green_hits(machine, lie: int) -> None:
    tee_shot(machine, lie, hole=4)
    fairways, _ = stats(machine)
    assert [i for i, hit in enumerate(fairways) if hit] == [4]


@pytest.mark.parametrize("lie", [TEE, ROUGH, BUNKER, WATER, OUT_OF_BOUNDS])
def test_a_tee_shot_anywhere_else_misses(machine, lie: int) -> None:
    tee_shot(machine, lie)
    assert stats(machine) == ((False,) * 18, 0)


def test_only_the_first_stroke_counts(machine) -> None:
    """After a whiff, or any second shot, the hole can no longer be hit."""
    tee_shot(machine, FAIRWAY, strokes=2)
    assert stats(machine) == ((False,) * 18, 0)


@pytest.mark.parametrize("par", [4, 5, 6])
def test_par_four_and_longer_count(machine, par: int) -> None:
    tee_shot(machine, FAIRWAY, par=par)
    assert stats(machine)[0][0]


def test_a_par_three_never_counts(machine) -> None:
    tee_shot(machine, GREEN, par=3)
    assert stats(machine) == ((False,) * 18, 0)


@pytest.mark.parametrize(
    ("address", "value"),
    [(MODE, 1), (MODE, 4), (MANUAL_WIND, 0x80), (REPLAY, 0x80)],
    ids=["tournament", "match play", "training", "replay"],
)
def test_nothing_counts_outside_eighteen_hole_stroke_play(
    machine, address: int, value: int
) -> None:
    machine.poke(address, value)
    tee_shot(machine, FAIRWAY)
    assert stats(machine) == ((False,) * 18, 0)


@pytest.mark.parametrize("hole", range(18))
def test_each_hole_sets_its_own_bit(machine, hole: int) -> None:
    tee_shot(machine, FAIRWAY, hole=hole)
    assert machine.read(LIVE, 3) == pack_stats(tuple(i == hole for i in range(18)), 0)


def test_player_two_has_their_own_bytes(machine) -> None:
    tee_shot(machine, FAIRWAY, player=1, hole=17)
    assert stats(machine, 0) == ((False,) * 18, 0)
    assert stats(machine, 1)[0] == tuple(i == 17 for i in range(18))


def test_a_fairway_leaves_the_penalties_alone(machine) -> None:
    machine.write(LIVE, pack_stats((False,) * 18, 63))
    tee_shot(machine, FAIRWAY, hole=16)
    tee_shot(machine, FAIRWAY, hole=17)
    fairways, penalties = stats(machine)
    assert fairways[16] and fairways[17]
    assert penalties == 63


def test_the_hook_goes_on_to_the_post_shot_code(machine) -> None:
    for lie in (FAIRWAY, ROUGH):
        tee_shot(machine, lie)
    machine.poke(MODE, 1)
    tee_shot(machine, FAIRWAY)
    assert machine.peek(POST_SHOT) == 3
    assert machine.peek(FAR_CALL_BANK) == 2


# --------------------------------------------------------------------------
# Penalties
# --------------------------------------------------------------------------


def test_a_penalty_the_game_counts_is_counted(machine) -> None:
    penalty(machine)
    penalty(machine)
    assert stats(machine) == ((False,) * 18, 2)
    assert machine.peek(STROKES) == 2


def test_a_stroke_the_game_refuses_is_not_a_penalty(machine) -> None:
    """The CPU flag, the forced-count mask and the 50-stroke cap all refuse."""
    penalty(machine, counted=False)
    assert stats(machine) == ((False,) * 18, 0)


def test_penalties_hold_at_sixty_three(machine) -> None:
    for _ in range(70):
        penalty(machine)
    assert stats(machine) == ((False,) * 18, 63)


def test_penalties_leave_the_last_two_fairways_alone(machine) -> None:
    tee_shot(machine, FAIRWAY, hole=16)
    tee_shot(machine, FAIRWAY, hole=17)
    penalty(machine)
    fairways, penalties = stats(machine)
    assert fairways[16] and fairways[17] and penalties == 1


def test_player_two_gets_their_own_penalties(machine) -> None:
    penalty(machine, player=1)
    assert stats(machine, 0) == ((False,) * 18, 0)
    assert stats(machine, 1) == ((False,) * 18, 1)
    assert machine.peek(STROKES + 1) == 1


def test_no_penalty_outside_eighteen_hole_stroke_play(machine) -> None:
    machine.poke(MANUAL_WIND, 0x80)
    penalty(machine)
    assert stats(machine) == ((False,) * 18, 0)
    assert machine.peek(STROKES) == 1  # the game's stroke still counts


# --------------------------------------------------------------------------
# Save and continue
# --------------------------------------------------------------------------


@pytest.mark.parametrize("slot", [0, 1])
def test_a_save_snapshots_the_live_bytes_for_its_slot(machine, slot: int) -> None:
    live = bytes(range(1, 7))
    machine.write(LIVE, live)
    machine.poke(SAVE_SLOT, slot)
    machine.call("RsSaveGame")
    assert machine.peek(SAVES) == 1
    assert machine.peek(FAR_CALL_BANK) == 0x09
    assert machine.read(SNAPSHOTS + 6 * slot, 6) == live
    assert machine.read(SNAPSHOTS + 6 * (1 - slot), 6) == bytes(6)


@pytest.mark.parametrize("slot", [0, 1])
def test_a_continue_restores_its_slots_snapshot(machine, slot: int) -> None:
    machine.write(SNAPSHOTS, bytes(range(1, 13)))
    machine.poke(SAVE_SLOT, slot)
    machine.call("RsLoadGame")
    assert machine.peek(LOADS) == 1
    assert machine.read(LIVE, 6) == bytes(range(1 + 6 * slot, 7 + 6 * slot))


def test_other_save_slots_are_saved_and_loaded_without_a_snapshot(machine) -> None:
    machine.write(LIVE, bytes([0xAA] * 6))
    machine.poke(SAVE_SLOT, 2)
    machine.call("RsSaveGame")
    machine.call("RsLoadGame")
    assert (machine.peek(SAVES), machine.peek(LOADS)) == (1, 1)
    assert machine.read(SNAPSHOTS, 12) == bytes(12)
    assert machine.read(LIVE, 6) == bytes([0xAA] * 6)


def test_a_round_survives_save_reset_and_continue(machine) -> None:
    """What a CONTINUE does: round setup zeroes, then the load restores."""
    tee_shot(machine, FAIRWAY, hole=3)
    penalty(machine)
    before = machine.read(LIVE, 6)
    machine.call("RsSaveGame")
    machine.call("RsResetRound", a=0xFF)
    assert machine.read(LIVE, 6) == bytes(6)
    machine.call("RsLoadGame")
    assert machine.read(LIVE, 6) == before
