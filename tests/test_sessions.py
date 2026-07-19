import random

import pytest

from commander_picker import elo, sessions
from commander_picker.pool import Commander


def _commander(name, decks=1000, colors="BR", themes=(), image_urls=(), rank=None, mana_cost=None, type_line=None):
    return Commander(
        name=name,
        color_identity=colors,
        num_decks=decks,
        edhrec_url=f"https://edhrec.com/commanders/{name.lower()}",
        themes=themes,
        image_urls=list(image_urls),
        rank=rank,
        mana_cost=mana_cost,
        type_line=type_line,
    )


@pytest.fixture
def conn(tmp_path):
    return sessions.connect(db_path=tmp_path / "sessions.db")


@pytest.fixture
def candidates():
    return [_commander("A"), _commander("B"), _commander("C"), _commander("D")]


def test_create_session_requires_at_least_two_candidates(conn):
    with pytest.raises(sessions.SessionError):
        sessions.create_session(conn, [_commander("Solo")])


def test_create_session_persists_candidates_at_default_rating(conn, candidates):
    session_id = sessions.create_session(conn, candidates, description="test")
    info = sessions.get_session(conn, session_id)
    assert info.status == "active"
    assert info.pool_size == 4
    assert info.rounds_completed == 0
    assert info.target_rounds > 0

    ranked = sessions.get_rankings(conn, session_id)
    assert {r.name for r in ranked} == {"A", "B", "C", "D"}
    assert all(r.rating == pytest.approx(1000.0) for r in ranked)


def test_create_session_carries_rank_mana_cost_type_line_through(conn):
    session_id = sessions.create_session(
        conn,
        [
            _commander("A", rank=1, mana_cost="{2}{B}{R}", type_line="Legendary Creature — Devil"),
            _commander("B"),
        ],
    )
    details = sessions.get_candidates(conn, session_id)
    assert details["A"].rank == 1
    assert details["A"].mana_cost == "{2}{B}{R}"
    assert details["A"].type_line == "Legendary Creature — Devil"
    assert details["B"].rank is None


def test_next_pairing_returns_two_distinct_candidates(conn, candidates):
    session_id = sessions.create_session(conn, candidates)
    pair = sessions.next_pairing(conn, session_id, rng=random.Random(1))
    assert pair is not None
    a, b = pair
    assert a != b
    assert {a, b} <= {"A", "B", "C", "D"}


def test_record_pick_updates_ratings_and_round_count(conn, candidates):
    session_id = sessions.create_session(conn, candidates)
    sessions.record_pick(conn, session_id, winner="A", loser="B")

    info = sessions.get_session(conn, session_id)
    assert info.rounds_completed == 1

    ranked = {r.name: r.rating for r in sessions.get_rankings(conn, session_id)}
    assert ranked["A"] > 1000.0
    assert ranked["B"] < 1000.0
    assert ranked["C"] == pytest.approx(1000.0)


def test_record_pick_rejects_unknown_commander(conn, candidates):
    session_id = sessions.create_session(conn, candidates)
    with pytest.raises(sessions.SessionError):
        sessions.record_pick(conn, session_id, winner="A", loser="Not In Pool")


def test_finish_session_stops_pairing(conn, candidates):
    session_id = sessions.create_session(conn, candidates)
    sessions.finish_session(conn, session_id)

    info = sessions.get_session(conn, session_id)
    assert info.status == "complete"
    assert sessions.next_pairing(conn, session_id) is None


def test_get_session_unknown_id_raises(conn):
    with pytest.raises(sessions.SessionError):
        sessions.get_session(conn, "does-not-exist")


def test_list_sessions_returns_all_newest_first(conn, candidates):
    id1 = sessions.create_session(conn, candidates, description="first")
    id2 = sessions.create_session(conn, candidates, description="second")
    listed = sessions.list_sessions(conn)
    assert [s.id for s in listed] == [id2, id1]


def test_rankings_sorted_by_rating_descending(conn, candidates):
    session_id = sessions.create_session(conn, candidates)
    sessions.record_pick(conn, session_id, winner="A", loser="B")
    sessions.record_pick(conn, session_id, winner="A", loser="C")

    ranked = sessions.get_rankings(conn, session_id)
    assert ranked[0].name == "A"
    ratings = [r.rating for r in ranked]
    assert ratings == sorted(ratings, reverse=True)


def test_pairing_avoids_repeats_until_exhausted(conn):
    # A 3-candidate pool has exactly 3 unique pairs; after recording
    # all 3, next_pairing should still return something (a repeat)
    # rather than erroring or returning None.
    candidates = [_commander("A"), _commander("B"), _commander("C")]
    session_id = sessions.create_session(conn, candidates)
    seen_pairs = set()
    rng = random.Random(3)
    for _ in range(3):
        pair = sessions.next_pairing(conn, session_id, rng=rng)
        assert frozenset(pair) not in seen_pairs
        seen_pairs.add(frozenset(pair))
        sessions.record_pick(conn, session_id, winner=pair[0], loser=pair[1])

    assert len(seen_pairs) == 3  # all 3 unique pairs for a 3-item pool

    # A 4th round has no fresh pair left -- should still return a pair.
    pair = sessions.next_pairing(conn, session_id, rng=rng)
    assert pair is not None


def test_get_candidates_includes_themes(conn):
    candidates = [
        _commander("Tagged", themes=("tokens", "aristocrats")),
        _commander("Untagged", themes=()),
    ]
    session_id = sessions.create_session(conn, candidates)

    details = sessions.get_candidates(conn, session_id)
    assert details["Tagged"].themes == ("tokens", "aristocrats")
    assert details["Untagged"].themes == ()
    assert details["Tagged"].rating == pytest.approx(1000.0)


def test_get_rankings_includes_themes(conn):
    candidates = [_commander("A", themes=("voltron",)), _commander("B")]
    session_id = sessions.create_session(conn, candidates)

    ranked = {r.name: r for r in sessions.get_rankings(conn, session_id)}
    assert ranked["A"].themes == ("voltron",)
    assert ranked["B"].themes == ()


def test_schema_migration_adds_themes_column_to_old_db(tmp_path):
    import sqlite3

    db_path = tmp_path / "old_sessions.db"
    raw = sqlite3.connect(db_path)
    raw.executescript(
        """
        CREATE TABLE sessions (
            id TEXT PRIMARY KEY, created_at REAL NOT NULL, description TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL, target_rounds INTEGER NOT NULL, rounds_completed INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE candidates (
            session_id TEXT NOT NULL, commander_name TEXT NOT NULL, color_identity TEXT,
            num_decks INTEGER, edhrec_url TEXT, rating REAL NOT NULL,
            PRIMARY KEY (session_id, commander_name)
        );
        CREATE TABLE comparisons (
            id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL, round_num INTEGER NOT NULL,
            winner TEXT NOT NULL, loser TEXT NOT NULL, created_at REAL NOT NULL
        );
        """
    )
    raw.commit()
    raw.close()

    conn = sessions.connect(db_path=db_path)
    session_id = sessions.create_session(conn, [_commander("A", themes=("tokens",)), _commander("B")])
    assert sessions.get_candidates(conn, session_id)["A"].themes == ("tokens",)


def test_image_urls_flow_through_candidates_and_rankings(conn):
    candidates = [
        # Partner pair / DFC -- two images, both should round-trip.
        _commander("Pictured", image_urls=["https://img/pictured-front.jpg", "https://img/pictured-back.jpg"]),
        _commander("Unpictured"),
    ]
    session_id = sessions.create_session(conn, candidates)

    details = sessions.get_candidates(conn, session_id)
    assert details["Pictured"].image_urls == ("https://img/pictured-front.jpg", "https://img/pictured-back.jpg")
    assert details["Unpictured"].image_urls == ()

    ranked = {r.name: r for r in sessions.get_rankings(conn, session_id)}
    assert ranked["Pictured"].image_urls == ("https://img/pictured-front.jpg", "https://img/pictured-back.jpg")
    assert ranked["Unpictured"].image_urls == ()


def test_migration_adds_image_urls_column_to_old_db(tmp_path):
    import sqlite3

    db_path = tmp_path / "old_sessions.db"
    raw = sqlite3.connect(db_path)
    raw.executescript(
        """
        CREATE TABLE sessions (
            id TEXT PRIMARY KEY, created_at REAL NOT NULL, description TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL, target_rounds INTEGER NOT NULL, rounds_completed INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE candidates (
            session_id TEXT NOT NULL, commander_name TEXT NOT NULL, color_identity TEXT,
            num_decks INTEGER, edhrec_url TEXT, themes TEXT NOT NULL DEFAULT '', rating REAL NOT NULL,
            PRIMARY KEY (session_id, commander_name)
        );
        CREATE TABLE comparisons (
            id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL, round_num INTEGER NOT NULL,
            winner TEXT NOT NULL, loser TEXT NOT NULL, created_at REAL NOT NULL
        );
        """
    )
    raw.commit()
    raw.close()

    conn = sessions.connect(db_path=db_path)
    session_id = sessions.create_session(conn, [_commander("A", image_urls=["https://img/a.jpg"]), _commander("B")])
    assert sessions.get_candidates(conn, session_id)["A"].image_urls == ("https://img/a.jpg",)


def test_migration_folds_legacy_single_image_url_into_image_urls(tmp_path):
    # An even older sessions.db from before the multi-image change had a
    # single `image_url` TEXT column with real data in it -- the
    # migration should fold that into the new list column rather than
    # silently dropping in-flight sessions' art.
    import sqlite3

    db_path = tmp_path / "legacy_sessions.db"
    raw = sqlite3.connect(db_path)
    raw.executescript(
        """
        CREATE TABLE sessions (
            id TEXT PRIMARY KEY, created_at REAL NOT NULL, description TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL, target_rounds INTEGER NOT NULL, rounds_completed INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE candidates (
            session_id TEXT NOT NULL, commander_name TEXT NOT NULL, color_identity TEXT,
            num_decks INTEGER, edhrec_url TEXT, themes TEXT NOT NULL DEFAULT '',
            image_url TEXT, rating REAL NOT NULL,
            PRIMARY KEY (session_id, commander_name)
        );
        CREATE TABLE comparisons (
            id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL, round_num INTEGER NOT NULL,
            winner TEXT NOT NULL, loser TEXT NOT NULL, created_at REAL NOT NULL
        );
        """
    )
    raw.execute(
        "INSERT INTO sessions (id, created_at, status, target_rounds, rounds_completed) "
        "VALUES ('legacy', 0, 'active', 2, 0)"
    )
    raw.execute(
        "INSERT INTO candidates (session_id, commander_name, rating, image_url) VALUES ('legacy', 'A', 1000, ?)",
        ("https://img/legacy-a.jpg",),
    )
    raw.execute(
        "INSERT INTO candidates (session_id, commander_name, rating, image_url) VALUES ('legacy', 'B', 1000, NULL)"
    )
    raw.commit()
    raw.close()

    conn = sessions.connect(db_path=db_path)
    details = sessions.get_candidates(conn, "legacy")
    assert details["A"].image_urls == ("https://img/legacy-a.jpg",)
    assert details["B"].image_urls == ()


def test_record_pick_auto_finishes_at_target_rounds(conn):
    # 2 candidates -> target_rounds = round(2 * log2(2)) = 2.
    candidates = [_commander("A"), _commander("B")]
    session_id = sessions.create_session(conn, candidates)
    info = sessions.get_session(conn, session_id)
    assert info.target_rounds == 2

    sessions.record_pick(conn, session_id, "A", "B")
    assert sessions.get_session(conn, session_id).status == "active"

    sessions.record_pick(conn, session_id, "A", "B")
    finished = sessions.get_session(conn, session_id)
    assert finished.status == "complete"
    assert finished.rounds_completed == 2
    assert sessions.next_pairing(conn, session_id) is None


def test_next_pairing_self_heals_a_session_already_past_target(conn):
    # Simulates a session created before auto-finish existed, sitting
    # well past its target_rounds with status still 'active' -- should
    # finalize the moment anything asks it for a pairing, not require
    # one more pick first.
    candidates = [_commander("A"), _commander("B"), _commander("C")]
    session_id = sessions.create_session(conn, candidates)
    conn.execute("UPDATE sessions SET rounds_completed = 999 WHERE id = ?", (session_id,))
    conn.commit()

    assert sessions.get_session(conn, session_id).status == "active"
    assert sessions.next_pairing(conn, session_id) is None
    assert sessions.get_session(conn, session_id).status == "complete"


def test_record_pick_on_already_finished_session_raises(conn):
    candidates = [_commander("A"), _commander("B")]
    session_id = sessions.create_session(conn, candidates)
    sessions.record_pick(conn, session_id, "A", "B")
    sessions.record_pick(conn, session_id, "A", "B")  # reaches target_rounds=2, auto-finishes

    with pytest.raises(sessions.SessionError):
        sessions.record_pick(conn, session_id, "A", "B")


def test_new_session_seeds_ratings_from_global_history(conn):
    # A's rating should carry over from a prior session instead of
    # resetting to DEFAULT_RATING; a commander with no history yet
    # still starts fresh.
    first = sessions.create_session(conn, [_commander("A"), _commander("B")])
    sessions.record_pick(conn, first, winner="A", loser="B")
    sessions.record_pick(conn, first, winner="A", loser="B")  # target_rounds=2, auto-finishes

    global_a_rating = sessions.get_leaderboard(conn)[0].rating
    assert global_a_rating > 1000.0

    second = sessions.create_session(conn, [_commander("A"), _commander("C")])
    details = sessions.get_candidates(conn, second)
    assert details["A"].rating == pytest.approx(global_a_rating)
    assert details["C"].rating == pytest.approx(1000.0)


def test_record_pick_updates_global_leaderboard(conn):
    session_id = sessions.create_session(conn, [_commander("A"), _commander("B"), _commander("C")])
    sessions.record_pick(conn, session_id, winner="A", loser="B")

    board = {r.name: r for r in sessions.get_leaderboard(conn)}
    assert board["A"].rating > 1000.0
    assert board["A"].games_played == 1
    assert board["B"].rating < 1000.0
    assert board["B"].games_played == 1
    # C never played a round yet -- no leaderboard entry for it at all,
    # not a phantom 1000-rating row.
    assert "C" not in board


def test_leaderboard_accumulates_across_multiple_sessions(conn):
    s1 = sessions.create_session(conn, [_commander("A"), _commander("B")])
    sessions.record_pick(conn, s1, winner="A", loser="B")
    sessions.record_pick(conn, s1, winner="A", loser="B")

    s2 = sessions.create_session(conn, [_commander("A"), _commander("D")])
    sessions.record_pick(conn, s2, winner="A", loser="D")
    sessions.record_pick(conn, s2, winner="A", loser="D")

    board = {r.name: r for r in sessions.get_leaderboard(conn)}
    # A played 4 total rounds across two sessions (2 in each) --
    # games_played and rating should reflect all of it, not just the
    # most recent session.
    assert board["A"].games_played == 4
    assert board["A"].rating > board["B"].rating
    assert board["A"].rating > board["D"].rating


def test_leaderboard_ordered_highest_rating_first(conn):
    session_id = sessions.create_session(conn, [_commander("A"), _commander("B"), _commander("C")])
    sessions.record_pick(conn, session_id, winner="A", loser="B")
    sessions.record_pick(conn, session_id, winner="A", loser="C")

    board = sessions.get_leaderboard(conn)
    ratings = [r.rating for r in board]
    assert ratings == sorted(ratings, reverse=True)
    assert board[0].name == "A"


def test_leaderboard_respects_limit(conn):
    session_id = sessions.create_session(conn, [_commander("A"), _commander("B"), _commander("C")])
    sessions.record_pick(conn, session_id, winner="A", loser="B")
    sessions.record_pick(conn, session_id, winner="B", loser="C")

    assert len(sessions.get_leaderboard(conn, limit=1)) == 1
    assert len(sessions.get_leaderboard(conn)) == 3


def test_leaderboard_carries_display_metadata_from_latest_session(conn):
    session_id = sessions.create_session(
        conn, [_commander("A", colors="UB", image_urls=["https://img/a.jpg"]), _commander("B")]
    )
    sessions.record_pick(conn, session_id, winner="A", loser="B")

    board = {r.name: r for r in sessions.get_leaderboard(conn)}
    assert board["A"].color_identity == "UB"
    assert board["A"].image_urls == ("https://img/a.jpg",)


def test_empty_leaderboard_before_any_picks(conn):
    sessions.create_session(conn, [_commander("A"), _commander("B")])
    assert sessions.get_leaderboard(conn) == []


def test_leaderboard_color_subset_mode(conn):
    # BR should include a mono-B commander (subset of BR) but not a
    # 3-color one -- same semantics as pool._color_identity_matches.
    session_id = sessions.create_session(
        conn,
        [_commander("BigRakdos", colors="BR"), _commander("MonoB", colors="B"), _commander("Jund", colors="BRG")],
    )
    sessions.record_pick(conn, session_id, winner="BigRakdos", loser="MonoB")
    sessions.record_pick(conn, session_id, winner="MonoB", loser="Jund")

    names = {r.name for r in sessions.get_leaderboard(conn, colors="BR", color_mode="subset")}
    assert names == {"BigRakdos", "MonoB"}


def test_leaderboard_color_exact_mode(conn):
    session_id = sessions.create_session(
        conn, [_commander("BigRakdos", colors="BR"), _commander("MonoB", colors="B")]
    )
    sessions.record_pick(conn, session_id, winner="BigRakdos", loser="MonoB")

    names = {r.name for r in sessions.get_leaderboard(conn, colors="BR", color_mode="exact")}
    assert names == {"BigRakdos"}


def test_leaderboard_no_color_filter_returns_everything(conn):
    session_id = sessions.create_session(
        conn, [_commander("BigRakdos", colors="BR"), _commander("MonoB", colors="B")]
    )
    sessions.record_pick(conn, session_id, winner="BigRakdos", loser="MonoB")

    names = {r.name for r in sessions.get_leaderboard(conn)}
    assert names == {"BigRakdos", "MonoB"}


def test_leaderboard_colorless_handling(conn):
    session_id = sessions.create_session(
        conn, [_commander("Golem", colors=""), _commander("MonoB", colors="B")]
    )
    sessions.record_pick(conn, session_id, winner="Golem", loser="MonoB")

    exact_colorless = {r.name for r in sessions.get_leaderboard(conn, colors="C", color_mode="exact")}
    assert exact_colorless == {"Golem"}

    # Colorless shouldn't leak into an unrelated color filter (regression
    # class already guarded in pool.py -- same underlying function).
    subset_b = {r.name for r in sessions.get_leaderboard(conn, colors="B", color_mode="subset")}
    assert "Golem" not in subset_b


def test_leaderboard_color_filter_applies_before_limit(conn):
    # Two BR commanders rated above a mono-B one -- limit=1 with a "B"
    # exact filter should still surface the mono-B commander, not cut
    # it before the filter had a chance to apply.
    session_id = sessions.create_session(
        conn,
        [_commander("BigRakdos", colors="BR"), _commander("SmallRakdos", colors="BR"), _commander("MonoB", colors="B")],
    )
    sessions.record_pick(conn, session_id, winner="BigRakdos", loser="MonoB")
    sessions.record_pick(conn, session_id, winner="SmallRakdos", loser="MonoB")
    sessions.record_pick(conn, session_id, winner="BigRakdos", loser="SmallRakdos")

    board = sessions.get_leaderboard(conn, limit=1, colors="B", color_mode="exact")
    assert len(board) == 1
    assert board[0].name == "MonoB"


def test_leaderboard_empty_when_color_filter_matches_nothing(conn):
    session_id = sessions.create_session(conn, [_commander("MonoB", colors="B"), _commander("MonoG", colors="G")])
    sessions.record_pick(conn, session_id, winner="MonoB", loser="MonoG")

    assert sessions.get_leaderboard(conn, colors="U", color_mode="exact") == []


def test_reset_leaderboard_clears_ratings(conn):
    session_id = sessions.create_session(conn, [_commander("A"), _commander("B")])
    sessions.record_pick(conn, session_id, winner="A", loser="B")
    assert sessions.get_leaderboard(conn) != []

    sessions.reset_leaderboard(conn)
    assert sessions.get_leaderboard(conn) == []


def test_reset_leaderboard_does_not_touch_session_history(conn):
    session_id = sessions.create_session(conn, [_commander("A"), _commander("B")])
    sessions.record_pick(conn, session_id, winner="A", loser="B")

    sessions.reset_leaderboard(conn)

    # The session itself, its rounds_completed, and its own per-session
    # rankings are all untouched -- only the cross-session
    # commander_ratings table was wiped.
    info = sessions.get_session(conn, session_id)
    assert info.rounds_completed == 1
    ranked = {r.name: r.rating for r in sessions.get_rankings(conn, session_id)}
    assert ranked["A"] > 1000.0
    assert ranked["B"] < 1000.0


def test_new_session_after_reset_seeds_at_default_rating(conn):
    session_id = sessions.create_session(conn, [_commander("A"), _commander("B")])
    sessions.record_pick(conn, session_id, winner="A", loser="B")
    sessions.reset_leaderboard(conn)

    second = sessions.create_session(conn, [_commander("A"), _commander("C")])
    details = sessions.get_candidates(conn, second)
    assert details["A"].rating == pytest.approx(1000.0)


# ---- bracket mode ----


def test_create_session_bracket_rejects_non_power_of_two_size(conn):
    with pytest.raises(sessions.SessionError):
        sessions.create_session(conn, [_commander(n) for n in "ABC"], mode="bracket")
    with pytest.raises(sessions.SessionError):
        sessions.create_session(conn, [_commander(n) for n in "ABCDE"], mode="bracket")


def _seed_ratings_round_robin(conn, names):
    """Play every pair in `names` once so the resulting all-time ratings
    are strictly ordered by `names`' given order (first beats everyone,
    second beats everyone but the first, etc.) -- via the public
    record_pick API, not by poking commander_ratings directly."""
    session_id = sessions.create_session(conn, [_commander(n) for n in names])
    for i, winner in enumerate(names):
        for loser in names[i + 1 :]:
            sessions.record_pick(conn, session_id, winner=winner, loser=loser)


def test_create_session_bracket_seeds_round_one_by_rating(conn):
    _seed_ratings_round_robin(conn, ["A", "B", "C", "D"])  # A > B > C > D

    bracket_id = sessions.create_session(conn, [_commander(n) for n in "ABCD"], mode="bracket")
    bracket = sessions.get_bracket(conn, bracket_id)

    assert len(bracket.rounds) == 2  # 4 entrants -> 2 rounds
    round1 = {frozenset((m.seed_a, m.seed_b)) for m in bracket.rounds[0]}
    # elo.bracket_seed_order(4) == [1, 4, 2, 3] -> slot pairs (seed1, seed4), (seed2, seed3)
    assert round1 == {frozenset(("A", "D")), frozenset(("B", "C"))}


def test_bracket_full_playthrough_to_champion(conn):
    _seed_ratings_round_robin(conn, ["A", "B", "C", "D"])
    bracket_id = sessions.create_session(conn, [_commander(n) for n in "ABCD"], mode="bracket")

    round_num, slot, seed_a, seed_b = sessions.next_bracket_match(conn, bracket_id)
    assert round_num == 1
    assert {seed_a, seed_b} == {"A", "D"}
    sessions.record_bracket_pick(conn, bracket_id, winner="A", loser="D")

    info = sessions.get_session(conn, bracket_id)
    assert info.rounds_completed == 0  # round 1 isn't fully decided yet

    round_num, slot, seed_a, seed_b = sessions.next_bracket_match(conn, bracket_id)
    assert round_num == 1
    assert {seed_a, seed_b} == {"B", "C"}
    sessions.record_bracket_pick(conn, bracket_id, winner="B", loser="C")

    info = sessions.get_session(conn, bracket_id)
    assert info.status == "active"
    assert info.rounds_completed == 1  # round 1 is now fully decided

    round_num, slot, seed_a, seed_b = sessions.next_bracket_match(conn, bracket_id)
    assert round_num == 2
    assert {seed_a, seed_b} == {"A", "B"}
    sessions.record_bracket_pick(conn, bracket_id, winner="A", loser="B")

    info = sessions.get_session(conn, bracket_id)
    assert info.status == "complete"
    assert info.rounds_completed == 2

    bracket = sessions.get_bracket(conn, bracket_id)
    assert bracket.champion == "A"
    assert sessions.next_bracket_match(conn, bracket_id) is None


def test_record_bracket_pick_rejects_mismatched_pair(conn):
    _seed_ratings_round_robin(conn, ["A", "B", "C", "D"])
    bracket_id = sessions.create_session(conn, [_commander(n) for n in "ABCD"], mode="bracket")

    # A/D and B/C are round 1's actual matches -- A vs B hasn't happened yet.
    with pytest.raises(sessions.SessionError):
        sessions.record_bracket_pick(conn, bracket_id, winner="A", loser="B")


def test_bracket_pick_uses_bracket_k_factor(conn):
    session_id = sessions.create_session(conn, [_commander(n) for n in "ABCD"], mode="bracket")
    sessions.record_bracket_pick(conn, session_id, winner="A", loser="D")

    expected_winner, expected_loser = elo.update_ratings(1000.0, 1000.0, k=elo.BRACKET_K_FACTOR)
    ranked = {r.name: r.rating for r in sessions.get_rankings(conn, session_id)}
    assert ranked["A"] == pytest.approx(expected_winner)
    assert ranked["D"] == pytest.approx(expected_loser)
    # Confirm it's actually gentler than the duel K-factor, not equal to it.
    duel_winner, _ = elo.update_ratings(1000.0, 1000.0)
    assert ranked["A"] < duel_winner


def test_bracket_pick_feeds_all_time_leaderboard(conn):
    session_id = sessions.create_session(conn, [_commander(n) for n in "ABCD"], mode="bracket")
    sessions.record_bracket_pick(conn, session_id, winner="A", loser="D")

    leaderboard = {r.name: r.rating for r in sessions.get_leaderboard(conn)}
    assert leaderboard["A"] > 1000.0
    assert leaderboard["D"] < 1000.0
