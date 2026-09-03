"""Guess-the-Commander mini-game: pick a random popular commander, show
its mana cost/type line up front, then reveal its oracle text one line
at a time as the player's guesses run out, capped at MAX_ATTEMPTS total
guesses.

Shares sessions.db with sessions.py/challenge.py/pods.py -- see
store.py for the connection/schema this module builds on. Picking the
commander itself reads from the catalog DB (commanders.db, via
pool.py) instead -- a game's own row snapshots everything needed to
finish it (name, art, oracle text, ...) at creation time, same posture
as sessions.py's `candidates` table, so a later `update-data` rebuild
of commanders.db can't retroactively change or break an in-progress
game.
"""

from __future__ import annotations

import json
import random
import re
import sqlite3
import time
import uuid
from dataclasses import dataclass, field

from commander_picker import pool as pool_module
from commander_picker.store import SessionError

# "Only pick from commanders with at least 10k decks" -- popular enough
# that a player has a fair shot at recognizing it, unlike the picker's
# own default pool (which deliberately favors *underbuilt* commanders).
DEFAULT_MIN_DECKS = 10_000

# At most this many oracle-text lines get queued as guessable clues --
# a long-winded commander doesn't get an unlimited number of chances.
# Total attempts per game is this plus 1 (the always-free first guess,
# made against just the type-line/mana-cost fact).
MAX_TEXT_CLUES = 5


class GuessGameError(SessionError):
    pass


@dataclass
class PickedCommander:
    """Everything one guess-game needs from the catalog, resolved once
    up front so create_game never has to touch commanders.db again.
    """

    name: str
    type_line: str | None
    mana_cost: str | None
    color_identity: str
    num_decks: int
    edhrec_url: str | None
    image_urls: list = field(default_factory=list)
    oracle_text: str | None = None


@dataclass
class GameInfo:
    id: str
    status: str  # "in_progress" | "won" | "lost"
    type_line: str | None
    mana_cost: str | None
    text_clues: list[str]  # oracle-text lines revealed so far
    total_text_clues: int  # total lines queued for this game (<= MAX_TEXT_CLUES)
    attempts_remaining: int
    guesses: list[str]
    # Only populated once status != "in_progress" -- never leaked to a
    # client polling/guessing against an in-progress game.
    answer_name: str | None = None
    color_identity: str | None = None
    oracle_text: str | None = None
    image_urls: list = field(default_factory=list)
    edhrec_url: str | None = None
    num_decks: int | None = None


REDACTED_NAME_PLACEHOLDER = "this card"


def _name_variants(full_name: str) -> list[str]:
    """Every way this commander's own name might appear in its own oracle
    text: each half of a Partner//DFC pair, plus the short form Magic's
    templating actually uses for self-reference -- the part before the
    first comma, e.g. "Celes" for "Celes, the Rune Knight" -- since a
    card's rules text almost never spells out its full epithet-bearing
    name. Sorted longest-first so a full name is matched (and redacted)
    before any short-name substring inside it would be.
    """
    variants: set[str] = set()
    for half in full_name.split(" // "):
        half = half.strip()
        if not half:
            continue
        variants.add(half)
        short = half.split(",", 1)[0].strip()
        if short:
            variants.add(short)
    return sorted(variants, key=len, reverse=True)


def _redact_name(text: str, full_name: str) -> str:
    """Replace every self-reference to `full_name` in `text` with a
    generic placeholder -- a card's own oracle text routinely names
    itself (e.g. "Celes, the Rune Knight" says just "Celes"), which
    would otherwise hand the answer away the moment a text clue reveals
    that line. Only the clue-facing copy is redacted; the stored raw
    oracle_text (used for the final reveal) is untouched.
    """
    for variant in _name_variants(full_name):
        text = re.sub(r"\b" + re.escape(variant) + r"\b", REDACTED_NAME_PLACEHOLDER, text, flags=re.IGNORECASE)
    return text


def _text_clues(oracle_text: str | None, commander_name: str) -> list[str]:
    redacted = _redact_name(oracle_text or "", commander_name)
    lines = [line.strip() for line in redacted.split("\n") if line.strip()]
    return lines[:MAX_TEXT_CLUES]


def _normalize(name: str) -> str:
    return " ".join(name.strip().lower().split())


def pick_commander(
    catalog_conn: sqlite3.Connection,
    min_decks: int = DEFAULT_MIN_DECKS,
    rng: random.Random | None = None,
) -> PickedCommander:
    """Pick one random commander with at least `min_decks` decks.

    No upper deck-count bound (unlike pool.py's own underbuilt-picker
    default) -- popularity is the whole point here. `max_pool_size` is
    set well above the real catalog's size so build_pool never trims
    the candidate set before this picks from it.
    """
    rng = rng or random.Random()
    filters = pool_module.PoolFilters(max_decks=None, min_decks=min_decks)
    try:
        candidates = pool_module.build_pool(catalog_conn, filters, max_pool_size=100_000, min_pool_size=1, rng=rng)
    except pool_module.PoolTooSmallError as exc:
        raise GuessGameError(str(exc)) from exc

    commander = rng.choice(candidates)
    row = catalog_conn.execute(
        "SELECT oracle_text FROM commanders WHERE name = ?", (commander.name,)
    ).fetchone()
    oracle_text = row["oracle_text"] if row else None

    return PickedCommander(
        name=commander.name,
        type_line=commander.type_line,
        mana_cost=commander.mana_cost,
        color_identity=commander.color_identity,
        num_decks=commander.num_decks,
        edhrec_url=commander.edhrec_url,
        image_urls=commander.image_urls,
        oracle_text=oracle_text,
    )


def create_game(conn: sqlite3.Connection, picked: PickedCommander) -> GameInfo:
    clues = _text_clues(picked.oracle_text, picked.name)
    game_id = str(uuid.uuid4())
    conn.execute(
        """
        INSERT INTO guess_games
            (id, created_at, status, answer_name, color_identity, num_decks,
             edhrec_url, image_urls, type_line, mana_cost, oracle_text, clues,
             clues_revealed, guesses)
        VALUES (?, ?, 'in_progress', ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, '[]')
        """,
        (
            game_id,
            time.time(),
            picked.name,
            picked.color_identity,
            picked.num_decks,
            picked.edhrec_url,
            json.dumps(picked.image_urls),
            picked.type_line,
            picked.mana_cost,
            picked.oracle_text,
            json.dumps(clues),
        ),
    )
    conn.commit()
    return get_game(conn, game_id)


def _get_row(conn: sqlite3.Connection, game_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM guess_games WHERE id = ?", (game_id,)).fetchone()
    if row is None:
        raise GuessGameError(f"No guess-game session {game_id!r}")
    return row


def get_game(conn: sqlite3.Connection, game_id: str) -> GameInfo:
    row = _get_row(conn, game_id)
    clues = json.loads(row["clues"])
    guesses = json.loads(row["guesses"])
    revealed = clues[: row["clues_revealed"]]
    total_attempts = len(clues) + 1
    attempts_remaining = max(total_attempts - len(guesses), 0)
    finished = row["status"] != "in_progress"

    return GameInfo(
        id=row["id"],
        status=row["status"],
        type_line=row["type_line"],
        mana_cost=row["mana_cost"],
        text_clues=revealed,
        total_text_clues=len(clues),
        attempts_remaining=attempts_remaining,
        guesses=guesses,
        answer_name=row["answer_name"] if finished else None,
        color_identity=row["color_identity"] if finished else None,
        oracle_text=row["oracle_text"] if finished else None,
        image_urls=json.loads(row["image_urls"]) if finished else [],
        edhrec_url=row["edhrec_url"] if finished else None,
        num_decks=row["num_decks"] if finished else None,
    )


def submit_guess(conn: sqlite3.Connection, game_id: str, guess: str) -> GameInfo:
    row = _get_row(conn, game_id)
    if row["status"] != "in_progress":
        raise GuessGameError("This game is already finished.")

    guess = (guess or "").strip()
    if not guess:
        raise GuessGameError("Guess can't be empty.")

    clues = json.loads(row["clues"])
    clues_revealed = row["clues_revealed"]
    guesses = json.loads(row["guesses"])
    guesses.append(guess)

    if _normalize(guess) == _normalize(row["answer_name"]):
        status = "won"
    elif clues_revealed < len(clues):
        status = "in_progress"
        clues_revealed += 1
    else:
        status = "lost"

    conn.execute(
        "UPDATE guess_games SET status = ?, clues_revealed = ?, guesses = ? WHERE id = ?",
        (status, clues_revealed, json.dumps(guesses), game_id),
    )
    conn.commit()
    return get_game(conn, game_id)
