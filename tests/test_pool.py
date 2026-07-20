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
            image_urls TEXT,
            price REAL,
            rank INTEGER,
            mana_cost TEXT,
            type_line TEXT,
            power_level INTEGER
        );
        CREATE TABLE commander_themes (
            commander_name TEXT NOT NULL,
            theme TEXT NOT NULL,
            num_decks INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (commander_name, theme)
        );
        """
    )
    return conn


def _insert(conn, name, color_identity, num_decks, themes=(), price=None):
    conn.execute(
        "INSERT INTO commanders (name, sanitized, color_identity, num_decks, edhrec_url, price) VALUES (?, ?, ?, ?, ?, ?)",
        (name, name.lower(), color_identity, num_decks, f"https://edhrec.com/commanders/{name.lower()}", price),
    )
    # `themes` is either a plain iterable of slugs (deck count 0, fine for
    # tests that don't care about the top-N-per-commander cap) or a
    # {slug: num_decks} dict for tests that do.
    rows = themes.items() if isinstance(themes, dict) else [(t, 0) for t in themes]
    conn.executemany(
        "INSERT INTO commander_themes (commander_name, theme, num_decks) VALUES (?, ?, ?)",
        [(name, t, count) for t, count in rows],
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
    _insert(conn, "Colorless Golem", "", 1000)
    conn.commit()
    return conn


def test_default_filters_exclude_over_10k_and_apply_no_color_filter(conn):
    candidates = pool.build_pool(conn, pool.PoolFilters(), min_pool_size=1)
    names = {c.name for c in candidates}
    assert "Big Rakdos" not in names  # over the default 10k ceiling
    assert names == {
        "Small Rakdos",
        "Tiny Rakdos",
        "Mono Black",
        "Jund Beatdown",
        "Five Color Pile",
        "Colorless Golem",
    }


def test_default_filters_min_decks_is_100():
    assert pool.PoolFilters().min_decks == pool.DEFAULT_MIN_DECKS == 100


def test_max_decks_and_min_decks(conn):
    filters = pool.PoolFilters(max_decks=4000, min_decks=1000)
    candidates = pool.build_pool(conn, filters, min_pool_size=1)
    names = {c.name for c in candidates}
    assert names == {"Jund Beatdown", "Mono Black", "Five Color Pile", "Colorless Golem"}


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


def test_themes_capped_to_top_n_per_commander(conn):
    # 5 themes, only the top TOP_THEMES_PER_COMMANDER by num_decks should
    # survive -- both for display (Commander.themes) and for matching a
    # filter against one of the dropped, low-count themes.
    _insert(
        conn,
        "Many Themes",
        "BR",
        1000,
        themes={"weakest": 1, "weak": 2, "mid": 3, "strong": 4, "strongest": 5},
    )
    conn.commit()

    candidates = pool.build_pool(conn, pool.PoolFilters(max_decks=None, colors="BR"), min_pool_size=1)
    many = next(c for c in candidates if c.name == "Many Themes")
    assert set(many.themes) == {"strongest", "strong", "mid"}
    assert len(many.themes) == pool.TOP_THEMES_PER_COMMANDER

    filtered = pool.build_pool(
        conn, pool.PoolFilters(max_decks=None, themes=("weakest",)), min_pool_size=0
    )
    assert "Many Themes" not in {c.name for c in filtered}


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


def test_count_matches_ignores_pool_size_bounds(conn):
    # count_matches should report the uncapped total even when
    # max_pool_size would normally sample it down.
    total = pool.count_matches(conn, pool.PoolFilters(max_decks=None))
    assert total == 7  # all fixture commanders


def test_count_matches_matches_build_pool_before_capping(conn):
    filters = pool.PoolFilters(colors="BR", color_mode="subset", max_decks=None)
    total = pool.count_matches(conn, filters)
    uncapped = pool.build_pool(conn, filters, max_pool_size=1000, min_pool_size=1)
    assert total == len(uncapped)


def test_count_matches_zero_does_not_raise(conn):
    filters = pool.PoolFilters(colors="U", color_mode="exact")
    assert pool.count_matches(conn, filters) == 0


def test_exact_mode_with_no_colors_selected_is_not_filtered(conn):
    # Regression: colors=None used to default `allowed` to the full
    # WUBRG set, which in "exact" mode silently meant "5-color
    # commanders only" instead of "no color filter" -- so leaving
    # colors unset with "exact" selected returned almost nothing
    # instead of everything.
    no_filter_count = pool.count_matches(conn, pool.PoolFilters(colors=None, max_decks=None))
    exact_no_colors_count = pool.count_matches(
        conn, pool.PoolFilters(colors=None, color_mode="exact", max_decks=None)
    )
    assert exact_no_colors_count == no_filter_count == 7  # all fixture commanders


def test_colorless_only_matches_when_explicitly_selected(conn):
    filters = pool.PoolFilters(colors="C", color_mode="exact", max_decks=None)
    candidates = pool.build_pool(conn, filters, min_pool_size=1)
    assert {c.name for c in candidates} == {"Colorless Golem"}


def test_colorless_does_not_leak_into_unrelated_color_filters(conn):
    # Regression: colorless commanders are stored with color_identity=""
    # (empty set), which is a subset of *any* allowed set -- so in
    # "subset" mode they used to match every color filter regardless of
    # whether "C" was actually selected. Selecting BR (with real BR/B
    # matches in the fixture) should not also pull in a colorless
    # commander that was never asked for.
    filters = pool.PoolFilters(colors="BR", color_mode="subset", max_decks=None)
    candidates = pool.build_pool(conn, filters, min_pool_size=1)
    assert "Colorless Golem" not in {c.name for c in candidates}


def test_colorless_included_in_subset_when_c_explicitly_selected(conn):
    filters = pool.PoolFilters(colors="RC", color_mode="subset", max_decks=None)
    candidates = pool.build_pool(conn, filters, min_pool_size=1)
    assert "Colorless Golem" in {c.name for c in candidates}


def test_max_price_excludes_commanders_priced_above_it():
    conn = _make_conn()
    _insert(conn, "Cheap Rakdos", "BR", 1000, price=5.0)
    _insert(conn, "Pricey Rakdos", "BR", 1000, price=50.0)
    conn.commit()

    filters = pool.PoolFilters(max_decks=None, max_price=10.0)
    candidates = pool.build_pool(conn, filters, min_pool_size=1)
    assert {c.name for c in candidates} == {"Cheap Rakdos"}


def test_max_price_none_means_no_price_filter(conn):
    # Default PoolFilters().max_price is None -- fixture commanders have
    # no price data at all, so this must not exclude everything.
    candidates = pool.build_pool(conn, pool.PoolFilters(max_decks=None), min_pool_size=1)
    assert len(candidates) == 7


def test_max_price_is_permissive_on_missing_price_data():
    # A commander with no price data (e.g. an unresolved Partner pair)
    # should never be excluded by an active price filter -- "we don't
    # know" is friendlier than silently shrinking the pool over a data gap.
    conn = _make_conn()
    _insert(conn, "No Price Data", "BR", 1000, price=None)
    _insert(conn, "Pricey Rakdos", "BR", 1000, price=50.0)
    conn.commit()

    filters = pool.PoolFilters(max_decks=None, max_price=10.0)
    candidates = pool.build_pool(conn, filters, min_pool_size=1)
    assert {c.name for c in candidates} == {"No Price Data"}


def test_commander_carries_rank_mana_cost_type_line():
    conn = _make_conn()
    conn.execute(
        "INSERT INTO commanders (name, color_identity, num_decks, edhrec_url, rank, mana_cost, type_line) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("Detailed Commander", "BR", 1000, "https://edhrec.com/commanders/detailed", 3, "{2}{B}{R}", "Legendary Creature — Devil"),
    )
    conn.commit()

    candidates = pool.build_pool(conn, pool.PoolFilters(max_decks=None), min_pool_size=1)
    detailed = next(c for c in candidates if c.name == "Detailed Commander")
    assert detailed.rank == 3
    assert detailed.mana_cost == "{2}{B}{R}"
    assert detailed.type_line == "Legendary Creature — Devil"


def test_commander_carries_power_level(conn):
    conn.execute("UPDATE commanders SET power_level = 3 WHERE name = 'Big Rakdos'")
    conn.commit()

    candidates = pool.build_pool(conn, pool.PoolFilters(max_decks=None), min_pool_size=1)
    big_rakdos = next(c for c in candidates if c.name == "Big Rakdos")
    assert big_rakdos.power_level == 3
    small_rakdos = next(c for c in candidates if c.name == "Small Rakdos")
    assert small_rakdos.power_level is None

    named = pool.commanders_by_names(conn, ["Big Rakdos"])
    assert named[0].power_level == 3


def test_search_commanders_substring_match_ordered_by_deck_count(conn):
    results = pool.search_commanders(conn, "rakdos")
    names = [r["name"] for r in results]
    assert names == ["Big Rakdos", "Small Rakdos", "Tiny Rakdos"]


def test_search_commanders_limit(conn):
    results = pool.search_commanders(conn, "rakdos", limit=1)
    assert [r["name"] for r in results] == ["Big Rakdos"]


def test_search_commanders_no_match(conn):
    assert pool.search_commanders(conn, "nonexistent-xyz") == []


def test_commanders_by_names_preserves_order(conn):
    candidates = pool.commanders_by_names(conn, ["Tiny Rakdos", "Big Rakdos", "Mono Black"])
    assert [c.name for c in candidates] == ["Tiny Rakdos", "Big Rakdos", "Mono Black"]
    assert candidates[0].color_identity == "BR"
    assert candidates[0].themes == ("aristocrats", "tokens")


def test_commanders_by_names_unknown_name_raises(conn):
    with pytest.raises(pool.CommanderLookupError, match="Unknown commander"):
        pool.commanders_by_names(conn, ["Big Rakdos", "Not A Real Commander"])


def test_commanders_by_names_duplicate_raises(conn):
    with pytest.raises(pool.CommanderLookupError, match="Duplicate"):
        pool.commanders_by_names(conn, ["Big Rakdos", "Big Rakdos"])


def test_list_known_themes_returns_distinct_themes(conn):
    assert pool.list_known_themes(conn) == ["aristocrats", "tokens"]


def test_list_known_themes_empty_when_no_themes():
    conn = _make_conn()
    _insert(conn, "No Themes Commander", "BR", 1000)
    conn.commit()
    assert pool.list_known_themes(conn) == []


def test_commander_images_by_name_returns_matches_only(conn):
    conn.execute(
        "UPDATE commanders SET image_urls = ? WHERE name = 'Big Rakdos'",
        ('["https://example.com/big-rakdos.jpg"]',),
    )
    conn.commit()

    result = pool.commander_images_by_name(conn, ["Big Rakdos", "Not A Real Commander"])

    assert set(result) == {"Big Rakdos"}
    assert result["Big Rakdos"]["image_urls"] == ["https://example.com/big-rakdos.jpg"]
    assert result["Big Rakdos"]["color_identity"] == "BR"


def test_commander_images_by_name_empty_list_returns_empty_dict(conn):
    assert pool.commander_images_by_name(conn, []) == {}
