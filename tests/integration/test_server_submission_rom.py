"""Integration: the QR code a signed-in download's ROM draws records its round on the site.

Downloads a finished ROM from the app, pulls the scorecard QR image back out of it, runs the
6502 routine under the simulator to build the URL the code carries, and opens that URL.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from golf.core import ips
from golf.core.patches import SCORECARD_QR_PATCH
from golf.qr.payload import URL_LEN, URL_PREFIX, pack_stats
from golf.qr.port import layout
from golf.qr.port.sim import Machine
from golf.randomizer.catalog import US_ROM
from golf.randomizer.roms import vanilla_rom
from server.app import create_app
from server.config import Config
from server.forms import FormState
from tests.app_state import app_state

ROOT = Path(__file__).resolve().parents[2]
ROM_PATH = ROOT / "nes_open_us.nes"
HEADER = 0x10

pytestmark = pytest.mark.skipif(
    not ROM_PATH.exists(), reason=f"{ROM_PATH.name} not present"
)

#: (strokes, putts) for holes 1-18, per player slot
ROUNDS = {
    0: [(4, 2)] * 9 + [(5, 2)] * 9,
    1: [(3, 1)] * 18,
}
#: (fairway bits, penalty strokes) per player slot, as round_stats keeps them
STATS = {
    0: (tuple(hole % 2 == 0 for hole in range(18)), 2),
    1: ((False,) * 18, 0),
}


def rom_url(rom: bytes, slot: int) -> str:
    """The URL the ROM's QR screen shows for `slot` after ROUNDS has been played."""
    image = rom[HEADER + SCORECARD_QR_PATCH.image_offset :][
        : len(SCORECARD_QR_PATCH.image)
    ]
    machine = Machine()
    machine.write(layout.TABLE_ORIGIN, image)
    for player, holes in ROUNDS.items():
        machine.set_round(
            holes, player=player, player_count=1, stats=pack_stats(*STATS[player])
        )
    machine.call("QrBuildPayload", a=slot)
    machine.call("QrBuildUrl")
    return machine.read(layout.URL, URL_LEN).decode("ascii")


def test_a_downloaded_roms_codes_record_both_players_rounds(vanilla_courses):
    with TestClient(
        create_app(
            Config(
                database=":memory:",
                rom_dir=ROOT,
                holes_dir=vanilla_courses,
                dev_login=True,
            )
        )
    ) as client:
        form = FormState.default()
        form.sources, form.music = {US_ROM}, "nes_us"
        data: dict[str, list[str]] = {}
        for name, value in form.to_pairs():
            data.setdefault(name, []).append(value)
        generated = client.post("/generate", data=data, follow_redirects=False)
        assert generated.status_code == 303, generated.text
        seed_path = generated.headers["location"]

        client.get("/auth/login", params={"as": "alice"})
        download = client.post(
            f"{seed_path}/patch.ips",
            data={
                "player_name": "toad",
                "clubs": ["1W", "PW"],
                f"rom_{US_ROM}": vanilla_rom(US_ROM).sha1,
            },
        )
        assert download.status_code == 200, download.text
        rom = ips.apply(ROM_PATH.read_bytes(), download.content)
        client.post("/auth/logout", data={"next": "/"})

        for slot in ROUNDS:
            url = rom_url(rom, slot)
            assert url.startswith(URL_PREFIX)
            # the ROM's own URL submits and hands the phone the round's permalink
            submitted = client.get(
                "/s/" + url.removeprefix(URL_PREFIX), follow_redirects=False
            )
            assert submitted.status_code == 303, submitted.text
            permalink = submitted.headers["location"]
            assert permalink.endswith("?recorded")
            response = client.get(permalink)
            assert response.status_code == 200, response.text

        with app_state(client).db.transaction() as conn:
            recorded = conn.execute(
                """
                SELECT slot, total_strokes, total_putts, penalty_strokes FROM rounds
                ORDER BY slot
                """
            ).fetchall()
            fairways = conn.execute(
                """
                SELECT rounds.slot, round_holes.fairway_hit FROM round_holes
                JOIN rounds ON rounds.id = round_holes.round_id
                ORDER BY rounds.slot, round_holes.position
                """
            ).fetchall()
    assert [tuple(row) for row in recorded] == [
        (slot, sum(s for s, _ in holes), sum(p for _, p in holes), STATS[slot][1])
        for slot, holes in ROUNDS.items()
    ]
    for slot in ROUNDS:
        assert (
            tuple(bool(row["fairway_hit"]) for row in fairways if row["slot"] == slot)
            == STATS[slot][0]
        )
