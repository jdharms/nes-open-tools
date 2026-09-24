"""
The behind-the-golfer view's pieces against the ROM's own routines, called
directly with random inputs: the projection (`LE87C`), the distance readout
(`DistanceBetweenPoints`) and the scene collision (`LE9C8`), the last over
scenes the game's own builder made for real holes.
"""

import json
import random
from pathlib import Path

import pytest

from golf.core.rom_reader import RomReader
from golf.physics import Ball, PhysicsTables, ShotInput
from golf.physics.distance import distance_between_points
from golf.physics.nes import NesMachine
from golf.physics.perspective import Projection, collide, project
from golf.physics.rom_game import RomGameShot, Swing

ROM_PATH = "nes_open_us.nes"

pytestmark = pytest.mark.skipif(
    not Path(ROM_PATH).exists(), reason=f"{ROM_PATH} not present"
)

PROJECT = 0xE87C
COLLIDE = 0xE9C8
DISTANCE = 0xE522


@pytest.fixture(scope="module")
def rom() -> RomReader:
    return RomReader(ROM_PATH)


@pytest.fixture(scope="module")
def machine(rom) -> NesMachine:
    return NesMachine(rom)


def test_projection(rom, machine):
    tables = PhysicsTables.from_rom(rom)
    m = machine.memory
    rng = random.Random(1)
    visible = 0
    for _ in range(20_000):
        ox, oy = rng.randrange(20, 160), rng.randrange(0x100, 0x300)
        ball = Ball(
            x=(ox + rng.randint(-140, 140)) % 256 << 16 | rng.randrange(0x10000),
            y=(oy + rng.randint(-140, 140)) << 16 | rng.randrange(0x10000),
            height=rng.choice([0, rng.randrange(1 << 31), rng.randrange(1 << 27)]),
        )
        origin_x = ox << 8 | rng.randrange(256)
        origin_y = oy << 8 | rng.randrange(256)
        anchor = rng.randrange(256)
        m[0xB8:0xBA] = origin_x.to_bytes(2, "little")
        m[0xBA:0xBD] = origin_y.to_bytes(3, "little")
        m[0xBD] = anchor
        m[0xBE:0xC0] = (ball.x >> 8).to_bytes(2, "little")
        m[0xC0:0xC3] = (ball.y >> 8 & 0xFFFFFF).to_bytes(3, "little")
        lo, hi = ball.height >> 16 & 0xFF, ball.height >> 24
        m[0xC3] = lo << 1 & 0xFF
        m[0xC4] = 0xFF if hi & 0x80 else (hi << 1 | lo >> 7) & 0xFF
        machine.call(PROJECT)

        model = project(ball, origin_x, origin_y, anchor, tables)
        assert model.depth == m[0xC5]
        if model.depth:
            visible += 1
            assert (model.screen_x, model.screen_y) == (m[0xC6], m[0xC7] | m[0xC8] << 8)
    assert visible > 1000


def test_distance(machine):
    m = machine.memory
    rng = random.Random(2)
    for _ in range(20_000):
        x1, x2 = rng.randrange(256), rng.randrange(256)
        y1, y2 = rng.randrange(0x600), rng.randrange(0x600)
        m[0x88], m[0x89], m[0x8A] = x1, y1 & 0xFF, y1 >> 8
        m[0x8C], m[0x8D], m[0x8E] = x2, y2 & 0xFF, y2 >> 8
        machine.call(DISTANCE)
        assert distance_between_points(x1, y1, x2, y2) == m[0x8C] | m[0x8D] << 8


@pytest.mark.parametrize(("course", "hole"), [("uk", 1), ("us", 7), ("japan", 12)])
def test_scene_collision(rom, vanilla_courses, course, hole):
    tee = json.loads((vanilla_courses / course / f"hole_{hole:02}.json").read_text())[
        "tee"
    ]
    game = RomGameShot(rom, course, hole)
    record = game.play(ShotInput(club=4, x=tee["x"], y=tee["y"]), Swing(4, 20, 12))
    scene = record.scene
    assert scene is not None

    machine = NesMachine(rom)
    machine.select_bank(13)  # LE9C8 runs from LD_BB6D in bank 13
    m = machine.memory
    rng = random.Random(hole)
    hits = 0
    for _ in range(5_000):
        m[0x6000:0x8000] = scene.memory[0x6000:0x8000]
        # Rows 0-23 of the scene (screen y up to 188); see PerspectiveScene.
        screen_x = rng.randrange(256)
        screen_y = rng.choice([rng.randrange(189), rng.randrange(0x70, 189)])
        depth = rng.randrange(1, 256)
        tile_depth = scene.read(0x7AE6 + ((screen_y + 3) >> 3) * 32 + (screen_x >> 3))
        if tile_depth != 0xFF and rng.random() < 0.5:
            # Just in front of whatever stands there, where hits happen.
            depth = max(1, tile_depth - rng.randint(1, 3))
        projection = Projection(depth, screen_x, screen_y)
        before = rng.choice([0, 0, rng.randrange(256)])
        m[0xC5], m[0xC6] = projection.depth, projection.screen_x
        m[0xC7], m[0xC8] = projection.screen_y & 0xFF, projection.screen_y >> 8
        m[0x0599] = before
        machine.call(COLLIDE)

        after = collide(projection, scene, before)
        assert after == m[0x0599], projection
        hits += after != before
    assert hits
