"""
The scene builder (`golf.physics.scene`) against the game's own.

`RomSceneBuilder` calls `BuildPerspectiveScene` and the sky blocks that follow
it on a hole the game loaded, and the port must leave the same bytes from the
tile map to the end of WRAM ($77E6-$7FFF: both maps and the builder's scratch)
and the same `RngState`. Each hole's scenes are built one after another on one
machine, so all but the first are built over what the last one left.

Then whole shots: the game plays one, and the model replays it with the scene
the port built in place of the one captured from the game.
"""

import random
from dataclasses import replace
from pathlib import Path

import pytest

from golf.core.rom_reader import RomReader
from golf.formats.hole_data import HoleData
from golf.physics import HoleGround, ShotInput, TerrainTables
from golf.physics.perspective import SCENE_DEPTH_MAP, SCENE_TILE_MAP
from golf.physics.rom_game import RomGameShot, RomSceneBuilder, Swing
from golf.physics.scene import (
    BALL_LIE_CLASS,
    FLAG_NEAR,
    FLAG_SCREEN_Y,
    GREEN_LEFT,
    GREEN_RIGHT,
    GRID,
    GRID_COLUMNS,
    GRID_ROWS,
    MAP_COLUMNS,
    MAP_ROWS,
    PALETTE_MAP,
    TREE_BANDS,
    TREE_DEPTHS,
    WRAM,
    SceneBuilder,
    SceneTables,
    build_scene,
)
from golf.physics.shot import ShotInFlight
from tests.physics.test_game_rom import CARRIED_FROM_LAUNCH, differences

ROM_PATH = "nes_open_us.nes"

pytestmark = pytest.mark.skipif(
    not Path(ROM_PATH).exists(), reason=f"{ROM_PATH} not present"
)

COMPARED = slice(SCENE_TILE_MAP - WRAM, 0x2000)
MAP_BYTES = MAP_ROWS * MAP_COLUMNS
TILES = slice(SCENE_TILE_MAP - WRAM, SCENE_TILE_MAP - WRAM + MAP_BYTES)
DEPTHS = slice(SCENE_DEPTH_MAP - WRAM, SCENE_DEPTH_MAP - WRAM + MAP_BYTES)

#: Six holes a course: openers, short holes, water, and the U.K. holes whose
#: trees shape the tee shot (`docs/hole_difficulty.md`).
HOLES = [
    *(("japan", hole) for hole in (1, 4, 8, 11, 15, 18)),
    *(("us", hole) for hole in (2, 5, 7, 12, 16, 17)),
    *(("uk", hole) for hole in (1, 2, 10, 14, 16, 18)),
]
SCENES_A_HOLE = 14


@pytest.fixture(scope="module")
def rom() -> RomReader:
    return RomReader(ROM_PATH)


@pytest.fixture(scope="module")
def tables(rom) -> tuple[SceneTables, TerrainTables]:
    return SceneTables.from_rom(rom), TerrainTables.from_rom(rom)


def load_hole(courses: Path, course: str, number: int) -> HoleData:
    hole = HoleData()
    hole.load(courses / course / f"hole_{number:02}.json")
    return hole


def spots(hole: HoleData, rng: random.Random):
    """(x, y, aim, RNG state, x fraction, y fraction) for one hole's scenes."""
    tee = hole.metadata["tee"]
    height = hole.terrain_height * 8
    # The tee along the hole, then either side, then turned right round.
    for aim in (0, 0x0C, 0xF4, 0x40, 0x80, 0xC0):
        yield tee["x"], tee["y"], aim, rng.randrange(1, 0x10000), 0, 0
    while True:
        yield (
            rng.randrange(0xB0),
            rng.randrange(height),
            rng.choice([0, rng.randrange(-32, 32) & 0xFF, rng.randrange(256)]),
            rng.randrange(0x10000),
            rng.choice([0, rng.randrange(256)]),
            rng.choice([0, rng.randrange(256)]),
        )


@pytest.mark.parametrize(("course", "number"), HOLES)
def test_scene(rom, tables, vanilla_courses, course, number):
    scene_tables, terrain_tables = tables
    hole = load_hole(vanilla_courses, course, number)
    ground = HoleGround(hole, terrain_tables)
    game = RomSceneBuilder(rom, course, number)
    rng = random.Random(f"{course} {number}")
    for _, spot in zip(range(SCENES_A_HOLE), spots(hole, rng), strict=False):
        x, y, aim, rng_state, x_fraction, y_fraction = spot
        theirs = game.build(x, y, aim, rng_state, x_fraction, y_fraction)
        ours = build_scene(
            ground,
            scene_tables,
            x,
            y,
            aim,
            game.flag,
            rng_state,
            x_fraction,
            y_fraction,
            wram=theirs.before,
            stale=theirs.stale,
        )
        assert ours.wram[COMPARED] == theirs.built[COMPARED], spot
        assert ours.shown[COMPARED] == theirs.shown[COMPARED], spot
        assert ours.rng_state == theirs.rng_state, spot


def test_what_the_scenes_cover(rom, vanilla_courses):
    """
    The cases `test_scene` relies on meeting do occur: trees, canopies drawn
    with the RNG, sky blocks both stamped and hidden, the green drawn and not,
    and a scene built over another's leftovers.
    """
    seen = set()
    for course, number in (("uk", 14), ("uk", 2), ("us", 7)):
        hole = load_hole(vanilla_courses, course, number)
        game = RomSceneBuilder(rom, course, number)
        rng = random.Random(f"{course} {number}")
        for _, spot in zip(range(SCENES_A_HOLE), spots(hole, rng), strict=False):
            x, y, aim, rng_state, x_fraction, y_fraction = spot
            theirs = game.build(
                x, y, aim, rng_state, x_fraction, y_fraction, stages=True
            )
            if any(depth != 0xFF for depth in theirs.built[DEPTHS]):
                seen.add("trees")
            if theirs.rng_state != rng_state:
                seen.add("random canopy tiles")
            changed = sum(
                a != b
                for a, b in zip(theirs.built[TILES], theirs.shown[TILES], strict=True)
            )
            seen.add("all the sky blocks" if changed >= 40 else "a hidden sky block")
            flag_in_view = theirs.stages["probed"][1][FLAG_NEAR]
            seen.add("green" if flag_in_view else "no green")
            if any(theirs.before[COMPARED]):
                seen.add("leftovers")
    assert seen == {
        "trees",
        "random canopy tiles",
        "all the sky blocks",
        "a hidden sky block",
        "green",
        "no green",
        "leftovers",
    }


def test_uk_14_tee_has_trees_close_by(rom, tables, vanilla_courses):
    """The hole the builder was ported for: trees a short carry from the tee."""
    scene_tables, terrain_tables = tables
    hole = load_hole(vanilla_courses, "uk", 14)
    ground = HoleGround(hole, terrain_tables)
    tee = hole.metadata["tee"]
    for aim in (0, 4, 0xFC, 0x10, 0xF0):
        for rng_state in (1, 0x1234, 0xBEEF):
            game = RomSceneBuilder(rom, "uk", 14)
            theirs = game.build(tee["x"], tee["y"], aim, rng_state)
            ours = build_scene(
                ground, scene_tables, tee["x"], tee["y"], aim, game.flag, rng_state
            )
            assert ours.shown[COMPARED] == theirs.shown[COMPARED], (aim, rng_state)
            assert ours.rng_state == theirs.rng_state
            depths = [depth for depth in ours.shown[DEPTHS] if depth != 0xFF]
            assert len(depths) > 100
            assert min(depths) < 0x40


#: (course, hole, club, swing speed, hi/lo, aim offset from the flag's line).
#: The first six hit the trees by the U.K. 14th's tee in the behind-the-golfer
#: view; the rest are drives the scene leaves alone.
SHOTS = [
    ("uk", 14, 0, 2, 1, 0),
    ("uk", 14, 0, 1, 0, 6),
    ("uk", 14, 2, 1, 0, 0),
    ("uk", 14, 2, 2, 1, 0xFA),
    ("uk", 14, 2, 2, -1, 6),
    ("uk", 14, 0, 2, 0, 6),
    ("uk", 14, 0, 1, 0, 0),
    ("uk", 14, 2, 1, -1, 0xFA),
    ("uk", 2, 0, 1, 0, 0),
    ("uk", 1, 0, 2, 1, 0x0A),
    ("uk", 16, 2, 1, 0, 0),
    ("us", 12, 0, 1, 0, 0),
    ("japan", 12, 0, 1, 1, 6),
]
TREE_SHOTS = SHOTS[:6]
SWING = Swing(4, 30, 20)
RNG_STATE = 0x2468


def play(rom, hole: HoleData, course, number, club, speed, hi_lo, turn):
    """The game's shot from the tee, and the game it was played in."""
    tee = hole.metadata["tee"]
    shot = ShotInput(
        club=club,
        x=tee["x"],
        y=tee["y"],
        rng_state=RNG_STATE,
        swing_speed=speed,
        hi_lo=hi_lo,
    )
    at_the_flag = RomGameShot(rom, course, number).play(shot, SWING).shot.aim
    game = RomGameShot(rom, course, number)
    return game, game.play(replace(shot, aim=(at_the_flag + turn) & 0xFF), SWING)


def fly(record, ground, physics, scene) -> ShotInFlight:
    """The model's flight of the game's shot, every frame checked against it."""
    flight = ShotInFlight(record.shot, ground, physics, scene=scene, flag=record.flag)
    for name in CARRIED_FROM_LAUNCH:
        setattr(flight.ball, name, getattr(record.frames[0], name))
    for frame, theirs in enumerate(record.frames[1:], 1):
        flight.step()
        assert differences(flight.ball, theirs) == {}, frame
    return flight


@pytest.mark.parametrize(("course", "number", "club", "speed", "hi_lo", "turn"), SHOTS)
def test_shot_with_the_ported_scene(
    rom, tables, vanilla_courses, course, number, club, speed, hi_lo, turn
):
    """
    A shot the game played, replayed in the model with the scene captured from
    the game and again with the ported one. The two scenes must be the same
    bytes, and both flights must agree with the game on every frame.
    """
    scene_tables, terrain_tables = tables
    hole = load_hole(vanilla_courses, course, number)
    ground = HoleGround(hole, terrain_tables)
    game, record = play(rom, hole, course, number, club, speed, hi_lo, turn)
    assert record.scene is not None
    assert record.shot.scene_aim is not None

    tee = hole.metadata["tee"]
    built = build_scene(
        ground,
        scene_tables,
        tee["x"],
        tee["y"],
        record.shot.scene_aim,
        game.flag,
        RNG_STATE,
    )
    captured = bytes(record.scene.memory[WRAM : WRAM + 0x2000])
    assert built.shown[COMPARED] == captured[COMPARED]
    fly(record, ground, scene_tables.physics, record.scene)
    fly(record, ground, scene_tables.physics, built.scene)


@pytest.mark.parametrize(
    ("course", "number", "club", "speed", "hi_lo", "turn"), TREE_SHOTS
)
def test_the_scene_changes_the_shot(
    rom, tables, vanilla_courses, course, number, club, speed, hi_lo, turn
):
    """
    `TREE_SHOTS` do hit the scene's trees: with the ported scene the model's
    ball stops where the game's does, and without a scene it flies on.
    """
    scene_tables, terrain_tables = tables
    hole = load_hole(vanilla_courses, course, number)
    ground = HoleGround(hole, terrain_tables)
    game, record = play(rom, hole, course, number, club, speed, hi_lo, turn)
    assert record.shot.scene_aim is not None
    tee = hole.metadata["tee"]
    built = build_scene(
        ground,
        scene_tables,
        tee["x"],
        tee["y"],
        record.shot.scene_aim,
        game.flag,
        RNG_STATE,
    )
    with_trees = fly(record, ground, scene_tables.physics, built.scene).ball

    without = ShotInFlight(record.shot, ground, scene_tables.physics, flag=record.flag)
    for _ in record.frames[1:]:
        without.step()
    assert (without.ball.x, without.ball.y) != (with_trees.x, with_trees.y)
    assert with_trees.pixel_y - without.ball.pixel_y > 30


# --- the builder's routines alone ------------------------------------------
#
# Whole scenes meet only the tile patterns real holes make. These call single
# routines on made-up inputs, to reach the rest of their branches.

THIN_BLOCKS = 0x8EE4
DRAW_GROUND = 0x9CB8
FIT_GROUND = 0xA30B
NOTE_TREE = 0x9149
DRAW_TREES = 0x91C9
PALETTES = slice(PALETTE_MAP, PALETTE_MAP + 0x60)


def random_grid(rng: random.Random) -> bytes:
    """A probe grid of patches of every lie, at a random scale, with some noise."""
    scale_x, scale_y = rng.choice([1, 2, 3, 5, 8, 13]), rng.choice([1, 2, 3, 5])
    lies = rng.choice([range(7), (0, 2, 3, 4), (0, 2, 6), (0, 3, 4, 6), (2, 4, 5, 6)])
    noise = rng.choice([0, 0.05, 0.3])
    coarse = [[rng.choice(lies) for _ in range(GRID_COLUMNS)] for _ in range(GRID_ROWS)]
    return bytes(
        rng.choice(lies)
        if rng.random() < noise
        else coarse[row // scale_y][column // scale_x]
        for row in range(GRID_ROWS)
        for column in range(GRID_COLUMNS)
    )


def matched_builders(rom, tables, vanilla_courses, course="uk", number=14):
    """The game and the port after the same scene, holding the same memory."""
    scene_tables, terrain_tables = tables
    hole = load_hole(vanilla_courses, course, number)
    game = RomSceneBuilder(rom, course, number)
    tee = hole.metadata["tee"]
    theirs = game.build(tee["x"], tee["y"], 0, 1)
    ours = SceneBuilder(
        HoleGround(hole, terrain_tables), scene_tables, theirs.before, theirs.stale
    )
    ours.run(tee["x"], tee["y"], 0, 0, 0, game.flag, 1)
    return game, ours


def assert_same_memory(game: RomSceneBuilder, ours: SceneBuilder, case) -> None:
    m = game.machine.memory
    assert bytes(ours.m[WRAM:0x8000])[COMPARED] == bytes(m[WRAM:0x8000])[COMPARED], case
    assert ours.m[PALETTES] == m[PALETTES], case


@pytest.mark.parametrize("seed", range(8))
def test_ground_from_random_grids(rom, tables, vanilla_courses, seed):
    """`$8EE4`, `$9CB8` and `$A30B` over grids no hole would give."""
    game, ours = matched_builders(rom, tables, vanilla_courses)
    m = game.machine.memory
    rng = random.Random(seed)
    for case in range(25):
        grid = random_grid(rng)
        ball_lie = rng.choice([0, 1, 2])
        for memory in (m, ours.m):
            memory[GRID : GRID + len(grid)] = grid
            memory[BALL_LIE_CLASS] = ball_lie
        ours.m[WRAM:0x8000] = m[WRAM:0x8000]
        game.call(THIN_BLOCKS)
        ours.thin_blocks()
        assert_same_memory(game, ours, (case, "blocks"))
        game.call(DRAW_GROUND)
        ours.draw_ground()
        assert_same_memory(game, ours, (case, "ground"))
        game.call(FIT_GROUND)
        ours.fit_neighbors()
        ours.finish_horizon()
        ours.block_bottom_rows()
        assert_same_memory(game, ours, (case, "fitted"))


@pytest.mark.parametrize("seed", range(4))
def test_trees_from_random_columns(rom, tables, vanilla_courses, seed):
    """`$91C9` with a tree of a random size and depth in each screen column."""
    game, ours = matched_builders(rom, tables, vanilla_courses)
    m = game.machine.memory
    rng = random.Random(seed)
    draws = 0
    for case in range(40):
        # A fresh ground under the trees, then the builder's own clearing.
        grid = random_grid(rng)
        m[GRID : GRID + len(grid)] = grid
        for routine in (THIN_BLOCKS, DRAW_GROUND, FIT_GROUND):
            game.call(routine)
        density = rng.choice([0.1, 0.4, 0.9])
        bands = bytes(
            rng.randrange(1, 16) if rng.random() < density else 0
            for _ in range(MAP_COLUMNS)
        )
        depths = bytes(rng.randrange(0x0E, 0x100) for _ in range(MAP_COLUMNS))
        rng_state = rng.randrange(0x10000)
        m[SCENE_TILE_MAP : SCENE_TILE_MAP + 14 * MAP_COLUMNS] = b"\x3a" * 448
        m[SCENE_DEPTH_MAP : SCENE_DEPTH_MAP + MAP_BYTES] = b"\xff" * MAP_BYTES
        m[TREE_BANDS : TREE_BANDS + MAP_COLUMNS] = bands
        m[TREE_DEPTHS : TREE_DEPTHS + MAP_COLUMNS] = depths
        m[0x42], m[0x43] = rng_state & 0xFF, rng_state >> 8
        # No sprites and no tile changes queued for the PPU.
        m[0x4B] = m[0x072C] = m[FLAG_NEAR] = 0
        ours.m[WRAM:0x8000] = m[WRAM:0x8000]
        ours.m[PALETTES] = m[PALETTES]
        ours.rng_state = rng_state

        game.call(DRAW_TREES)
        ours.draw_trees()
        assert_same_memory(game, ours, case)
        assert ours.rng_state == m[0x42] | m[0x43] << 8, case
        draws += ours.rng_state != rng_state
    assert draws > 10


@pytest.mark.parametrize(
    ("course", "number", "aim"), [("uk", 14, 0), ("uk", 2, 0x20), ("us", 7, 0xF0)]
)
def test_tree_points(rom, tables, vanilla_courses, course, number, aim):
    """`$9149`: random points projected as trees, one after another."""
    scene_tables, terrain_tables = tables
    hole = load_hole(vanilla_courses, course, number)
    game = RomSceneBuilder(rom, course, number)
    tee = hole.metadata["tee"]
    theirs = game.build(tee["x"], tee["y"], aim, 1)
    ours = SceneBuilder(
        HoleGround(hole, terrain_tables), scene_tables, theirs.before, theirs.stale
    )
    ours.run(tee["x"], tee["y"], 0, 0, aim, game.flag, 1)
    m = game.machine.memory
    rng = random.Random(number)
    kept = 0
    for case in range(3000):
        if case % 500 == 0:
            # Start the columns again, and move the green's row about.
            flag_y, left = rng.randrange(0x60, 0xB0), rng.randrange(0, 0xD0, 8)
            for memory in (m, ours.m):
                memory[TREE_BANDS : TREE_BANDS + 2 * MAP_COLUMNS] = bytes(64)
                memory[FLAG_SCREEN_Y] = flag_y
                memory[GREEN_LEFT], memory[GREEN_RIGHT] = left, left + 0x30
        x = (tee["x"] + rng.randint(-90, 90)) & 0xFF
        y = (tee["y"] - rng.randint(-20, 130)) & 0xFFFF
        before = bytes(ours.m[TREE_BANDS : TREE_BANDS + 2 * MAP_COLUMNS])
        m[0x9C], m[0x9E], m[0x9F] = x, y & 0xFF, y >> 8
        game.call(NOTE_TREE)
        ours.note_tree(x, y)
        after = bytes(ours.m[TREE_BANDS : TREE_BANDS + 2 * MAP_COLUMNS])
        assert after == bytes(m[TREE_BANDS : TREE_BANDS + 2 * MAP_COLUMNS]), case
        registers = ours.registers
        assert (registers.depth, registers.screen_x, registers.screen_y) == (
            m[0xC5],
            m[0xC6],
            m[0xC7] | m[0xC8] << 8,
        ), case
        kept += after != before
    assert kept > 100


def test_grid_is_twice_the_map():
    assert GRID_COLUMNS == 2 * MAP_COLUMNS
