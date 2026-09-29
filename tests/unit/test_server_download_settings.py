"""Saved download settings on the account: one row per player, replaced, read leniently, forgotten."""

import sqlite3

import pytest

from golf.core.patches.new_save_options import BallSpin, SwingSpeed
from golf.core.patches.sram_defaults import Club
from server.db import Database
from server.download_settings import forget_settings, load_settings, save_settings
from server.forms import SavedSettings
from server.users import sign_in

LUIGI = SavedSettings(
    player_name="LUIGI",
    clubs=frozenset({Club.W1, Club.PW, Club.PT}),
    bgm=False,
    swing=SwingSpeed.FAST,
    putt=SwingSpeed.OFF,
    spin=BallSpin.BACK2,
)


@pytest.fixture
def db():
    database = Database(":memory:")
    database.migrate()
    yield database
    database.close()


def user(db, name: str) -> int:
    return sign_in(db, f"dev:{name}", name, None, None).id


def test_a_player_with_nothing_saved_has_no_settings(db):
    assert load_settings(db, user(db, "alice")) is None


def test_saving_creates_and_then_replaces_the_row(db):
    alice = user(db, "alice")
    save_settings(db, alice, SavedSettings(), now="2026-09-28T00:00:00Z")
    save_settings(db, alice, LUIGI, now="2026-09-29T00:00:00Z")
    assert load_settings(db, alice) == LUIGI
    with db.transaction() as conn:
        rows = conn.execute(
            "SELECT user_id, updated_at FROM download_settings"
        ).fetchall()
    assert [tuple(row) for row in rows] == [(alice, "2026-09-29T00:00:00Z")]


def test_each_player_has_their_own(db):
    alice, bob = user(db, "alice"), user(db, "bob")
    save_settings(db, alice, LUIGI)
    assert load_settings(db, bob) is None
    save_settings(db, bob, SavedSettings())
    assert load_settings(db, alice) == LUIGI


def test_a_stored_record_is_read_as_leniently_as_the_cookie(db):
    alice = user(db, "alice")
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO download_settings (user_id, settings, updated_at) VALUES (?, ?, ?)",
            (alice, '{"v": 1, "name": "LU!GI", "swing": "fast", "later": true}', "now"),
        )
    loaded = load_settings(db, alice)
    assert loaded == SavedSettings(swing=SwingSpeed.FAST)


def test_the_column_holds_only_a_json_object(db):
    alice = user(db, "alice")
    for value in ("not json", "[1, 2]"):
        with (
            pytest.raises(sqlite3.IntegrityError, match="CHECK"),
            db.transaction() as conn,
        ):
            conn.execute(
                "INSERT INTO download_settings (user_id, settings, updated_at) VALUES (?, ?, ?)",
                (alice, value, "now"),
            )


def test_forgetting_deletes_the_row(db):
    alice = user(db, "alice")
    assert forget_settings(db, alice) is False
    save_settings(db, alice, LUIGI)
    assert forget_settings(db, alice) is True
    assert load_settings(db, alice) is None
