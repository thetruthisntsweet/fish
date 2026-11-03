"""Tests for B1 as the project uses it (b1-v1): it plays the frozen games, ``b1(setting)``
gives it memory, and on the website it presses Call (``would_call``) exactly when it has a
certain call on a turn, naming the set it would call in the environment."""

import dataclasses
from typing import cast

import pytest

from fish_agents.b0 import B0
from fish_agents.b1 import B1, B1_VERSION, b1, certain_calls, decide, would_call
from fish_agents.base import Agent
from fish_agents.memory import FULL, NONE, MemorySetting, Remembering
from fish_agents.play import play_game
from fish_env.env import AGENTS, FishEnv, seat_of
from fish_rules.action_index import CALL_BASE
from fish_rules.cards import SEATS, Card, Seat, set_cards, team_of
from fish_rules.deduce.solve import Deduction, deduce
from fish_rules.engine import apply
from fish_rules.events import OpenWindow
from fish_rules.record import replay_record
from fish_rules.rng import SplitMix64
from fish_rules.state import Phase, State, new_game, state_hash
from fish_rules.view import project

SETTINGS = {"full": FULL, "last-8": MemorySetting.last_k(8), "none": NONE}

FROZEN = (
    ("full", 0, "self", 1239, 1,
     "17d0808e5092f8e0a26f9925da7677fb7a7052a04cfee3c5084e37c9548d8e93"),
    ("full", 1, "self", 1330, 1,
     "0944dcf420f7ca7a47d577300cefc0fa10c091fe20033786af56a081b3d6db22"),
    ("full", 2, "self", 992, 0,
     "c9391bcfd18d80cb49b792332bad49c2c6b93d0e008600f70ac9da025ca2d22f"),
    ("last-8", 1, "self", 1373, 0,
     "2dd449c4b0dfcd5077f2b77071283e87a978e77a2fb5044711185cb6e7424636"),
    ("none", 0, "b0", 320, 0,
     "1aa99cea4409940df39ac4a0243b0cc163f283738f934938532f692c86e140b3"),
)  # fmt: skip
"""b1-v1 games: memory, seed, opponents (six B1s, or B1 in seats 0-2 against three B0s),
number of actions, winning team, final state hash. If these change, B1 changed."""


def test_version() -> None:
    assert B1_VERSION == "b1-v1"


@pytest.mark.parametrize(("memory", "seed", "against", "actions", "winner", "final"), FROZEN)
def test_frozen_games(
    memory: str, seed: int, against: str, actions: int, winner: int, final: str
) -> None:
    agent: Agent = b1(SETTINGS[memory])
    opponent: Agent = agent if against == "self" else B0()
    agents = [agent] * 3 + [opponent] * 3  # team 0 is seats 0-2
    record = play_game(agents, seed)
    assert len(record["actions"]) == actions  # pyright: ignore[reportArgumentType]
    assert record["winner"] == winner
    assert state_hash(replay_record(record)) == final


def test_b1_with_memory_is_b1_remembering() -> None:
    agent = b1(MemorySetting.last_k(8))
    assert isinstance(agent, Remembering)
    assert isinstance(agent.agent, B1)
    assert agent.setting == MemorySetting.last_k(8)
    assert b1(FULL).memories is not b1(FULL).memories  # each has memories of its own
    assert play_game([b1(FULL)] * 6, 2) == play_game([b1(FULL) for _ in range(6)], 2)


# ---------------------------------------------------------------- pressing Call


def _dealt(state: State, seat: Seat, hand: tuple[Card, ...]) -> State:
    """``state`` with ``hand`` (nine cards) in ``seat``'s hand and the other cards dealt round
    the other seats one at a time, so none of them holds a whole set."""
    others = [s for s in SEATS if s != seat]
    rest = [c for c in range(54) if c not in hand]
    hands = {s: tuple(sorted(rest[i::5])) for i, s in enumerate(others)}
    hands[seat] = tuple(sorted(hand))
    return dataclasses.replace(state, hands=tuple(hands[s] for s in SEATS))


class _Proved:
    """A deduction in which ``seat`` knows it holds every card of ``sets`` and nothing else."""

    def __init__(self, seat: Seat, sets: tuple[int, ...]) -> None:
        self._held = {card: seat for s in sets for card in set_cards(s)}

    def known(self, card: Card) -> Seat | None:
        return self._held.get(card)


def test_b1_presses_call_for_a_set_it_holds_and_calls_the_same_set_on_its_turn() -> None:
    turn = new_game(3).current
    assert turn is not None
    state = _dealt(new_game(3), turn, (*set_cards(0), *set_cards(1)[:3]))
    view = project(state, turn, None)
    deduction = deduce(view, [])
    assert would_call(view, deduction, SplitMix64(1)) == 0
    assert decide(view, deduction, SplitMix64(1)) == CALL_BASE + 0
    other = next(s for s in SEATS if s != turn)
    elsewhere = project(state, other, None)
    assert would_call(elsewhere, deduce(elsewhere, []), SplitMix64(1)) is None  # nothing proved


def test_with_two_certain_calls_the_press_and_the_call_draw_the_same_set() -> None:
    state = new_game(3)
    assert state.current is not None
    view = project(state, state.current, None)
    deduction = cast(Deduction, _Proved(state.current, (0, 4)))
    assert certain_calls(state.current, deduction, view.scored_by) == [0, 4]
    picks: set[int] = set()
    for seed in range(20):
        pressed = would_call(view, deduction, SplitMix64(seed))
        assert pressed is not None
        assert decide(view, deduction, SplitMix64(seed)) == CALL_BASE + pressed
        picks.add(pressed)
    assert picks == {0, 4}  # a tie, broken by the generator, the same way both times


def test_no_press_in_a_window_an_assignment_a_choice_or_run_out() -> None:
    state = _dealt(new_game(3), 0, (*set_cards(0), *set_cards(4)[:3]))
    windowed, _ = apply(state, OpenWindow())
    view = project(windowed, 0, None)
    deduction = deduce(view, [])
    assert certain_calls(0, deduction, view.scored_by) == [0]
    for phase in (Phase.WINDOW, Phase.ASSIGN, Phase.CHOOSE, Phase.VOTE, Phase.RUNOUT, Phase.OVER):
        assert would_call(dataclasses.replace(view, phase=phase), deduction, SplitMix64(1)) is None
    assert would_call(dataclasses.replace(view, phase=Phase.TURN), deduction, SplitMix64(1)) == 0


def test_every_press_in_a_game_is_a_certain_call_and_is_right() -> None:
    """At every view of every seat in a full-memory game, taken as a moment between events
    when Call may be pressed: B1 presses exactly when it has a certain call, and the set it
    names is wholly with its team. (In the environment B1 declares such a call in the next
    window, so its turns never have one.)"""
    agent = b1(FULL)
    game = FishEnv()
    game.reset(seed=4)
    pressed = 0
    while game.agents:
        for seat in SEATS:
            agent.observe(game.view(AGENTS[seat]))
        for seat in SEATS:
            view = dataclasses.replace(game.view(AGENTS[seat]), phase=Phase.TURN)
            deduction = agent.memory(seat).deduction
            chosen = would_call(view, deduction, SplitMix64(seat))
            if chosen is None:
                assert not certain_calls(seat, deduction, view.scored_by)
                continue
            pressed += 1
            truth = [game.game.holder(card) for card in set_cards(chosen)]
            assert all(h is not None and team_of(h) == team_of(seat) for h in truth)
        name = game.agent_selection
        if game.terminations[name] or game.truncations[name]:
            game.step(None)
            continue
        game.step(decide(game.view(name), agent.memory(seat_of(name)).deduction, SplitMix64(0)))
    assert pressed > 0
