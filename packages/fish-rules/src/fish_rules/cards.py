"""Seats, teams, cards, sets and the deal (Canonical Ruleset R.1).

FROZEN: the card numbering and the deal below are part of every recorded game. A game is a
seed plus an event log, and the log names cards by number, so changing the numbering or the
way the shuffled deck is cut into hands breaks replay of existing games and requires a new
ruleset version (R.10). Specified in ``docs/determinism.md`` §6; checked by
``tests/vectors/deal_v1.json`` and the independent JavaScript implementation.
"""

from typing import Final

from fish_rules.rng import stream

type Seat = int
"""A seat number, 0 to 5, clockwise (R.1.1)."""

type Team = int
"""0 for seats 0-2, 1 for seats 3-5 (R.1.1)."""

type Card = int
"""A card number, 0 to 53: ``6 * set + position`` (R.1.2, R.1.3)."""

type SetId = int
"""A set number, 0 to 8 (R.1.3)."""

type Hand = tuple[Card, ...]
"""One player's cards, sorted ascending."""

NUM_SEATS: Final = 6
NUM_TEAMS: Final = 2
SEATS_PER_TEAM: Final = 3
NUM_CARDS: Final = 54
NUM_SETS: Final = 9
CARDS_PER_SET: Final = 6
HAND_SIZE: Final = 9

SEATS: Final[tuple[Seat, ...]] = tuple(range(NUM_SEATS))
TEAMS: Final[tuple[Team, ...]] = tuple(range(NUM_TEAMS))
CARDS: Final[tuple[Card, ...]] = tuple(range(NUM_CARDS))
SETS: Final[tuple[SetId, ...]] = tuple(range(NUM_SETS))

# ---------------------------------------------------------------- names (FROZEN order)

SUITS: Final = ("C", "D", "H", "S")
"""Clubs, diamonds, hearts, spades: the order of the four suits in every set below."""

_LOW_RANKS: Final = ("2", "3", "4", "5", "6", "7")
_HIGH_RANKS: Final = ("9", "10", "J", "Q", "K", "A")

SET_NAMES: Final[tuple[str, ...]] = (
    *(f"low-{suit}" for suit in SUITS),
    *(f"high-{suit}" for suit in SUITS),
    "eights",
)
"""Set names by set number: low clubs to low spades (0-3), high clubs to high spades (4-7),
then the 9th set of the four 8s and both jokers (8). R.1.3."""

CARD_NAMES: Final[tuple[str, ...]] = (
    *(rank + suit for suit in SUITS for rank in _LOW_RANKS),
    *(rank + suit for suit in SUITS for rank in _HIGH_RANKS),
    *("8" + suit for suit in SUITS),
    "RJ",
    "BJ",
)
"""Card names by card number, e.g. ``CARD_NAMES[0] == "2C"``. Rank then suit letter;
``RJ`` and ``BJ`` are the red and black jokers, which are distinct cards (R.1.2)."""

_CARD_BY_NAME: Final[dict[str, Card]] = {name: card for card, name in enumerate(CARD_NAMES)}


# ---------------------------------------------------------------- checks


def _check_index(value: object, what: str, size: int) -> int:
    """Return ``value`` if it is an int in [0, size); raise otherwise. Rejects bools."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{what} must be an int, got {type(value).__name__}")
    if not 0 <= value < size:
        raise ValueError(f"{what} must be in [0, {size}), got {value}")
    return value


def check_seat(seat: object) -> Seat:
    """Return ``seat`` if it is a valid seat number (R.1.1); raise otherwise."""
    return _check_index(seat, "seat", NUM_SEATS)


def check_team(team: object) -> Team:
    """Return ``team`` if it is a valid team number (R.1.1); raise otherwise."""
    return _check_index(team, "team", NUM_TEAMS)


def check_card(card: object) -> Card:
    """Return ``card`` if it is a valid card number (R.1.2); raise otherwise."""
    return _check_index(card, "card", NUM_CARDS)


def check_set(set_id: object) -> SetId:
    """Return ``set_id`` if it is a valid set number (R.1.3); raise otherwise."""
    return _check_index(set_id, "set", NUM_SETS)


# ---------------------------------------------------------------- seats and teams (R.1.1)


def team_of(seat: Seat) -> Team:
    """R.1.1: seats 0, 1 and 2 are team 0; seats 3, 4 and 5 are team 1."""
    return check_seat(seat) // SEATS_PER_TEAM


def team_seats(team: Team) -> tuple[Seat, Seat, Seat]:
    """R.1.1: the three seats of ``team``, in clockwise order."""
    first = check_team(team) * SEATS_PER_TEAM
    return (first, first + 1, first + 2)


def next_teammate(seat: Seat) -> Seat:
    """The next member of ``seat``'s team clockwise, wrapping within the team (R.1.1, R.8.1).

    Seats 0, 1, 2 go to 1, 2, 0; seats 3, 4, 5 go to 4, 5, 3.
    """
    first = team_of(seat) * SEATS_PER_TEAM
    return first + (seat - first + 1) % SEATS_PER_TEAM


def opponent_team(team: Team) -> Team:
    """The other team."""
    return 1 - check_team(team)


# ---------------------------------------------------------------- cards and sets (R.1.2, R.1.3)


def set_of(card: Card) -> SetId:
    """R.1.3: the set that ``card`` belongs to."""
    return check_card(card) // CARDS_PER_SET


def set_cards(set_id: SetId) -> tuple[Card, ...]:
    """R.1.3: the six cards of ``set_id``, ascending."""
    first = check_set(set_id) * CARDS_PER_SET
    return tuple(range(first, first + CARDS_PER_SET))


def card_name(card: Card) -> str:
    """The short name of ``card``, e.g. ``"10H"`` or ``"RJ"``."""
    return CARD_NAMES[check_card(card)]


def card_from_name(name: str) -> Card:
    """The card number for a short name from ``CARD_NAMES``; raises ValueError if unknown."""
    try:
        return _CARD_BY_NAME[name]
    except KeyError:
        raise ValueError(f"unknown card name {name!r}") from None


# ---------------------------------------------------------------- the deal (R.1.4)


def deal(game_seed: int) -> tuple[Hand, ...]:
    """R.1.4: the six starting hands, by seat, each sorted ascending.

    FROZEN: shuffle ``range(54)`` with the ``deal`` stream (index 0); seat ``k`` gets
    positions ``9k`` to ``9k + 8`` of the shuffled order.
    """
    order = stream(game_seed, "deal").shuffled(CARDS)
    return tuple(tuple(sorted(order[HAND_SIZE * seat : HAND_SIZE * (seat + 1)])) for seat in SEATS)


def first_player(game_seed: int) -> Seat:
    """R.1.4: the seat of the first turn. FROZEN: ``below(6)`` on ``first_player`` (index 0)."""
    return stream(game_seed, "first_player").below(NUM_SEATS)
