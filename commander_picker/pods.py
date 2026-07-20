"""Pod tracker: multiplayer Elo for real EDH games, players, and decks.

Extends the same Elo idea the picker uses to actual games played at
the table -- a genuine multiplayer generalization
(elo.multiplayer_expected_scores/update_multiplayer_ratings), not
naive pairwise decomposition, applied identically to two separate
rated entities: players (freeform names, a row created implicitly the
first time a name is used, same posture as commander_ratings) and
decks (a separate registry -- registered once via register_deck,
reused across many games, never hard-deleted, only archived).

Shares sessions.db with sessions.py (picker sessions) and challenge.py
(32-deck challenge tracker) -- see store.py for the connection/schema/
SessionError this module builds on.
"""

from __future__ import annotations

import sqlite3
import time
import uuid
from dataclasses import dataclass

from commander_picker import elo
from commander_picker.store import SessionError


@dataclass
class Deck:
    id: str
    name: str
    commander_name: str | None
    color_identity: str | None
    owner_name: str | None
    rating: float
    games_played: int
    archived: bool
    created_at: float
    updated_at: float


@dataclass
class PlayerRanking:
    name: str
    rating: float
    games_played: int
    updated_at: float


@dataclass
class PodParticipant:
    player_name: str
    deck_id: str
    deck_name: str
    is_winner: bool
    player_rating_before: float
    player_rating_after: float
    deck_rating_before: float
    deck_rating_after: float


@dataclass
class PodGame:
    id: str
    created_at: float
    notes: str
    participants: list[PodParticipant]


def _row_to_deck(row) -> Deck:
    return Deck(
        id=row["id"],
        name=row["name"],
        commander_name=row["commander_name"],
        color_identity=row["color_identity"],
        owner_name=row["owner_name"],
        rating=row["rating"],
        games_played=row["games_played"],
        archived=bool(row["archived"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def register_deck(
    conn: sqlite3.Connection,
    name: str,
    commander_name: str | None = None,
    color_identity: str | None = None,
    owner_name: str | None = None,
) -> Deck:
    """Add a deck to the persistent registry, starting at elo.DEFAULT_RATING.

    `color_identity` is taken as given (same posture as the challenge
    tracker's "auto" endpoint, which trusts the color_identity a search
    result already carries) rather than looked up here -- sessions.py
    only ever holds a sessions.db connection, never the catalog DB, so
    any catalog lookup has to happen at the web/app.py layer before
    calling in, using pool_module.commander_images_by_name/
    commanders_by_names the same way the challenge tracker's read-side
    enrichment already does.
    """
    if not name.strip():
        raise SessionError("Deck name can't be empty.")
    deck_id = uuid.uuid4().hex[:12]
    now = time.time()
    conn.execute(
        "INSERT INTO decks (id, name, commander_name, color_identity, owner_name, rating, games_played, "
        "archived, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, 0, 0, ?, ?)",
        (deck_id, name.strip(), commander_name, color_identity, owner_name, elo.DEFAULT_RATING, now, now),
    )
    conn.commit()
    return get_deck(conn, deck_id)


def get_deck(conn: sqlite3.Connection, deck_id: str) -> Deck:
    row = conn.execute("SELECT * FROM decks WHERE id = ?", (deck_id,)).fetchone()
    if row is None:
        raise SessionError(f"No deck {deck_id!r}")
    return _row_to_deck(row)


def list_decks(conn: sqlite3.Connection) -> list[Deck]:
    """Every registered deck, active and archived alike, highest rating
    first -- callers section by the `archived` flag themselves (same
    posture as get_challenge_tracker always returning all 32 combos
    regardless of status, rather than the DB layer pre-filtering).
    """
    rows = conn.execute("SELECT * FROM decks ORDER BY rating DESC").fetchall()
    return [_row_to_deck(r) for r in rows]


def _set_deck_archived(conn: sqlite3.Connection, deck_id: str, archived: bool) -> Deck:
    get_deck(conn, deck_id)  # raises SessionError if unknown
    conn.execute(
        "UPDATE decks SET archived = ?, updated_at = ? WHERE id = ?", (int(archived), time.time(), deck_id)
    )
    conn.commit()
    return get_deck(conn, deck_id)


def archive_deck(conn: sqlite3.Connection, deck_id: str) -> Deck:
    """Hide a deck from active use without losing it or its game
    history -- decks are never hard-deleted (see module docstring
    above), only archived/unarchived.
    """
    return _set_deck_archived(conn, deck_id, True)


def unarchive_deck(conn: sqlite3.Connection, deck_id: str) -> Deck:
    return _set_deck_archived(conn, deck_id, False)


def list_players(conn: sqlite3.Connection) -> list[PlayerRanking]:
    rows = conn.execute("SELECT * FROM players ORDER BY rating DESC").fetchall()
    return [
        PlayerRanking(name=r["name"], rating=r["rating"], games_played=r["games_played"], updated_at=r["updated_at"])
        for r in rows
    ]


def _get_or_seed_player_rating(conn: sqlite3.Connection, name: str) -> float:
    row = conn.execute("SELECT rating FROM players WHERE name = ?", (name,)).fetchone()
    return row["rating"] if row is not None else elo.DEFAULT_RATING


def log_pod_game(
    conn: sqlite3.Connection,
    participants: list[tuple[str, str, bool]],
    notes: str = "",
) -> PodGame:
    """Record a completed pod game and update both player and deck ratings.

    `participants` is a list of (player_name, deck_id, is_winner)
    tuples. Requires at least 2 participants and exactly one winner --
    EDH pods are almost always tracked casually as "who won," not a
    full 1st/2nd/3rd/4th placement, so this mirrors that rather than
    modeling ranked placements. A player name not seen before gets a
    `players` row created on the spot (elo.DEFAULT_RATING), same as a
    commander's first-ever pick seeds its commander_ratings row --
    decks must already exist (register_deck first), since they're a
    separate pre-registered catalog, not implicitly created.
    """
    if len(participants) < 2:
        raise SessionError("Need at least 2 participants to log a pod game.")
    winners = [p for p in participants if p[2]]
    if len(winners) != 1:
        raise SessionError(f"Exactly one participant must be marked as the winner (got {len(winners)}).")
    player_names = [p[0] for p in participants]
    if len(set(player_names)) != len(player_names):
        raise SessionError("Each player can only appear once per game.")
    deck_ids = [p[1] for p in participants]
    if len(set(deck_ids)) != len(deck_ids):
        raise SessionError("Each deck can only appear once per game.")

    decks_by_id: dict[str, Deck] = {}
    for deck_id in deck_ids:
        try:
            decks_by_id[deck_id] = get_deck(conn, deck_id)
        except SessionError as exc:
            raise SessionError(f"Unknown deck {deck_id!r} -- register it first.") from exc

    winner_index = next(i for i, p in enumerate(participants) if p[2])
    player_ratings_before = [_get_or_seed_player_rating(conn, p[0]) for p in participants]
    deck_ratings_before = [decks_by_id[p[1]].rating for p in participants]
    player_ratings_after = elo.update_multiplayer_ratings(player_ratings_before, winner_index)
    deck_ratings_after = elo.update_multiplayer_ratings(deck_ratings_before, winner_index)

    game_id = uuid.uuid4().hex[:12]
    now = time.time()
    conn.execute("INSERT INTO pod_games (id, created_at, notes) VALUES (?, ?, ?)", (game_id, now, notes))

    result_participants = []
    for i, (player_name, deck_id, is_winner) in enumerate(participants):
        conn.execute(
            """
            INSERT INTO players (name, rating, games_played, updated_at)
            VALUES (?, ?, 1, ?)
            ON CONFLICT(name) DO UPDATE SET
                rating = excluded.rating,
                games_played = games_played + 1,
                updated_at = excluded.updated_at
            """,
            (player_name, player_ratings_after[i], now),
        )
        conn.execute(
            "UPDATE decks SET rating = ?, games_played = games_played + 1, updated_at = ? WHERE id = ?",
            (deck_ratings_after[i], now, deck_id),
        )
        conn.execute(
            "INSERT INTO pod_game_participants (game_id, player_name, deck_id, is_winner, "
            "player_rating_before, player_rating_after, deck_rating_before, deck_rating_after) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                game_id,
                player_name,
                deck_id,
                int(is_winner),
                player_ratings_before[i],
                player_ratings_after[i],
                deck_ratings_before[i],
                deck_ratings_after[i],
            ),
        )
        result_participants.append(
            PodParticipant(
                player_name=player_name,
                deck_id=deck_id,
                deck_name=decks_by_id[deck_id].name,
                is_winner=is_winner,
                player_rating_before=player_ratings_before[i],
                player_rating_after=player_ratings_after[i],
                deck_rating_before=deck_ratings_before[i],
                deck_rating_after=deck_ratings_after[i],
            )
        )

    conn.commit()
    return PodGame(id=game_id, created_at=now, notes=notes, participants=result_participants)


def _pod_game_participants(conn: sqlite3.Connection, game_id: str) -> list[PodParticipant]:
    rows = conn.execute(
        "SELECT pgp.*, d.name AS deck_name FROM pod_game_participants pgp "
        "JOIN decks d ON d.id = pgp.deck_id WHERE pgp.game_id = ?",
        (game_id,),
    ).fetchall()
    return [
        PodParticipant(
            player_name=r["player_name"],
            deck_id=r["deck_id"],
            deck_name=r["deck_name"],
            is_winner=bool(r["is_winner"]),
            player_rating_before=r["player_rating_before"],
            player_rating_after=r["player_rating_after"],
            deck_rating_before=r["deck_rating_before"],
            deck_rating_after=r["deck_rating_after"],
        )
        for r in rows
    ]


def list_pod_games(conn: sqlite3.Connection, limit: int | None = None) -> list[PodGame]:
    query = "SELECT * FROM pod_games ORDER BY created_at DESC"
    if limit is not None:
        query += f" LIMIT {int(limit)}"
    rows = conn.execute(query).fetchall()
    return [
        PodGame(id=r["id"], created_at=r["created_at"], notes=r["notes"], participants=_pod_game_participants(conn, r["id"]))
        for r in rows
    ]


def delete_last_pod_game(conn: sqlite3.Connection) -> None:
    """Undo the single most-recently-logged pod game, reverting every
    participant's player/deck rating to its pre-game snapshot.

    Mirrors undo_last_pick's "only the most recent step" precedent --
    deleting an arbitrary earlier game would need to replay every game
    after it to stay consistent, which is a real feature on its own
    (deferred, see PLAN.md).

    Asymmetric on purpose: if this was a player's first-ever game,
    their `players` row is deleted entirely (they were created
    implicitly by this same game, same as undo_last_pick removing a
    commander's first-ever commander_ratings row). A deck's row is
    NEVER deleted here -- decks are pre-registered independently of any
    game via register_deck, so they always survive an undo; only their
    rating/games_played reverts.
    """
    game_row = conn.execute("SELECT * FROM pod_games ORDER BY created_at DESC LIMIT 1").fetchone()
    if game_row is None:
        raise SessionError("No pod games to delete.")
    game_id = game_row["id"]
    participants = _pod_game_participants(conn, game_id)

    for p in participants:
        player_row = conn.execute(
            "SELECT games_played FROM players WHERE name = ?", (p.player_name,)
        ).fetchone()
        if player_row is not None and player_row["games_played"] <= 1:
            # This game was that player's only one -- it created their
            # row, so undoing it removes the row entirely rather than
            # leaving a games_played=0 row with a meaningless rating.
            conn.execute("DELETE FROM players WHERE name = ?", (p.player_name,))
        else:
            conn.execute(
                "UPDATE players SET rating = ?, games_played = games_played - 1 WHERE name = ?",
                (p.player_rating_before, p.player_name),
            )
        conn.execute(
            "UPDATE decks SET rating = ?, games_played = games_played - 1 WHERE id = ?",
            (p.deck_rating_before, p.deck_id),
        )

    conn.execute("DELETE FROM pod_game_participants WHERE game_id = ?", (game_id,))
    conn.execute("DELETE FROM pod_games WHERE id = ?", (game_id,))
    conn.commit()
