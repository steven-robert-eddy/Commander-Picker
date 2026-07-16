import random

import pytest

from commander_picker import elo


def test_expected_score_equal_ratings_is_fifty_fifty():
    assert elo.expected_score(1000, 1000) == pytest.approx(0.5)


def test_expected_score_favors_higher_rating():
    assert elo.expected_score(1200, 1000) > 0.5
    assert elo.expected_score(1000, 1200) < 0.5


def test_update_ratings_winner_gains_loser_loses():
    new_winner, new_loser = elo.update_ratings(1000, 1000)
    assert new_winner > 1000
    assert new_loser < 1000
    # Symmetric for equal starting ratings.
    assert (new_winner - 1000) == pytest.approx(1000 - new_loser)


def test_update_ratings_upset_moves_more_than_expected_win():
    # A big underdog winning should gain more than a coin-flip winner.
    upset_winner, _ = elo.update_ratings(winner_rating=800, loser_rating=1200)
    expected_winner, _ = elo.update_ratings(winner_rating=1000, loser_rating=1000)
    assert (upset_winner - 800) > (expected_winner - 1000)


def test_target_round_count_scales_with_pool_size():
    small = elo.target_round_count(4)
    large = elo.target_round_count(40)
    assert small > 0
    assert large > small


def test_target_round_count_trivial_pool():
    assert elo.target_round_count(0) == 0
    assert elo.target_round_count(1) == 0


def test_choose_pairing_returns_none_below_two_candidates():
    assert elo.choose_pairing([], {}, 0, 0, set()) is None
    assert elo.choose_pairing(["A"], {"A": 1000}, 0, 0, set()) is None


def test_choose_pairing_prefers_fresh_pairs():
    names = ["A", "B", "C"]
    ratings = {n: 1000.0 for n in names}
    already = {frozenset(("A", "B")), frozenset(("A", "C"))}
    rng = random.Random(1)
    for _ in range(20):
        pair = elo.choose_pairing(names, ratings, 0, 10, already, rng=rng)
        assert pair is not None
        assert frozenset(pair) == frozenset(("B", "C"))


def test_choose_pairing_falls_back_to_repeat_when_pool_exhausted():
    names = ["A", "B"]
    ratings = {"A": 1000.0, "B": 1000.0}
    already = {frozenset(("A", "B"))}
    rng = random.Random(1)
    pair = elo.choose_pairing(names, ratings, 0, 10, already, rng=rng)
    assert frozenset(pair) == frozenset(("A", "B"))


def test_choose_pairing_late_phase_prefers_rating_adjacent():
    names = ["low", "mid", "high"]
    ratings = {"low": 800.0, "mid": 1000.0, "high": 1400.0}
    rng = random.Random(7)
    # Late phase (rounds_completed >= target_rounds // 3): should never
    # pair the two extremes (low/high) since mid is always the adjacent
    # neighbor of both in sorted order.
    for _ in range(30):
        pair = elo.choose_pairing(names, ratings, rounds_completed=10, target_rounds=9, already_paired=set(), rng=rng)
        assert frozenset(pair) != frozenset(("low", "high"))
