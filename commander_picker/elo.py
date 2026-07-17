"""Elo rating math and pairing selection for the swipe picker.

Pure functions, no DB/session dependency, so the rating logic and the
pairing heuristic can be unit tested directly and reused from
`sessions.py`.
"""

from __future__ import annotations

import math
import random

DEFAULT_RATING = 1000.0
K_FACTOR = 32.0

# How many pairing attempts to try before giving up on finding a fresh
# (not-yet-compared) pair and just allowing a repeat.
_MAX_FRESH_PAIR_ATTEMPTS = 20


def expected_score(rating_a: float, rating_b: float) -> float:
    """Probability `a` beats `b`, per the standard Elo formula."""
    return 1.0 / (1.0 + 10 ** ((rating_b - rating_a) / 400.0))


def update_ratings(winner_rating: float, loser_rating: float, k: float = K_FACTOR) -> tuple[float, float]:
    """Return (new_winner_rating, new_loser_rating) after one comparison."""
    expected_winner = expected_score(winner_rating, loser_rating)
    new_winner = winner_rating + k * (1 - expected_winner)
    new_loser = loser_rating + k * (0 - (1 - expected_winner))
    return new_winner, new_loser


def target_round_count(pool_size: int) -> int:
    """Number of comparisons to reasonably separate a pool this size.

    `n * log2(n)` is a common heuristic for comparison-sort-like
    problems -- enough rounds for ratings to meaningfully separate
    without demanding an exhaustive round robin. `sessions.py` treats
    this as a hard stopping point: a session auto-finishes once
    `rounds_completed` reaches it (originally this was meant as a
    soft suggestion with sessions staying open indefinitely past it,
    but that left no visible end -- a user reported playing 70 rounds
    of a session with a target of 59 with no sign it would ever stop,
    since the web UI in particular gave no indication anything had
    changed once the target was crossed). `finish_session`/the "finish
    early" actions still let a session end before this point.
    """
    if pool_size <= 1:
        return 0
    return max(1, round(pool_size * math.log2(pool_size)))


def choose_pairing(
    candidate_names: list[str],
    ratings: dict[str, float],
    rounds_completed: int,
    target_rounds: int,
    already_paired: set[frozenset],
    rng: random.Random | None = None,
) -> tuple[str, str] | None:
    """Pick the next pair to compare.

    Early rounds (the first third of `target_rounds`) pair uniformly
    at random across the whole pool, to get initial signal everywhere.
    Later rounds sort candidates by current rating and pair a random
    one with a rating-adjacent neighbor, since close-rating matchups
    carry more discriminating signal once ratings have started to
    separate. Prefers a pair not already in `already_paired`; if
    adjacency search can't find one (a small pool can "false exhaust"
    here -- the one remaining fresh pair can end up non-adjacent in
    the current rating order once everything else has been compared),
    falls back to an exhaustive scan across all pairs before finally
    accepting a genuine repeat once the pool really has seen every
    combination.

    Returns None if there are fewer than 2 candidates.
    """
    rng = rng or random.Random()
    if len(candidate_names) < 2:
        return None

    def is_fresh(a: str, b: str) -> bool:
        return frozenset((a, b)) not in already_paired

    early_phase = rounds_completed < max(1, target_rounds // 3)

    if early_phase:
        for _ in range(_MAX_FRESH_PAIR_ATTEMPTS):
            a, b = rng.sample(candidate_names, 2)
            if is_fresh(a, b):
                return (a, b)
        return tuple(rng.sample(candidate_names, 2))

    sorted_names = sorted(candidate_names, key=lambda n: ratings[n])
    for _ in range(_MAX_FRESH_PAIR_ATTEMPTS):
        i = rng.randrange(len(sorted_names) - 1)
        a, b = sorted_names[i], sorted_names[i + 1]
        if is_fresh(a, b):
            return (a, b)

    # Adjacency-only search can "false exhaust" on a small pool: if the
    # one remaining fresh pair happens to be non-adjacent in the
    # current rating order (e.g. the two extremes, with everything
    # else already compared and sorted between them), the loop above
    # never finds it even though the pool isn't actually exhausted.
    # Before accepting a genuine repeat, fall back to an exhaustive
    # scan across all pairs for any fresh one.
    all_fresh = [
        (a, b)
        for idx, a in enumerate(sorted_names)
        for b in sorted_names[idx + 1 :]
        if is_fresh(a, b)
    ]
    if all_fresh:
        return rng.choice(all_fresh)

    i = rng.randrange(len(sorted_names) - 1)
    return (sorted_names[i], sorted_names[i + 1])
