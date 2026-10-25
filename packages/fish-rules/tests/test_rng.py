"""Tests for fish_rules.rng (T2.1 subtask 6)."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from fish_rules.rng import RNG_ALGORITHM, STREAM_NAMES, SplitMix64, StreamName, stream

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


# ---------------------------------------------------------------- streams (6.2)


@pytest.mark.parametrize(
    ("game_seed", "name", "index", "expected"),
    [
        (0, "deal", 0, [13005668785293732255, 5349247664637781293, 7545985798254693917]),
        (42, "deal", 0, [3704813143314896102, 17132994753748584267, 12187306368531682049]),
        (42, "priority", 3, [5720394983243077335, 14909900981371132404, 2586259669756280784]),
        (
            2**64 - 1,
            "bot_policy",
            2**64 - 1,
            [13677204693936284854, 14656210551439091564, 11473732172714903504],
        ),
    ],
)
def test_stream_matches_frozen_values(
    game_seed: int, name: StreamName, index: int, expected: list[int]
) -> None:
    """Frozen outputs, cross-checked against an independent Node.js implementation."""
    rng = stream(game_seed, name, index)
    assert [rng.next_u64() for _ in range(3)] == expected


def test_stream_names_are_the_seven_in_section_2() -> None:
    assert STREAM_NAMES == (
        "deal",
        "first_player",
        "priority",
        "tiebreak",
        "bot_delay",
        "bot_policy",
        "cohort",
    )


@given(U64, st.sampled_from(STREAM_NAMES), U64)
def test_same_inputs_same_stream(game_seed: int, name: StreamName, index: int) -> None:
    a, b = stream(game_seed, name, index), stream(game_seed, name, index)
    assert [a.next_u64() for _ in range(5)] == [b.next_u64() for _ in range(5)]


@given(U64)
def test_every_name_gives_a_different_stream(game_seed: int) -> None:
    firsts = {stream(game_seed, name).next_u64() for name in STREAM_NAMES}
    assert len(firsts) == len(STREAM_NAMES)


@given(U64, st.sampled_from(STREAM_NAMES))
def test_neighbouring_indices_give_different_streams(game_seed: int, name: StreamName) -> None:
    firsts = {stream(game_seed, name, i).next_u64() for i in range(10)}
    assert len(firsts) == 10


def test_index_defaults_to_zero() -> None:
    assert stream(7, "deal").next_u64() == stream(7, "deal", 0).next_u64()


@pytest.mark.parametrize("bad", [-1, 2**64])
def test_seed_out_of_range_is_rejected(bad: int) -> None:
    with pytest.raises(ValueError, match="game_seed"):
        stream(bad, "deal")


@pytest.mark.parametrize("bad", [-1, 2**64])
def test_index_out_of_range_is_rejected(bad: int) -> None:
    with pytest.raises(ValueError, match="index"):
        stream(0, "deal", bad)


@pytest.mark.parametrize("bad", [True, 1.0, "1", None])
def test_non_int_seed_is_rejected(bad: object) -> None:
    with pytest.raises(TypeError, match="game_seed"):
        stream(bad, "deal")  # pyright: ignore[reportArgumentType]


def test_unknown_stream_name_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown stream name"):
        stream(0, "runout")  # pyright: ignore[reportArgumentType]


# ---------------------------------------------------------------- bounded integers (6.3)

# Frozen outputs for stream(42, "deal"), cross-checked against an independent Node.js version.
BELOW_VECTORS = [
    (1, [0, 0, 0, 0, 0, 0]),
    (2, [0, 1, 1, 0, 0, 0]),
    (3, [2, 0, 2, 1, 1, 0]),
    (6, [2, 3, 5, 4, 4, 0]),
    (54, [32, 39, 29, 22, 34, 18]),
    (
        2**63 + 1,
        [
            7909622716893808458,
            2963934331676906240,
            6389450727017529523,
            16107916182958393,
            37368867601736973,
            4112457410559145480,
        ],
    ),
    (
        2**64,
        [
            3704813143314896102,
            17132994753748584267,
            12187306368531682049,
            15612822763872305332,
            9239479953037734202,
            9260740904456512782,
        ],
    ),
]


@pytest.mark.parametrize(("n", "expected"), BELOW_VECTORS)
def test_below_matches_frozen_values(n: int, expected: list[int]) -> None:
    rng = stream(42, "deal")
    assert [rng.below(n) for _ in range(6)] == expected


def test_below_rejects_low_draws_and_draws_again() -> None:
    """State 3's first draw falls under the threshold for n = 2**63 + 1, so the second is used."""
    n = 2**63 + 1
    raw = SplitMix64(3)
    first, second = raw.next_u64(), raw.next_u64()
    assert first < (2**64 - n) % n <= second
    rng = SplitMix64(3)
    assert rng.below(n) == second % n
    assert rng.next_u64() == raw.next_u64()  # exactly two draws were consumed


def test_below_one_is_zero_and_still_draws() -> None:
    rng, twin = SplitMix64(9), SplitMix64(9)
    assert rng.below(1) == 0
    twin.next_u64()
    assert rng.next_u64() == twin.next_u64()


@given(U64)
def test_below_two_to_the_64_is_the_raw_draw(state: int) -> None:
    assert SplitMix64(state).below(2**64) == SplitMix64(state).next_u64()


@given(U64, st.integers(min_value=1, max_value=2**64))
def test_below_is_in_range(state: int, n: int) -> None:
    assert 0 <= SplitMix64(state).below(n) < n


@pytest.mark.parametrize("bad", [0, -1, 2**64 + 1])
def test_below_out_of_range_n_is_rejected(bad: int) -> None:
    with pytest.raises(ValueError, match="n must be"):
        SplitMix64(0).below(bad)


@pytest.mark.parametrize("bad", [True, 3.0, "3"])
def test_below_non_int_n_is_rejected(bad: object) -> None:
    with pytest.raises(TypeError, match="n must be"):
        SplitMix64(0).below(bad)  # pyright: ignore[reportArgumentType]


def test_below_three_is_uniform() -> None:
    """60,000 draws from a fixed seed: each value within 3% of 20,000. Deterministic."""
    rng = stream(1, "deal")
    counts = [0, 0, 0]
    for _ in range(60_000):
        counts[rng.below(3)] += 1
    assert all(19_400 <= c <= 20_600 for c in counts)


def test_between_matches_frozen_values() -> None:
    rng = stream(42, "bot_delay")
    assert [rng.between(1500, 4000) for _ in range(6)] == [2524, 2089, 2641, 2201, 1566, 3831]


@given(U64, st.integers(-(2**70), 2**70), st.integers(0, 2**64 - 1))
def test_between_is_in_range(state: int, lo: int, width: int) -> None:
    assert lo <= SplitMix64(state).between(lo, lo + width) <= lo + width


def test_between_single_value() -> None:
    assert SplitMix64(0).between(5, 5) == 5


def test_between_rejects_reversed_bounds() -> None:
    with pytest.raises(ValueError, match="lo must not exceed hi"):
        SplitMix64(0).between(4000, 1500)


def test_between_rejects_too_wide_a_range() -> None:
    with pytest.raises(ValueError, match="n must be"):
        SplitMix64(0).between(0, 2**64)


@pytest.mark.parametrize(("lo", "hi", "what"), [(True, 5, "lo"), (0, 5.0, "hi")])
def test_between_non_int_bounds_are_rejected(lo: object, hi: object, what: str) -> None:
    with pytest.raises(TypeError, match=what):
        SplitMix64(0).between(lo, hi)  # pyright: ignore[reportArgumentType]


def test_choice_matches_frozen_values() -> None:
    rng = stream(42, "bot_policy")
    assert [rng.choice("abcdef") for _ in range(6)] == ["a", "a", "b", "f", "c", "b"]


@given(U64, st.lists(st.integers(), min_size=1, max_size=60))
def test_choice_is_items_at_below(state: int, items: list[int]) -> None:
    assert SplitMix64(state).choice(items) == items[SplitMix64(state).below(len(items))]


def test_choice_from_empty_is_rejected() -> None:
    with pytest.raises(ValueError, match="empty"):
        SplitMix64(0).choice([])


# ---------------------------------------------------------------- shuffle (6.4)


SHUFFLE_42_RANGE_10 = [5, 8, 0, 7, 9, 6, 4, 1, 3, 2]  # cross-checked against Node.js


def test_shuffled_matches_frozen_values() -> None:
    rng = stream(42, "deal")
    assert rng.shuffled(range(10)) == SHUFFLE_42_RANGE_10


@given(U64, st.lists(st.integers(), max_size=60))
def test_shuffled_is_a_permutation(state: int, items: list[int]) -> None:
    assert sorted(SplitMix64(state).shuffled(items)) == sorted(items)


@given(U64, st.lists(st.integers(), max_size=60))
def test_shuffled_leaves_input_unchanged(state: int, items: list[int]) -> None:
    before = list(items)
    SplitMix64(state).shuffled(items)
    assert items == before


@given(U64, st.integers(min_value=0, max_value=60))
def test_shuffled_uses_exactly_n_minus_1_draws(state: int, n: int) -> None:
    rng, twin = SplitMix64(state), SplitMix64(state)
    rng.shuffled(range(n))
    for i in range(n - 1, 0, -1):
        twin.below(i + 1)
    assert rng.next_u64() == twin.next_u64()


def test_shuffled_empty_and_single() -> None:
    assert SplitMix64(0).shuffled([]) == []
    assert SplitMix64(0).shuffled(["x"]) == ["x"]


def test_shuffle_of_three_is_uniform() -> None:
    """60,000 shuffles from a fixed seed: each of the 6 orders within 3% of 10,000."""
    rng = stream(2, "deal")
    counts: dict[tuple[int, ...], int] = {}
    for _ in range(60_000):
        key = tuple(rng.shuffled(range(3)))
        counts[key] = counts.get(key, 0) + 1
    assert len(counts) == 6
    assert all(9_700 <= c <= 10_300 for c in counts.values())


def test_card_zero_lands_evenly_across_54_positions() -> None:
    """Chi-square over where item 0 lands in 10,800 shuffles of 54 (200 expected per slot).

    90.57 is the 0.1% critical value for 53 degrees of freedom. Fixed seed: deterministic.
    """
    rng = stream(3, "deal")
    counts = [0] * 54
    for _ in range(10_800):
        counts[rng.shuffled(range(54)).index(0)] += 1
    chi2 = sum((c - 200) ** 2 / 200 for c in counts)
    assert chi2 < 90.57


# ---------------------------------------------------------------- version pin (6.5)


def test_rng_algorithm_is_pinned() -> None:
    """Changing this string means the algorithm changed: that needs a new ruleset version."""
    assert RNG_ALGORITHM == "splitmix64-sha256-v1"
