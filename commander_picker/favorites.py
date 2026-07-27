"""Per-commander owned/wishlist tracking, independent of any session.

A commander's favorite status lives entirely in its own table, keyed
by name -- no session_id, no reference to challenge_tracker or
challenge_commanders. Deliberately decoupled from the 32-deck
challenge tracker (challenge.py) even though the two pair naturally
in the UI (e.g. marking a chosen commander "owned" once its physical
deck exists): neither module needs to know the other's schema.

"None" (not favorited at all) has no stored row -- a commander's
favorite status is just whether a commander_favorites row exists for
its name, same posture as commander_ratings (no games played means no
row, not a row with rating=0).

Shares sessions.db with sessions.py/challenge.py/pods.py -- see
store.py for the connection/schema/SessionError this module builds on.
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass

from commander_picker.store import SessionError

VALID_STATUSES = ("owned", "wishlist")


@dataclass
class FavoriteEntry:
    commander_name: str
    status: str
    updated_at: float


def set_favorite_status(conn: sqlite3.Connection, commander_name: str, status: str) -> FavoriteEntry:
    if status not in VALID_STATUSES:
        raise SessionError(f"status must be one of {VALID_STATUSES}, got {status!r}")

    updated_at = time.time()
    conn.execute(
        """
        INSERT INTO commander_favorites (commander_name, status, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(commander_name) DO UPDATE SET
            status = excluded.status,
            updated_at = excluded.updated_at
        """,
        (commander_name, status, updated_at),
    )
    conn.commit()
    return FavoriteEntry(commander_name=commander_name, status=status, updated_at=updated_at)


def clear_favorite(conn: sqlite3.Connection, commander_name: str) -> None:
    conn.execute("DELETE FROM commander_favorites WHERE commander_name = ?", (commander_name,))
    conn.commit()


def favorites_by_name(conn: sqlite3.Connection, names: list[str]) -> dict[str, str]:
    """Bulk name -> status lookup, for enriching a list of rendered rows.

    Mirrors pool.commander_images_by_name's shape -- a name with no
    row simply isn't a key in the result, not an error.
    """
    if not names:
        return {}
    placeholders = ",".join("?" * len(names))
    rows = conn.execute(
        f"SELECT commander_name, status FROM commander_favorites WHERE commander_name IN ({placeholders})",
        names,
    ).fetchall()
    return {row["commander_name"]: row["status"] for row in rows}
