"""A signed-in player's saved download settings: the only code that writes `download_settings`.

One row per user holds a `SavedSettings` record as JSON (`server/forms.py`). A signed-in
download saves into it by the saving rule, and `/me` edits or forgets it. The row is read
back as leniently as the cookie: whatever a stored record lacks reads as vanilla. See
docs/planning/download_settings.md.
"""

import json

from .db import Database
from .forms import SavedSettings
from .seeds import utc_now


def load_settings(db: Database, user_id: int) -> SavedSettings | None:
    """The player's saved settings, or None when they have saved none."""
    with db.transaction() as conn:
        row = conn.execute(
            "SELECT settings FROM download_settings WHERE user_id = ?", (user_id,)
        ).fetchone()
    return None if row is None else SavedSettings.from_json(json.loads(row["settings"]))


def save_settings(
    db: Database, user_id: int, settings: SavedSettings, now: str | None = None
) -> None:
    """Create or replace the player's saved settings."""
    at = now if now is not None else utc_now()
    with db.transaction() as conn:
        conn.execute(
            """
            INSERT INTO download_settings (user_id, settings, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT (user_id) DO UPDATE
                SET settings = excluded.settings, updated_at = excluded.updated_at
            """,
            (user_id, json.dumps(settings.to_json(), separators=(",", ":")), at),
        )


def forget_settings(db: Database, user_id: int) -> bool:
    """Delete the player's saved settings. Returns whether there were any."""
    with db.transaction() as conn:
        cursor = conn.execute(
            "DELETE FROM download_settings WHERE user_id = ?", (user_id,)
        )
    return cursor.rowcount > 0
