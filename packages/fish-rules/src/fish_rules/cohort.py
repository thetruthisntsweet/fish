"""The held-out cohort draw (docs/corpus.md §2.1, T1.1 §5.1).

At sign-up, before a first game, each player is assigned to the held-out cohort or not by
their sign-up number. Sign-ups are taken in blocks of ``BLOCK``; in each block exactly
``PER_BLOCK`` positions are in the cohort, drawn from stream ``cohort`` of the cohort seed with
the block number as the index. So the cohort is exactly 15% of sign-ups at every multiple of
20, and a player's assignment depends only on the seed and their sign-up number.

FROZEN as ``fish-cohort-v1``: the draw is the first ``PER_BLOCK`` entries of a shuffle of
``range(BLOCK)`` (``SplitMix64.shuffled``), sorted. Changing it reassigns players who have
already played; it needs a new name and a decision log entry.
"""

from typing import Final

from fish_rules.rng import stream

COHORT_DRAW: Final = "fish-cohort-v1"
"""Names this draw. Recorded with the cohort seed when the corpus is frozen."""

BLOCK: Final = 20
"""Sign-ups per block."""

PER_BLOCK: Final = 3
"""Cohort positions in each block: 3 in 20 is 15%."""


def cohort_positions(cohort_seed: int, block: int) -> tuple[int, ...]:
    """The positions, ascending, within block ``block`` (sign-ups ``BLOCK * block`` onward)
    that are in the cohort."""
    order = stream(cohort_seed, "cohort", block).shuffled(range(BLOCK))
    return tuple(sorted(order[:PER_BLOCK]))


def in_cohort(cohort_seed: int, signup_number: int) -> bool:
    """Whether the player with sign-up number ``signup_number`` (0, 1, 2, ...) is in the
    held-out cohort."""
    if type(signup_number) is not int:  # bools are ints to isinstance
        raise TypeError(f"signup_number must be an int, got {type(signup_number).__name__}")
    if signup_number < 0:
        raise ValueError(f"signup_number must be at least 0, got {signup_number}")
    block, position = divmod(signup_number, BLOCK)
    return position in cohort_positions(cohort_seed, block)
