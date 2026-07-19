"""Persist picker sessions: candidate pools, ratings, comparison history.

Lives in a separate `data/sessions.db`, not `commanders.db` -- the
catalog DB is fully dropped and rebuilt on every `update-data` run
(see `db.py::build_database`), which would silently wipe any
in-progress or completed picker sessions if they shared a file.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from commander_picker import colors as color_slugs
from commander_picker import elo
from commander_picker.pool import Commander, _color_identity_matches

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
SESSIONS_DB_PATH = DATA_DIR / "sessions.db"


class SessionError(RuntimeError):
    pass


class _TursoRow(tuple):
    """`row["col"]` access on top of libsql's plain-tuple rows.

    The `libsql` package (used to reach a remote Turso database -- see
    connect() below) doesn't implement sqlite3's `row_factory`, so every
    `row["commander_name"]`-style access elsewhere in this module would
    break against it otherwise. Only used for the Turso connection path;
    plain local sqlite3 keeps using the stdlib's own `sqlite3.Row`.
    """

    def __new__(cls, values, columns):
        obj = super().__new__(cls, values)
        obj._columns = columns
        return obj

    def __getitem__(self, key):
        if isinstance(key, str):
            return tuple.__getitem__(self, self._columns.index(key))
        return tuple.__getitem__(self, key)

    def keys(self):
        return self._columns


class _TursoCursor:
    def __init__(self, cursor):
        self._cursor = cursor

    def _columns(self) -> tuple:
        return tuple(d[0] for d in self._cursor.description) if self._cursor.description else ()

    def execute(self, sql, params=()):
        self._cursor.execute(sql, params)
        return self

    def executemany(self, sql, seq_of_params):
        self._cursor.executemany(sql, seq_of_params)
        return self

    def fetchone(self):
        row = self._cursor.fetchone()
        return _TursoRow(row, self._columns()) if row is not None else None

    def fetchall(self):
        columns = self._columns()
        return [_TursoRow(row, columns) for row in self._cursor.fetchall()]

    def __iter__(self):
        return iter(self.fetchall())

    @property
    def lastrowid(self):
        return self._cursor.lastrowid


class _TursoConnection:
    """Wraps a `libsql` remote connection so the rest of this module can keep
    using the same sqlite3-style calling convention (`conn.execute(...)`
    returning something with dict-style `fetchall()`/`fetchone()` rows,
    direct cursor iteration) it already used for local sqlite3.
    """

    def __init__(self, conn):
        self._conn = conn

    def execute(self, sql, params=()):
        return _TursoCursor(self._conn.cursor()).execute(sql, params)

    def executemany(self, sql, seq_of_params):
        return _TursoCursor(self._conn.cursor()).executemany(sql, seq_of_params)

    def executescript(self, script):
        self._conn.executescript(script)

    def commit(self):
        self._conn.commit()

    def close(self):
        self._conn.close()


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            created_at REAL NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL,
            target_rounds INTEGER NOT NULL,
            rounds_completed INTEGER NOT NULL DEFAULT 0,
            mode TEXT NOT NULL DEFAULT 'duel'
        );
        CREATE TABLE IF NOT EXISTS bracket_matches (
            session_id TEXT NOT NULL REFERENCES sessions(id),
            round_num INTEGER NOT NULL,
            slot INTEGER NOT NULL,
            seed_a TEXT,
            seed_b TEXT,
            winner TEXT,
            PRIMARY KEY (session_id, round_num, slot)
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
            rank INTEGER,
            mana_cost TEXT,
            type_line TEXT,
            power_level INTEGER,
            PRIMARY KEY (session_id, commander_name)
        );
        CREATE TABLE IF NOT EXISTS comparisons (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL REFERENCES sessions(id),
            round_num INTEGER NOT NULL,
            winner TEXT NOT NULL,
            loser TEXT NOT NULL,
            created_at REAL NOT NULL,
            winner_rating_before REAL,
            loser_rating_before REAL,
            winner_global_rating_before REAL,
            loser_global_rating_before REAL
        );
        CREATE TABLE IF NOT EXISTS commander_ratings (
            commander_name TEXT PRIMARY KEY,
            rating REAL NOT NULL,
            games_played INTEGER NOT NULL DEFAULT 0,
            updated_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS challenge_tracker (
            slug TEXT PRIMARY KEY,
            status TEXT NOT NULL DEFAULT 'not_started',
            notes TEXT,
            updated_at REAL
        );
        CREATE TABLE IF NOT EXISTS challenge_commanders (
            slug TEXT NOT NULL,
            commander_name TEXT NOT NULL,
            is_chosen INTEGER NOT NULL DEFAULT 0,
            added_at REAL,
            PRIMARY KEY (slug, commander_name)
        );
        """
    )
    # Migration for sessions.db files created before these columns
    # existed (CREATE TABLE IF NOT EXISTS doesn't add columns to an
    # already-existing table).
    existing_session_columns = {row["name"] for row in conn.execute("PRAGMA table_info(sessions)")}
    if "mode" not in existing_session_columns:
        conn.execute("ALTER TABLE sessions ADD COLUMN mode TEXT NOT NULL DEFAULT 'duel'")

    # Undo needs to know each pick's pre-pick state to revert exactly --
    # rows from before this existed simply have NULL here, and
    # undo_last_pick refuses to undo those rather than guessing.
    existing_comparison_columns = {row["name"] for row in conn.execute("PRAGMA table_info(comparisons)")}
    for column in (
        "winner_rating_before",
        "loser_rating_before",
        "winner_global_rating_before",
        "loser_global_rating_before",
    ):
        if column not in existing_comparison_columns:
            conn.execute(f"ALTER TABLE comparisons ADD COLUMN {column} REAL")

    existing_columns = {row["name"] for row in conn.execute("PRAGMA table_info(candidates)")}
    if "themes" not in existing_columns:
        conn.execute("ALTER TABLE candidates ADD COLUMN themes TEXT NOT NULL DEFAULT ''")
    if "rank" not in existing_columns:
        conn.execute("ALTER TABLE candidates ADD COLUMN rank INTEGER")
    if "mana_cost" not in existing_columns:
        conn.execute("ALTER TABLE candidates ADD COLUMN mana_cost TEXT")
    if "type_line" not in existing_columns:
        conn.execute("ALTER TABLE candidates ADD COLUMN type_line TEXT")
    if "power_level" not in existing_columns:
        conn.execute("ALTER TABLE candidates ADD COLUMN power_level INTEGER")
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
    # An explicit db_path (tests, or any future caller that wants a specific
    # local file) always wins and stays plain sqlite3 -- Turso auto-detection
    # only kicks in for the zero-arg call cli.py/web/app.py actually use in
    # production, so a stray TURSO_DATABASE_URL in someone's shell can't
    # silently redirect a test run at the real remote database.
    if db_path is None:
        turso_url = os.environ.get("TURSO_DATABASE_URL")
        if turso_url:
            import libsql

            conn = _TursoConnection(libsql.connect(database=turso_url, auth_token=os.environ.get("TURSO_AUTH_TOKEN")))
            _ensure_schema(conn)
            return conn
        db_path = SESSIONS_DB_PATH

    # See db.py::connect for why this can't default to `= SESSIONS_DB_PATH`
    # directly -- that binds at def-time and breaks monkeypatching.
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


def create_session(
    conn: sqlite3.Connection,
    candidates: list[Commander],
    description: str = "",
    mode: str = "duel",
) -> str:
    if len(candidates) < 2:
        raise SessionError("Need at least 2 candidates to start a picker session.")
    if mode == "bracket" and not elo.is_valid_bracket_size(len(candidates)):
        raise SessionError(
            f"Bracket mode needs a candidate count that's a power of two (4, 8, 16, ...) -- got {len(candidates)}."
        )

    session_id = uuid.uuid4().hex[:12]
    global_ratings = _global_ratings(conn, [c.name for c in candidates])
    target_rounds = (
        elo.bracket_round_count(len(candidates)) if mode == "bracket" else elo.target_round_count(len(candidates))
    )
    conn.execute(
        "INSERT INTO sessions (id, created_at, description, status, target_rounds, rounds_completed, mode) "
        "VALUES (?, ?, ?, 'active', ?, 0, ?)",
        (session_id, time.time(), description, target_rounds, mode),
    )
    conn.executemany(
        "INSERT INTO candidates "
        "(session_id, commander_name, color_identity, num_decks, edhrec_url, themes, image_urls, rating, rank, mana_cost, type_line, power_level) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
                c.rank,
                c.mana_cost,
                c.type_line,
                c.power_level,
            )
            for c in candidates
        ],
    )

    if mode == "bracket":
        _create_bracket(conn, session_id, candidates, global_ratings, target_rounds)

    conn.commit()
    return session_id


def _create_bracket(
    conn: sqlite3.Connection,
    session_id: str,
    candidates: list[Commander],
    global_ratings: dict[str, float],
    round_count: int,
) -> None:
    """Populate `bracket_matches` for every round upfront.

    Round 1 is fully seeded (best-to-worst by current all-time rating,
    placed via elo.bracket_seed_order so top seeds can't meet early).
    Later rounds' slots are inserted with seed_a/seed_b left NULL, so the
    full bracket shape (including "TBD" placeholders) is known immediately
    for rendering, and record_bracket_pick just fills them in as winners
    are decided.
    """
    n = len(candidates)
    seeded = sorted(candidates, key=lambda c: global_ratings.get(c.name, elo.DEFAULT_RATING), reverse=True)
    order = elo.bracket_seed_order(n)  # 1-indexed seed positions, slot order
    slot_names = [seeded[seed - 1].name for seed in order]

    rows = []
    round1_slots = n // 2
    for slot in range(round1_slots):
        rows.append((session_id, 1, slot, slot_names[2 * slot], slot_names[2 * slot + 1], None))
    for round_num in range(2, round_count + 1):
        for slot in range(n // (2**round_num)):
            rows.append((session_id, round_num, slot, None, None, None))

    conn.executemany(
        "INSERT INTO bracket_matches (session_id, round_num, slot, seed_a, seed_b, winner) VALUES (?, ?, ?, ?, ?, ?)",
        rows,
    )


@dataclass
class SessionInfo:
    id: str
    description: str
    status: str
    target_rounds: int
    rounds_completed: int
    pool_size: int
    mode: str


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
        mode=row["mode"],
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
    rank: int | None = None
    mana_cost: str | None = None
    type_line: str | None = None
    power_level: int | None = None


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
            rank=r["rank"],
            mana_cost=r["mana_cost"],
            type_line=r["type_line"],
            power_level=r["power_level"],
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

    # Captured before either rating changes -- undo_last_pick restores
    # exactly these values rather than trying to invert the Elo formula
    # (which isn't reliably reversible without them).
    winner_rating_before = ratings[winner]
    loser_rating_before = ratings[loser]
    global_before = _global_ratings(conn, [winner, loser])
    winner_global_rating_before = global_before.get(winner)  # None means no prior row (first-ever game)
    loser_global_rating_before = global_before.get(loser)

    new_winner, new_loser = elo.update_ratings(winner_rating_before, loser_rating_before)
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
        "INSERT INTO comparisons "
        "(session_id, round_num, winner, loser, created_at, "
        "winner_rating_before, loser_rating_before, winner_global_rating_before, loser_global_rating_before) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            session_id,
            info.rounds_completed + 1,
            winner,
            loser,
            time.time(),
            winner_rating_before,
            loser_rating_before,
            winner_global_rating_before,
            loser_global_rating_before,
        ),
    )
    conn.execute("UPDATE sessions SET rounds_completed = rounds_completed + 1 WHERE id = ?", (session_id,))
    conn.commit()
    _maybe_auto_finish(conn, session_id)


def undo_last_pick(conn: sqlite3.Connection, session_id: str) -> None:
    """Revert the most recently recorded pick in a duel-mode session.

    Restores both candidates' session-local ratings and the all-time
    `commander_ratings` table to exactly their pre-pick values (captured
    by record_pick), deletes the `comparisons` row, and decrements
    `rounds_completed` -- un-finishing the session if that pick was what
    completed it.

    Bracket mode isn't supported here: a bracket pick also propagates its
    winner into the next round's slot, and safely undoing that would need
    to confirm nothing downstream has consumed that winner yet -- a real
    feature on its own, deferred (see PLAN.md).

    Only ever reverses the single most recent pick; call again to step
    back further (like a normal undo stack). Assumes single-sequential
    play, same as the rest of this module -- if the same commander's
    all-time rating was also touched by a *different* concurrent session
    in between, this can't detect that and will still restore the
    pre-pick snapshot, potentially clobbering that other session's update.
    """
    info = get_session(conn, session_id)
    if info.mode != "duel":
        raise SessionError("Undo isn't available for bracket sessions yet.")

    row = conn.execute(
        "SELECT * FROM comparisons WHERE session_id = ? ORDER BY id DESC LIMIT 1",
        (session_id,),
    ).fetchone()
    if row is None:
        raise SessionError("No picks to undo.")
    if row["winner_rating_before"] is None:
        raise SessionError("Can't undo this pick -- it predates undo support.")

    winner, loser = row["winner"], row["loser"]
    conn.execute(
        "UPDATE candidates SET rating = ? WHERE session_id = ? AND commander_name = ?",
        (row["winner_rating_before"], session_id, winner),
    )
    conn.execute(
        "UPDATE candidates SET rating = ? WHERE session_id = ? AND commander_name = ?",
        (row["loser_rating_before"], session_id, loser),
    )

    for name, before in (
        (winner, row["winner_global_rating_before"]),
        (loser, row["loser_global_rating_before"]),
    ):
        if before is None:
            # This pick created the commander's first-ever all-time
            # rating row -- undo removes it entirely, same as if it had
            # never been played.
            conn.execute("DELETE FROM commander_ratings WHERE commander_name = ?", (name,))
        else:
            conn.execute(
                "UPDATE commander_ratings SET rating = ?, games_played = games_played - 1 WHERE commander_name = ?",
                (before, name),
            )

    conn.execute("DELETE FROM comparisons WHERE id = ?", (row["id"],))
    conn.execute("UPDATE sessions SET rounds_completed = rounds_completed - 1 WHERE id = ?", (session_id,))
    if info.status == "complete":
        # Undoing the pick that finished the session un-finishes it --
        # rounds_completed just dropped back below (or to) target_rounds.
        conn.execute("UPDATE sessions SET status = 'active' WHERE id = ?", (session_id,))
    conn.commit()


def finish_session(conn: sqlite3.Connection, session_id: str) -> None:
    conn.execute("UPDATE sessions SET status = 'complete' WHERE id = ?", (session_id,))
    conn.commit()


def next_bracket_match(conn: sqlite3.Connection, session_id: str) -> tuple[int, int, str, str] | None:
    """The next ready bracket match: (round_num, slot, seed_a, seed_b), or
    None if the session isn't active or no match is ready yet (waiting on
    an earlier match in a different branch of the tree to resolve first)."""
    info = get_session(conn, session_id)
    if info.status != "active":
        return None
    row = conn.execute(
        "SELECT round_num, slot, seed_a, seed_b FROM bracket_matches "
        "WHERE session_id = ? AND winner IS NULL AND seed_a IS NOT NULL AND seed_b IS NOT NULL "
        "ORDER BY round_num, slot LIMIT 1",
        (session_id,),
    ).fetchone()
    if row is None:
        return None
    return (row["round_num"], row["slot"], row["seed_a"], row["seed_b"])


def record_bracket_pick(conn: sqlite3.Connection, session_id: str, winner: str, loser: str) -> None:
    """Record the outcome of a bracket match and advance the bracket.

    Looks up which ready match `winner`/`loser` belong to itself (same
    minimal winner/loser contract as record_pick -- no round/slot
    bookkeeping pushed onto callers). Applies the same Elo update
    machinery as record_pick, but with elo.BRACKET_K_FACTOR instead of
    the duel K_FACTOR (see elo.py for why bracket matches use a gentler
    K). Propagates the winner into next round's slot, and marks the
    session complete once the final's winner is set.
    """
    info = get_session(conn, session_id)
    if info.status != "active":
        raise SessionError(f"Session {session_id!r} is {info.status}, not active -- can't record a pick.")

    match = conn.execute(
        "SELECT round_num, slot FROM bracket_matches "
        "WHERE session_id = ? AND winner IS NULL AND seed_a IS NOT NULL AND seed_b IS NOT NULL "
        "AND ((seed_a = ? AND seed_b = ?) OR (seed_a = ? AND seed_b = ?)) "
        "ORDER BY round_num, slot LIMIT 1",
        (session_id, winner, loser, loser, winner),
    ).fetchone()
    if match is None:
        raise SessionError("winner/loser don't match any ready bracket match in this session")
    round_num, slot = match["round_num"], match["slot"]

    ratings = _ratings(conn, session_id)
    new_winner, new_loser = elo.update_ratings(ratings[winner], ratings[loser], k=elo.BRACKET_K_FACTOR)
    conn.execute(
        "UPDATE candidates SET rating = ? WHERE session_id = ? AND commander_name = ?",
        (new_winner, session_id, winner),
    )
    conn.execute(
        "UPDATE candidates SET rating = ? WHERE session_id = ? AND commander_name = ?",
        (new_loser, session_id, loser),
    )
    # Same cross-session leaderboard feed as record_pick, just via the
    # dampened bracket K-factor above.
    _bump_global_rating(conn, winner, new_winner)
    _bump_global_rating(conn, loser, new_loser)

    conn.execute(
        "UPDATE bracket_matches SET winner = ? WHERE session_id = ? AND round_num = ? AND slot = ?",
        (winner, session_id, round_num, slot),
    )
    conn.execute(
        "INSERT INTO comparisons (session_id, round_num, winner, loser, created_at) VALUES (?, ?, ?, ?, ?)",
        (session_id, round_num, winner, loser, time.time()),
    )

    next_round = round_num + 1
    if next_round <= info.target_rounds:
        next_slot = slot // 2
        column = "seed_a" if slot % 2 == 0 else "seed_b"
        conn.execute(
            f"UPDATE bracket_matches SET {column} = ? WHERE session_id = ? AND round_num = ? AND slot = ?",
            (winner, session_id, next_round, next_slot),
        )

    remaining_in_round = conn.execute(
        "SELECT COUNT(*) c FROM bracket_matches WHERE session_id = ? AND round_num = ? AND winner IS NULL",
        (session_id, round_num),
    ).fetchone()["c"]
    if remaining_in_round == 0:
        conn.execute("UPDATE sessions SET rounds_completed = rounds_completed + 1 WHERE id = ?", (session_id,))
        if round_num == info.target_rounds:
            conn.execute("UPDATE sessions SET status = 'complete' WHERE id = ?", (session_id,))

    conn.commit()


@dataclass
class BracketMatch:
    round_num: int
    slot: int
    seed_a: str | None
    seed_b: str | None
    winner: str | None


@dataclass
class BracketState:
    rounds: list[list[BracketMatch]]  # rounds[0] is round 1
    champion: str | None


def get_bracket(conn: sqlite3.Connection, session_id: str) -> BracketState:
    """Full bracket tree for a session -- the single source of truth for
    both the in-progress compact tree view and the final results tree."""
    get_session(conn, session_id)  # raises SessionError if the session doesn't exist
    rows = conn.execute(
        "SELECT round_num, slot, seed_a, seed_b, winner FROM bracket_matches "
        "WHERE session_id = ? ORDER BY round_num, slot",
        (session_id,),
    ).fetchall()
    by_round: dict[int, list[BracketMatch]] = {}
    for r in rows:
        by_round.setdefault(r["round_num"], []).append(
            BracketMatch(
                round_num=r["round_num"],
                slot=r["slot"],
                seed_a=r["seed_a"],
                seed_b=r["seed_b"],
                winner=r["winner"],
            )
        )
    rounds = [by_round[n] for n in sorted(by_round)]
    champion = None
    if rounds and len(rounds[-1]) == 1:
        champion = rounds[-1][0].winner
    return BracketState(rounds=rounds, champion=champion)


@dataclass
class RankedCommander:
    name: str
    rating: float
    color_identity: str
    num_decks: int
    edhrec_url: str | None
    themes: tuple[str, ...]
    image_urls: tuple[str, ...]
    power_level: int | None = None


def get_rankings(conn: sqlite3.Connection, session_id: str) -> list[RankedCommander]:
    rows = conn.execute(
        "SELECT commander_name, rating, color_identity, num_decks, edhrec_url, themes, image_urls, power_level "
        "FROM candidates WHERE session_id = ? ORDER BY rating DESC",
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
            power_level=r["power_level"],
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


def get_leaderboard(
    conn: sqlite3.Connection,
    limit: int | None = None,
    colors: str | None = None,
    color_mode: str = "subset",
) -> list[GlobalRanking]:
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

    `colors`/`color_mode` reuse `pool._color_identity_matches` --
    exact same subset-vs-exact/colorless-as-"C" semantics as the duel
    pool filter, applied here in Python after the query (color
    identity isn't a SQL column, it comes from the joined snapshot).
    `colors=None` means no filter at all, same convention as
    `pool.PoolFilters.colors`. Filtering happens *before* `limit` is
    applied -- "top 25" means the top 25 matching the color filter,
    not the top 25 overall further trimmed by color.
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
    rows = conn.execute(query).fetchall()
    ranked = [
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
    if colors:
        allowed = set(colors.upper())
        ranked = [r for r in ranked if _color_identity_matches(r.color_identity, allowed, color_mode)]
    if limit is not None:
        ranked = ranked[:limit]
    return ranked


def reset_leaderboard(conn: sqlite3.Connection) -> None:
    """Permanently erase every commander's all-time rating/games_played.

    Only touches `commander_ratings` -- past sessions and their own
    results (`sessions`/`candidates`/`comparisons`) are untouched, so
    session history/resume/results still work exactly as before. A
    commander picked again after this starts fresh from
    `elo.DEFAULT_RATING`, same as one with no history at all.
    """
    conn.execute("DELETE FROM commander_ratings")
    conn.commit()


# ---- 32-deck challenge tracker ----
#
# A personal planning tool riding on data this app already produces --
# not a rating/Elo concept. Tracks one entry per color-identity combo
# (colors.all_slugs(), colorless through five-color) with a status and
# a short shortlist of candidate commanders, at most one marked chosen.
# Entries aren't pre-seeded: get_challenge_tracker synthesizes all 32 at
# read time by overlaying whatever's in challenge_tracker/
# challenge_commanders onto colors.all_slugs(), so a combo with no rows
# yet just reads as not_started/empty.

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
