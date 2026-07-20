"""32-deck challenge tracker: a personal planning tool riding on data
this app already produces -- not a rating/Elo concept.

Tracks one entry per color-identity combo (colors.all_slugs(),
colorless through five-color) with a status and a short shortlist of
candidate commanders, at most one marked chosen. Entries aren't
pre-seeded: get_challenge_tracker synthesizes all 32 at read time by
overlaying whatever's in challenge_tracker/challenge_commanders onto
colors.all_slugs(), so a combo with no rows yet just reads as
not_started/empty.

Shares sessions.db with sessions.py (picker sessions) and pods.py (pod
tracker) -- see store.py for the connection/schema/SessionError this
module builds on.
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass

from commander_picker import colors as color_slugs
from commander_picker.store import SessionError

VALID_CHALLENGE_STATUSES = ("not_started", "planning", "building", "complete")


@dataclass
class ChallengeCommanderOption:
    name: str
    is_chosen: bool


@dataclass
class ChallengeEntry:
    slug: str
    colors: str  # e.g. "BR", WUBRG-ordered
    status: str
    notes: str | None
    commanders: list[ChallengeCommanderOption]
    updated_at: float | None


def _require_known_slug(slug: str) -> None:
    if slug not in color_slugs.COLOR_IDENTITY_BY_SLUG:
        raise SessionError(f"Unknown color-identity slug {slug!r}")


def get_challenge_tracker(conn: sqlite3.Connection) -> list[ChallengeEntry]:
    status_rows = {r["slug"]: r for r in conn.execute("SELECT * FROM challenge_tracker")}
    commander_rows = conn.execute(
        "SELECT slug, commander_name, is_chosen FROM challenge_commanders ORDER BY added_at"
    ).fetchall()
    commanders_by_slug: dict[str, list[ChallengeCommanderOption]] = {}
    for row in commander_rows:
        commanders_by_slug.setdefault(row["slug"], []).append(
            ChallengeCommanderOption(name=row["commander_name"], is_chosen=bool(row["is_chosen"]))
        )

    entries = []
    for slug in color_slugs.all_slugs():
        status_row = status_rows.get(slug)
        entries.append(
            ChallengeEntry(
                slug=slug,
                colors="".join(color_slugs.COLOR_IDENTITY_BY_SLUG[slug]),
                status=status_row["status"] if status_row else "not_started",
                notes=status_row["notes"] if status_row else None,
                commanders=commanders_by_slug.get(slug, []),
                updated_at=status_row["updated_at"] if status_row else None,
            )
        )
    return entries


def _get_challenge_entry(conn: sqlite3.Connection, slug: str) -> ChallengeEntry:
    return next(e for e in get_challenge_tracker(conn) if e.slug == slug)


def set_challenge_status(
    conn: sqlite3.Connection, slug: str, status: str, notes: str | None = None
) -> ChallengeEntry:
    """Full overwrite of one combo's status/notes (not its candidate
    list, which has its own add/remove/choose functions below) -- the
    web form always submits the whole status/notes state, so this
    avoids a None-means-"leave unchanged" footgun.
    """
    _require_known_slug(slug)
    if status not in VALID_CHALLENGE_STATUSES:
        raise SessionError(f"status must be one of {VALID_CHALLENGE_STATUSES}, got {status!r}")

    conn.execute(
        """
        INSERT INTO challenge_tracker (slug, status, notes, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(slug) DO UPDATE SET
            status = excluded.status,
            notes = excluded.notes,
            updated_at = excluded.updated_at
        """,
        (slug, status, notes, time.time()),
    )
    conn.commit()
    return _get_challenge_entry(conn, slug)


def add_challenge_commander(conn: sqlite3.Connection, slug: str, commander_name: str) -> ChallengeEntry:
    """Append one candidate to a combo's shortlist. No cap enforced in
    code -- "a couple" is a UI expectation, not a hard limit -- and
    re-adding an already-present name is a no-op.
    """
    _require_known_slug(slug)
    conn.execute(
        "INSERT OR IGNORE INTO challenge_commanders (slug, commander_name, is_chosen, added_at) VALUES (?, ?, 0, ?)",
        (slug, commander_name, time.time()),
    )
    conn.commit()
    return _get_challenge_entry(conn, slug)


def remove_challenge_commander(conn: sqlite3.Connection, slug: str, commander_name: str) -> ChallengeEntry:
    _require_known_slug(slug)
    conn.execute(
        "DELETE FROM challenge_commanders WHERE slug = ? AND commander_name = ?", (slug, commander_name)
    )
    conn.commit()
    return _get_challenge_entry(conn, slug)


def choose_challenge_commander(conn: sqlite3.Connection, slug: str, commander_name: str) -> ChallengeEntry:
    """Marks one candidate as chosen, unmarking any previous chosen
    entry for that slug (at most one chosen commander per combo) --
    raises SessionError if commander_name isn't already in that combo's
    candidate list, so choosing implies add-first, not add-and-choose
    in one call.
    """
    _require_known_slug(slug)
    existing = conn.execute(
        "SELECT 1 FROM challenge_commanders WHERE slug = ? AND commander_name = ?", (slug, commander_name)
    ).fetchone()
    if existing is None:
        raise SessionError(f"{commander_name!r} isn't a candidate for {slug!r} yet -- add it first.")

    conn.execute("UPDATE challenge_commanders SET is_chosen = 0 WHERE slug = ?", (slug,))
    conn.execute(
        "UPDATE challenge_commanders SET is_chosen = 1 WHERE slug = ? AND commander_name = ?",
        (slug, commander_name),
    )
    conn.commit()
    return _get_challenge_entry(conn, slug)


def challenge_slug_for_commander(color_identity: str) -> str:
    return color_slugs.slug_for_colors(color_identity)


