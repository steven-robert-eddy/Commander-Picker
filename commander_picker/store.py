"""Shared sessions.db infrastructure: connection, schema, the shared
error type -- everything genuinely common to every feature built on
top of picker sessions (sessions.py), the 32-deck challenge tracker
(challenge.py), and the pod tracker (pods.py).

Lives in a separate `data/sessions.db`, not `commanders.db` -- the
catalog DB is fully dropped and rebuilt on every `update-data` run
(see `db.py::build_database`), which would silently wipe any
in-progress or completed picker sessions if they shared a file.

`_ensure_schema` intentionally stays one flat function covering all
three feature areas' tables/migrations, rather than each feature
module owning its own schema hook -- this module can't import
sessions.py/challenge.py/pods.py to call per-module schema functions
without those modules importing `connect`/`SessionError` back from
here first (circular). A registration pattern would dodge that, but
it's real added machinery this single-maintainer, no-build-step
project doesn't need for three known, stable concerns. Don't "fix"
this layering without a real reason to.
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

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
        CREATE TABLE IF NOT EXISTS players (
            name TEXT PRIMARY KEY,
            rating REAL NOT NULL,
            games_played INTEGER NOT NULL DEFAULT 0,
            updated_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS decks (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            commander_name TEXT,
            color_identity TEXT,
            owner_name TEXT,
            rating REAL NOT NULL,
            games_played INTEGER NOT NULL DEFAULT 0,
            archived INTEGER NOT NULL DEFAULT 0,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS pod_games (
            id TEXT PRIMARY KEY,
            created_at REAL NOT NULL,
            notes TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS pod_game_participants (
            game_id TEXT NOT NULL REFERENCES pod_games(id),
            player_name TEXT NOT NULL,
            deck_id TEXT NOT NULL REFERENCES decks(id),
            is_winner INTEGER NOT NULL DEFAULT 0,
            player_rating_before REAL NOT NULL,
            player_rating_after REAL NOT NULL,
            deck_rating_before REAL NOT NULL,
            deck_rating_after REAL NOT NULL,
            PRIMARY KEY (game_id, player_name)
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
