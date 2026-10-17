"""The rules engine: applies one action to a state (Canonical Ruleset v1.1).

``apply(state, action)`` returns the new state and the records of what happened, or raises
``IllegalActionError`` and leaves nothing changed (the state is immutable). The engine has no
timers and never reads a clock (R.8.6); the server adds the website's timers around it.

Legality checks that need only a player's own hand and public information are plain
functions of those values (``ask_violation``, ``legal_asks``, ``assignment_violation``), so
the same rules can be checked against hands a player might hold: Layer 2 (T5.3) and RQ2's
leakage estimate need exactly that.
"""

from collections.abc import Iterable
from dataclasses import replace

from fish_rules.cards import (
    CARDS_PER_SET,
    SEATS,
    Card,
    Hand,
    Seat,
    SetId,
    check_card,
    check_seat,
    check_set,
    opponent_team,
    set_cards,
    set_of,
    team_of,
    team_seats,
)
from fish_rules.events import (
    Action,
    Ask,
    AskEvent,
    Assign,
    Call,
    CallEvent,
    ChoiceEvent,
    Choose,
    CloseWindow,
    DeclarationDiscarded,
    Declare,
    Declared,
    GameOver,
    OpenWindow,
    Pass,
    Record,
    SeedChose,
    Vote,
    VoteCast,
    WindowClosed,
    WindowOpened,
)
from fish_rules.priority import first_in_priority, priority_order
from fish_rules.rng import stream
from fish_rules.state import (
    MAX_ASKS,
    CallSource,
    Outcome,
    PendingCall,
    PendingChoice,
    Phase,
    State,
    Window,
)

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


def _set_in_play(state: State, value: object) -> SetId:
    """R.4.6: a call must name one set still in play; anything else is rejected at input."""
    try:
        set_id = check_set(value)
    except (TypeError, ValueError) as error:
        raise IllegalActionError(f"set: {error}") from None
    if state.scored_by[set_id] is not None:
        raise IllegalActionError(f"set {set_id} has already been scored (R.4.6)")
    return set_id


def _require(state: State, phase: Phase, what: str) -> None:
    if state.phase is not phase:
        raise IllegalActionError(f"cannot {what} now; the game is in phase {state.phase}")


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


# ---------------------------------------------------------------- windows (R.4.2, R.4.3)


def _open_window(state: State) -> Step:
    """R.4.2: open a declaration window, before the current player acts.

    The environment opens one at the start of the game and after every event; the website only
    when a player presses Call (R.8.3). Windows open only on a turn: not during another window,
    a call assignment or an after-call choice (R.8.3), and not during run-out (R.6.2). The
    window's index is the number of windows opened earlier (R.8.1).
    """
    _require(state, Phase.TURN, "open a declaration window")
    index = state.windows_opened
    window = Window(index=index, declared=(None,) * 6, responded=(False,) * 6)
    state = replace(state, phase=Phase.WINDOW, window=window, windows_opened=index + 1)
    return state, (WindowOpened(index=index),)


def _respond(state: State, seat: Seat, set_id: SetId | None) -> State:
    """Record ``seat``'s declaration (or pass, if ``set_id`` is None) in the open window."""
    window = state.window
    assert window is not None
    if window.responded[seat]:
        raise IllegalActionError(f"seat {seat} has already responded in this window")
    declared = tuple(
        set_id if s == seat else d for s, d in zip(SEATS, window.declared, strict=True)
    )
    responded = tuple(s == seat or r for s, r in zip(SEATS, window.responded, strict=True))
    return replace(state, window=replace(window, declared=declared, responded=responded))


def _declare(state: State, action: Declare) -> Step:
    """R.4.2, R.4.3: declare a call in the open window, naming the set but not assigning cards.

    Any player may declare in any window, out of turn and with no cards. A declaration must
    name a set still in play (R.4.6). Each seat responds at most once per window.
    """
    _require(state, Phase.WINDOW, "declare a call")
    seat = _seat(action.seat, "seat")
    set_id = _set_in_play(state, action.set_id)
    state = _respond(state, seat, set_id)
    assert state.window is not None
    return state, (Declared(window=state.window.index, seat=seat, set_id=set_id),)


def _pass(state: State, action: Pass) -> Step:
    """R.8.9: in the environment every agent is asked in every window; a pass declines."""
    _require(state, Phase.WINDOW, "pass")
    return _respond(state, _seat(action.seat, "seat"), None), ()


def _close_window(state: State) -> Step:
    """R.4.3, R.8.1: close the window. The declared call with the highest priority proceeds to
    the assignment step; all other declarations are discarded, recorded but never shown. With
    no declaration, the current player may ask or call (R.4.2)."""
    _require(state, Phase.WINDOW, "close a window")
    window = state.window
    assert window is not None
    order = priority_order(state.seed, window.index)
    declarers = [seat for seat in order if window.declared[seat] is not None]
    caller = first_in_priority(order, declarers)
    if caller is None:
        state = replace(state, phase=Phase.TURN, window=None)
        return state, (WindowClosed(index=window.index, caller=None, set_id=None),)

    set_id = window.declared[caller]
    assert set_id is not None
    discarded = tuple(
        DeclarationDiscarded(window=window.index, seat=seat, set_id=declared)
        for seat in declarers
        if seat != caller and (declared := window.declared[seat]) is not None
    )
    call = PendingCall(caller=caller, set_id=set_id, source=CallSource.WINDOW)
    state = replace(state, phase=Phase.ASSIGN, window=None, call=call)
    return state, (WindowClosed(index=window.index, caller=caller, set_id=set_id), *discarded)


# ---------------------------------------------------------------- calls (R.4)


def _call(state: State, action: Call) -> Step:
    """R.4.2: if a window closes with no declaration, the current player may call; the call
    goes directly to the assignment step. (Run-out calls, R.6.2, are added in subtask 7.)"""
    _require(state, Phase.TURN, "call without a window")
    seat = _seat(action.seat, "seat")
    if seat != state.current:
        raise IllegalActionError(
            f"only the current player, seat {state.current}, may call on their turn (R.3.1)"
        )
    set_id = _set_in_play(state, action.set_id)
    call = PendingCall(caller=seat, set_id=set_id, source=CallSource.TURN)
    return replace(state, phase=Phase.ASSIGN, call=call), ()


def assignment_violation(caller: Seat, holders: tuple[Seat, ...]) -> str | None:
    """R.4.1, R.4.6: why ``holders`` is not a valid assignment for ``caller``, or None.

    A valid call assigns each of the set's six cards to a member of the caller's team, the
    caller included. Assigning a card to a teammate who holds no cards is valid; it only makes
    the call incorrect. Needs no hidden information.
    """
    check_seat(caller)
    if len(holders) != CARDS_PER_SET:
        return f"an assignment names six holders, got {len(holders)} (R.4.1)"
    for holder in holders:
        if team_of(holder) != team_of(caller):
            return f"seat {holder} is not on the caller's team (R.4.1, R.4.6)"
    return None


def _assign(state: State, action: Assign) -> Step:
    """R.4.3-R.4.6, R.2.3: the caller assigns the six cards; the call is resolved.

    Correct if every card is held by the teammate it was assigned to; a correct call scores the
    set for the caller's team, an incorrect one for the other team. Either way all six cards
    leave play, from whichever hands hold them, and their true holders are revealed.
    """
    _require(state, Phase.ASSIGN, "assign cards")
    call = state.call
    assert call is not None
    seat = _seat(action.seat, "seat")
    if seat != call.caller:
        raise IllegalActionError(f"only the caller, seat {call.caller}, may assign (R.4.3)")
    holders = tuple(_seat(holder, "assigned holder") for holder in action.holders)
    why = assignment_violation(call.caller, holders)
    if why is not None:
        raise IllegalActionError(why)

    cards = set_cards(call.set_id)
    true_holders = tuple(state.holder(card) for card in cards)
    revealed = tuple(holder for holder in true_holders if holder is not None)
    assert len(revealed) == len(cards), "every card of a set in play is in some hand"
    correct = revealed == holders
    caller_team = team_of(call.caller)
    scoring_team = caller_team if correct else opponent_team(caller_team)
    record = CallEvent(
        number=state.events,
        caller=call.caller,
        set_id=call.set_id,
        source=call.source,
        assignment=holders,
        holders=revealed,
        correct=correct,
        scored_by=scoring_team,
    )
    gone = set(cards)
    state = replace(
        state,
        hands=tuple(tuple(card for card in hand if card not in gone) for hand in state.hands),
        scored_by=tuple(
            scoring_team if s == call.set_id else by for s, by in enumerate(state.scored_by)
        ),
        phase=Phase.TURN,
        call=None,
        current=None,
        events=state.events + 1,
    )
    return _after_call(state, record, correct)


def _after_call(state: State, record: CallEvent, correct: bool) -> Step:
    """What follows a resolved call.

    R.7.2: if the call brought a team to five sets, the game ends at once with no choice.
    R.6.2: if one team now holds no cards, run-out begins and no choice is made (subtask 7).
    R.5.1-R.5.2: otherwise the scoring team chooses which of its players holding cards takes
    the turn: the caller chooses if the caller's team scored, otherwise that team votes.
    """
    if state.winner() is not None:
        return _end(state, Outcome.FINISHED, (record,))
    if not all(state.team_has_cards(team) for team in (0, 1)):
        raise NotImplementedError("run-out (R.6.2) is added in T2.2 subtask 7")
    team = record.scored_by
    candidates = tuple(seat for seat in team_seats(team) if state.hands[seat])
    choice = PendingChoice(
        team=team,
        candidates=candidates,
        chooser=record.caller if correct else None,
        votes=(None, None, None),
        call_event=record.number,
    )
    phase = Phase.CHOOSE if correct else Phase.VOTE
    return replace(state, phase=phase, choice=choice), (record,)


# ---------------------------------------------------------------- after-call choice (R.5)


def tiebreak_seat(game_seed: int, call_event: int, among: Iterable[Seat]) -> Seat:
    """R.5.2: the seat the game seed chooses, from ``among``, after the call numbered
    ``call_event``.

    FROZEN (``docs/determinism.md`` §8): ``choice`` over the seats in ascending order, from
    stream ``tiebreak`` with the call's event number as the index.
    """
    seats = sorted({check_seat(seat) for seat in among})
    return stream(game_seed, "tiebreak", call_event).choice(seats)


def _chosen(state: State, value: object) -> Seat:
    """R.5.1: the turn can only go to one of the scoring team's players holding cards."""
    choice = state.choice
    assert choice is not None
    seat = _seat(value, "chosen")
    if seat not in choice.candidates:
        raise IllegalActionError(
            f"seat {seat} cannot take the turn; the choice is among {choice.candidates} (R.5.1)"
        )
    return seat


def _give_turn(state: State, seat: Seat, records: tuple[Record, ...]) -> Step:
    """R.5: the after-call choice is made; ``seat`` becomes the current player. This is an
    event (R.4.2); in the environment the next window opens now."""
    choice = state.choice
    assert choice is not None
    record = ChoiceEvent(number=state.events, team=choice.team, seat=seat)
    state = replace(state, phase=Phase.TURN, choice=None, current=seat, events=state.events + 1)
    return state, (*records, record)


def _choose(state: State, action: Choose) -> Step:
    """R.5.2: if the caller's team is choosing, the caller makes the choice."""
    _require(state, Phase.CHOOSE, "choose")
    choice = state.choice
    assert choice is not None
    seat = _seat(action.seat, "seat")
    if seat != choice.chooser:
        raise IllegalActionError(f"only the caller, seat {choice.chooser}, chooses (R.5.2)")
    return _give_turn(state, _chosen(state, action.chosen), ())


def _settle_vote(state: State, records: tuple[Record, ...]) -> Step:
    """R.5.2: count the votes cast. The seat with the most votes takes the turn. If the vote
    ties, the game seed chooses among the tied seats; if no votes were cast, among the scoring
    team's players holding cards. Only the outcome is public."""
    choice = state.choice
    assert choice is not None
    counts = [(sum(1 for vote in choice.votes if vote == seat), seat) for seat in choice.candidates]
    most = max(count for count, _ in counts)
    leaders = tuple(seat for count, seat in counts if count == most)
    if len(leaders) == 1:
        return _give_turn(state, leaders[0], records)
    seat = tiebreak_seat(state.seed, choice.call_event, leaders)
    seed_record = SeedChose(call_event=choice.call_event, among=leaders, chosen=seat)
    return _give_turn(state, seat, (*records, seed_record))


def _vote(state: State, action: Vote) -> Step:
    """R.5.2: if the other team is choosing, its members vote. All members vote, including
    those with no cards; each votes once. Individual votes are recorded in the event log but
    not shown. In the environment every member votes (R.8.6), so the vote is settled when the
    third vote is cast."""
    _require(state, Phase.VOTE, "vote")
    choice = state.choice
    assert choice is not None
    seat = _seat(action.seat, "seat")
    members = team_seats(choice.team)
    if seat not in members:
        raise IllegalActionError(f"only members of team {choice.team} vote (R.5.2)")
    position = members.index(seat)
    if choice.votes[position] is not None:
        raise IllegalActionError(f"seat {seat} has already voted (R.5.2)")
    chosen = _chosen(state, action.chosen)
    votes = (
        chosen if position == 0 else choice.votes[0],
        chosen if position == 1 else choice.votes[1],
        chosen if position == 2 else choice.votes[2],
    )
    state = replace(state, choice=replace(choice, votes=votes))
    record = VoteCast(call_event=choice.call_event, seat=seat, chosen=chosen)
    if any(vote is None for vote in votes):
        return state, (record,)
    return _settle_vote(state, (record,))


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
        case OpenWindow():
            return _open_window(state)
        case Declare():
            return _declare(state, action)
        case Pass():
            return _pass(state, action)
        case CloseWindow():
            return _close_window(state)
        case Call():
            return _call(state, action)
        case Assign():
            return _assign(state, action)
        case Choose():
            return _choose(state, action)
        case Vote():
            return _vote(state, action)
        case _:
            raise IllegalActionError(f"not an action: {action!r}")
