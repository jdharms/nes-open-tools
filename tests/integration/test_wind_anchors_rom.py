"""Integration: the wind anchors patch on the vanilla ROM, with `InitHole` run under emulation."""

from pathlib import Path

import pytest

from golf.core.patches import (
    COURSE_MIRRORS_PATCH,
    PatchStack,
    seeded_wind_patch,
    wind_anchors_patch,
)
from golf.core.patches.recipe import Recipe
from golf.core.patches.wind_anchors import wind_anchors_patches
from golf.core.rng import predict_hole
from golf.core.rom_reader import RomReader
from golf.physics.nes import NesMachine

ROM_PATH = Path(__file__).resolve().parents[2] / "nes_open_us.nes"

pytestmark = pytest.mark.skipif(
    not ROM_PATH.exists(), reason=f"{ROM_PATH.name} not present"
)

HEADER = 0x10
INIT_HOLE = 0xDA90
WIND_ADJUSTMENT_ROUTINE = 0xDA25
HOLE_NUMBER = 0x94
RNG_STATE = 0x42
WIND_DIRECTION = 0x96
WIND_SPEED = 0x97
WIND_DIRECTION_ANCHOR = 0x012F
WIND_SPEED_ANCHOR = 0x0130

SEEDS = [(hole * 0x1F3D + 0x0101) & 0xFFFF for hole in range(18)]
#: every direction and every speed anchor, on holes whose seeds deal something else
ANCHORS = [((hole * 0x70) & 0xF0, (hole * 7) % 11) for hole in range(18)]


@pytest.fixture(scope="module")
def vanilla() -> bytes:
    return ROM_PATH.read_bytes()


@pytest.fixture(scope="module")
def seeded(vanilla) -> bytes:
    """Seeded wind alone: every hole's anchors are what its seed deals."""
    return (
        PatchStack([COURSE_MIRRORS_PATCH, seeded_wind_patch(seeds=SEEDS)])
        .build(vanilla)
        .rom
    )


@pytest.fixture(scope="module")
def anchored(vanilla) -> bytes:
    steps = [
        COURSE_MIRRORS_PATCH,
        seeded_wind_patch(seeds=SEEDS),
        wind_anchors_patch(ANCHORS),
    ]
    return PatchStack(steps).build(vanilla).rom


def after_init_hole(rom: bytes, hole: int) -> NesMachine:
    machine = NesMachine(RomReader.from_bytes(rom))
    machine.memory[HOLE_NUMBER] = hole
    machine.call(INIT_HOLE)
    return machine


def test_the_patch_expects_the_bytes_the_vanilla_rom_holds(vanilla):
    for patch in wind_anchors_patches(ANCHORS):
        start = HEADER + patch.prg_offset
        assert vanilla[start : start + len(patch.original)] == patch.original


def test_the_anchors_cover_every_direction_and_speed():
    assert {direction for direction, _ in ANCHORS} == set(range(0, 0x100, 0x10))
    assert {speed for _, speed in ANCHORS} == set(range(11))
    dealt = [predict_hole(seed, swings=0) for seed in SEEDS]
    assert all(
        (forecast.direction_anchor, forecast.speed_anchor) != anchors
        for forecast, anchors in zip(dealt, ANCHORS, strict=True)
    )


@pytest.mark.parametrize("hole", range(18))
def test_init_hole_reads_the_holes_anchors_from_the_table(anchored, hole):
    m = after_init_hole(anchored, hole).memory
    forecast = predict_hole(SEEDS[hole], swings=0, anchors=ANCHORS[hole])
    assert (m[WIND_DIRECTION_ANCHOR], m[WIND_SPEED_ANCHOR]) == ANCHORS[hole]
    assert m[RNG_STATE] | m[RNG_STATE + 1] << 8 == forecast.slot_state


@pytest.mark.parametrize("hole", [0, 5, 11, 17])
def test_only_the_anchors_differ_from_a_rom_without_the_patch(seeded, anchored, hole):
    """The pin, the hole and the RNG are untouched: the two draws still happen."""
    without = after_init_hole(seeded, hole).memory
    with_patch = after_init_hole(anchored, hole).memory
    differing = {
        address for address in range(0x8000) if without[address] != with_patch[address]
    }
    assert differing and differing <= {WIND_DIRECTION_ANCHOR, WIND_SPEED_ANCHOR}
    assert (with_patch[WIND_DIRECTION_ANCHOR], with_patch[WIND_SPEED_ANCHOR]) == (
        ANCHORS[hole]
    )
    dealt = predict_hole(SEEDS[hole], swings=0)
    assert (without[WIND_DIRECTION_ANCHOR], without[WIND_SPEED_ANCHOR]) == (
        dealt.direction_anchor,
        dealt.speed_anchor,
    )


@pytest.mark.parametrize("hole", [2, 9, 14])
def test_each_swings_wind_follows_the_table_anchors(anchored, hole):
    machine = after_init_hole(anchored, hole)
    m = machine.memory
    forecast = predict_hole(SEEDS[hole], swings=8, anchors=ANCHORS[hole])
    winds = []
    for _ in forecast.winds:
        machine.call(WIND_ADJUSTMENT_ROUTINE)
        winds.append((m[WIND_DIRECTION], m[WIND_SPEED]))
    assert winds == forecast.winds


def test_a_recipe_step_builds_the_same_rom(vanilla, anchored):
    text = " ".join(f"{direction:02X}/{speed}" for direction, speed in ANCHORS)
    recipe = Recipe.from_dict(
        {
            "steps": [
                {"patch": "course_mirrors"},
                {"patch": "seeded_wind", "seed": "unused"},
                {"patch": "wind_anchors", "anchors": text},
            ]
        },
        Path.cwd(),
    )
    steps = [built.patch for built in recipe.build_steps(vanilla)]
    steps[1] = seeded_wind_patch(seeds=SEEDS)
    assert PatchStack(steps).build(vanilla).rom == anchored


@pytest.mark.parametrize("anchor", ["80", "8G/3", "80/x", "/3"])
def test_a_recipe_refuses_a_malformed_anchor(vanilla, anchor):
    recipe = Recipe.from_dict(
        {"steps": [{"patch": "wind_anchors", "anchors": " ".join([anchor] * 18)}]},
        Path.cwd(),
    )
    with pytest.raises(ValueError, match="such as 80/7"):
        recipe.build_steps(vanilla)
