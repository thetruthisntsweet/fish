"""Tests for fish_rules.cards: seats, teams, cards, sets and the deal (R.1)."""

from collections.abc import Callable

import pytest
from hypothesis import given
from hypothesis import strategies as st

from fish_rules.cards import (
    CARD_NAMES,
    CARDS,
    HAND_SIZE,
    NUM_CARDS,
    NUM_SEATS,
    NUM_SETS,
    SEATS,
    SET_NAMES,
    SETS,
    card_from_name,
    card_name,
    check_card,
    check_seat,
    check_set,
    check_team,
    deal,
    first_player,
    next_teammate,
    opponent_team,
    set_cards,
    set_of,
    team_of,
    team_seats,
)

U64 = st.integers(min_value=0, max_value=2**64 - 1)


# ---------------------------------------------------------------- R.1.1 seats and teams


def test_r1_1_six_seats() -> None:
    """R.1.1: six players in seats 0 to 5."""
    assert SEATS == (0, 1, 2, 3, 4, 5)


def test_r1_1_teams_sit_together() -> None:
    """R.1.1: seats 0, 1, 2 form one team and seats 3, 4, 5 the other."""
    assert [team_of(seat) for seat in SEATS] == [0, 0, 0, 1, 1, 1]
    assert team_seats(0) == (0, 1, 2)
    assert team_seats(1) == (3, 4, 5)
    assert opponent_team(0) == 1
    assert opponent_team(1) == 0


def test_r1_1_next_teammate_clockwise_wraps_within_team() -> None:
    """R.1.1 / R.8.1: the next teammate clockwise, as in the example 1, 4, 2, 5, 0, 3."""
    assert [next_teammate(seat) for seat in SEATS] == [1, 2, 0, 4, 5, 3]


# ---------------------------------------------------------------- R.1.2 and R.1.3 deck and sets


def test_r1_2_deck_has_54_distinct_cards() -> None:
    """R.1.2: 52 standard cards plus a red and a black joker, all distinct."""
    assert len(CARDS) == NUM_CARDS == 54
    assert len(set(CARD_NAMES)) == 54
    assert "RJ" in CARD_NAMES
    assert "BJ" in CARD_NAMES
    standard = {rank + suit for suit in "CDHS" for rank in (*"23456789", "10", *"JQKA")}
    assert set(CARD_NAMES) - {"RJ", "BJ"} == standard


def test_r1_3_nine_sets_of_six() -> None:
    """R.1.3: nine sets of six cards that together make up the deck."""
    assert len(SETS) == NUM_SETS == 9
    assert len(SET_NAMES) == 9
    all_cards = [card for set_id in SETS for card in set_cards(set_id)]
    assert sorted(all_cards) == list(CARDS)
    assert all(len(set_cards(set_id)) == 6 for set_id in SETS)
    assert all(set_of(card) == set_id for set_id in SETS for card in set_cards(set_id))


@pytest.mark.parametrize(
    ("set_name", "cards"),
    [
        ("low-C", "2C 3C 4C 5C 6C 7C"),
        ("low-D", "2D 3D 4D 5D 6D 7D"),
        ("low-H", "2H 3H 4H 5H 6H 7H"),
        ("low-S", "2S 3S 4S 5S 6S 7S"),
        ("high-C", "9C 10C JC QC KC AC"),
        ("high-D", "9D 10D JD QD KD AD"),
        ("high-H", "9H 10H JH QH KH AH"),
        ("high-S", "9S 10S JS QS KS AS"),
        ("eights", "8C 8D 8H 8S RJ BJ"),
    ],
)
def test_r1_3_set_contents(set_name: str, cards: str) -> None:
    """R.1.3: low sets are 2-7, high sets 9-A, and the 9th set is the four 8s and both jokers.
    Also freezes the card numbering (docs/determinism.md §6)."""
    set_id = SET_NAMES.index(set_name)
    assert [card_name(card) for card in set_cards(set_id)] == cards.split()


def test_card_names_round_trip() -> None:
    assert all(card_from_name(card_name(card)) == card for card in CARDS)


def test_card_numbering_is_frozen() -> None:
    """docs/determinism.md §6: card = 6 * set + position."""
    assert card_from_name("2C") == 0
    assert card_from_name("10H") == 37
    assert card_from_name("RJ") == 52
    assert card_from_name("BJ") == 53


def test_unknown_card_name_rejected() -> None:
    with pytest.raises(ValueError, match="unknown card name"):
        card_from_name("1C")


@pytest.mark.parametrize(
    ("check", "size"), [(check_seat, 6), (check_team, 2), (check_card, 54), (check_set, 9)]
)
def test_checks_accept_valid_and_reject_out_of_range(
    check: Callable[[object], int], size: int
) -> None:
    assert [check(i) for i in range(size)] == list(range(size))
    for bad in (-1, size):
        with pytest.raises(ValueError, match=r"must be in \[0, "):
            check(bad)


@pytest.mark.parametrize("bad", [True, 1.0, "1", None])
def test_checks_reject_non_ints(bad: object) -> None:
    with pytest.raises(TypeError, match="must be an int"):
        check_card(bad)


# ---------------------------------------------------------------- R.1.4 the deal


@given(U64)
def test_r1_4_deal_gives_nine_cards_to_each_of_six_players(seed: int) -> None:
    """R.1.4: the seed deals nine cards to each player; every card is dealt exactly once."""
    hands = deal(seed)
    assert len(hands) == NUM_SEATS
    assert all(len(hand) == HAND_SIZE for hand in hands)
    assert sorted(card for hand in hands for card in hand) == list(CARDS)
    assert all(list(hand) == sorted(hand) for hand in hands)


@given(U64)
def test_r1_4_deal_and_first_player_are_determined_by_the_seed(seed: int) -> None:
    """R.1.4: every game is generated from its seed."""
    assert deal(seed) == deal(seed)
    assert first_player(seed) == first_player(seed)
    assert 0 <= first_player(seed) < NUM_SEATS


def test_r1_4_different_seeds_give_different_deals() -> None:
    assert len({deal(seed) for seed in range(50)}) == 50


def test_r1_4_first_player_uses_every_seat() -> None:
    assert {first_player(seed) for seed in range(200)} == set(SEATS)


@pytest.mark.parametrize("bad", [-1, 2**64])
def test_r1_4_seed_out_of_range_rejected(bad: int) -> None:
    with pytest.raises(ValueError, match="game_seed"):
        deal(bad)
    with pytest.raises(ValueError, match="game_seed"):
        first_player(bad)
