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


def test_is_valid_bracket_size():
    assert not elo.is_valid_bracket_size(1)
    assert not elo.is_valid_bracket_size(2)
    assert not elo.is_valid_bracket_size(3)
    assert elo.is_valid_bracket_size(4)
    assert not elo.is_valid_bracket_size(5)
    assert not elo.is_valid_bracket_size(6)
    assert elo.is_valid_bracket_size(8)
    assert elo.is_valid_bracket_size(16)
    assert elo.is_valid_bracket_size(32)
    assert not elo.is_valid_bracket_size(24)


def test_bracket_round_count():
    assert elo.bracket_round_count(4) == 2
    assert elo.bracket_round_count(8) == 3
    assert elo.bracket_round_count(16) == 4
    assert elo.bracket_round_count(32) == 5


def test_bracket_seed_order_known_values():
    assert elo.bracket_seed_order(1) == [1]
    assert elo.bracket_seed_order(2) == [1, 2]
    assert elo.bracket_seed_order(4) == [1, 4, 2, 3]
    assert elo.bracket_seed_order(8) == [1, 8, 4, 5, 2, 7, 3, 6]


def test_bracket_seed_order_top_seeds_meet_only_in_final():
    for n in (4, 8, 16):
        order = elo.bracket_seed_order(n)
        # Slot pairs are (order[0], order[1]), (order[2], order[3]), ...
        pairs = list(zip(order[0::2], order[1::2]))
        # Seed 1 and 2 should never share a round-1 match.
        assert {1, 2} not in (set(p) for p in pairs)
        # Seeds 3 and 4 should never share a round-1 match either.
        assert {3, 4} not in (set(p) for p in pairs)


def test_bracket_round_label():
    assert elo.bracket_round_label(3, 3) == "Final"
    assert elo.bracket_round_label(2, 3) == "Semifinal"
    assert elo.bracket_round_label(1, 3) == "Quarterfinal"
    assert elo.bracket_round_label(1, 4) == "Round of 16"
    assert elo.bracket_round_label(2, 4) == "Quarterfinal"


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


# ---- multiplayer (pod tracker) Elo ----


def test_multiplayer_expected_scores_sums_to_one():
    scores = elo.multiplayer_expected_scores([1000.0, 1200.0, 800.0, 1000.0])
    assert sum(scores) == pytest.approx(1.0)


def test_multiplayer_expected_scores_equal_ratings_even_split():
    scores = elo.multiplayer_expected_scores([1000.0, 1000.0, 1000.0, 1000.0])
    assert scores == pytest.approx([0.25, 0.25, 0.25, 0.25])


def test_multiplayer_expected_scores_monotonic_in_rating():
    scores = elo.multiplayer_expected_scores([800.0, 1000.0, 1200.0])
    assert scores[0] < scores[1] < scores[2]


def test_update_multiplayer_ratings_is_zero_sum():
    ratings = [1000.0, 1100.0, 900.0, 1000.0]
    new_ratings = elo.update_multiplayer_ratings(ratings, winner_index=2)
    assert sum(new_ratings) == pytest.approx(sum(ratings))


def test_update_multiplayer_ratings_winner_always_gains():
    ratings = [1200.0, 1000.0, 800.0, 1000.0]
    for winner_index in range(len(ratings)):
        new_ratings = elo.update_multiplayer_ratings(ratings, winner_index)
        assert new_ratings[winner_index] > ratings[winner_index]


def test_update_multiplayer_ratings_underdog_gains_more_than_favorite():
    ratings = [1200.0, 1000.0, 800.0, 1000.0]
    favorite_win, _, underdog_win, _ = (
        elo.update_multiplayer_ratings(ratings, winner_index=0)[0],
        None,
        elo.update_multiplayer_ratings(ratings, winner_index=2)[2],
        None,
    )
    assert (underdog_win - ratings[2]) > (favorite_win - ratings[0])


def test_update_multiplayer_ratings_loser_above_expected_still_loses():
    # Standard Elo property generalized to N players: even a player who
    # didn't win can still lose rating if their expected score (given
    # their rating relative to the field) was higher than what "not
    # winning" (actual score 0) gives them.
    ratings = [1400.0, 1000.0, 1000.0, 1000.0]
    new_ratings = elo.update_multiplayer_ratings(ratings, winner_index=1)
    assert new_ratings[0] < ratings[0]


def test_update_multiplayer_ratings_two_player_matches_pairwise_direction():
    # Sanity cross-check against the 1v1 formula -- not an exact match
    # (different K-factors), but the direction and rough magnitude
    # should agree for a 2-player field.
    winner_new, loser_new = elo.update_ratings(1000.0, 1000.0, k=elo.MULTIPLAYER_K_FACTOR)
    mp_winner_new, mp_loser_new = elo.update_multiplayer_ratings([1000.0, 1000.0], winner_index=0)
    assert mp_winner_new == pytest.approx(winner_new)
    assert mp_loser_new == pytest.approx(loser_new)
