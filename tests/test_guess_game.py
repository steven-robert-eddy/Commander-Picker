import random
import sqlite3

import pytest

from commander_picker import guess_game, store


def _make_catalog_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE commanders (
            name TEXT PRIMARY KEY,
            sanitized TEXT,
            color_identity TEXT NOT NULL,
            num_decks INTEGER NOT NULL,
            salt REAL,
            edhrec_url TEXT,
            image_urls TEXT,
            price REAL,
            rank INTEGER,
            mana_cost TEXT,
            type_line TEXT,
            power_level INTEGER,
            oracle_text TEXT
        );
        CREATE TABLE commander_themes (
            commander_name TEXT NOT NULL,
            theme TEXT NOT NULL,
            num_decks INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (commander_name, theme)
        );
        CREATE TABLE commander_sets (
            commander_name TEXT NOT NULL,
            set_slug TEXT NOT NULL,
            set_name TEXT NOT NULL,
            num_decks INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (commander_name, set_slug)
        );
        """
    )
    return conn


def _insert(conn, name, num_decks, mana_cost="{1}{R}", type_line="Legendary Creature — Human Wizard", oracle_text=None):
    conn.execute(
        "INSERT INTO commanders (name, sanitized, color_identity, num_decks, edhrec_url, image_urls, mana_cost, type_line, oracle_text) "
        "VALUES (?, ?, 'R', ?, ?, '[\"https://img/card.jpg\"]', ?, ?, ?)",
        (name, name.lower(), num_decks, f"https://edhrec.com/commanders/{name.lower()}", mana_cost, type_line, oracle_text),
    )


@pytest.fixture
def catalog_conn():
    conn = _make_catalog_conn()
    _insert(
        conn,
        "Popular Wizard",
        50_000,
        oracle_text="Flying, haste\nWhenever Popular Wizard attacks, draw a card.\nSacrifice a permanent: Deal 1 damage.",
    )
    _insert(conn, "Obscure Wizard", 500, oracle_text="Some obscure ability.")
    conn.commit()
    return conn


@pytest.fixture
def conn(tmp_path):
    return store.connect(db_path=tmp_path / "sessions.db")


def test_pick_commander_filters_by_min_decks(catalog_conn):
    picked = guess_game.pick_commander(catalog_conn, min_decks=10_000)
    assert picked.name == "Popular Wizard"
    assert picked.oracle_text.startswith("Flying, haste")


def test_pick_commander_raises_when_no_matches(catalog_conn):
    with pytest.raises(guess_game.GuessGameError):
        guess_game.pick_commander(catalog_conn, min_decks=1_000_000)


def test_pick_commander_ignores_pool_py_default_max_decks_cap(catalog_conn):
    # PoolFilters.max_decks defaults to 10_000 -- pick_commander must
    # override it to None, or a genuinely popular (>10k-deck) commander
    # like "Popular Wizard" would never be selectable at all.
    picked = guess_game.pick_commander(catalog_conn, min_decks=10_000, rng=random.Random(0))
    assert picked.name == "Popular Wizard"


def test_create_game_caps_text_clues_at_five(conn, catalog_conn):
    picked = guess_game.pick_commander(catalog_conn, min_decks=10_000)
    picked.oracle_text = "\n".join(f"Line {i}" for i in range(1, 10))  # 9 lines
    info = guess_game.create_game(conn, picked)
    assert info.total_text_clues == guess_game.MAX_TEXT_CLUES
    assert info.attempts_remaining == guess_game.MAX_TEXT_CLUES + 1


def test_create_game_short_text_gives_fewer_total_attempts(conn, catalog_conn):
    picked = guess_game.pick_commander(catalog_conn, min_decks=10_000)
    picked.oracle_text = "Just one line."
    info = guess_game.create_game(conn, picked)
    assert info.total_text_clues == 1
    assert info.attempts_remaining == 2  # fact clue + one text line


def test_create_game_starts_with_no_text_clues_revealed(conn, catalog_conn):
    picked = guess_game.pick_commander(catalog_conn, min_decks=10_000)
    info = guess_game.create_game(conn, picked)
    assert info.text_clues == []
    assert info.status == "in_progress"
    assert info.type_line == "Legendary Creature — Human Wizard"
    assert info.mana_cost == "{1}{R}"


def test_create_game_and_get_game_never_leak_answer_while_in_progress(conn, catalog_conn):
    picked = guess_game.pick_commander(catalog_conn, min_decks=10_000)
    info = guess_game.create_game(conn, picked)
    fetched = guess_game.get_game(conn, info.id)
    for leaked in (fetched.answer_name, fetched.color_identity, fetched.oracle_text, fetched.edhrec_url, fetched.num_decks):
        assert leaked is None
    assert fetched.image_urls == []


def test_submit_guess_wrong_reveals_next_clue(conn, catalog_conn):
    picked = guess_game.pick_commander(catalog_conn, min_decks=10_000)
    info = guess_game.create_game(conn, picked)

    result = guess_game.submit_guess(conn, info.id, "Not The Right Commander")
    assert result.status == "in_progress"
    assert result.text_clues == ["Flying, haste"]
    assert result.attempts_remaining == 3
    assert result.guesses == ["Not The Right Commander"]


def test_submit_guess_correct_wins_and_reveals_full_card(conn, catalog_conn):
    picked = guess_game.pick_commander(catalog_conn, min_decks=10_000)
    info = guess_game.create_game(conn, picked)

    result = guess_game.submit_guess(conn, info.id, "Popular Wizard")
    assert result.status == "won"
    assert result.answer_name == "Popular Wizard"
    assert result.color_identity == "R"
    assert result.oracle_text.startswith("Flying, haste")
    assert result.image_urls == ["https://img/card.jpg"]
    assert result.edhrec_url == "https://edhrec.com/commanders/popular wizard"


def test_submit_guess_is_case_and_whitespace_insensitive(conn, catalog_conn):
    picked = guess_game.pick_commander(catalog_conn, min_decks=10_000)
    info = guess_game.create_game(conn, picked)

    result = guess_game.submit_guess(conn, info.id, "  popular   WIZARD  ")
    assert result.status == "won"


def test_submit_guess_exhausting_attempts_loses_and_reveals(conn, catalog_conn):
    picked = guess_game.pick_commander(catalog_conn, min_decks=10_000)
    info = guess_game.create_game(conn, picked)
    assert info.attempts_remaining == 4  # fact clue + 3 text lines

    result = None
    for _ in range(4):
        result = guess_game.submit_guess(conn, info.id, "Wrong Guess")

    assert result.status == "lost"
    assert result.answer_name == "Popular Wizard"
    assert result.attempts_remaining == 0


def test_submit_guess_on_finished_game_raises(conn, catalog_conn):
    picked = guess_game.pick_commander(catalog_conn, min_decks=10_000)
    info = guess_game.create_game(conn, picked)
    guess_game.submit_guess(conn, info.id, "Popular Wizard")  # wins

    with pytest.raises(guess_game.GuessGameError):
        guess_game.submit_guess(conn, info.id, "Popular Wizard")


def test_submit_guess_empty_raises(conn, catalog_conn):
    picked = guess_game.pick_commander(catalog_conn, min_decks=10_000)
    info = guess_game.create_game(conn, picked)

    with pytest.raises(guess_game.GuessGameError):
        guess_game.submit_guess(conn, info.id, "   ")


def test_get_game_unknown_id_raises(conn):
    with pytest.raises(guess_game.GuessGameError):
        guess_game.get_game(conn, "not-a-real-id")


def test_submit_guess_unknown_id_raises(conn):
    with pytest.raises(guess_game.GuessGameError):
        guess_game.submit_guess(conn, "not-a-real-id", "Anything")
