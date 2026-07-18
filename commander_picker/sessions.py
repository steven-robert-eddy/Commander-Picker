"""Persist picker sessions: candidate pools, ratings, comparison history.

Lives in a separate `data/sessions.db`, not `commanders.db` -- the
catalog DB is fully dropped and rebuilt on every `update-data` run
(see `db.py::build_database`), which would silently wipe any
in-progress or completed picker sessions if they shared a file.
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from commander_picker import elo
from commander_picker.pool import Commander

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
SESSIONS_DB_PATH = DATA_DIR / "sessions.db"


class SessionError(RuntimeError):
    pass


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            created_at REAL NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL,
            target_rounds INTEGER NOT NULL,
            rounds_completed INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS candidates (
            session_id TEXT NOT NULL REFERENCES sessions(id),
            commander_name TEXT NOT NULL,
            color_identity TEXT,
            num_decks INTEGER,
            edhrec_url TEXT,
            themes TEXT NOT NULL DEFAULT '',
            image_urls TEXT NOT NULL DEFAULT '[]',
            rating REAL NOT NULL,
            PRIMARY KEY (session_id, commander_name)
        );
        CREATE TABLE IF NOT EXISTS comparisons (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL REFERENCES sessions(id),
            round_num INTEGER NOT NULL,
            winner TEXT NOT NULL,
            loser TEXT NOT NULL,
            created_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS commander_ratings (
            commander_name TEXT PRIMARY KEY,
            rating REAL NOT NULL,
            games_played INTEGER NOT NULL DEFAULT 0,
            updated_at REAL NOT NULL
        );
        """
    )
    # Migration for sessions.db files created before these columns
    # existed (CREATE TABLE IF NOT EXISTS doesn't add columns to an
    # already-existing table).
    existing_columns = {row["name"] for row in conn.execute("PRAGMA table_info(candidates)")}
    if "themes" not in existing_columns:
        conn.execute("ALTER TABLE candidates ADD COLUMN themes TEXT NOT NULL DEFAULT ''")
    if "image_urls" not in existing_columns:
        conn.execute("ALTER TABLE candidates ADD COLUMN image_urls TEXT NOT NULL DEFAULT '[]'")
        if "image_url" in existing_columns:
            # Older sessions.db files stored a single image_url string --
            # fold any existing value into the new list column so
            # in-flight sessions don't lose their art on upgrade.
            rows = conn.execute(
                "SELECT session_id, commander_name, image_url FROM candidates WHERE image_url IS NOT NULL"
            ).fetchall()
            conn.executemany(
                "UPDATE candidates SET image_urls = ? WHERE session_id = ? AND commander_name = ?",
                [(json.dumps([r["image_url"]]), r["session_id"], r["commander_name"]) for r in rows],
            )
    conn.commit()


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    # See db.py::connect for why this can't default to `= SESSIONS_DB_PATH`
    # directly -- that binds at def-time and breaks monkeypatching.
    if db_path is None:
        db_path = SESSIONS_DB_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    _ensure_schema(conn)
    return conn


def _global_ratings(conn: sqlite3.Connection, names: list[str]) -> dict[str, float]:
    """Current all-time rating for each name that has one, keyed by name.

    A name with no history yet (never picked/passed-over in any
    session before) simply isn't in the returned dict -- callers fall
    back to elo.DEFAULT_RATING for those.
    """
    if not names:
        return {}
    placeholders = ",".join("?" * len(names))
    rows = conn.execute(
        f"SELECT commander_name, rating FROM commander_ratings WHERE commander_name IN ({placeholders})",
        names,
    ).fetchall()
    return {r["commander_name"]: r["rating"] for r in rows}


def _bump_global_rating(conn: sqlite3.Connection, name: str, new_rating: float) -> None:
    """Persist a commander's post-pick rating into the all-time table.

    Called once per side of every pick (see record_pick), so a
    commander's all-time rating keeps compounding across every session
    it's ever appeared in, rather than resetting to DEFAULT_RATING each
    time a new session starts (create_session seeds each candidate's
    starting rating from here via _global_ratings).
    """
    conn.execute(
        """
        INSERT INTO commander_ratings (commander_name, rating, games_played, updated_at)
        VALUES (?, ?, 1, ?)
        ON CONFLICT(commander_name) DO UPDATE SET
            rating = excluded.rating,
            games_played = games_played + 1,
            updated_at = excluded.updated_at
        """,
        (name, new_rating, time.time()),
    )


def create_session(conn: sqlite3.Connection, candidates: list[Commander], description: str = "") -> str:
    if len(candidates) < 2:
        raise SessionError("Need at least 2 candidates to start a picker session.")
    session_id = uuid.uuid4().hex[:12]
    target_rounds = elo.target_round_count(len(candidates))
    conn.execute(
        "INSERT INTO sessions (id, created_at, description, status, target_rounds, rounds_completed) "
        "VALUES (?, ?, ?, 'active', ?, 0)",
        (session_id, time.time(), description, target_rounds),
    )
    global_ratings = _global_ratings(conn, [c.name for c in candidates])
    conn.executemany(
        "INSERT INTO candidates (session_id, commander_name, color_identity, num_decks, edhrec_url, themes, image_urls, rating) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                session_id,
                c.name,
                c.color_identity,
                c.num_decks,
                c.edhrec_url,
                ",".join(c.themes),
                json.dumps(list(c.image_urls)),
                global_ratings.get(c.name, elo.DEFAULT_RATING),
            )
            for c in candidates
        ],
    )
    conn.commit()
    return session_id


@dataclass
class SessionInfo:
    id: str
    description: str
    status: str
    target_rounds: int
    rounds_completed: int
    pool_size: int


def get_session(conn: sqlite3.Connection, session_id: str) -> SessionInfo:
    row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
    if row is None:
        raise SessionError(f"No session {session_id!r}")
    pool_size = conn.execute(
        "SELECT COUNT(*) c FROM candidates WHERE session_id = ?", (session_id,)
    ).fetchone()["c"]
    return SessionInfo(
        id=row["id"],
        description=row["description"],
        status=row["status"],
        target_rounds=row["target_rounds"],
        rounds_completed=row["rounds_completed"],
        pool_size=pool_size,
    )


def list_sessions(conn: sqlite3.Connection) -> list[SessionInfo]:
    rows = conn.execute("SELECT id FROM sessions ORDER BY created_at DESC").fetchall()
    return [get_session(conn, r["id"]) for r in rows]


def _ratings(conn: sqlite3.Connection, session_id: str) -> dict[str, float]:
    rows = conn.execute(
        "SELECT commander_name, rating FROM candidates WHERE session_id = ?", (session_id,)
    ).fetchall()
    return {r["commander_name"]: r["rating"] for r in rows}


def _already_paired(conn: sqlite3.Connection, session_id: str) -> set[frozenset]:
    rows = conn.execute(
        "SELECT winner, loser FROM comparisons WHERE session_id = ?", (session_id,)
    ).fetchall()
    return {frozenset((r["winner"], r["loser"])) for r in rows}


@dataclass
class CandidateDetail:
    name: str
    color_identity: str
    num_decks: int
    edhrec_url: str | None
    themes: tuple[str, ...]
    image_urls: tuple[str, ...]
    rating: float


def get_candidates(conn: sqlite3.Connection, session_id: str) -> dict[str, CandidateDetail]:
    """Full candidate details for a session, keyed by commander name -- used to
    render a pairing (name alone isn't enough for the UI to show colors/decks/themes)."""
    rows = conn.execute("SELECT * FROM candidates WHERE session_id = ?", (session_id,)).fetchall()
    return {
        r["commander_name"]: CandidateDetail(
            name=r["commander_name"],
            color_identity=r["color_identity"],
            num_decks=r["num_decks"],
            edhrec_url=r["edhrec_url"],
            themes=tuple(t for t in (r["themes"] or "").split(",") if t),
            image_urls=tuple(json.loads(r["image_urls"])) if r["image_urls"] else (),
            rating=r["rating"],
        )
        for r in rows
    }


def _maybe_auto_finish(conn: sqlite3.Connection, session_id: str) -> SessionInfo:
    """Finalize the session if it's reached target_rounds and hasn't been marked complete yet.

    target_rounds used to be purely a suggestion -- sessions stayed
    active indefinitely until the user explicitly finished, with no
    real signal in the web UI that the suggested count had passed
    (the CLI printed a one-time message; the web UI printed nothing at
    all). Confirmed with the user this was confusing rather than
    useful: they wanted a real stopping point, not an unbounded
    session with no visible end. Called from both `next_pairing` (so
    a session already sitting past its target -- e.g. one created
    before this existed -- self-heals the next time anything touches
    it, not just after one more pick) and `record_pick` (so it
    finalizes at the exact pick that reaches the threshold).
    """
    info = get_session(conn, session_id)
    if info.status == "active" and info.rounds_completed >= info.target_rounds:
        finish_session(conn, session_id)
        info = get_session(conn, session_id)
    return info


def next_pairing(conn: sqlite3.Connection, session_id: str, rng=None) -> tuple[str, str] | None:
    """The next pair to present, or None if the session isn't active."""
    info = _maybe_auto_finish(conn, session_id)
    if info.status != "active":
        return None
    ratings = _ratings(conn, session_id)
    already = _already_paired(conn, session_id)
    return elo.choose_pairing(list(ratings), ratings, info.rounds_completed, info.target_rounds, already, rng=rng)


def record_pick(conn: sqlite3.Connection, session_id: str, winner: str, loser: str) -> None:
    # Guards against a stale client (a duel screen left open past
    # auto-finish, e.g. in a second tab) still POSTing a pick after the
    # session has already concluded -- the round it's picking for
    # doesn't exist anymore.
    info = _maybe_auto_finish(conn, session_id)
    if info.status != "active":
        raise SessionError(f"Session {session_id!r} is {info.status}, not active -- can't record a pick.")

    ratings = _ratings(conn, session_id)
    if winner not in ratings or loser not in ratings:
        raise SessionError("winner/loser must both be candidates in this session")

    new_winner, new_loser = elo.update_ratings(ratings[winner], ratings[loser])
    conn.execute(
        "UPDATE candidates SET rating = ? WHERE session_id = ? AND commander_name = ?",
        (new_winner, session_id, winner),
    )
    conn.execute(
        "UPDATE candidates SET rating = ? WHERE session_id = ? AND commander_name = ?",
        (new_loser, session_id, loser),
    )
    # Every pick also feeds the cross-session all-time rating -- this is
    # what lets a commander's Elo keep compounding across every session
    # it's ever been in, instead of resetting to DEFAULT_RATING each time.
    _bump_global_rating(conn, winner, new_winner)
    _bump_global_rating(conn, loser, new_loser)

    info = get_session(conn, session_id)
    conn.execute(
        "INSERT INTO comparisons (session_id, round_num, winner, loser, created_at) VALUES (?, ?, ?, ?, ?)",
        (session_id, info.rounds_completed + 1, winner, loser, time.time()),
    )
    conn.execute("UPDATE sessions SET rounds_completed = rounds_completed + 1 WHERE id = ?", (session_id,))
    conn.commit()
    _maybe_auto_finish(conn, session_id)


def finish_session(conn: sqlite3.Connection, session_id: str) -> None:
    conn.execute("UPDATE sessions SET status = 'complete' WHERE id = ?", (session_id,))
    conn.commit()


@dataclass
class RankedCommander:
    name: str
    rating: float
    color_identity: str
    num_decks: int
    edhrec_url: str | None
    themes: tuple[str, ...]
    image_urls: tuple[str, ...]


def get_rankings(conn: sqlite3.Connection, session_id: str) -> list[RankedCommander]:
    rows = conn.execute(
        "SELECT commander_name, rating, color_identity, num_decks, edhrec_url, themes, image_urls FROM candidates "
        "WHERE session_id = ? ORDER BY rating DESC",
        (session_id,),
    ).fetchall()
    return [
        RankedCommander(
            name=r["commander_name"],
            rating=r["rating"],
            color_identity=r["color_identity"],
            num_decks=r["num_decks"],
            edhrec_url=r["edhrec_url"],
            themes=tuple(t for t in (r["themes"] or "").split(",") if t),
            image_urls=tuple(json.loads(r["image_urls"])) if r["image_urls"] else (),
        )
        for r in rows
    ]


@dataclass
class GlobalRanking:
    name: str
    rating: float
    games_played: int
    updated_at: float
    color_identity: str
    num_decks: int
    edhrec_url: str | None
    image_urls: tuple[str, ...]


def get_leaderboard(conn: sqlite3.Connection, limit: int | None = None) -> list[GlobalRanking]:
    """All-time ranking across every session ever played, highest rating first.

    Distinct from get_rankings(), which is scoped to a single session's
    pool -- this reads straight from `commander_ratings`, the
    cross-session table `_bump_global_rating` keeps updated on every
    pick and `_global_ratings` seeds new sessions from, so a
    commander's rating keeps compounding the more it's played rather
    than resetting each session.

    `commander_ratings` itself only has name/rating/games_played -- the
    display fields (color, deck count, art) are pulled from that
    commander's most recent `candidates` row across any session, since
    that's the same denormalized-at-session-creation data every other
    ranking view in this module already uses (there's no live
    dependency on `commanders.db` here, which is a separate file that
    gets fully rebuilt on every `update-data` run).
    """
    query = """
        SELECT
            cr.commander_name,
            cr.rating,
            cr.games_played,
            cr.updated_at,
            latest.color_identity,
            latest.num_decks,
            latest.edhrec_url,
            latest.image_urls
        FROM commander_ratings cr
        LEFT JOIN (
            SELECT commander_name, color_identity, num_decks, edhrec_url, image_urls,
                   ROW_NUMBER() OVER (PARTITION BY commander_name ORDER BY rowid DESC) AS rn
            FROM candidates
        ) latest ON latest.commander_name = cr.commander_name AND latest.rn = 1
        ORDER BY cr.rating DESC
    """
    if limit is not None:
        rows = conn.execute(query + " LIMIT ?", (limit,)).fetchall()
    else:
        rows = conn.execute(query).fetchall()
    return [
        GlobalRanking(
            name=r["commander_name"],
            rating=r["rating"],
            games_played=r["games_played"],
            updated_at=r["updated_at"],
            color_identity=r["color_identity"] or "",
            num_decks=r["num_decks"] or 0,
            edhrec_url=r["edhrec_url"],
            image_urls=tuple(json.loads(r["image_urls"])) if r["image_urls"] else (),
        )
        for r in rows
    ]
