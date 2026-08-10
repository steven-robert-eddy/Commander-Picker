"""Set challenge tracker: like the 32-deck color-identity challenge
(challenge.py), but one entry per EDHREC set release that actually has
a real (non-reprint) commander -- see db.py's commander_sets table and
pool.list_known_sets. A personal planning tool, not a rating/Elo
concept, same as challenge.py.

Unlike colors.all_slugs() (a small, fixed, hardcoded 32-entry list),
the known-sets list is fully data-driven and grows every time
`update-data --discover-sets` finds a new release -- so, unlike
challenge.py, this module can't synthesize its own "every known slug"
list internally. Every function here takes `known_sets` (a
``[{"slug", "name"}, ...]`` list, e.g. from pool.list_known_sets(catalog
connection)) in from the caller instead, rather than reaching for a
second, catalog-DB connection of its own on top of the sessions-DB one
it's already given.

Also unlike colors, a commander can't be auto-routed to "the" set it
belongs to the way a color identity always maps to exactly one of the
32 combos (see challenge.challenge_slug_for_commander) -- a set's
candidate list is meant to hold commanders actually printed in that
release, and a commander only knows its own color identity, not which
set(s) it shipped in. Candidates are added by slug explicitly instead
(the web layer scopes a search to one set's own commander_sets rows --
see pool.search_commanders_in_set -- rather than this module guessing).

Shares sessions.db with sessions.py/challenge.py/pods.py/favorites.py
-- see store.py for the connection/schema this module builds on.
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass

from commander_picker.store import SessionError

VALID_SET_CHALLENGE_STATUSES = ("not_started", "planning", "building", "complete")


@dataclass
class SetChallengeCommanderOption:
    name: str
    is_chosen: bool


@dataclass
class SetChallengeEntry:
    slug: str
    name: str  # human-readable set name, e.g. "Duskmourn: House of Horror"
    status: str
    notes: str | None
    commanders: list[SetChallengeCommanderOption]
    updated_at: float | None


def _slugs(known_sets: list[dict]) -> set[str]:
    return {s["slug"] for s in known_sets}


def _require_known_slug(slug: str, known_sets: list[dict]) -> None:
    if slug not in _slugs(known_sets):
        raise SessionError(f"Unknown set slug {slug!r}")


def get_tracker(conn: sqlite3.Connection, known_sets: list[dict]) -> list[SetChallengeEntry]:
    """Entries aren't pre-seeded: synthesizes one entry per `known_sets`
    at read time by overlaying whatever's in set_challenge_tracker/
    set_challenge_commanders onto it -- a set with no rows yet just
    reads as not_started/empty, same "synthesize at read time" contract
    as challenge.get_challenge_tracker.
    """
    status_rows = {r["slug"]: r for r in conn.execute("SELECT * FROM set_challenge_tracker")}
    commander_rows = conn.execute(
        "SELECT slug, commander_name, is_chosen FROM set_challenge_commanders ORDER BY added_at"
    ).fetchall()
    commanders_by_slug: dict[str, list[SetChallengeCommanderOption]] = {}
    for row in commander_rows:
        commanders_by_slug.setdefault(row["slug"], []).append(
            SetChallengeCommanderOption(name=row["commander_name"], is_chosen=bool(row["is_chosen"]))
        )

    entries = []
    for s in known_sets:
        slug = s["slug"]
        status_row = status_rows.get(slug)
        entries.append(
            SetChallengeEntry(
                slug=slug,
                name=s["name"],
                status=status_row["status"] if status_row else "not_started",
                notes=status_row["notes"] if status_row else None,
                commanders=commanders_by_slug.get(slug, []),
                updated_at=status_row["updated_at"] if status_row else None,
            )
        )
    return entries


def _get_entry(conn: sqlite3.Connection, slug: str, known_sets: list[dict]) -> SetChallengeEntry:
    return next(e for e in get_tracker(conn, known_sets) if e.slug == slug)


def set_status(
    conn: sqlite3.Connection, known_sets: list[dict], slug: str, status: str, notes: str | None = None
) -> SetChallengeEntry:
    """Full overwrite of one set's status/notes, mirroring
    challenge.set_challenge_status -- the web form always submits the
    whole status/notes state.
    """
    _require_known_slug(slug, known_sets)
    if status not in VALID_SET_CHALLENGE_STATUSES:
        raise SessionError(f"status must be one of {VALID_SET_CHALLENGE_STATUSES}, got {status!r}")

    conn.execute(
        """
        INSERT INTO set_challenge_tracker (slug, status, notes, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(slug) DO UPDATE SET
            status = excluded.status,
            notes = excluded.notes,
            updated_at = excluded.updated_at
        """,
        (slug, status, notes, time.time()),
    )
    conn.commit()
    return _get_entry(conn, slug, known_sets)


def add_commander(
    conn: sqlite3.Connection, known_sets: list[dict], slug: str, commander_name: str
) -> SetChallengeEntry:
    """Append one candidate to a set's shortlist. No cap enforced in
    code, same posture as challenge.add_challenge_commander -- and
    re-adding an already-present name is a no-op.
    """
    _require_known_slug(slug, known_sets)
    conn.execute(
        "INSERT OR IGNORE INTO set_challenge_commanders (slug, commander_name, is_chosen, added_at) VALUES (?, ?, 0, ?)",
        (slug, commander_name, time.time()),
    )
    conn.commit()
    return _get_entry(conn, slug, known_sets)


def remove_commander(
    conn: sqlite3.Connection, known_sets: list[dict], slug: str, commander_name: str
) -> SetChallengeEntry:
    _require_known_slug(slug, known_sets)
    conn.execute(
        "DELETE FROM set_challenge_commanders WHERE slug = ? AND commander_name = ?", (slug, commander_name)
    )
    conn.commit()
    return _get_entry(conn, slug, known_sets)


def choose_commander(
    conn: sqlite3.Connection, known_sets: list[dict], slug: str, commander_name: str
) -> SetChallengeEntry:
    """Marks one candidate as chosen, unmarking any previous chosen
    entry for that set (at most one chosen commander per set) -- raises
    SessionError if commander_name isn't already in that set's
    candidate list, same choose-implies-add-first contract as
    challenge.choose_challenge_commander.
    """
    _require_known_slug(slug, known_sets)
    existing = conn.execute(
        "SELECT 1 FROM set_challenge_commanders WHERE slug = ? AND commander_name = ?", (slug, commander_name)
    ).fetchone()
    if existing is None:
        raise SessionError(f"{commander_name!r} isn't a candidate for {slug!r} yet -- add it first.")

    conn.execute("UPDATE set_challenge_commanders SET is_chosen = 0 WHERE slug = ?", (slug,))
    conn.execute(
        "UPDATE set_challenge_commanders SET is_chosen = 1 WHERE slug = ? AND commander_name = ?",
        (slug, commander_name),
    )
    conn.commit()
    return _get_entry(conn, slug, known_sets)
