import random
import sqlite3

import pytest

from commander_picker import pool


def _make_conn():
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
            image_url TEXT,
            price REAL
        );
        CREATE TABLE commander_themes (
            commander_name TEXT NOT NULL,
            theme TEXT NOT NULL,
            PRIMARY KEY (commander_name, theme)
        );
        """
    )
    return conn


def _insert(conn, name, color_identity, num_decks, themes=()):
    conn.execute(
        "INSERT INTO commanders (name, sanitized, color_identity, num_decks, edhrec_url) VALUES (?, ?, ?, ?, ?)",
        (name, name.lower(), color_identity, num_decks, f"https://edhrec.com/commanders/{name.lower()}"),
    )
    conn.executemany(
        "INSERT INTO commander_themes (commander_name, theme) VALUES (?, ?)",
        [(name, t) for t in themes],
    )


@pytest.fixture
def conn():
    conn = _make_conn()
    _insert(conn, "Big Rakdos", "BR", 50000, themes=("aristocrats",))
    _insert(conn, "Small Rakdos", "BR", 5000, themes=("tokens",))
    _insert(conn, "Tiny Rakdos", "BR", 500, themes=("tokens", "aristocrats"))
    _insert(conn, "Mono Black", "B", 3000)
    _insert(conn, "Jund Beatdown", "BRG", 4000, themes=("aristocrats",))
    _insert(conn, "Five Color Pile", "WUBRG", 2000)
    conn.commit()
    return conn


def test_default_filters_exclude_over_10k_and_apply_no_color_filter(conn):
    candidates = pool.build_pool(conn, pool.PoolFilters(), min_pool_size=1)
    names = {c.name for c in candidates}
    assert "Big Rakdos" not in names  # over the default 10k ceiling
    assert names == {"Small Rakdos", "Tiny Rakdos", "Mono Black", "Jund Beatdown", "Five Color Pile"}


def test_max_decks_and_min_decks(conn):
    filters = pool.PoolFilters(max_decks=4000, min_decks=1000)
    candidates = pool.build_pool(conn, filters, min_pool_size=1)
    names = {c.name for c in candidates}
    assert names == {"Jund Beatdown", "Mono Black", "Five Color Pile"}


def test_color_subset_mode(conn):
    # BR commanders should include mono-B (subset) but not 3-color Jund.
    filters = pool.PoolFilters(colors="BR", color_mode="subset", max_decks=None)
    candidates = pool.build_pool(conn, filters, min_pool_size=1)
    names = {c.name for c in candidates}
    assert names == {"Big Rakdos", "Small Rakdos", "Tiny Rakdos", "Mono Black"}


def test_color_exact_mode(conn):
    filters = pool.PoolFilters(colors="BR", color_mode="exact", max_decks=None)
    candidates = pool.build_pool(conn, filters, min_pool_size=1)
    names = {c.name for c in candidates}
    assert names == {"Big Rakdos", "Small Rakdos", "Tiny Rakdos"}


def test_themes_any_mode(conn):
    filters = pool.PoolFilters(themes=("tokens",), max_decks=None)
    candidates = pool.build_pool(conn, filters, min_pool_size=1)
    names = {c.name for c in candidates}
    assert names == {"Small Rakdos", "Tiny Rakdos"}


def test_themes_all_mode(conn):
    filters = pool.PoolFilters(themes=("tokens", "aristocrats"), themes_mode="all", max_decks=None)
    candidates = pool.build_pool(conn, filters, min_pool_size=1)
    names = {c.name for c in candidates}
    assert names == {"Tiny Rakdos"}


def test_themes_any_vs_all_differ(conn):
    any_candidates = pool.build_pool(
        conn, pool.PoolFilters(themes=("tokens", "aristocrats"), themes_mode="any", max_decks=None), min_pool_size=1
    )
    all_candidates = pool.build_pool(
        conn, pool.PoolFilters(themes=("tokens", "aristocrats"), themes_mode="all", max_decks=None), min_pool_size=1
    )
    assert len(any_candidates) > len(all_candidates)


def test_pool_too_small_raises(conn):
    filters = pool.PoolFilters(colors="U", color_mode="exact")  # no mono-blue commanders in fixture
    with pytest.raises(pool.PoolTooSmallError):
        pool.build_pool(conn, filters, min_pool_size=1)


def test_pool_size_cap_samples_randomly(conn):
    filters = pool.PoolFilters(max_decks=None)
    rng = random.Random(42)
    candidates = pool.build_pool(conn, filters, max_pool_size=2, min_pool_size=1, rng=rng)
    assert len(candidates) == 2


def test_commander_carries_its_themes(conn):
    candidates = pool.build_pool(conn, pool.PoolFilters(max_decks=None), min_pool_size=1)
    tiny = next(c for c in candidates if c.name == "Tiny Rakdos")
    assert tiny.themes == ("aristocrats", "tokens")
    mono_black = next(c for c in candidates if c.name == "Mono Black")
    assert mono_black.themes == ()
