import pytest

from commander_picker import elo, pods, store


@pytest.fixture
def conn(tmp_path):
    return store.connect(db_path=tmp_path / "sessions.db")


def _register_decks(conn, n=3):
    return [pods.register_deck(conn, f"Deck {i}") for i in range(n)]


def test_register_deck_starts_at_default_rating(conn):
    deck = pods.register_deck(conn, "Meren Value", commander_name="Meren of Clan Nel Toth", color_identity="BG", owner_name="Alice")
    assert deck.rating == elo.DEFAULT_RATING
    assert deck.games_played == 0
    assert deck.archived is False
    assert deck.commander_name == "Meren of Clan Nel Toth"
    assert deck.owner_name == "Alice"


def test_register_deck_requires_a_name(conn):
    with pytest.raises(pods.SessionError):
        pods.register_deck(conn, "   ")


def test_archive_and_unarchive_deck_round_trip(conn):
    deck = pods.register_deck(conn, "Krenko Goblins")
    archived = pods.archive_deck(conn, deck.id)
    assert archived.archived is True
    unarchived = pods.unarchive_deck(conn, deck.id)
    assert unarchived.archived is False


def test_archive_deck_unknown_id_raises(conn):
    with pytest.raises(pods.SessionError):
        pods.archive_deck(conn, "no-such-deck")


def test_list_decks_includes_archived_ordered_by_rating(conn):
    a, b = _register_decks(conn, 2)
    pods.archive_deck(conn, b.id)
    decks = pods.list_decks(conn)
    assert {d.id for d in decks} == {a.id, b.id}
    assert any(d.archived for d in decks)


def test_log_pod_game_requires_at_least_two_participants(conn):
    (deck,) = _register_decks(conn, 1)
    with pytest.raises(pods.SessionError):
        pods.log_pod_game(conn, [("Alice", deck.id, True)])


def test_log_pod_game_requires_exactly_one_winner(conn):
    a, b = _register_decks(conn, 2)
    with pytest.raises(pods.SessionError):
        pods.log_pod_game(conn, [("Alice", a.id, True), ("Bob", b.id, True)])
    with pytest.raises(pods.SessionError):
        pods.log_pod_game(conn, [("Alice", a.id, False), ("Bob", b.id, False)])


def test_log_pod_game_rejects_unknown_deck(conn):
    (a,) = _register_decks(conn, 1)
    with pytest.raises(pods.SessionError):
        pods.log_pod_game(conn, [("Alice", a.id, True), ("Bob", "no-such-deck", False)])


def test_log_pod_game_rejects_duplicate_player_or_deck(conn):
    a, b = _register_decks(conn, 2)
    with pytest.raises(pods.SessionError):
        pods.log_pod_game(conn, [("Alice", a.id, True), ("Alice", b.id, False)])
    with pytest.raises(pods.SessionError):
        pods.log_pod_game(conn, [("Alice", a.id, True), ("Bob", a.id, False)])


def test_log_pod_game_updates_player_and_deck_ratings(conn):
    a, b, c = _register_decks(conn, 3)
    game = pods.log_pod_game(conn, [("Alice", a.id, True), ("Bob", b.id, False), ("Carol", c.id, False)])
    assert len(game.participants) == 3

    winner = next(p for p in game.participants if p.is_winner)
    assert winner.player_rating_after > elo.DEFAULT_RATING
    assert winner.deck_rating_after > elo.DEFAULT_RATING

    players = {p.name: p for p in pods.list_players(conn)}
    assert players["Alice"].rating == pytest.approx(winner.player_rating_after)
    assert players["Alice"].games_played == 1
    assert players["Bob"].games_played == 1

    decks = {d.id: d for d in pods.list_decks(conn)}
    assert decks[a.id].rating == pytest.approx(winner.deck_rating_after)
    assert decks[a.id].games_played == 1


def test_log_pod_game_creates_player_rows_implicitly(conn):
    a, b = _register_decks(conn, 2)
    assert pods.list_players(conn) == []
    pods.log_pod_game(conn, [("NewPlayer1", a.id, True), ("NewPlayer2", b.id, False)])
    names = {p.name for p in pods.list_players(conn)}
    assert names == {"NewPlayer1", "NewPlayer2"}


def test_log_pod_game_second_game_uses_existing_player_rating(conn):
    a, b, c = _register_decks(conn, 3)
    pods.log_pod_game(conn, [("Alice", a.id, True), ("Bob", b.id, False), ("Carol", c.id, False)])
    alice_after_first = next(p for p in pods.list_players(conn) if p.name == "Alice").rating

    pods.log_pod_game(conn, [("Alice", a.id, False), ("Bob", b.id, True), ("Carol", c.id, False)])
    alice = next(p for p in pods.list_players(conn) if p.name == "Alice")
    assert alice.games_played == 2
    assert alice.rating != alice_after_first  # a second game moved it again


def test_delete_last_pod_game_reverts_ratings_exactly(conn):
    a, b, c = _register_decks(conn, 3)
    pods.log_pod_game(conn, [("Alice", a.id, True), ("Bob", b.id, False), ("Carol", c.id, False)])
    pods.delete_last_pod_game(conn)

    decks = {d.id: d for d in pods.list_decks(conn)}
    assert decks[a.id].rating == elo.DEFAULT_RATING
    assert decks[a.id].games_played == 0
    assert pods.list_pod_games(conn) == []


def test_delete_last_pod_game_removes_first_time_players_entirely(conn):
    a, b = _register_decks(conn, 2)
    pods.log_pod_game(conn, [("OnlyGame", a.id, True), ("AlsoOnce", b.id, False)])
    pods.delete_last_pod_game(conn)
    assert pods.list_players(conn) == []


def test_delete_last_pod_game_never_deletes_deck_rows(conn):
    a, b = _register_decks(conn, 2)
    pods.log_pod_game(conn, [("Alice", a.id, True), ("Bob", b.id, False)])
    pods.delete_last_pod_game(conn)
    deck_ids = {d.id for d in pods.list_decks(conn)}
    assert deck_ids == {a.id, b.id}


def test_delete_last_pod_game_keeps_returning_player_row_with_reverted_rating(conn):
    a, b, c = _register_decks(conn, 3)
    pods.log_pod_game(conn, [("Alice", a.id, True), ("Bob", b.id, False), ("Carol", c.id, False)])
    pods.log_pod_game(conn, [("Alice", a.id, False), ("Bob", b.id, True), ("Carol", c.id, False)])
    alice_after_first_game = [p for p in pods.list_pod_games(conn)][1].participants
    alice_rating_after_first = next(p.player_rating_after for p in alice_after_first_game if p.player_name == "Alice")

    pods.delete_last_pod_game(conn)
    alice = next(p for p in pods.list_players(conn) if p.name == "Alice")
    assert alice.games_played == 1
    assert alice.rating == pytest.approx(alice_rating_after_first)


def test_delete_last_pod_game_raises_when_nothing_logged(conn):
    with pytest.raises(pods.SessionError):
        pods.delete_last_pod_game(conn)


def test_list_pod_games_orders_most_recent_first(conn):
    a, b = _register_decks(conn, 2)
    pods.log_pod_game(conn, [("Alice", a.id, True), ("Bob", b.id, False)], notes="first")
    pods.log_pod_game(conn, [("Alice", a.id, False), ("Bob", b.id, True)], notes="second")
    games = pods.list_pod_games(conn)
    assert [g.notes for g in games] == ["second", "first"]
