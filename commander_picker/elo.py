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
# Half the duel K-factor. A duel session gives each commander several
# comparisons spread across the session, so one bad early result gets
# balanced out later -- Elo's self-correction gets to work. A
# single-elimination bracket gives a round-1 loser exactly one comparison
# for the whole session, then nothing to average it out, and that result
# is permanent in commander_ratings. The seeded-by-rating bracket design
# already keeps *expected*-outcome swings small on its own (K * (1 -
# expected) is small when the favorite wins as expected); the real risk
# is variance from too few games per commander, which this dampens.
BRACKET_K_FACTOR = 16.0

# For real multiplayer EDH pod games (sessions.py's pod tracker) --
# one shot per game, same as a bracket match (no averaging
# across a session), so it doesn't deserve the duel's full K_FACTOR.
# But a pod's outcome carries more noise per game than a seeded bracket
# match does: turn order, multiplayer politics/targeting, and table
# dynamics all swing a single game's result in a way a seeded 1v1
# bracket match doesn't, so it shouldn't be dampened as hard as
# BRACKET_K_FACTOR either. Untuned against real data -- a reasonable
# starting point between the two, not a derived constant.
MULTIPLAYER_K_FACTOR = 24.0

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


def multiplayer_expected_scores(ratings: list[float]) -> list[float]:
    """Bradley-Terry-Luce softmax generalization of expected_score to N players.

    Each rating's "win strength" is 10**(rating/400), normalized so the
    whole field sums to 1 -- an N-player field starts near 1/N expected
    win probability each (not 50/50, the way naively pairing every
    participant against every other one would imply). Used identically
    for player ratings and deck ratings in the pod tracker -- call this
    twice per game, once per rating list, rather than modeling
    players-and-decks jointly.
    """
    strengths = [10 ** (r / 400.0) for r in ratings]
    total = sum(strengths)
    return [s / total for s in strengths]


def update_multiplayer_ratings(
    ratings: list[float], winner_index: int, k: float = MULTIPLAYER_K_FACTOR
) -> list[float]:
    """New ratings after one N-player game with a single winner.

    Winner's actual score is 1, everyone else's is 0 (single-winner-
    take-all -- this is how EDH pods are almost always tracked
    casually: one winner, no ranked placements among the rest).
    new_i = ratings[i] + k * (actual_i - expected_i). Zero-sum overall
    since expected_i sums to 1 across the field, same as actual_i does.
    """
    expected = multiplayer_expected_scores(ratings)
    return [
        r + k * ((1.0 if i == winner_index else 0.0) - expected[i])
        for i, r in enumerate(ratings)
    ]


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


def is_valid_bracket_size(n: int) -> bool:
    """A single-elimination bracket needs an exact power of two >= 4.

    Anything else is rejected rather than padded with byes or trimmed --
    see sessions.create_session/cli.py/web/app.py for where this is
    enforced before a bracket session is ever created.
    """
    return n >= 4 and (n & (n - 1)) == 0


def bracket_round_count(n: int) -> int:
    """Number of rounds to go from `n` entrants down to a single champion."""
    return int(math.log2(n))


def bracket_seed_order(n: int) -> list[int]:
    """Standard recursive tournament-seeding permutation for `n` slots.

    Returns 1-indexed seed numbers in bracket-slot order, e.g. n=8 ->
    [1, 8, 4, 5, 2, 7, 3, 6]. Guarantees seed 1 and seed 2 can't meet
    before the final, seeds 3/4 can't meet before the semis, and so on --
    sessions.py sorts candidates best-to-worst by rating and uses this
    order to place them into round-1 slots.
    """
    if n == 1:
        return [1]
    prev = bracket_seed_order(n // 2)
    out = []
    for s in prev:
        out.append(s)
        out.append(n + 1 - s)
    return out


def bracket_round_label(round_num: int, total_rounds: int) -> str:
    """Human label for a bracket round, e.g. "Round of 16", "Quarterfinal",
    "Semifinal", "Final" -- shared by the CLI and web UI so both describe
    bracket progress the same way."""
    remaining_after = total_rounds - round_num
    if remaining_after == 0:
        return "Final"
    if remaining_after == 1:
        return "Semifinal"
    if remaining_after == 2:
        return "Quarterfinal"
    entrants = 2 ** (remaining_after + 1)
    return f"Round of {entrants}"


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
