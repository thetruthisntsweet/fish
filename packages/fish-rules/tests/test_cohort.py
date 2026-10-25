"""Tests for fish_rules.cohort: the held-out cohort is exactly 3 in every 20 sign-ups, drawn
from a frozen stream (docs/corpus.md §2.1). ``vectors/cohort_v1.json`` was written once by
``scripts/make_cohort_vectors.py`` and is also checked by ``scripts/verify_rng_vectors.mjs``."""

import json
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from fish_rules.cohort import BLOCK, COHORT_DRAW, PER_BLOCK, cohort_positions, in_cohort
from fish_rules.rng import RNG_ALGORITHM

U64 = st.integers(min_value=0, max_value=2**64 - 1)
VECTORS: dict[str, Any] = json.loads(
    (Path(__file__).parent / "vectors" / "cohort_v1.json").read_text(encoding="utf-8")
)


def test_vectors_are_for_this_draw() -> None:
    assert VECTORS["algorithm"] == RNG_ALGORITHM
    assert VECTORS["draw"] == COHORT_DRAW == "fish-cohort-v1"
    assert (VECTORS["block"], VECTORS["per_block"]) == (BLOCK, PER_BLOCK) == (20, 3)
    assert len(VECTORS["positions"]) == 17


@pytest.mark.parametrize(
    "case", VECTORS["positions"], ids=lambda c: f"seed={c['seed']},block={c['block']}"
)
def test_frozen_positions(case: dict[str, Any]) -> None:
    positions = cohort_positions(int(case["seed"]), int(case["block"]))
    assert list(positions) == case["positions"]


@given(U64, U64)
def test_every_block_has_exactly_three_distinct_positions(seed: int, block: int) -> None:
    positions = cohort_positions(seed, block)
    assert len(set(positions)) == PER_BLOCK
    assert positions == tuple(sorted(positions))
    assert all(0 <= p < BLOCK for p in positions)


@given(U64, st.integers(min_value=1, max_value=50))
def test_the_cohort_is_exactly_15_percent_at_every_multiple_of_20(seed: int, blocks: int) -> None:
    members = sum(in_cohort(seed, n) for n in range(BLOCK * blocks))
    assert members * 100 == 15 * BLOCK * blocks


@given(U64, st.integers(min_value=0, max_value=10**6))
def test_assignment_is_the_block_draw(seed: int, signup_number: int) -> None:
    block, position = divmod(signup_number, BLOCK)
    assert in_cohort(seed, signup_number) == (position in cohort_positions(seed, block))


def test_different_seeds_give_different_cohorts() -> None:
    assert {cohort_positions(seed, 0) for seed in range(20)} != {cohort_positions(0, 0)}


@pytest.mark.parametrize(
    ("value", "error"), [(-1, ValueError), (True, TypeError), (1.0, TypeError)]
)
def test_bad_signup_numbers_are_rejected(value: object, error: type[Exception]) -> None:
    with pytest.raises(error):
        in_cohort(0, value)  # pyright: ignore[reportArgumentType]
