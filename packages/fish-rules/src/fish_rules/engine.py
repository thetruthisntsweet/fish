"""The rules engine: applies one action to a state (Canonical Ruleset v1.0).

``apply(state, action)`` returns the new state and the records of what happened, or raises
``IllegalActionError`` and leaves nothing changed (the state is immutable). The engine has no
timers and never reads a clock (R.8.6); the server adds the website's timers around it.

Legality checks that need only a player's own hand and public information are plain
functions of those values (``ask_violation``, ``legal_asks``), so the same rules can be
checked against hands a player might hold: Layer 2 (T5.3) and RQ2's leakage estimate need
exactly that.
"""

from dataclasses import replace

from fish_rules.cards import (
    SEATS,
    Card,
    Hand,
    Seat,
    check_card,
    check_seat,
    opponent_team,
    set_cards,
    set_of,
    team_of,
    team_seats,
)
from fish_rules.events import Action, Ask, AskEvent, GameOver, Record
from fish_rules.state import MAX_ASKS, Outcome, Phase, State

type Step = tuple[State, tuple[Record, ...]]
"""The new state and the records of what happened, in order."""


class IllegalActionError(ValueError):
    """The rules do not allow this action in this state. The action has no effect; the player
    acts again (R.8.7)."""


# ---------------------------------------------------------------- input checks


def _seat(value: object, what: str) -> Seat:
    try:
        return check_seat(value)
    except (TypeError, ValueError) as error:
        raise IllegalActionError(f"{what}: {error}") from None


def _card(value: object) -> Card:
    try:
        return check_card(value)
    except (TypeError, ValueError) as error:
        raise IllegalActionError(f"card: {error}") from None


# ---------------------------------------------------------------- asking (R.3)


def ask_violation(
    asker: Seat, asker_hand: Hand, target: Seat, target_hand_size: int, card: Card
) -> str | None:
    """R.3.2: why asking ``target`` for ``card`` is illegal, or None if it is legal.

    An ask names one opponent and one card. It is legal only if the opponent holds at least
    one card (R.3.2, R.6.1), the asker holds at least one card of that card's set, and the
    asker does not hold the card itself. Uses only the asker's own hand and the target's
    public hand size, so it can be evaluated for any hand the asker might hold.
    """
    check_seat(asker)
    check_seat(target)
    set_id = set_of(card)
    if team_of(target) == team_of(asker):
        return "the target must be an opponent (R.3.2)"
    if target_hand_size < 1:
        return "the target holds no cards and cannot be asked (R.3.2, R.6.1)"
    if card in asker_hand:
        return "the asker already holds that card (R.3.2)"
    if not any(set_of(held) == set_id for held in asker_hand):
        return "the asker holds no card of that set (R.3.2)"
    return None


def legal_asks(asker: Seat, asker_hand: Hand, hand_sizes: tuple[int, ...]) -> tuple[Ask, ...]:
    """R.3.2: every legal ask for ``asker``, ordered by target seat, then card number.

    ``hand_sizes`` is every seat's public hand size (R.2.2). Empty if no ask is legal, in
    which case a current player must call (R.9).
    """
    held_sets = sorted({set_of(card) for card in asker_hand})
    wanted = [card for set_id in held_sets for card in set_cards(set_id) if card not in asker_hand]
    return tuple(
        Ask(seat=asker, target=target, card=card)
        for target in team_seats(opponent_team(team_of(asker)))
        if hand_sizes[target] > 0
        for card in wanted
    )


def _move(hands: tuple[Hand, ...], card: Card, source: Seat, dest: Seat) -> tuple[Hand, ...]:
    """``hands`` with ``card`` moved from ``source`` to ``dest``, each hand kept sorted."""
    return tuple(
        tuple(c for c in hand if c != card)
        if seat == source
        else tuple(sorted((*hand, card)))
        if seat == dest
        else hand
        for seat, hand in zip(SEATS, hands, strict=True)
    )


def _ask(state: State, action: Ask) -> Step:
    """R.3.1-R.3.3, R.8.2: resolve an ask."""
    asker = _seat(action.seat, "seat")
    target = _seat(action.target, "target")
    card = _card(action.card)
    if state.phase is not Phase.TURN:
        raise IllegalActionError(f"no one may ask now; the game is in phase {state.phase} (R.3.1)")
    if asker != state.current:
        raise IllegalActionError(f"only the current player, seat {state.current}, may ask (R.3.1)")
    why = ask_violation(asker, state.hands[asker], target, len(state.hands[target]), card)
    if why is not None:
        raise IllegalActionError(why)

    success = card in state.hands[target]
    record = AskEvent(number=state.events, asker=asker, target=target, card=card, success=success)
    state = replace(
        state,
        hands=_move(state.hands, card, target, asker) if success else state.hands,
        current=asker if success else target,  # R.3.3
        events=state.events + 1,
        asks=state.asks + 1,
    )
    if state.asks >= MAX_ASKS:
        return _end(state, Outcome.UNFINISHED, (record,))
    if not all(state.team_has_cards(team) for team in (0, 1)):
        raise NotImplementedError("run-out (R.6.2) is added in T2.2 subtask 7")
    return state, (record,)


# ---------------------------------------------------------------- end of game (R.7, R.8.2)


def _end(state: State, outcome: Outcome, records: tuple[Record, ...]) -> Step:
    """End the game. R.7.1: finished, won by the team with five sets. R.8.2: unfinished."""
    winner = state.winner() if outcome is Outcome.FINISHED else None
    state = replace(state, phase=Phase.OVER, outcome=outcome, current=None)
    return state, (*records, GameOver(outcome=outcome, winner=winner))


# ---------------------------------------------------------------- dispatch


def apply(state: State, action: Action) -> Step:
    """Apply ``action`` to ``state``. Returns the new state and the records it produced.

    Raises ``IllegalActionError`` if the rules do not allow the action now; nothing changes.
    """
    if state.phase is Phase.OVER:
        raise IllegalActionError("the game is over (R.7, R.8.2)")
    match action:
        case Ask():
            return _ask(state, action)
        case _:
            raise NotImplementedError(f"{type(action).__name__} is added in a later subtask")
