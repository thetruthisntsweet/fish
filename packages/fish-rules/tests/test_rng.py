"""Tests for fish_rules.rng (T2.1 subtask 6)."""

from hypothesis import given
from hypothesis import strategies as st

from fish_rules.rng import SplitMix64

U64 = st.integers(min_value=0, max_value=2**64 - 1)


def test_splitmix64_matches_published_reference() -> None:
    """Reference outputs for seed 1234567, from Vigna's splitmix64.c and Java's SplittableRandom."""
    rng = SplitMix64(1234567)
    assert [rng.next_u64() for _ in range(5)] == [
        6457827717110365317,
        3203168211198807973,
        9817491932198370423,
        4593380528125082431,
        16408922859458223821,
    ]


@given(U64)
def test_same_state_same_sequence(state: int) -> None:
    a, b = SplitMix64(state), SplitMix64(state)
    assert [a.next_u64() for _ in range(10)] == [b.next_u64() for _ in range(10)]


@given(U64)
def test_outputs_are_64_bit_unsigned(state: int) -> None:
    rng = SplitMix64(state)
    assert all(0 <= rng.next_u64() < 2**64 for _ in range(10))