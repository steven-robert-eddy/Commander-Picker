"""Persist picker sessions: candidate pools, ratings, comparison history.

Lives in a separate `data/sessions.db`, not `commanders.db` -- the
catalog DB is fully dropped and rebuilt on every `update-data` run
(see `db.py::build_database`), which would silently wipe any
in-progress or completed picker sessions if they shared a file.
"""

from __future__ import annotations

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
        """
    )
    conn.commit()


def connect(db_path: Path = SESSIONS_DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    _ensure_schema(conn)
    return conn


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
    conn.executemany(
        "INSERT INTO candidates (session_id, commander_name, color_identity, num_decks, edhrec_url, rating) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [
            (session_id, c.name, c.color_identity, c.num_decks, c.edhrec_url, elo.DEFAULT_RATING)
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


def next_pairing(conn: sqlite3.Connection, session_id: str, rng=None) -> tuple[str, str] | None:
    """The next pair to present, or None if the session isn't active."""
    info = get_session(conn, session_id)
    if info.status != "active":
        return None
    ratings = _ratings(conn, session_id)
    already = _already_paired(conn, session_id)
    return elo.choose_pairing(list(ratings), ratings, info.rounds_completed, info.target_rounds, already, rng=rng)


def record_pick(conn: sqlite3.Connection, session_id: str, winner: str, loser: str) -> None:
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

    info = get_session(conn, session_id)
    conn.execute(
        "INSERT INTO comparisons (session_id, round_num, winner, loser, created_at) VALUES (?, ?, ?, ?, ?)",
        (session_id, info.rounds_completed + 1, winner, loser, time.time()),
    )
    conn.execute("UPDATE sessions SET rounds_completed = rounds_completed + 1 WHERE id = ?", (session_id,))
    conn.commit()


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


def get_rankings(conn: sqlite3.Connection, session_id: str) -> list[RankedCommander]:
    rows = conn.execute(
        "SELECT commander_name, rating, color_identity, num_decks, edhrec_url FROM candidates "
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
        )
        for r in rows
    ]
