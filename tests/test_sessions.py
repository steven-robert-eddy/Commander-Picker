import random

import pytest

from commander_picker import sessions
from commander_picker.pool import Commander


def _commander(name, decks=1000, colors="BR"):
    return Commander(
        name=name,
        color_identity=colors,
        num_decks=decks,
        edhrec_url=f"https://edhrec.com/commanders/{name.lower()}",
        themes=(),
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
