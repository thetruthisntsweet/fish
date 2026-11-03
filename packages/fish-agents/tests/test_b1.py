"""Tests for B1's decisions (fish_agents.b1, T5.2), checked against the true deal at every
decision of real games, at full, last-k and no memory: every move is legal; every call B1
chooses is correct; it takes a certain hit whenever it has one and asks a certain miss only
when nothing else is legal; its asks are the likeliest by its own estimate; and forced calls,
choices and votes follow their rules."""

import dataclasses
from collections import Counter
from fractions import Fraction
from typing import cast

import pytest
from hypothesis import settings

from fish_agents.b0 import B0
from fish_agents.b1 import (
    B1,
    IllegalChoiceError,
    _pick,  # pyright: ignore[reportPrivateUsage]
    assignment,
    certain_asks,
    certain_calls,
    decide,
    hit_chance,
    known_on_team,
)
from fish_agents.base import Agent, PolicyStreams
from fish_agents.memory import FULL, NONE, MemorySetting, Remembering
from fish_env.env import AGENTS, FishEnv, seat_of
from fish_rules.action_index import (
    CALL_BASE,
    NOMINATE_BASE,
    PASS_INDEX,
    decode,
    legal_indices,
    teammates,
)
from fish_rules.cards import SEATS, Card, Seat, set_cards, team_of
from fish_rules.deduce.solve import Deduction, deduce
from fish_rules.engine import apply
from fish_rules.events import Ask, Assign, Call, CloseWindow, Declare, OpenWindow, Pass
from fish_rules.rng import SplitMix64
from fish_rules.state import CallSource, Phase, State, new_game
from fish_rules.view import project

SETTINGS = [FULL, MemorySetting.last_k(4), MemorySetting.last_k(1), NONE]
SEEDS = range(min(40, max(2, int(settings().max_examples) // 100)))  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
"""Games per memory setting, each checked at every decision: 2 in dev, 10 in CI, 40 nightly."""


class Seen:
    """What the games showed: how often each kind of decision came up."""

    def __init__(self) -> None:
        self.kinds: Counter[str] = Counter()


def _check(state: State, seat: Seat, deduction: Deduction, chosen: int, seen: Seen) -> None:
    """One B1 decision, against the truth in ``state``."""
    action = decode(seat, chosen, state.phase)
    team = team_of(seat)
    match action:
        case Declare(set_id=set_id) | Call(set_id=set_id) if state.phase is not Phase.RUNOUT:
            seen.kinds["certain call"] += 1
            assert all(team_of(state.holder(c) or seat) == team for c in set_cards(set_id))
            assert all(state.holder(c) is not None for c in set_cards(set_id))
        case Call():
            seen.kinds["forced call"] += 1
        case Ask(target=target, card=card):
            chance = hit_chance(deduction, target, card)
            legal = [decode(seat, i, Phase.TURN) for i in state_legal(state, seat) if i < CALL_BASE]
            chances = [hit_chance(deduction, a.target, a.card) for a in legal if isinstance(a, Ask)]
            assert chance == max(chances)  # the likeliest, by its own estimate
            if chance == 1:
                seen.kinds["certain hit"] += 1
                assert state.holder(card) == target
            if chance == 0:
                seen.kinds["certain miss"] += 1
                assert max(chances) == 0  # only when every legal ask is one
                assert state.holder(card) != target
            if any(c == 1 for c in chances):
                assert chance == 1
            seen.kinds["ask"] += 1
        case Assign(holders=holders):
            assert state.call is not None
            truth = tuple(state.holder(c) for c in set_cards(state.call.set_id))
            if state.call.source is not CallSource.RUNOUT:
                assert holders == truth  # a call it chose is exactly right
            seen.kinds["assign"] += 1
        case _:
            if state.phase in (Phase.CHOOSE, Phase.VOTE):
                seen.kinds["nominate"] += 1
            else:
                assert chosen == PASS_INDEX
                seen.kinds["pass"] += 1


def state_legal(state: State, seat: Seat) -> tuple[int, ...]:
    return legal_indices(state, seat)


def play_checked(agents: list[Agent], b1_seats: set[Seat], seed: int, seen: Seen) -> FishEnv:
    """Play a game, checking every decision of the B1 seats against the true deal; the
    finished game."""
    game = FishEnv()
    game.reset(seed=seed)
    streams = PolicyStreams(seed)
    while game.agents:
        for seat, agent in enumerate(agents):
            if isinstance(agent, Remembering):
                agent.observe(game.view(AGENTS[seat]))
        name = game.agent_selection
        if game.terminations[name] or game.truncations[name]:
            game.step(None)
            continue
        seat = seat_of(name)
        view = game.view(name)
        chosen = agents[seat].act(view, streams.for_decision(seat, game.game.events))
        if seat in b1_seats:
            agent = agents[seat]
            assert isinstance(agent, Remembering)
            _check(game.game, seat, agent.memory(seat).deduction, chosen, seen)
        game.step(chosen)
    return game


@pytest.mark.parametrize("setting", SETTINGS, ids=str)
def test_every_decision_of_b1_games_follows_its_rules(setting: MemorySetting) -> None:
    seen = Seen()
    for seed in SEEDS:
        b1 = Remembering(B1(), setting)
        final = play_checked([b1] * 6, set(SEATS), seed, seen)
        assert final.game.phase is Phase.OVER
    for kind in ("certain call", "ask", "assign", "nominate", "pass"):
        assert seen.kinds[kind] > 0, kind  # each rule was exercised
    if setting is FULL:
        assert seen.kinds["certain hit"] > 0


@pytest.mark.parametrize("setting", [FULL, NONE], ids=str)
def test_b1_against_b0_wins_and_every_call_it_chooses_is_right(setting: MemorySetting) -> None:
    seen = Seen()
    for seed in SEEDS:
        b1 = Remembering(B1(), setting)
        agents: list[Agent] = [b1, b1, b1, B0(), B0(), B0()]  # team 0 against team 1
        final = play_checked(agents, {0, 1, 2}, seed, seen)
        assert final.game.winner() == 0


def test_a_set_wholly_in_hand_is_a_certain_call_and_nothing_else_is() -> None:
    state = _with_hands(new_game(3), {0: (0, 1, 2, 3, 4, 5, 12, 20, 30)})
    deduction = deduce(project(state, 0, None), [])
    assert certain_calls(0, deduction, state.scored_by) == [0]
    assert known_on_team(0, 0, deduction) == 6
    assert known_on_team(0, 2, deduction) == 1  # card 12 only
    assert assignment(0, 0, deduction) == (0,) * 6
    assert certain_calls(0, deduction, (1, *state.scored_by[1:])) == []  # scored: not in play


def test_a_card_nobody_has_shown_is_equally_likely_with_each_other_seat() -> None:
    state = new_game(3)
    view = project(state, 0, None)
    deduction = deduce(view, [])
    card = next(c for c in range(54) if c not in view.hand)
    assert hit_chance(deduction, 4, card) == Fraction(1, 5)
    assert hit_chance(deduction, 0, card) == 0  # it is not in B1's own hand
    assert certain_asks(0, deduction, view.hand_sizes) == 0


class _Known:
    """A deduction with chosen answers, for the assignment's fallbacks."""

    def __init__(self, possible: dict[Card, tuple[Seat, ...]], example: dict[Card, Seat]) -> None:
        self._possible = possible
        self._example = example

    def possible(self, card: Card) -> tuple[Seat, ...]:
        return self._possible[card]

    def known(self, card: Card) -> Seat | None:
        seats = self._possible[card]
        return seats[0] if len(seats) == 1 else None

    def example_now(self) -> tuple[tuple[Card, ...], ...]:
        return tuple(tuple(c for c, s in self._example.items() if s == seat) for seat in SEATS)


def test_unknown_cards_are_assigned_as_the_example_deal_has_them_or_to_a_possible_teammate() -> (
    None
):
    cards = set_cards(1)  # 6 to 11
    possible = {
        cards[0]: (1,),  # known, a teammate
        cards[1]: (2, 4),  # the example says 2
        cards[2]: (1, 3),  # the example says 3, an opponent: the possible teammate, 1
        cards[3]: (4,),  # only an opponent may hold it: B1 itself (the call is lost anyway)
        cards[4]: (0, 2),
        cards[5]: (5, 2),
    }
    example = {cards[1]: 2, cards[2]: 3, cards[3]: 4, cards[4]: 0, cards[5]: 5, cards[0]: 1}
    deduction = cast(Deduction, _Known(possible, example))
    assert assignment(0, 1, deduction) == (1, 2, 1, 0, 0, 2)


def test_b1_never_plays_an_illegal_action() -> None:
    state, _ = apply(new_game(5), OpenWindow())
    view = project(state, 1, None)
    deduction = deduce(view, [])
    assert decide(view, deduction, SplitMix64(1)) == PASS_INDEX
    with pytest.raises(IllegalChoiceError, match="not legal"):
        decide(dataclasses.replace(view, legal=()), deduction, SplitMix64(1))
    with pytest.raises(IllegalChoiceError, match="nothing to choose from"):
        _pick([], SplitMix64(1))


def test_b1_has_nothing_to_do_once_the_game_is_over_or_in_someone_elses_assignment() -> None:
    seen = Seen()
    final = play_checked([Remembering(B1(), FULL)] * 6, set(SEATS), 0, seen)
    over = final.view(AGENTS[0])
    with pytest.raises(IllegalChoiceError, match="no decision"):
        decide(over, deduce(over, []), SplitMix64(1))
    state = _assigning(new_game(11))
    assert state.call is not None
    other = next(s for s in SEATS if s != state.call.caller)
    view = dataclasses.replace(project(state, other, None), legal=(0,))
    with pytest.raises(IllegalChoiceError, match="not this seat's"):
        decide(view, deduce(project(state, other, None), []), SplitMix64(1))


def test_a_nomination_goes_to_the_teammate_with_most_certain_asks_then_most_cards() -> None:
    state = _with_hands(new_game(3), {0: (0, 1, 2, 3, 4, 5, 12, 20, 30)})
    view = project(state, 0, None)
    deduction = deduce(view, [])
    mates = teammates(0)
    nominate = [NOMINATE_BASE + i for i in range(3)]
    choosing = dataclasses.replace(view, phase=Phase.CHOOSE, legal=tuple(nominate))
    chosen = decide(choosing, deduction, SplitMix64(1))
    sizes = view.hand_sizes
    best = max(sizes[m] for m in mates)
    assert sizes[mates[chosen - NOMINATE_BASE]] == best  # nobody has a certain ask yet


# ---------------------------------------------------------------- building positions


def _with_hands(state: State, wanted: dict[Seat, tuple[Card, ...]]) -> State:
    """``state`` with the given seats' hands, the displaced cards dealt back to the others so
    every seat keeps nine."""
    taken = {c for hand in wanted.values() for c in hand}
    rest = [c for hand in state.hands for c in hand if c not in taken]
    hands: list[tuple[Card, ...]] = []
    for seat in SEATS:
        if seat in wanted:
            hands.append(tuple(sorted(wanted[seat])))
        else:
            hands.append(tuple(sorted(rest[:9])))
            rest = rest[9:]
    return dataclasses.replace(state, hands=tuple(hands))


def _assigning(state: State) -> State:
    """``state`` moved on to a call's assignment: a window, a declaration, the window closed."""
    state, _ = apply(state, OpenWindow())
    caller = 1
    set_id = next(s for s in range(9) if state.scored_by[s] is None)
    state, _ = apply(state, Declare(caller, set_id))
    for seat in SEATS:
        if seat != caller:
            state, _ = apply(state, Pass(seat))
    state, _ = apply(state, CloseWindow())
    assert state.phase is Phase.ASSIGN
    return state


def test_on_its_turn_b1_calls_a_certain_set_rather_than_ask() -> None:
    state = new_game(3)
    assert state.current is not None
    turn = state.current
    team_cards = (0, 1, 2, 3, 4, 5, 12, 20, 30) if turn != 0 else (0, 1, 2, 3, 4, 5, 13, 21, 31)
    state = _with_hands(state, {turn: team_cards})
    view = project(state, turn, None)
    assert view.phase is Phase.TURN
    chosen = decide(view, deduce(view, []), SplitMix64(1))
    assert chosen == CALL_BASE + 0


def test_a_call_that_must_be_made_is_the_set_with_most_cards_known_on_the_team() -> None:
    state = _with_hands(new_game(3), {0: (0, 1, 2, 3, 4, 6, 7, 8, 12)})
    view = project(state, 0, None)
    deduction = deduce(view, [])
    calls = tuple(CALL_BASE + s for s in range(9))
    for phase in (Phase.RUNOUT, Phase.TURN):  # run-out, or a turn with no legal ask
        forced = dataclasses.replace(view, phase=phase, legal=calls)
        assert decide(forced, deduction, SplitMix64(1)) == CALL_BASE + 0  # five known cards
